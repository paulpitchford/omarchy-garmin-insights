"""Owner-only non-blocking process lock for activity refreshes."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from omarchy_garmin.storage import (
    PRIVATE_FILE_MODE,
    UnsafeStoragePathError,
    ensure_private_directory,
)


class RefreshLockError(RuntimeError):
    """Base class for refresh-lock failures."""


class RefreshRuntimeUnavailableError(RefreshLockError):
    """Raised when XDG_RUNTIME_DIR is unavailable."""


class RefreshInProgressError(RefreshLockError):
    """Raised when another process owns the refresh lock."""


class RefreshLockStorageError(RefreshLockError):
    """Raised when the lock path is unsafe or unavailable."""


@contextmanager
def activity_refresh_lock(lock_path: Path | None) -> Iterator[None]:
    """Acquire the owner-only activity refresh lock without waiting."""
    if lock_path is None:
        raise RefreshRuntimeUnavailableError("a private runtime directory is required")

    descriptor: int | None = None
    try:
        try:
            ensure_private_directory(lock_path.parent)
            flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(lock_path, flags, PRIVATE_FILE_MODE)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise UnsafeStoragePathError("refresh lock is not an owner-owned regular file")
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RefreshInProgressError("another activity refresh is running") from error
        except RefreshInProgressError:
            raise
        except (OSError, UnsafeStoragePathError) as error:
            raise RefreshLockStorageError("refresh lock is unsafe or unavailable") from error
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
