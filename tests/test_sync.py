import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import omarchy_garmin.summary as summary_module
from omarchy_garmin.auth import AccountMismatchError, AuthenticatedSession, AuthStore
from omarchy_garmin.database import ActivityRepository
from omarchy_garmin.locking import activity_refresh_lock
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.storage import ensure_private_directory
from omarchy_garmin.summary import SummaryCache
from omarchy_garmin.sync import (
    ActivityAuthenticationRequiredError,
    ActivityDataError,
    ActivityFetch,
    ActivityGateway,
    ActivityRefreshInProgressError,
    ActivityStorageError,
    ActivitySyncConfigurationError,
    ActivitySyncService,
)

_TODAY = date(2026, 8, 26)
_NOW = datetime(2026, 8, 26, 12, 30, tzinfo=UTC)


def _paths(tmp_path: Path, *, runtime: bool = True) -> AppPaths:
    return AppPaths(
        state=tmp_path / "state",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime" if runtime else None,
    )


def _token(marker: str) -> bytes:
    return json.dumps(
        {
            "di_token": f"access-{marker}",
            "di_refresh_token": f"refresh-{marker}",
            "di_client_id": f"client-{marker}",
        }
    ).encode()


def _session(
    account: str = "synthetic-account-101", marker: str = "refreshed"
) -> AuthenticatedSession:
    return AuthenticatedSession(account_id=account, token_json=_token(marker))


def _raw_activity(activity_id: int = 101, *, name: str = "Synthetic ride") -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": name,
        "activityType": {"typeKey": "virtual_cycling"},
        "startTimeLocal": "2026-08-25 18:00:00",
        "duration": 3600,
        "distance": 25000,
        "latitude": "must-not-persist",
        "longitude": "must-not-persist",
    }


