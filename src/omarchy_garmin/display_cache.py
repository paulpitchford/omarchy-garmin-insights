"""Hardened reads for bounded display-cache contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from omarchy_garmin.paths import AppPaths
from omarchy_garmin.storage import UnsafeStoragePathError, read_private_file
from omarchy_garmin.summary import MAX_SUMMARY_BYTES
from omarchy_garmin.trends import MAX_ACTIVITY_TRENDS_BYTES
from omarchy_garmin.wellness_presentation import MAX_WELLNESS_PRESENTATION_BYTES

DISPLAY_CACHE_ENVELOPE_OVERHEAD_BYTES = 4_096


class DisplayCacheError(RuntimeError):
    """Base class for safe display-cache read failures."""


class DisplayCacheMissingError(DisplayCacheError):
    """Raised when a reviewed display cache does not exist."""


class DisplayCacheStorageError(DisplayCacheError):
    """Raised when a display-cache path cannot be read safely."""


class DisplayCacheDataError(DisplayCacheError):
    """Raised when display-cache content cannot cross the process boundary safely."""


class DisplayCacheKind(StrEnum):
    """Reviewed display caches available to the QML service."""

    SUMMARY = "summary"
    ACTIVITY_TRENDS = "activity-trends"
    WELLNESS = "wellness"


class DisplayCacheOperations(Protocol):
    """Bounded display-cache operation exposed by the CLI."""

    def read(self, kind: DisplayCacheKind) -> str:
        """Return one bounded cache as UTF-8 text."""
        ...


def display_cache_output_limit(kind: DisplayCacheKind) -> int:
    """Return the strict process-envelope byte limit for one cache kind."""
    if kind is DisplayCacheKind.SUMMARY:
        content_limit = MAX_SUMMARY_BYTES
    elif kind is DisplayCacheKind.ACTIVITY_TRENDS:
        content_limit = MAX_ACTIVITY_TRENDS_BYTES
    elif kind is DisplayCacheKind.WELLNESS:
        content_limit = MAX_WELLNESS_PRESENTATION_BYTES
    else:
        raise DisplayCacheDataError("display cache kind is not implemented")
    return content_limit * 2 + DISPLAY_CACHE_ENVELOPE_OVERHEAD_BYTES


class DisplayCacheReader:
    """Read display caches through owner and file-type checks."""

    def __init__(self, paths: AppPaths) -> None:
        """Initialize the reader with resolved private application paths."""
        self._paths = paths

    def read(self, kind: DisplayCacheKind) -> str:
        """Read one reviewed cache without following links or blocking on FIFOs."""
        if kind is DisplayCacheKind.SUMMARY:
            path = self._paths.summary_file
            max_bytes = MAX_SUMMARY_BYTES
        elif kind is DisplayCacheKind.ACTIVITY_TRENDS:
            path = self._paths.activity_trends_file
            max_bytes = MAX_ACTIVITY_TRENDS_BYTES
        elif kind is DisplayCacheKind.WELLNESS:
            path = self._paths.wellness_file
            max_bytes = MAX_WELLNESS_PRESENTATION_BYTES
        else:
            raise DisplayCacheDataError("display cache kind is not implemented")

        try:
            content = read_private_file(path, max_bytes=max_bytes)
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DisplayCacheDataError("display cache is not UTF-8") from error
        except FileNotFoundError as error:
            raise DisplayCacheMissingError("display cache does not exist") from error
        except (OSError, UnsafeStoragePathError) as error:
            raise DisplayCacheStorageError("display cache could not be read safely") from error
