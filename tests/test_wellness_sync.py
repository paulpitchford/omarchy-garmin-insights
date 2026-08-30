import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from omarchy_garmin.auth import AuthenticatedSession, AuthStore
from omarchy_garmin.locking import activity_refresh_lock
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.wellness import (
    InvalidWellnessDataError,
    UnsupportedWellnessSourceError,
    WellnessFailureClassification,
    WellnessSource,
)
from omarchy_garmin.wellness_database import WellnessCadenceState, WellnessRepository
from omarchy_garmin.wellness_presentation import WellnessPresentationCache
from omarchy_garmin.wellness_sync import (
    MAX_WELLNESS_DATA_CALLS,
    WellnessAccountScopeError,
    WellnessAuthenticationError,
    WellnessGatewayConnection,
    WellnessNetworkError,
    WellnessRateLimitedError,
    WellnessRefreshInProgressError,
    WellnessRemoteServiceError,
    WellnessStorageError,
    WellnessSyncConfigurationError,
    WellnessSyncService,
)

TODAY = date(2026, 8, 26)
NOW = datetime(2026, 8, 26, 12, 30, tzinfo=UTC)
ACCOUNT_ID = "synthetic-account-101"


def _token(marker: str) -> bytes:
    return json.dumps(
        {
            "di_token": f"access-{marker}",
            "di_refresh_token": f"refresh-{marker}",
            "di_client_id": f"client-{marker}",
        }
    ).encode()


def _session(account_id: str = ACCOUNT_ID, marker: str = "refreshed") -> AuthenticatedSession:
    return AuthenticatedSession(account_id=account_id, token_json=_token(marker))


def _paths(tmp_path: Path, *, runtime: bool = True) -> AppPaths:
    return AppPaths(
        state=tmp_path / "state",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime" if runtime else None,
    )


class _Clock:
    def __init__(self) -> None:
        self.today = TODAY
        self.now = NOW

    def local_date(self) -> date:
        return self.today

    def instant(self) -> datetime:
        return self.now


class _FakeConnection(WellnessGatewayConnection):
    def __init__(
        self,
        *,
        session: AuthenticatedSession,
        failures: dict[str, Exception],
        fail_on_call: dict[str, int],
    ) -> None:
        self._session = session
        self._failures = failures
        self._fail_on_call = fail_on_call
        self._call_counts: dict[str, int] = {}
        self.calls: list[tuple[str, date, date]] = []
        self._request_attempts = 1  # fixed account-verification call

    @property
    def request_attempts(self) -> int:
        return self._request_attempts

    def refreshed_session(self) -> AuthenticatedSession:
        return self._session

    def _call(self, name: str, start_date: date, end_date: date) -> None:
        self.calls.append((name, start_date, end_date))
        self._request_attempts += 1
        self._call_counts[name] = self._call_counts.get(name, 0) + 1
        failure = self._failures.get(name)
        if failure is not None and self._call_counts[name] == self._fail_on_call.get(name, 1):
            raise failure

    def user_summary(self, requested_date: date) -> object:
        self._call("user_summary", requested_date, requested_date)
        return {
            "calendarDate": requested_date.isoformat(),
            "totalSteps": 9_999,
            "dailyStepGoal": 10_000,
            "restingHeartRate": 55,
            "private": "discard-me",
        }

    def daily_steps(self, start_date: date, end_date: date) -> object:
        self._call("steps", start_date, end_date)
        return [
            {"calendarDate": day.isoformat(), "totalSteps": 111}
            for day in _dates(start_date, end_date)
        ]

    def body_battery(self, start_date: date, end_date: date) -> object:
        self._call("body_battery", start_date, end_date)
        return [
            {
                "date": day.isoformat(),
                "charged": 40,
                "drained": 30,
                "bodyBatteryValuesArray": [[_body_timestamp(day), 60]],
            }
            for day in _dates(start_date, end_date)
        ]

    def sleep_range(self, start_date: date, end_date: date) -> object:
        self._call("sleep_range", start_date, end_date)
        return [
            {"calendarDate": day.isoformat(), "overallSleepScore": 77}
            for day in _dates(start_date, end_date)
        ]

    def sleep_detail(self, requested_date: date) -> object:
        self._call("sleep_detail", requested_date, requested_date)
        return {
            "dailySleepDTO": {
                "calendarDate": requested_date.isoformat(),
                "sleepTimeSeconds": 27_000,
                "deepSleepSeconds": 4_000,
                "lightSleepSeconds": 16_000,
                "remSleepSeconds": 6_000,
                "awakeSleepSeconds": 1_000,
                "sleepScores": {"overall": {"value": 88}},
            }
        }

    def hrv_range(self, start_date: date, end_date: date) -> object:
        self._call("hrv_range", start_date, end_date)
        return {
            "hrvSummaries": [
                {
                    "calendarDate": day.isoformat(),
                    "weeklyAvg": 44,
                    "lastNightAvg": 45,
                    "status": "BALANCED",
                    "baseline": {"balancedLow": 35, "balancedUpper": 55},
                }
                for day in _dates(start_date, end_date)
            ]
        }

    def hrv_detail(self, requested_date: date) -> object:
        self._call("hrv_detail", requested_date, requested_date)
        return {
            "hrvSummary": {
                "calendarDate": requested_date.isoformat(),
                "weeklyAvg": 46,
                "lastNightAvg": 47,
                "status": "BALANCED",
                "baseline": {"balancedLow": 36, "balancedUpper": 56},
            }
        }

    def resting_heart_rate(self, start_date: date, end_date: date) -> object:
        self._call("resting_heart_rate", start_date, end_date)
        return [
            {"calendarDate": day.isoformat(), "value": 50} for day in _dates(start_date, end_date)
        ]

    def training_readiness(self, requested_date: date) -> object:
        self._call("training_readiness", requested_date, requested_date)
        return [
            {
                "calendarDate": requested_date.isoformat(),
                "timestampLocal": f"{requested_date.isoformat()}T07:30:00",
                "inputContext": "AFTER_WAKEUP_RESET",
                "score": 74,
                "level": "HIGH",
            }
        ]