class _FakeGateway(ActivityGateway):
    def __init__(
        self,
        *,
        payload: object | None = None,
        session: AuthenticatedSession | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.payload = [_raw_activity()] if payload is None else payload
        self.session = session or _session()
        self.failure = failure
        self.calls: list[tuple[bytes, date, date]] = []

    def fetch(self, token_json: bytes, start_date: date, end_date: date) -> ActivityFetch:
        self.calls.append((token_json, start_date, end_date))
        if self.failure is not None:
            raise self.failure
        return ActivityFetch(session=self.session, payload=self.payload)


def _configured_service(
    tmp_path: Path,
    *,
    gateway: _FakeGateway | None = None,
    runtime: bool = True,
) -> tuple[ActivitySyncService, AppPaths, _FakeGateway]:
    paths = _paths(tmp_path, runtime=runtime)
    store = AuthStore(paths)
    store.persist(_session(marker="stored"))
    selected_gateway = gateway or _FakeGateway()
    service = ActivitySyncService(
        paths=paths,
        auth_store=store,
        gateway=selected_gateway,
        repository=ActivityRepository(paths.activity_database),
        summary=SummaryCache(paths.summary_file),
        today=lambda: _TODAY,
        now=lambda: _NOW,
    )
    return service, paths, selected_gateway


def test_first_refresh_fetches_full_90_day_period_and_persists_refreshed_tokens(
    tmp_path: Path,
) -> None:
    service, paths, gateway = _configured_service(tmp_path)

    result = service.refresh()

    assert result.mode == "full"
    assert result.start_date == date(2026, 5, 29)
    assert result.end_date == _TODAY
    assert result.fetched_count == 1
    assert result.deleted_count == 0
    assert gateway.calls == [(_token("stored"), date(2026, 5, 29), _TODAY)]
    assert paths.token_file.read_bytes() == _token("refreshed")
    database_bytes = paths.activity_database.read_bytes()
    summary = json.loads(paths.summary_file.read_bytes())
    assert b"latitude" not in database_bytes
    assert b"longitude" not in database_bytes
    assert summary["asOfLocalDate"] == "2026-08-26"
    assert summary["periods"][-1]["overall"]["activityCount"] == 1


def test_later_refresh_on_same_day_uses_seven_day_overlap(tmp_path: Path) -> None:
    service, _, gateway = _configured_service(tmp_path)
    service.refresh()
    gateway.calls.clear()

    result = service.refresh()

    assert result.mode == "incremental"
    assert result.start_date == date(2026, 8, 20)
    assert gateway.calls == [(_token("refreshed"), date(2026, 8, 20), _TODAY)]


def test_force_full_overrides_same_day_incremental_schedule(tmp_path: Path) -> None:
    service, _, gateway = _configured_service(tmp_path)
    service.refresh()
    gateway.calls.clear()

    result = service.refresh(force_full=True)

    assert result.mode == "full"
    assert gateway.calls[0][1] == date(2026, 5, 29)


def test_refresh_without_tokens_fails_before_garmin_request(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    gateway = _FakeGateway()
    service = ActivitySyncService(
        paths=paths,
        auth_store=AuthStore(paths),
        gateway=gateway,
        repository=ActivityRepository(paths.activity_database),
        summary=SummaryCache(paths.summary_file),
    )

    with pytest.raises(ActivityAuthenticationRequiredError):
        service.refresh()

    assert gateway.calls == []
    assert paths.activity_database.exists() is False


def test_malformed_response_preserves_previous_database_and_tokens(tmp_path: Path) -> None:
    gateway = _FakeGateway()
    service, paths, _ = _configured_service(tmp_path, gateway=gateway)
    service.refresh()
    original_database = paths.activity_database.read_bytes()
    original_tokens = paths.token_file.read_bytes()
    original_summary = paths.summary_file.read_bytes()
    gateway.payload = [_raw_activity(name="")]
    gateway.session = _session(marker="must-not-persist")

    with pytest.raises(ActivityDataError):
        service.refresh()

    assert paths.activity_database.read_bytes() == original_database
    assert paths.token_file.read_bytes() == original_tokens
    assert paths.summary_file.read_bytes() == original_summary


def test_invalid_summary_preserves_database_but_reports_data_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, paths, _ = _configured_service(tmp_path)
    monkeypatch.setattr(summary_module, "MAX_SUMMARY_BYTES", 1)

    with pytest.raises(ActivityDataError):
        service.refresh()

    with closing(sqlite3.connect(paths.activity_database)) as connection:
        count = connection.execute("SELECT count(*) FROM activities").fetchone()[0]
    assert count == 1
    assert paths.summary_file.exists() is False


def test_failed_summary_write_preserves_database_but_reports_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, paths, _ = _configured_service(tmp_path)

    def fail_write(destination: Path, content: bytes) -> None:
        raise OSError("fabricated interrupted write")

    monkeypatch.setattr(summary_module, "atomic_write_private", fail_write)

    with pytest.raises(ActivityStorageError):
        service.refresh()

    with closing(sqlite3.connect(paths.activity_database)) as connection:
        count = connection.execute("SELECT count(*) FROM activities").fetchone()[0]
    assert count == 1
    assert paths.summary_file.exists() is False


def test_different_account_cannot_reach_activity_database(tmp_path: Path) -> None:
    gateway = _FakeGateway(session=_session(account="synthetic-account-202"))
    service, paths, _ = _configured_service(tmp_path, gateway=gateway)

    with pytest.raises(AccountMismatchError):
        service.refresh()

    assert paths.activity_database.exists() is True
    with closing(sqlite3.connect(paths.activity_database)) as connection:
        count = connection.execute("SELECT count(*) FROM activities").fetchone()[0]
    assert count == 0


def test_overlapping_refresh_is_mapped_to_domain_failure(tmp_path: Path) -> None:
    service, paths, gateway = _configured_service(tmp_path)

    with (
        activity_refresh_lock(paths.sync_lock_file),
        pytest.raises(ActivityRefreshInProgressError),
    ):
        service.refresh()

    assert gateway.calls == []


def test_refresh_without_runtime_directory_is_configuration_failure(tmp_path: Path) -> None:
    service, _, gateway = _configured_service(tmp_path, runtime=False)

    with pytest.raises(ActivitySyncConfigurationError):
        service.refresh()

    assert gateway.calls == []


def test_unsafe_lock_path_is_storage_failure(tmp_path: Path) -> None:
    service, paths, gateway = _configured_service(tmp_path)
    assert paths.runtime is not None
    ensure_private_directory(paths.runtime)
    target = tmp_path / "target-lock"
    target.write_bytes(b"keep")
    assert paths.sync_lock_file is not None
    paths.sync_lock_file.symlink_to(target)

    with pytest.raises(ActivityStorageError):
        service.refresh()

    assert gateway.calls == []
    assert target.read_bytes() == b"keep"
