"""Command-line boundary for the Garmin Insights backend."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import NoReturn, TextIO

from omarchy_garmin import __version__
from omarchy_garmin.activity_views import (
    MAX_ACTIVITY_PAGE_OFFSET,
    MAX_ACTIVITY_PAGE_SIZE,
    MAX_ACTIVITY_VIEW_BYTES,
    ActivityViewDataError,
    ActivityViewError,
    ActivityViewOperations,
    ActivityViewRequestError,
    ActivityViewService,
    activity_detail_payload,
    activity_page_payload,
    validate_activity_id,
    validate_type_key,
)
from omarchy_garmin.auth import (
    AccountMismatchError,
    AuthenticationRejectedError,
    AuthError,
    AuthNetworkError,
    AuthOperations,
    AuthRateLimitedError,
    AuthRefreshInProgressError,
    AuthRemoteServiceError,
    AuthService,
    AuthStatus,
    AuthStorageError,
    AuthStore,
    InteractiveTerminalRequiredError,
    InvalidAuthResponseError,
)
from omarchy_garmin.errors import ERROR_SPECS, CommandError, ErrorCode, ExitStatus
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.prompts import TerminalCredentialProvider
from omarchy_garmin.sync import (
    ActivityAuthenticationRequiredError,
    ActivityDataError,
    ActivityNetworkError,
    ActivityRateLimitedError,
    ActivityRefreshInProgressError,
    ActivityRemoteServiceError,
    ActivityStorageError,
    ActivitySyncConfigurationError,
    ActivitySyncError,
    ActivitySyncService,
    RefreshOperations,
)

OUTPUT_SCHEMA_VERSION = 1
_KNOWN_AUTH_COMMANDS = frozenset({"status", "login", "logout", "purge"})


class _ArgumentParser(argparse.ArgumentParser):
    """Convert parser failures into the stable command error contract."""

    def error(self, message: str) -> NoReturn:
        """Reject invalid arguments without reflecting their content in output."""
        raise CommandError(ErrorCode.INVALID_ARGUMENTS)


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = _ArgumentParser(
        prog="omarchy-garmin-insights",
        description="Backend for the Garmin Insights Omarchy plugin",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    doctor = subparsers.add_parser("doctor", help="inspect backend prerequisites and paths")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    auth = subparsers.add_parser("auth", help="manage Garmin authentication")
    auth_subparsers = auth.add_subparsers(
        dest="auth_command", required=True, parser_class=_ArgumentParser
    )
    for action in ("status", "login"):
        auth_command = auth_subparsers.add_parser(action)
        auth_command.add_argument("--json", action="store_true", dest="as_json")
    for action in ("logout", "purge"):
        auth_command = auth_subparsers.add_parser(action)
        auth_command.add_argument("--json", action="store_true", dest="as_json")
        auth_command.add_argument("--confirm", action="store_true")

    refresh = subparsers.add_parser("refresh", help="synchronize recent Garmin activities")
    refresh.add_argument("--json", action="store_true", dest="as_json")
    refresh.add_argument("--full", action="store_true", dest="force_full")

    activities = subparsers.add_parser("activities", help="read local activity details")
    activity_subparsers = activities.add_subparsers(
        dest="activities_command", required=True, parser_class=_ArgumentParser
    )
    activity_list = activity_subparsers.add_parser("list")
    activity_list.add_argument("--json", action="store_true", dest="as_json")
    activity_list.add_argument(
        "--period", required=True, choices=("today", "7Days", "30Days", "90Days")
    )
    activity_list.add_argument("--as-of", required=True, type=_local_date_argument)
    activity_list.add_argument("--type-key", type=_type_key_argument)
    activity_list.add_argument("--offset", type=_page_offset_argument, default=0)
    activity_detail = activity_subparsers.add_parser("detail")
    activity_detail.add_argument("--json", action="store_true", dest="as_json")
    activity_detail.add_argument("--activity-id", required=True, type=_activity_id_argument)
    return parser


def _local_date_argument(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid local date") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("invalid local date")
    return parsed


def _type_key_argument(value: str) -> str:
    try:
        validated = validate_type_key(value)
    except ActivityViewRequestError as error:
        raise argparse.ArgumentTypeError("invalid activity type") from error
    if validated is None:  # pragma: no cover - argparse always supplies text
        raise argparse.ArgumentTypeError("invalid activity type")
    return validated


def _page_offset_argument(value: str) -> int:
    try:
        offset = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid activity page") from error
    if (
        str(offset) != value
        or offset < 0
        or offset > MAX_ACTIVITY_PAGE_OFFSET
        or offset % MAX_ACTIVITY_PAGE_SIZE != 0
    ):
        raise argparse.ArgumentTypeError("invalid activity page")
    return offset


def _activity_id_argument(value: str) -> str:
    try:
        return validate_activity_id(value)
    except ActivityViewRequestError as error:
        raise argparse.ArgumentTypeError("invalid activity identifier") from error


def _path_text(path: Path | None) -> str | None:
    """Convert an optional path into its stable JSON representation."""
    return str(path) if path is not None else None


def _doctor_payload(paths: AppPaths) -> dict[str, object]:
    """Build the versioned doctor response consumed by tests and future QML code."""
    return {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": "doctor",
        "ok": True,
        "data": {
            "backendVersion": __version__,
            "pythonVersion": platform.python_version(),
            "paths": {
                "state": _path_text(paths.state),
                "data": _path_text(paths.data),
                "cache": _path_text(paths.cache),
                "runtime": _path_text(paths.runtime),
            },
            "runtimeDirectoryAvailable": paths.runtime is not None,
        },
        "error": None,
    }


def _write_human_doctor(stdout: TextIO, paths: AppPaths) -> None:
    """Write a concise, human-readable doctor response."""
    runtime = _path_text(paths.runtime) or "unavailable"
    stdout.write(
        "Garmin Insights backend is ready.\n"
        f"Python: {platform.python_version()}\n"
        f"State: {paths.state}\n"
        f"Data: {paths.data}\n"
        f"Cache: {paths.cache}\n"
        f"Runtime: {runtime}\n"
    )


def _success_payload(command: str, data: dict[str, object]) -> dict[str, object]:
    """Build the versioned success envelope shared by machine-readable commands."""
    return {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": command,
        "ok": True,
        "data": data,
        "error": None,
    }


def _auth_status_data(status: AuthStatus) -> dict[str, object]:
    """Serialize local authentication state without account details."""
    return {
        "configured": status.configured,
        "verified": status.verified,
        "accountScoped": status.account_scoped,
    }


def _default_auth_operations(paths: AppPaths, stdin: TextIO, stderr: TextIO) -> AuthOperations:
    """Build authentication dependencies at the process composition root."""
    from omarchy_garmin.garmin_gateway import GarminAuthGateway

    return AuthService(
        store=AuthStore(paths),
        gateway=GarminAuthGateway(),
        credential_provider=TerminalCredentialProvider(stdin, stderr),
    )


def _default_activity_view_operations(paths: AppPaths) -> ActivityViewOperations:
    """Build local activity-view dependencies at the process composition root."""
    from omarchy_garmin.database import ActivityRepository

    return ActivityViewService(ActivityRepository(paths.activity_database))


def _default_refresh_operations(paths: AppPaths) -> RefreshOperations:
    """Build activity synchronization dependencies at the process composition root."""
    from omarchy_garmin.database import ActivityRepository
    from omarchy_garmin.garmin_gateway import GarminActivityGateway
    from omarchy_garmin.summary import SummaryCache
    from omarchy_garmin.trends import ActivityTrendsCache

    return ActivitySyncService(
        paths=paths,
        auth_store=AuthStore(paths),
        gateway=GarminActivityGateway(),
        repository=ActivityRepository(paths.activity_database),
        summary=SummaryCache(paths.summary_file),
        trends=ActivityTrendsCache(paths.activity_trends_file),
    )


def _write_auth_success(
    *,
    stdout: TextIO,
    command: str,
    as_json: bool,
    data: dict[str, object],
    human_message: str,
) -> int:
    """Write one bounded authentication success response."""
    if as_json:
        payload = _success_payload(command, data)
        stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    else:
        stdout.write(human_message + "\n")
    return int(ExitStatus.SUCCESS)


def _run_auth(
    arguments: argparse.Namespace,
    *,
    paths: AppPaths,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    operations: AuthOperations | None,
) -> int:
    """Dispatch one parsed authentication command."""
    action: str = arguments.auth_command
    command = f"auth.{action}"
    auth = operations or _default_auth_operations(paths, stdin, stderr)

    if action == "status":
        status = auth.status()
        return _write_auth_success(
            stdout=stdout,
            command=command,
            as_json=arguments.as_json,
            data=_auth_status_data(status),
            human_message=(
                "Garmin authentication is configured but unverified."
                if status.configured
                else "Garmin authentication is not configured."
            ),
        )
    if action == "login":
        status = auth.login()
        return _write_auth_success(
            stdout=stdout,
            command=command,
            as_json=arguments.as_json,
            data=_auth_status_data(status),
            human_message="Garmin authentication verified.",
        )
    if not arguments.confirm:
        raise CommandError(ErrorCode.INVALID_ARGUMENTS)
    if action == "logout":
        auth.logout()
        return _write_auth_success(
            stdout=stdout,
            command=command,
            as_json=arguments.as_json,
            data={"configured": False, "localActivityDataRetained": True},
            human_message="Garmin tokens removed. Local activity data retained.",
        )
    if action == "purge":
        auth.purge()
        return _write_auth_success(
            stdout=stdout,
            command=command,
            as_json=arguments.as_json,
            data={"configured": False, "localDataRetained": False},
            human_message="Local Garmin authentication and activity data removed.",
        )
    raise AssertionError(f"unhandled auth command: {action}")  # pragma: no cover


def _run_refresh(
    arguments: argparse.Namespace,
    *,
    paths: AppPaths,
    stdout: TextIO,
    operations: RefreshOperations | None,
) -> int:
    """Run one activity refresh and write its bounded result."""
    refresh = operations or _default_refresh_operations(paths)
    result = refresh.refresh(force_full=arguments.force_full)
    data: dict[str, object] = {
        "mode": result.mode,
        "startDate": result.start_date.isoformat(),
        "endDate": result.end_date.isoformat(),
        "fetchedCount": result.fetched_count,
        "deletedCount": result.deleted_count,
        "trendsUpdated": result.trends_updated,
    }
    return _write_auth_success(
        stdout=stdout,
        command="refresh",
        as_json=arguments.as_json,
        data=data,
        human_message=(
            f"Garmin data refreshed ({result.mode}, {result.fetched_count} stored, "
            f"{result.deleted_count} removed)."
        ),
    )


def _run_activity_view(
    arguments: argparse.Namespace,
    *,
    paths: AppPaths,
    stdout: TextIO,
    operations: ActivityViewOperations | None,
) -> int:
    """Run one bounded local activity-list or detail command."""
    views = operations or _default_activity_view_operations(paths)
    action: str = arguments.activities_command
    if action == "list":
        page = views.list_activities(
            period_key=arguments.period,
            as_of_date=arguments.as_of,
            type_key=arguments.type_key,
            offset=arguments.offset,
        )
        data = activity_page_payload(page)
        human_message = f"Returned {len(page.activities)} local activities."
    elif action == "detail":
        detail = views.activity_detail(arguments.activity_id)
        data = activity_detail_payload(detail)
        human_message = (
            "Local activity detail found."
            if detail.activity is not None
            else "Local activity was not found."
        )
    else:
        raise AssertionError(f"unhandled activities command: {action}")  # pragma: no cover

    command = f"activities.{action}"
    if arguments.as_json:
        payload = _success_payload(command, data)
        content = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
        if len(content.encode()) + 1 > MAX_ACTIVITY_VIEW_BYTES:
            raise ActivityViewDataError("activity view exceeds the output bound")
        stdout.write(content + "\n")
    else:
        stdout.write(human_message + "\n")
    return int(ExitStatus.SUCCESS)


def _requested_command(argv: Sequence[str]) -> str | None:
    """Return only a recognized command name for public error output."""
    if argv and argv[0] in {"doctor", "refresh"}:
        return argv[0]
    if len(argv) > 1 and argv[0] == "auth" and argv[1] in _KNOWN_AUTH_COMMANDS:
        return f"auth.{argv[1]}"
    if len(argv) > 1 and argv[0] == "activities" and argv[1] in {"list", "detail"}:
        return f"activities.{argv[1]}"
    return None


def _error_payload(command: str | None, code: ErrorCode) -> dict[str, object]:
    """Build a bounded error envelope from the reviewed error catalog."""
    spec = ERROR_SPECS[code]
    return {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "command": command,
        "ok": False,
        "data": None,
        "error": {
            "code": code.value,
            "message": spec.message,
        },
    }


def _write_error(
    *,
    stdout: TextIO,
    stderr: TextIO,
    command: str | None,
    as_json: bool,
    code: ErrorCode,
) -> int:
    """Write a safe error response and return its stable exit status."""
    spec = ERROR_SPECS[code]
    if as_json:
        payload = _error_payload(command, code)
        stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    else:
        stderr.write(f"Error [{code.value}]: {spec.message}\n")
    return int(spec.exit_status)


def _resolve_paths(environment: Mapping[str, str], home: Path) -> AppPaths:
    """Resolve paths while translating configuration failures to a public error."""
    try:
        return AppPaths.from_environment(environment, home)
    except ValueError as error:
        raise CommandError(ErrorCode.INVALID_CONFIGURATION) from error


def _sync_error_code(error: ActivitySyncError) -> ErrorCode:
    """Map activity-sync failures to the stable process contract."""
    if isinstance(error, ActivitySyncConfigurationError):
        return ErrorCode.INVALID_CONFIGURATION
    if isinstance(error, ActivityAuthenticationRequiredError):
        return ErrorCode.AUTH_REQUIRED
    if isinstance(error, ActivityRateLimitedError):
        return ErrorCode.RATE_LIMITED
    if isinstance(error, ActivityNetworkError):
        return ErrorCode.NETWORK_UNAVAILABLE
    if isinstance(error, ActivityRemoteServiceError):
        return ErrorCode.REMOTE_SERVICE_ERROR
    if isinstance(error, ActivityDataError):
        return ErrorCode.INVALID_REMOTE_DATA
    if isinstance(error, ActivityStorageError):
        return ErrorCode.LOCAL_STORAGE_ERROR
    if isinstance(error, ActivityRefreshInProgressError):
        return ErrorCode.REFRESH_IN_PROGRESS
    return ErrorCode.INTERNAL_ERROR


def _auth_error_code(error: AuthError) -> ErrorCode:
    """Map authentication-domain failures to the stable process contract."""
    if isinstance(error, InteractiveTerminalRequiredError):
        return ErrorCode.INTERACTIVE_TERMINAL_REQUIRED
    if isinstance(error, AuthenticationRejectedError):
        return ErrorCode.AUTHENTICATION_FAILED
    if isinstance(error, AccountMismatchError):
        return ErrorCode.ACCOUNT_MISMATCH
    if isinstance(error, AuthRateLimitedError):
        return ErrorCode.RATE_LIMITED
    if isinstance(error, AuthNetworkError):
        return ErrorCode.NETWORK_UNAVAILABLE
    if isinstance(error, AuthRemoteServiceError):
        return ErrorCode.REMOTE_SERVICE_ERROR
    if isinstance(error, InvalidAuthResponseError):
        return ErrorCode.INVALID_REMOTE_DATA
    if isinstance(error, AuthStorageError):
        return ErrorCode.LOCAL_STORAGE_ERROR
    if isinstance(error, AuthRefreshInProgressError):
        return ErrorCode.REFRESH_IN_PROGRESS
    return ErrorCode.INTERNAL_ERROR


def _dispatch_command(
    arguments: argparse.Namespace,
    *,
    paths: AppPaths,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    auth_operations: AuthOperations | None,
    refresh_operations: RefreshOperations | None,
    activity_view_operations: ActivityViewOperations | None,
) -> int:
    """Dispatch one parsed command to its explicit operation boundary."""
    if arguments.command == "doctor":
        payload = _doctor_payload(paths)
        if arguments.as_json:
            stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
        else:
            _write_human_doctor(stdout, paths)
        return int(ExitStatus.SUCCESS)
    if arguments.command == "auth":
        return _run_auth(
            arguments,
            paths=paths,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            operations=auth_operations,
        )
    if arguments.command == "refresh":
        return _run_refresh(
            arguments,
            paths=paths,
            stdout=stdout,
            operations=refresh_operations,
        )
    if arguments.command == "activities":
        return _run_activity_view(
            arguments,
            paths=paths,
            stdout=stdout,
            operations=activity_view_operations,
        )
    raise AssertionError(f"unhandled command: {arguments.command}")  # pragma: no cover


def run(
    argv: Sequence[str],
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO,
    stderr: TextIO,
    environment: Mapping[str, str],
    home: Path,
    auth_operations: AuthOperations | None = None,
    refresh_operations: RefreshOperations | None = None,
    activity_view_operations: ActivityViewOperations | None = None,
) -> int:
    """Run the CLI with explicit process boundaries for deterministic testing.

    Args:
        argv: Command arguments excluding the executable name.
        stdin: Source for visible-terminal credential input.
        stdout: Destination for successful command and machine-readable error output.
        stderr: Destination for concise human-readable errors.
        environment: Environment variables used to resolve XDG paths.
        home: Home directory used for XDG defaults.
        auth_operations: Optional injected authentication boundary for tests.
        refresh_operations: Optional injected activity-refresh boundary for tests.
        activity_view_operations: Optional injected local activity-view boundary for tests.

    Returns:
        A process exit status.
    """
    command = _requested_command(argv)
    as_json = "--json" in argv
    try:
        arguments = _build_parser().parse_args(argv)
        paths = _resolve_paths(environment, home)
        return _dispatch_command(
            arguments,
            paths=paths,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            auth_operations=auth_operations,
            refresh_operations=refresh_operations,
            activity_view_operations=activity_view_operations,
        )
    except CommandError as error:
        return _write_error(
            stdout=stdout,
            stderr=stderr,
            command=command,
            as_json=as_json,
            code=error.code,
        )
    except AuthError as error:
        return _write_error(
            stdout=stdout,
            stderr=stderr,
            command=command,
            as_json=as_json,
            code=_auth_error_code(error),
        )
    except ActivitySyncError as error:
        return _write_error(
            stdout=stdout,
            stderr=stderr,
            command=command,
            as_json=as_json,
            code=_sync_error_code(error),
        )
    except ActivityViewError as error:
        code = (
            ErrorCode.INVALID_ARGUMENTS
            if isinstance(error, ActivityViewRequestError)
            else ErrorCode.LOCAL_STORAGE_ERROR
        )
        return _write_error(
            stdout=stdout,
            stderr=stderr,
            command=command,
            as_json=as_json,
            code=code,
        )
    except Exception:  # noqa: BLE001 - final process boundary returns a fixed, redacted failure
        return _write_error(
            stdout=stdout,
            stderr=stderr,
            command=command,
            as_json=as_json,
            code=ErrorCode.INTERNAL_ERROR,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface against the current process environment."""
    arguments = sys.argv[1:] if argv is None else argv
    return run(
        arguments,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        environment=os.environ,
        home=Path.home(),
    )
