import json
from collections.abc import Iterator, Mapping
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from omarchy_garmin.auth import (
    AccountMismatchError,
    AuthenticationRejectedError,
    AuthNetworkError,
    AuthRateLimitedError,
    AuthRemoteServiceError,
    AuthStatus,
    AuthStorageError,
    InteractiveTerminalRequiredError,
    InvalidAuthResponseError,
)
from omarchy_garmin.cli import OUTPUT_SCHEMA_VERSION, run
from omarchy_garmin.errors import ERROR_SPECS, ErrorCode, ExitStatus


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


class _FailingEnvironment(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        raise RuntimeError("fabricated-sensitive-value")

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


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
        "cache": "/home/example/.cache/omarchy-garmin-activities",
        "data": "/home/example/.local/share/omarchy-garmin-activities",
        "runtime": "/run/user/1000/omarchy-garmin-activities",
        "state": "/home/example/.local/state/omarchy-garmin-activities",
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
    assert "Garmin Activities backend is ready." in stdout.getvalue()
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
