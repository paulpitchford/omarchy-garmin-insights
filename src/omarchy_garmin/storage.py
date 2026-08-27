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


@contextmanager
def _secured_directory(path: Path) -> Iterator[int]:
    """Open an application directory, verify ownership, and enforce mode 0700."""
    with _opened_directory_without_following(path) as descriptor:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid():
            raise UnsafeStoragePathError(f"storage directory has a different owner: {path}")
        os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
        yield descriptor


def private_directory_exists(path: Path) -> bool:
    """Return whether an owner-only application directory exists safely."""
    _require_absolute(path)
    try:
        with _secured_directory(path):
            return True
    except FileNotFoundError:
        return False


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

    with _secured_directory(path):
        pass

    return path


def _sync_directory(path: Path) -> None:
    """Flush a directory entry after an atomic replacement."""
    with _secured_directory(path) as descriptor:
        os.fsync(descriptor)


@contextmanager
def _opened_private_file(path: Path) -> Iterator[int]:
    """Open a regular owner-only file relative to its secured parent directory."""
    _require_absolute(path)
    with _secured_directory(path.parent) as parent_descriptor:
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise UnsafeStoragePathError(
                    f"private file is not a regular file: {path}"
                ) from error
            raise

        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise UnsafeStoragePathError(f"private file is not a regular file: {path}")
            if metadata.st_uid != os.geteuid():
                raise UnsafeStoragePathError(f"private file has a different owner: {path}")
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            yield descriptor
        finally:
            os.close(descriptor)


def private_file_exists(path: Path) -> bool:
    """Return whether an owner-only regular file exists safely."""
    try:
        with _opened_private_file(path):
            return True
    except FileNotFoundError:
        return False


def read_private_file(path: Path, *, max_bytes: int) -> bytes:
    """Read a bounded owner-only regular file without following symlinks."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    with (
        _opened_private_file(path) as descriptor,
        os.fdopen(descriptor, "rb", closefd=False) as private_file,
    ):
        content = private_file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise UnsafeStoragePathError(f"private file exceeds its size limit: {path}")
    return content


def remove_private_file(path: Path) -> bool:
    """Remove one owner-owned regular file without following symlinks."""
    _require_absolute(path)
    try:
        with _secured_directory(path.parent) as parent_descriptor:
            metadata = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise UnsafeStoragePathError(f"private file is not a regular file: {path}")
            if metadata.st_uid != os.geteuid():
                raise UnsafeStoragePathError(f"private file has a different owner: {path}")
            os.unlink(path.name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
            return True
    except FileNotFoundError:
        return False


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
