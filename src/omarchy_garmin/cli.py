"""Command-line boundary for the Garmin Activities backend."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from omarchy_garmin import __version__
from omarchy_garmin.paths import AppPaths

OUTPUT_SCHEMA_VERSION = 1


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="omarchy-garmin-activities",
        description="Backend for the Garmin Activities Omarchy plugin",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command", required=True)
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


def run(
    argv: Sequence[str],
    *,
    stdout: TextIO,
    environment: Mapping[str, str],
    home: Path,
) -> int:
    """Run the CLI with explicit process boundaries for deterministic testing.

    Args:
        argv: Command arguments excluding the executable name.
        stdout: Destination for successful command output.
        environment: Environment variables used to resolve XDG paths.
        home: Home directory used for XDG defaults.

    Returns:
        A process exit status.
    """
    arguments = _build_parser().parse_args(argv)
    paths = AppPaths.from_environment(environment, home)

    if arguments.command == "doctor":
        payload = _doctor_payload(paths)
        if arguments.as_json:
            stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
        else:
            _write_human_doctor(stdout, paths)
        return 0

    raise AssertionError(f"unhandled command: {arguments.command}")  # pragma: no cover


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface against the current process environment."""
    arguments = sys.argv[1:] if argv is None else argv
    return run(arguments, stdout=sys.stdout, environment=os.environ, home=Path.home())
