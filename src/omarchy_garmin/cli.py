"""Command-line boundary for the Garmin Activities backend."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from omarchy_garmin import __version__
from omarchy_garmin.errors import ERROR_SPECS, CommandError, ErrorCode, ExitStatus
from omarchy_garmin.paths import AppPaths

OUTPUT_SCHEMA_VERSION = 1
_KNOWN_COMMANDS = frozenset({"doctor"})


class _ArgumentParser(argparse.ArgumentParser):
    """Convert parser failures into the stable command error contract."""

    def error(self, message: str) -> NoReturn:
        """Reject invalid arguments without reflecting their content in output."""
        raise CommandError(ErrorCode.INVALID_ARGUMENTS)


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = _ArgumentParser(
        prog="omarchy-garmin-activities",
        description="Backend for the Garmin Activities Omarchy plugin",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    doctor = subparsers.add_parser("doctor", help="inspect backend prerequisites and paths")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    return parser


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
        "Garmin Activities backend is ready.\n"
        f"Python: {platform.python_version()}\n"
        f"State: {paths.state}\n"
        f"Data: {paths.data}\n"
        f"Cache: {paths.cache}\n"
        f"Runtime: {runtime}\n"
    )


def _requested_command(argv: Sequence[str]) -> str | None:
    """Return only a recognized command name for public error output."""
    return argv[0] if argv and argv[0] in _KNOWN_COMMANDS else None


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


def run(
    argv: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    environment: Mapping[str, str],
    home: Path,
) -> int:
    """Run the CLI with explicit process boundaries for deterministic testing.

    Args:
        argv: Command arguments excluding the executable name.
        stdout: Destination for successful command and machine-readable error output.
        stderr: Destination for concise human-readable errors.
        environment: Environment variables used to resolve XDG paths.
        home: Home directory used for XDG defaults.

    Returns:
        A process exit status.
    """
    command = _requested_command(argv)
    as_json = "--json" in argv
    try:
        arguments = _build_parser().parse_args(argv)
        paths = _resolve_paths(environment, home)

        if arguments.command == "doctor":
            payload = _doctor_payload(paths)
            if arguments.as_json:
                stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
            else:
                _write_human_doctor(stdout, paths)
            return int(ExitStatus.SUCCESS)

        raise AssertionError(f"unhandled command: {arguments.command}")  # pragma: no cover
    except CommandError as error:
        return _write_error(
            stdout=stdout,
            stderr=stderr,
            command=command,
            as_json=as_json,
            code=error.code,
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
        stdout=sys.stdout,
        stderr=sys.stderr,
        environment=os.environ,
        home=Path.home(),
    )