class _FakeGateway:
    def __init__(
        self,
        *,
        session: AuthenticatedSession | None = None,
        failures: dict[str, Exception] | None = None,
        fail_on_call: dict[str, int] | None = None,
        connect_failure: Exception | None = None,
    ) -> None:
        self.session = session or _session()
        self.failures = failures or {}
        self.fail_on_call = fail_on_call or {}
        self.connect_failure = connect_failure
        self.connections: list[_FakeConnection] = []
        self.tokens: list[bytes] = []

    @contextmanager
    def connect(self, token_json: bytes) -> Iterator[_FakeConnection]:
        self.tokens.append(token_json)
        if self.connect_failure is not None:
            raise self.connect_failure
        connection = _FakeConnection(
            session=self.session,
            failures=self.failures,
            fail_on_call=self.fail_on_call,
        )
        self.connections.append(connection)
        yield connection


class _Configured:
    def __init__(
        self,
        tmp_path: Path,
        gateway: _FakeGateway | None = None,
        *,
        presentation: bool = False,
    ) -> None:
        self.paths = _paths(tmp_path)
        self.store = AuthStore(self.paths)
        self.store.persist(_session(marker="stored"))
        self.clock = _Clock()
        self.gateway = gateway or _FakeGateway()
        self.service = WellnessSyncService(
            paths=self.paths,
            auth_store=self.store,
            gateway=self.gateway,
            presentation=(
                WellnessPresentationCache(self.paths.wellness_file) if presentation else None
            ),
            today=self.clock.local_date,
            now=self.clock.instant,
        )

    @property
    def repository(self) -> WellnessRepository:
        scope = self.store.read_scope()
        assert scope is not None
        return WellnessRepository(self.paths.activity_database, scope)


def _dates(start_date: date, end_date: date) -> list[date]:
    return [
        start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)
    ]


def _body_timestamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp() * 1_000)


def _source(result: Any, source: WellnessSource) -> Any:
    return next(item for item in result.sources if item.source is source)


def test_optional_presentation_cache_is_generated_after_source_commits(tmp_path: Path) -> None:
    configured = _Configured(tmp_path, presentation=True)

    result = configured.service.refresh()

    payload: dict[str, Any] = json.loads(configured.paths.wellness_file.read_bytes())
    assert result.cache_updated is True
    assert payload["asOfLocalDate"] == TODAY.isoformat()
    assert payload["days"][-1]["steps"] == {"goal": 10_000, "value": 9_999}
    assert payload["sources"][0]["refreshedAt"] == "2026-08-26T12:30:00Z"


def test_optional_presentation_failure_preserves_cache_and_source_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _Configured(tmp_path, presentation=True)
    first = configured.service.refresh()
    original = configured.paths.wellness_file.read_bytes()
    configured.paths.summary_file.write_bytes(b"fabricated valid activity summary")
    configured.clock.now += timedelta(minutes=31)

    def fail_write(destination: Path, content: bytes) -> None:
        raise OSError("fabricated interrupted presentation write")

    monkeypatch.setattr(
        "omarchy_garmin.wellness_presentation.atomic_write_private",
        fail_write,
    )

    result = configured.service.refresh()

    assert first.cache_updated is True
    assert result.cache_updated is False
    assert _source(result, WellnessSource.USER_SUMMARY).refreshed is True
    assert configured.paths.wellness_file.read_bytes() == original
    assert configured.paths.summary_file.read_bytes() == b"fabricated valid activity summary"


