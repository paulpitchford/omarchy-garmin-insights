import stat
from pathlib import Path

import pytest

from omarchy_garmin.locking import (
    RefreshInProgressError,
    RefreshLockStorageError,
    RefreshRuntimeUnavailableError,
    activity_refresh_lock,
)


def test_refresh_lock_is_owner_only_and_reusable(tmp_path: Path) -> None:
    lock_path = tmp_path / "runtime" / "sync.lock"

    with activity_refresh_lock(lock_path):
        assert lock_path.is_file()
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(lock_path.parent.stat().st_mode) == 0o700

    with activity_refresh_lock(lock_path):
        pass


def test_overlapping_refresh_lock_is_rejected_without_waiting(tmp_path: Path) -> None:
    lock_path = tmp_path / "runtime" / "sync.lock"

    with (
        activity_refresh_lock(lock_path),
        pytest.raises(RefreshInProgressError),
        activity_refresh_lock(lock_path),
    ):
        pytest.fail("overlapping lock was acquired")


def test_error_from_locked_operation_is_not_misclassified(tmp_path: Path) -> None:
    lock_path = tmp_path / "runtime" / "sync.lock"

    with pytest.raises(OSError, match="operation failed"), activity_refresh_lock(lock_path):
        raise OSError("operation failed")


def test_refresh_requires_private_runtime_directory() -> None:
    with pytest.raises(RefreshRuntimeUnavailableError), activity_refresh_lock(None):
        pytest.fail("lock without runtime directory was acquired")


def test_symlinked_refresh_lock_is_rejected_without_touching_target(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"keep")
    lock_path = runtime / "sync.lock"
    lock_path.symlink_to(target)

    with pytest.raises(RefreshLockStorageError), activity_refresh_lock(lock_path):
        pytest.fail("symlinked lock was acquired")

    assert target.read_bytes() == b"keep"
