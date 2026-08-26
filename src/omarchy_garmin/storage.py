"""Secure local storage primitives for private Garmin state."""

from __future__ import annotations

import errno
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

PRIVATE_DIRECTORY_MODE = stat.S_IRWXU
PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR


class UnsafeStoragePathError(RuntimeError):
    """Raised when an application storage path is unsafe to use."""


def _require_absolute(path: Path) -> None:
    """Reject relative paths before a filesystem operation."""
    if not path.is_absolute():
        raise UnsafeStoragePathError(f"storage path must be absolute: {path}")


@contextmanager
def _opened_directory_without_following(path: Path) -> Iterator[int]:
    """Open and close a directory without following its final path component."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise UnsafeStoragePathError(f"storage path is not a real directory: {path}") from error
        raise

    try:
        yield descriptor
    finally:
        os.close(descriptor)


def ensure_private_directory(path: Path) -> Path:
    """Create or secure an owner-only application directory.

    Generic XDG parents may retain their existing permissions, but the final
    application-owned directory is opened without following a symlink, checked
    for ownership, and set to mode ``0700``.

    Args:
        path: Absolute application directory to prepare.

    Returns:
        The prepared path.

    Raises:
        UnsafeStoragePathError: If the path is relative, is not a real directory,
            or is owned by another user.
        OSError: If the directory cannot be created or secured.
    """
    _require_absolute(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with suppress(FileExistsError):
        path.mkdir(mode=PRIVATE_DIRECTORY_MODE)

    with _opened_directory_without_following(path) as descriptor:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid():
            raise UnsafeStoragePathError(f"storage directory has a different owner: {path}")
        os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)

    return path


def _sync_directory(path: Path) -> None:
    """Flush a directory entry after an atomic replacement."""
    with _opened_directory_without_following(path) as descriptor:
        os.fsync(descriptor)


def atomic_write_private(path: Path, content: bytes) -> None:
    """Atomically replace a private file with owner-only content.

    The temporary file is created beside the destination, flushed, and replaced
    with ``os.replace``. Replacing a destination symlink replaces the link itself
    rather than writing through it.

    Args:
        path: Absolute destination path.
        content: Complete file content.

    Raises:
        UnsafeStoragePathError: If the destination or its parent is unsafe.
        OSError: If the write cannot be completed and made durable.
    """
    _require_absolute(path)
    ensure_private_directory(path.parent)

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as temporary_file:
            os.fchmod(temporary_file.fileno(), PRIVATE_FILE_MODE)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        temporary_path.replace(path)
        _sync_directory(path.parent)
    finally:
        os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary_path.unlink()