def test_initial_refresh_uses_exact_bounded_full_plan_and_precedence(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)

    result = configured.service.refresh()

    assert result.full_reconciliation is True
    assert result.request_attempts == 18
    assert result.request_attempts <= 20
    connection = configured.gateway.connections[0]
    assert len(connection.calls) == 17 == MAX_WELLNESS_DATA_CALLS - 1
    assert [call for call in connection.calls if call[0] == "steps"] == [
        ("steps", date(2026, 7, 28), date(2026, 8, 24)),
        ("steps", date(2026, 8, 25), TODAY),
    ]
    assert [call for call in connection.calls if call[0] == "body_battery"] == [
        ("body_battery", date(2026, 7, 28), date(2026, 8, 3)),
        ("body_battery", date(2026, 8, 4), date(2026, 8, 10)),
        ("body_battery", date(2026, 8, 11), date(2026, 8, 17)),
        ("body_battery", date(2026, 8, 18), date(2026, 8, 24)),
        ("body_battery", date(2026, 8, 25), TODAY),
    ]
    assert [call[0] for call in connection.calls].count("sleep_detail") == 2
    assert [call[0] for call in connection.calls].count("training_readiness") == 2
    today = configured.repository.wellness_between(TODAY, TODAY)[0]
    assert today.steps == 9_999
    assert today.step_goal == 10_000
    assert today.resting_heart_rate_bpm == 55
    assert today.sleep_score == 88
    assert today.hrv_weekly_average_ms == 46
    assert today.body_battery_latest == 60
    assert today.training_readiness_score == 74
    assert _source(result, WellnessSource.STEPS).stored_count == 30
    assert _source(result, WellnessSource.SLEEP).stored_count == 32
    assert configured.paths.token_file.read_bytes() == _token("refreshed")


def test_immediate_repeat_is_idempotent_and_preserves_existing_presentation(
    tmp_path: Path,
) -> None:
    configured = _Configured(tmp_path, presentation=True)
    configured.service.refresh()
    original = configured.paths.wellness_file.read_bytes()

    result = configured.service.refresh()

    assert result.request_attempts == 0
    assert result.cache_updated is False
    assert configured.paths.wellness_file.read_bytes() == original
    assert len(configured.gateway.connections) == 1
    assert len(configured.repository.wellness_between(TODAY - timedelta(days=29), TODAY)) == 30


def test_current_cadence_and_backfill_cooldown_are_independent(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)
    configured.service.refresh()
    configured.clock.now += timedelta(minutes=31)

    fast_result = configured.service.refresh()

    assert fast_result.request_attempts == 3
    assert [call[0] for call in configured.gateway.connections[-1].calls] == [
        "user_summary",
        "body_battery",
    ]

    configured.clock.now += timedelta(minutes=30)
    backfill_result = configured.service.refresh()

    assert backfill_result.request_attempts == 7
    names = [call[0] for call in configured.gateway.connections[-1].calls]
    assert names == [
        "user_summary",
        "body_battery",
        "sleep_detail",
        "sleep_detail",
        "training_readiness",
        "training_readiness",
    ]


def test_manual_refresh_bypasses_only_current_value_cadence(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)
    configured.service.refresh()

    result = configured.service.refresh(manual=True)

    assert result.full_reconciliation is False
    assert result.request_attempts == 5
    assert [call[0] for call in configured.gateway.connections[-1].calls] == [
        "user_summary",
        "body_battery",
        "sleep_detail",
        "training_readiness",
    ]


def test_historical_overlap_runs_once_each_local_date_and_full_no_more_than_weekly(
    tmp_path: Path,
) -> None:
    configured = _Configured(tmp_path)
    configured.service.refresh()
    configured.clock.today += timedelta(days=1)
    configured.clock.now += timedelta(days=1)

    incremental = configured.service.refresh()

    assert incremental.full_reconciliation is False
    assert ("steps", date(2026, 8, 21), date(2026, 8, 27)) in configured.gateway.connections[
        -1
    ].calls
    assert (
        len([call for call in configured.gateway.connections[-1].calls if call[0] == "steps"]) == 1
    )

    configured.clock.today = TODAY + timedelta(days=7)
    configured.clock.now = NOW + timedelta(days=7)
    weekly = configured.service.refresh()

    assert weekly.full_reconciliation is True
    assert (
        len([call for call in configured.gateway.connections[-1].calls if call[0] == "steps"]) == 2
    )


