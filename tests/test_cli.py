import json
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import omarchy_garmin.cli as cli_module
from omarchy_garmin.activities import Activity
from omarchy_garmin.activity_views import (
    ActivityDetail,
    ActivityPage,
    ActivityViewStorageError,
)
from omarchy_garmin.auth import (
    AccountMismatchError,
    AuthenticationRejectedError,
    AuthNetworkError,
    AuthRateLimitedError,
    AuthRefreshInProgressError,
    AuthRemoteServiceError,
    AuthStatus,
    AuthStorageError,
    InteractiveTerminalRequiredError,
    InvalidAuthResponseError,
)
from omarchy_garmin.cli import OUTPUT_SCHEMA_VERSION, run
from omarchy_garmin.display_cache import (
    DisplayCacheDataError,
    DisplayCacheKind,
    DisplayCacheStorageError,
)
from omarchy_garmin.errors import ERROR_SPECS, ErrorCode, ExitStatus
from omarchy_garmin.sync import (
    ActivityAuthenticationRequiredError,
    ActivityDataError,
    ActivityNetworkError,
    ActivityRateLimitedError,
    ActivityRefreshInProgressError,
    ActivityRemoteServiceError,
    ActivityStorageError,
    ActivitySyncConfigurationError,
    RefreshResult,
)


