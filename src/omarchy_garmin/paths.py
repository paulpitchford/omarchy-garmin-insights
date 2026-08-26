"""Resolve private application paths according to the XDG base directory specification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_DIRECTORY = "omarchy-garmin-activities"


def _absolute_xdg_path(environment: Mapping[str, str], variable: str) -> Path | None:
    """Return an absolute XDG override, ignoring unset or relative values."""
    raw_value = environment.get(variable)
    if not raw_value:
        return None

    path = Path(raw_value)
    return path if path.is_absolute() else None


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved storage roots for application-owned private data."""

    state: Path
    data: Path
    cache: Path
    runtime: Path | None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], home: Path) -> AppPaths:
        """Resolve application paths from an environment and an explicit home directory.

        Relative XDG overrides are invalid under the XDG specification and fall back to
        their default locations. The runtime path has no safe fallback because shared
        temporary directories are unsuitable for process locks.

        Args:
            environment: Environment variables to inspect.
            home: Absolute home directory used for XDG defaults.

        Returns:
            The resolved application paths.

        Raises:
            ValueError: If ``home`` is not absolute.
        """
        if not home.is_absolute():
            raise ValueError("home must be an absolute path")

        state_root = _absolute_xdg_path(environment, "XDG_STATE_HOME")
        data_root = _absolute_xdg_path(environment, "XDG_DATA_HOME")
        cache_root = _absolute_xdg_path(environment, "XDG_CACHE_HOME")
        runtime_root = _absolute_xdg_path(environment, "XDG_RUNTIME_DIR")

        return cls(
            state=(state_root or home / ".local" / "state") / APP_DIRECTORY,
            data=(data_root or home / ".local" / "share") / APP_DIRECTORY,
            cache=(cache_root or home / ".cache") / APP_DIRECTORY,
            runtime=runtime_root / APP_DIRECTORY if runtime_root else None,
        )