def test_invalid_and_unsupported_sources_do_not_discard_other_successes(tmp_path: Path) -> None:
    gateway = _FakeGateway(
        failures={
            "hrv_range": InvalidWellnessDataError(WellnessSource.HRV),
            "sleep_range": UnsupportedWellnessSourceError(WellnessSource.SLEEP),
        }
    )
    configured = _Configured(tmp_path, gateway, presentation=True)

    result = configured.service.refresh()

    presentation: dict[str, Any] = json.loads(configured.paths.wellness_file.read_bytes())
    assert result.cache_updated is True
    assert presentation["sources"][3]["failure"] == "unsupported"
    assert presentation["sources"][4]["failure"] == "invalid_data"
    original_presentation = configured.paths.wellness_file.read_bytes()
    repeat = configured.service.refresh()
    assert repeat.cache_updated is False
    assert configured.paths.wellness_file.read_bytes() == original_presentation
    assert _source(result, WellnessSource.STEPS).refreshed is True
    assert _source(result, WellnessSource.BODY_BATTERY).refreshed is True
    assert _source(result, WellnessSource.HRV).failure is WellnessFailureClassification.INVALID_DATA
    assert (
        _source(result, WellnessSource.SLEEP).failure is WellnessFailureClassification.UNSUPPORTED
    )
    assert _source(result, WellnessSource.SLEEP).refreshed is True
    stored = configured.repository.wellness_between(TODAY, TODAY)[0]
    assert stored.steps == 9_999
    assert stored.sleep_total_seconds == 27_000
    assert stored.hrv_weekly_average_ms == 46
    assert "discard-me" not in configured.paths.activity_database.read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_failed_second_range_chunk_commits_none_of_that_source(tmp_path: Path) -> None:
    gateway = _FakeGateway(
        failures={"steps": InvalidWellnessDataError(WellnessSource.STEPS)},
        fail_on_call={"steps": 2},
    )
    configured = _Configured(tmp_path, gateway)

    result = configured.service.refresh()

    oldest = configured.repository.wellness_between(date(2026, 7, 28), date(2026, 7, 28))[0]
    assert oldest.steps is None
    assert oldest.body_battery_latest == 60
    assert _source(result, WellnessSource.STEPS).refreshed is False
    assert (
        _source(result, WellnessSource.STEPS).failure is WellnessFailureClassification.INVALID_DATA
    )


def test_network_and_remote_failures_remain_source_specific(tmp_path: Path) -> None:
    gateway = _FakeGateway(
        failures={
            "steps": WellnessNetworkError("safe offline classification"),
            "body_battery": WellnessRemoteServiceError("safe remote classification"),
        }
    )
    configured = _Configured(tmp_path, gateway)

    result = configured.service.refresh()

    assert (
        _source(result, WellnessSource.STEPS).failure
        is WellnessFailureClassification.OFFLINE_TRANSPORT
    )
    assert (
        _source(result, WellnessSource.BODY_BATTERY).failure
        is WellnessFailureClassification.REMOTE_SERVICE
    )
    assert _source(result, WellnessSource.SLEEP).refreshed is True


def test_authentication_failure_stops_later_source_requests(tmp_path: Path) -> None:
    gateway = _FakeGateway(
        failures={"steps": WellnessAuthenticationError("safe authentication classification")}
    )
    configured = _Configured(tmp_path, gateway)

    result = configured.service.refresh()

    assert (
        _source(result, WellnessSource.STEPS).failure
        is WellnessFailureClassification.AUTHENTICATION
    )
    assert gateway.connections[0].calls == [("steps", date(2026, 7, 28), date(2026, 8, 24))]