class _FakeAuthOperations:
    def __init__(
        self,
        *,
        status: AuthStatus | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.status_result = status or AuthStatus(False, False, False)
        self.failure = failure
        self.calls: list[str] = []

    def _record(self, action: str) -> None:
        self.calls.append(action)
        if self.failure is not None:
            raise self.failure

    def status(self) -> AuthStatus:
        self._record("status")
        return self.status_result

    def login(self) -> AuthStatus:
        self._record("login")
        return AuthStatus(True, True, True)

    def logout(self) -> None:
        self._record("logout")

    def purge(self) -> None:
        self._record("purge")


class _FakeRefreshOperations:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.force_full_calls: list[bool] = []

    def refresh(self, *, force_full: bool = False) -> RefreshResult:
        self.force_full_calls.append(force_full)
        if self.failure is not None:
            raise self.failure
        return RefreshResult(
            mode="full" if force_full else "incremental",
            start_date=date(2026, 5, 29) if force_full else date(2026, 8, 20),
            end_date=date(2026, 8, 26),
            fetched_count=3,
            deleted_count=1,
            trends_updated=True,
        )


class _FakeActivityViewOperations:
    def __init__(
        self,
        *,
        activity: Activity | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.activity = activity
        self.failure = failure
        self.list_calls: list[tuple[str, date, str | None, int]] = []
        self.detail_calls: list[str] = []

    def list_activities(
        self,
        *,
        period_key: str,
        as_of_date: date,
        type_key: str | None,
        offset: int,
    ) -> ActivityPage:
        self.list_calls.append((period_key, as_of_date, type_key, offset))
        if self.failure is not None:
            raise self.failure
        activities = () if self.activity is None else (self.activity,)
        return ActivityPage(
            period_key=period_key,
            start_date=date(2026, 8, 20),
            end_date=as_of_date,
            type_key=type_key,
            offset=offset,
            activities=activities,
            has_more=False,
            next_offset=None,
            stale=False,
        )

    def activity_detail(self, activity_id: str) -> ActivityDetail:
        self.detail_calls.append(activity_id)
        if self.failure is not None:
            raise self.failure
        return ActivityDetail(self.activity)


class _FakeDisplayCacheOperations:
    def __init__(self, *, content: str = "synthetic", failure: Exception | None = None) -> None:
        self.content = content
        self.failure = failure
        self.calls: list[DisplayCacheKind] = []

    def read(self, kind: DisplayCacheKind) -> str:
        self.calls.append(kind)
        if self.failure is not None:
            raise self.failure
        return self.content


class _FailingEnvironment(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        raise RuntimeError("fabricated-sensitive-value")

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def test_cache_read_json_has_stable_bounded_contract() -> None:
    operations = _FakeDisplayCacheOperations(content='{"schemaVersion":1}\n')
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["cache", "read", "--json", "--kind", "summary"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
        display_cache_operations=operations,
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.SUCCESS
    assert stderr.getvalue() == ""
    assert operations.calls == [DisplayCacheKind.SUMMARY]
    assert payload == {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": "cache.read",
        "ok": True,
        "data": {"kind": "summary", "content": '{"schemaVersion":1}\n'},
        "error": None,
    }


def test_cache_read_human_output_does_not_expose_content() -> None:
    operations = _FakeDisplayCacheOperations(content="synthetic-private-content")
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["cache", "read", "--kind", "activity-trends"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
        display_cache_operations=operations,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert stderr.getvalue() == ""
    assert stdout.getvalue() == "activity-trends display cache is available.\n"
    assert "synthetic-private-content" not in stdout.getvalue()


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(DisplayCacheStorageError("fabricated path"), id="storage"),
        pytest.param(DisplayCacheDataError("fabricated content"), id="data"),
    ],
)
def test_cache_read_failure_uses_redacted_local_storage_error(failure: Exception) -> None:
    operations = _FakeDisplayCacheOperations(failure=failure)
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["cache", "read", "--json", "--kind", "summary"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
        display_cache_operations=operations,
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.STORAGE_ERROR
    assert stderr.getvalue() == ""
    assert payload["command"] == "cache.read"
    assert payload["error"]["code"] == "local_storage_error"
    assert "fabricated" not in stdout.getvalue()


def test_cache_read_rejects_unsupported_kind_without_reflection() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["cache", "read", "--json", "--kind", "hostile-kind"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.INVALID_ARGUMENTS
    assert payload["command"] == "cache.read"
    assert payload["error"]["code"] == "invalid_arguments"
    assert "hostile-kind" not in stdout.getvalue()


def test_cache_read_rejects_output_above_process_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = _FakeDisplayCacheOperations(content="synthetic")
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(cli_module, "MAX_DISPLAY_CACHE_OUTPUT_BYTES", 1)

    exit_status = run(
        ["cache", "read", "--json", "--kind", "summary"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
        display_cache_operations=operations,
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.STORAGE_ERROR
    assert payload["error"]["code"] == "local_storage_error"


def test_doctor_json_has_stable_machine_contract() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["doctor", "--json"],
        stdout=stdout,
        stderr=stderr,
        environment={"XDG_RUNTIME_DIR": "/run/user/1000"},
        home=Path("/home/example"),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.SUCCESS
    assert stderr.getvalue() == ""
    assert payload["schemaVersion"] == OUTPUT_SCHEMA_VERSION
    assert payload["command"] == "doctor"
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["runtimeDirectoryAvailable"] is True
    assert payload["data"]["paths"] == {
        "cache": "/home/example/.cache/omarchy-garmin-insights",
        "data": "/home/example/.local/share/omarchy-garmin-insights",
        "runtime": "/run/user/1000/omarchy-garmin-insights",
        "state": "/home/example/.local/state/omarchy-garmin-insights",
    }


def test_doctor_human_output_marks_missing_runtime_directory() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["doctor"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
    )

    assert exit_status == ExitStatus.SUCCESS
    assert stderr.getvalue() == ""
    assert "Garmin Insights backend is ready." in stdout.getvalue()
    assert "Runtime: unavailable" in stdout.getvalue()


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        pytest.param(ErrorCode.INVALID_ARGUMENTS, 2, id="invalid-arguments"),
        pytest.param(ErrorCode.INVALID_CONFIGURATION, 10, id="configuration"),
        pytest.param(ErrorCode.INTERACTIVE_TERMINAL_REQUIRED, 10, id="terminal-required"),
        pytest.param(ErrorCode.AUTH_REQUIRED, 20, id="auth-required"),
        pytest.param(ErrorCode.AUTHENTICATION_FAILED, 20, id="auth-failed"),
        pytest.param(ErrorCode.ACCOUNT_MISMATCH, 20, id="account-mismatch"),
        pytest.param(ErrorCode.NETWORK_UNAVAILABLE, 30, id="network-unavailable"),
        pytest.param(ErrorCode.RATE_LIMITED, 30, id="rate-limited"),
        pytest.param(ErrorCode.REMOTE_SERVICE_ERROR, 30, id="remote-service"),
        pytest.param(ErrorCode.INVALID_REMOTE_DATA, 40, id="invalid-remote-data"),
        pytest.param(ErrorCode.LOCAL_STORAGE_ERROR, 50, id="local-storage"),
        pytest.param(ErrorCode.REFRESH_IN_PROGRESS, 60, id="refresh-in-progress"),
        pytest.param(ErrorCode.INTERNAL_ERROR, 70, id="internal"),
    ],
)
def test_error_code_has_stable_exit_status(code: ErrorCode, expected_status: int) -> None:
    assert ERROR_SPECS[code].exit_status == expected_status


def test_every_error_code_has_a_public_specification() -> None:
    assert set(ERROR_SPECS) == set(ErrorCode)


def test_invalid_arguments_use_bounded_json_error_envelope() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["doctor", "--json", "--password", "fabricated-sensitive-value"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.INVALID_ARGUMENTS
    assert stderr.getvalue() == ""
    assert payload == {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": "doctor",
        "ok": False,
        "data": None,
        "error": {
            "code": "invalid_arguments",
            "message": "Invalid command arguments.",
        },
    }
    assert "fabricated-sensitive-value" not in stdout.getvalue()


def test_unknown_command_is_not_reflected_in_json_error() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["fabricated-sensitive-value", "--json"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.INVALID_ARGUMENTS
    assert stderr.getvalue() == ""
    assert payload["command"] is None
    assert "fabricated-sensitive-value" not in stdout.getvalue()


def test_invalid_arguments_use_redacted_human_error() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["doctor", "--password", "fabricated-sensitive-value"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
    )

    assert exit_status == ExitStatus.INVALID_ARGUMENTS
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Error [invalid_arguments]: Invalid command arguments.\n"
    assert "fabricated-sensitive-value" not in stderr.getvalue()


def test_invalid_configuration_uses_safe_human_error() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["doctor"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("relative/private-home"),
    )

    assert exit_status == ExitStatus.CONFIGURATION_ERROR
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "Error [invalid_configuration]: The backend configuration is invalid.\n"
    )
    assert "relative/private-home" not in stderr.getvalue()


def test_unexpected_failure_uses_redacted_internal_error_envelope() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_status = run(
        ["doctor", "--json"],
        stdout=stdout,
        stderr=stderr,
        environment=_FailingEnvironment(),
        home=Path("/home/example"),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.INTERNAL_ERROR
    assert stderr.getvalue() == ""
    assert payload["error"] == {
        "code": "internal_error",
        "message": "The backend encountered an internal error.",
    }
    assert "fabricated-sensitive-value" not in stdout.getvalue()


def test_auth_status_json_reports_configured_but_unverified_state() -> None:
    stdout = StringIO()
    stderr = StringIO()
    auth = _FakeAuthOperations(status=AuthStatus(True, False, True))

    exit_status = run(
        ["auth", "status", "--json"],
        stdout=stdout,
        stderr=stderr,
        environment={},
        home=Path("/home/example"),
        auth_operations=auth,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": "auth.status",
        "ok": True,
        "data": {
            "configured": True,
            "verified": False,
            "accountScoped": True,
        },
        "error": None,
    }
    assert auth.calls == ["status"]


def test_auth_status_default_composition_is_local_and_non_mutating(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_status = run(
        ["auth", "status", "--json"],
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=tmp_path,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert json.loads(stdout.getvalue())["data"] == {
        "configured": False,
        "verified": False,
        "accountScoped": False,
    }
    assert (tmp_path / ".local").exists() is False


def test_auth_login_default_composition_rejects_redirected_input(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_status = run(
        ["auth", "login", "--json"],
        stdin=StringIO("runner@example.test\n"),
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=tmp_path,
    )

    assert exit_status == ExitStatus.CONFIGURATION_ERROR
    assert json.loads(stdout.getvalue())["error"]["code"] == ("interactive_terminal_required")


def test_auth_status_human_output_marks_unconfigured_state() -> None:
    stdout = StringIO()
    auth = _FakeAuthOperations()

    exit_status = run(
        ["auth", "status"],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        auth_operations=auth,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert stdout.getvalue() == "Garmin authentication is not configured.\n"


def test_auth_login_reports_verified_state() -> None:
    stdout = StringIO()
    auth = _FakeAuthOperations()

    exit_status = run(
        ["auth", "login", "--json"],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        auth_operations=auth,
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.SUCCESS
    assert payload["command"] == "auth.login"
    assert payload["data"] == {
        "configured": True,
        "verified": True,
        "accountScoped": True,
    }
    assert auth.calls == ["login"]


@pytest.mark.parametrize(
    ("action", "expected_data"),
    [
        pytest.param(
            "logout",
            {"configured": False, "localActivityDataRetained": True},
            id="logout",
        ),
        pytest.param(
            "purge",
            {"configured": False, "localDataRetained": False},
            id="purge",
        ),
    ],
)
def test_destructive_auth_commands_require_confirmation_and_return_contract(
    action: str, expected_data: dict[str, object]
) -> None:
    rejected_stdout = StringIO()
    auth = _FakeAuthOperations()

    rejected_status = run(
        ["auth", action, "--json"],
        stdout=rejected_stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        auth_operations=auth,
    )
    confirmed_stdout = StringIO()
    confirmed_status = run(
        ["auth", action, "--json", "--confirm"],
        stdout=confirmed_stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        auth_operations=auth,
    )

    assert rejected_status == ExitStatus.INVALID_ARGUMENTS
    assert auth.calls == [action]
    assert confirmed_status == ExitStatus.SUCCESS
    assert json.loads(confirmed_stdout.getvalue())["data"] == expected_data


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_status"),
    [
        pytest.param(
            InteractiveTerminalRequiredError("private"),
            "interactive_terminal_required",
            10,
            id="terminal",
        ),
        pytest.param(
            AuthenticationRejectedError("private"),
            "authentication_failed",
            20,
            id="authentication",
        ),
        pytest.param(
            AccountMismatchError("private"),
            "account_mismatch",
            20,
            id="account-mismatch",
        ),
        pytest.param(AuthRateLimitedError("private"), "rate_limited", 30, id="rate-limit"),
        pytest.param(
            AuthNetworkError("private"),
            "network_unavailable",
            30,
            id="network",
        ),
        pytest.param(
            AuthRemoteServiceError("private"),
            "remote_service_error",
            30,
            id="remote-service",
        ),
        pytest.param(
            InvalidAuthResponseError("private"),
            "invalid_remote_data",
            40,
            id="invalid-response",
        ),
        pytest.param(
            AuthStorageError("private"),
            "local_storage_error",
            50,
            id="storage",
        ),
        pytest.param(
            AuthRefreshInProgressError("private"),
            "refresh_in_progress",
            60,
            id="refresh-in-progress",
        ),
    ],
)
def test_auth_failures_map_to_redacted_error_contract(
    failure: Exception, expected_code: str, expected_status: int
) -> None:
    stdout = StringIO()

    exit_status = run(
        ["auth", "status", "--json"],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        auth_operations=_FakeAuthOperations(failure=failure),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == expected_status
    assert payload["error"]["code"] == expected_code
    assert "private" not in stdout.getvalue()


def test_activity_list_json_has_bounded_local_contract() -> None:
    activity = Activity(
        activity_id="101",
        name="Fabricated ride <not markup>",
        type_key="synthetic_cycling",
        started_at_local="2026-08-25 18:30:00",
        local_date=date(2026, 8, 25),
        duration_seconds=3600,
        moving_duration_seconds=3500,
        distance_metres=25_000,
        elevation_gain_metres=300,
        energy_joules=2_000_000,
        average_heart_rate_bpm=140,
        maximum_heart_rate_bpm=175,
        average_speed_metres_per_second=7.1,
        average_power_watts=190,
        total_sets=None,
        total_repetitions=None,
    )
    views = _FakeActivityViewOperations(activity=activity)
    stdout = StringIO()

    exit_status = run(
        [
            "activities",
            "list",
            "--json",
            "--period",
            "7Days",
            "--as-of",
            "2026-08-26",
            "--type-key",
            "synthetic_cycling",
        ],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        activity_view_operations=views,
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.SUCCESS
    assert views.list_calls == [("7Days", date(2026, 8, 26), "synthetic_cycling", 0)]
    assert payload["command"] == "activities.list"
    assert payload["data"]["pageSize"] == 20
    assert payload["data"]["activities"][0]["activityId"] == "101"
    assert "https://" not in stdout.getvalue()


def test_activity_detail_not_found_is_a_stable_success_result() -> None:
    views = _FakeActivityViewOperations()
    stdout = StringIO()

    exit_status = run(
        ["activities", "detail", "--json", "--activity-id", "999"],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        activity_view_operations=views,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert views.detail_calls == ["999"]
    assert json.loads(stdout.getvalue())["data"] == {"found": False, "activity": None}


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(
            ["activities", "list", "--json", "--period", "year", "--as-of", "2026-08-26"],
            id="period",
        ),
        pytest.param(
            ["activities", "list", "--json", "--period", "7Days", "--as-of", "invalid"],
            id="date",
        ),
        pytest.param(
            [
                "activities",
                "list",
                "--json",
                "--period",
                "7Days",
                "--as-of",
                "2026-08-26",
                "--offset",
                "1",
            ],
            id="offset",
        ),
        pytest.param(
            ["activities", "detail", "--json", "--activity-id", "1 OR 1=1"],
            id="activity-id",
        ),
    ],
)
def test_invalid_activity_view_arguments_are_redacted(arguments: list[str]) -> None:
    stdout = StringIO()

    exit_status = run(
        arguments,
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        activity_view_operations=_FakeActivityViewOperations(),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == ExitStatus.INVALID_ARGUMENTS
    assert payload["error"]["code"] == "invalid_arguments"
    assert "1 OR 1=1" not in stdout.getvalue()


def test_oversized_activity_view_output_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = StringIO()
    monkeypatch.setattr(cli_module, "MAX_ACTIVITY_VIEW_BYTES", 1)

    exit_status = run(
        [
            "activities",
            "list",
            "--json",
            "--period",
            "7Days",
            "--as-of",
            "2026-08-26",
        ],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        activity_view_operations=_FakeActivityViewOperations(),
    )

    assert exit_status == ExitStatus.STORAGE_ERROR
    assert json.loads(stdout.getvalue())["error"]["code"] == "local_storage_error"


def test_activity_view_storage_failure_uses_redacted_local_error() -> None:
    stdout = StringIO()

    exit_status = run(
        ["activities", "detail", "--json", "--activity-id", "101"],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=Path("/home/example"),
        activity_view_operations=_FakeActivityViewOperations(
            failure=ActivityViewStorageError("private database path")
        ),
    )

    assert exit_status == ExitStatus.STORAGE_ERROR
    assert json.loads(stdout.getvalue())["error"]["code"] == "local_storage_error"
    assert "private database path" not in stdout.getvalue()


def test_activity_list_default_composition_is_local_and_non_mutating(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_status = run(
        [
            "activities",
            "list",
            "--json",
            "--period",
            "today",
            "--as-of",
            datetime.now().astimezone().date().isoformat(),
        ],
        stdout=stdout,
        stderr=StringIO(),
        environment={},
        home=tmp_path,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert json.loads(stdout.getvalue())["data"]["activities"] == []
    assert (tmp_path / ".local").exists() is False


def test_refresh_json_has_bounded_contract_and_forwards_full_option() -> None:
    stdout = StringIO()
    refresh = _FakeRefreshOperations()

    exit_status = run(
        ["refresh", "--json", "--full"],
        stdout=stdout,
        stderr=StringIO(),
        environment={"XDG_RUNTIME_DIR": "/run/user/1000"},
        home=Path("/home/example"),
        refresh_operations=refresh,
    )

    assert exit_status == ExitStatus.SUCCESS
    assert refresh.force_full_calls == [True]
    assert json.loads(stdout.getvalue()) == {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": "refresh",
        "ok": True,
        "data": {
            "mode": "full",
            "startDate": "2026-05-29",
            "endDate": "2026-08-26",
            "fetchedCount": 3,
            "deletedCount": 1,
            "trendsUpdated": True,
        },
        "error": None,
    }


def test_refresh_default_composition_requires_stored_authentication(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_status = run(
        ["refresh", "--json"],
        stdout=stdout,
        stderr=StringIO(),
        environment={"XDG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path,
    )

    assert exit_status == ExitStatus.AUTHENTICATION_ERROR
    assert json.loads(stdout.getvalue())["error"]["code"] == "auth_required"


def test_refresh_human_output_is_concise() -> None:
    stdout = StringIO()

    exit_status = run(
        ["refresh"],
        stdout=stdout,
        stderr=StringIO(),
        environment={"XDG_RUNTIME_DIR": "/run/user/1000"},
        home=Path("/home/example"),
        refresh_operations=_FakeRefreshOperations(),
    )

    assert exit_status == ExitStatus.SUCCESS
    assert stdout.getvalue() == ("Garmin data refreshed (incremental, 3 stored, 1 removed).\n")


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_status"),
    [
        pytest.param(
            ActivitySyncConfigurationError("private"),
            "invalid_configuration",
            10,
            id="configuration",
        ),
        pytest.param(
            ActivityAuthenticationRequiredError("private"),
            "auth_required",
            20,
            id="authentication",
        ),
        pytest.param(ActivityRateLimitedError("private"), "rate_limited", 30, id="rate-limit"),
        pytest.param(
            ActivityNetworkError("private"),
            "network_unavailable",
            30,
            id="network",
        ),
        pytest.param(
            ActivityRemoteServiceError("private"),
            "remote_service_error",
            30,
            id="remote",
        ),
        pytest.param(
            ActivityDataError("private"),
            "invalid_remote_data",
            40,
            id="data",
        ),
        pytest.param(
            ActivityStorageError("private"),
            "local_storage_error",
            50,
            id="storage",
        ),
        pytest.param(
            ActivityRefreshInProgressError("private"),
            "refresh_in_progress",
            60,
            id="concurrency",
        ),
    ],
)
def test_refresh_failures_map_to_redacted_error_contract(
    failure: Exception,
    expected_code: str,
    expected_status: int,
) -> None:
    stdout = StringIO()

    exit_status = run(
        ["refresh", "--json"],
        stdout=stdout,
        stderr=StringIO(),
        environment={"XDG_RUNTIME_DIR": "/run/user/1000"},
        home=Path("/home/example"),
        refresh_operations=_FakeRefreshOperations(failure),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == expected_status
    assert payload["command"] == "refresh"
    assert payload["error"]["code"] == expected_code
    assert "private" not in stdout.getvalue()