def test_source_storage_failure_does_not_erase_other_source_success(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)
    configured.repository.set_collection_enabled(True)
    with closing(sqlite3.connect(configured.paths.activity_database)) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_steps_source
            BEFORE INSERT ON wellness_source_state
            WHEN NEW.source = 'steps'
            BEGIN
                SELECT RAISE(ABORT, 'fabricated storage interruption');
            END
            """
        )
        connection.commit()

    result = configured.service.refresh()

    assert (
        _source(result, WellnessSource.STEPS).failure is WellnessFailureClassification.LOCAL_STORAGE
    )
    assert _source(result, WellnessSource.BODY_BATTERY).refreshed is True
    oldest = configured.repository.wellness_between(date(2026, 7, 28), date(2026, 7, 28))[0]
    assert oldest.steps is None
    assert oldest.body_battery_latest == 60


def test_rate_limit_stops_later_requests_but_keeps_earlier_source_commit(tmp_path: Path) -> None:
    gateway = _FakeGateway(failures={"body_battery": WellnessRateLimitedError("private")})
    configured = _Configured(tmp_path, gateway)

    result = configured.service.refresh()

    assert _source(result, WellnessSource.STEPS).refreshed is True
    assert (
        _source(result, WellnessSource.BODY_BATTERY).failure
        is WellnessFailureClassification.RATE_LIMIT
    )
    assert [call[0] for call in gateway.connections[0].calls] == [
        "steps",
        "steps",
        "body_battery",
    ]
    assert configured.repository.wellness_between(TODAY, TODAY)[0].steps == 111


def test_collection_stop_prevents_requests_and_updates_only_local_presentation(
    tmp_path: Path,
) -> None:
    configured = _Configured(tmp_path, presentation=True)
    configured.repository.upsert_source(
        WellnessSource.STEPS,
        [],
        as_of_date=TODAY,
        refreshed_at=NOW,
    )
    configured.repository.set_collection_enabled(False)

    result = configured.service.refresh(manual=True)

    presentation: dict[str, Any] = json.loads(configured.paths.wellness_file.read_bytes())
    assert result.collection_enabled is False
    assert result.request_attempts == 0
    assert result.cache_updated is True
    assert presentation["collectionEnabled"] is False
    assert configured.gateway.tokens == []
    assert configured.repository.collection_enabled() is False


def test_failed_cadence_reservation_stops_before_first_data_request(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)
    configured.repository.set_collection_enabled(True)
    with closing(sqlite3.connect(configured.paths.activity_database)) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_cadence_reservation
            BEFORE INSERT ON sync_state
            WHEN NEW.key LIKE 'wellness_%'
            BEGIN
                SELECT RAISE(ABORT, 'fabricated cadence interruption');
            END
            """
        )
        connection.commit()

    with pytest.raises(WellnessStorageError):
        configured.service.refresh()

    assert configured.gateway.connections[0].calls == []
    assert configured.repository.cadence_state() == WellnessCadenceState()


def test_different_verified_account_is_rejected_before_wellness_transaction(tmp_path: Path) -> None:
    gateway = _FakeGateway(session=_session("synthetic-account-202"))
    configured = _Configured(tmp_path, gateway)

    with pytest.raises(WellnessAccountScopeError):
        configured.service.refresh()

    assert gateway.connections[0].calls == []
    assert configured.paths.activity_database.exists() is False


def test_authentication_failure_during_verification_is_distinct(tmp_path: Path) -> None:
    gateway = _FakeGateway(connect_failure=WellnessAuthenticationError("verification failed"))
    configured = _Configured(tmp_path, gateway)

    with pytest.raises(WellnessAuthenticationError) as caught:
        configured.service.refresh()

    assert caught.value.classification is WellnessFailureClassification.AUTHENTICATION
    assert configured.paths.activity_database.exists() is False


def test_missing_authentication_fails_before_repository_or_gateway(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    gateway = _FakeGateway()
    service = WellnessSyncService(paths=paths, auth_store=AuthStore(paths), gateway=gateway)

    with pytest.raises(WellnessAuthenticationError):
        service.refresh()

    assert gateway.tokens == []
    assert paths.activity_database.exists() is False


def test_shared_lock_prevents_overlap_with_activity_refresh(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)

    with (
        activity_refresh_lock(configured.paths.sync_lock_file),
        pytest.raises(WellnessRefreshInProgressError),
    ):
        configured.service.refresh()

    assert configured.gateway.tokens == []


def test_missing_runtime_and_malformed_cadence_fail_without_request(tmp_path: Path) -> None:
    configured = _Configured(tmp_path)
    configured.repository.set_collection_enabled(True)
    with closing(sqlite3.connect(configured.paths.activity_database)) as connection:
        connection.execute(
            "INSERT INTO sync_state (key, value) VALUES ('wellness_backfill_at', 'invalid')"
        )
        connection.commit()

    with pytest.raises(WellnessStorageError):
        configured.service.refresh()
    assert configured.gateway.tokens == []

    paths = _paths(tmp_path / "other", runtime=False)
    store = AuthStore(paths)
    store.persist(_session())
    no_runtime = WellnessSyncService(paths=paths, auth_store=store, gateway=_FakeGateway())
    with pytest.raises(WellnessSyncConfigurationError):
        no_runtime.refresh()
