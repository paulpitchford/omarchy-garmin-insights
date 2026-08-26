import os
import stat
from pathlib import Path

import pytest

from omarchy_garmin.storage import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    UnsafeStoragePathError,
    atomic_write_private,
    ensure_private_directory,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_private_directory_is_created_with_owner_only_permissions(tmp_path: Path) -> None:
    directory = tmp_path / "state" / "omarchy-garmin-activities"

    result = ensure_private_directory(directory)

    assert result == directory
    assert directory.is_dir()
    assert _mode(directory) == PRIVATE_DIRECTORY_MODE


def test_existing_directory_permissions_are_restricted(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir(mode=0o755)

    ensure_private_directory(directory)

    assert _mode(directory) == PRIVATE_DIRECTORY_MODE


def test_directory_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "state"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(UnsafeStoragePathError, match="not a real directory"):
        ensure_private_directory(link)


def test_regular_file_cannot_be_used_as_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "state"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(UnsafeStoragePathError, match="not a real directory"):
        ensure_private_directory(file_path)


def test_relative_directory_is_rejected() -> None:
    with pytest.raises(UnsafeStoragePathError, match="must be absolute"):
        ensure_private_directory(Path("relative/state"))


def test_directory_owned_by_another_user_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    different_user = directory.stat().st_uid + 1
    monkeypatch.setattr(os, "geteuid", lambda: different_user)

    with pytest.raises(UnsafeStoragePathError, match="different owner"):
        ensure_private_directory(directory)


def test_atomic_write_creates_owner_only_file(tmp_path: Path) -> None:
    destination = tmp_path / "cache" / "summary.json"

    atomic_write_private(destination, b'{"status":"ready"}\n')

    assert destination.read_bytes() == b'{"status":"ready"}\n'
    assert _mode(destination) == PRIVATE_FILE_MODE
    assert _mode(destination.parent) == PRIVATE_DIRECTORY_MODE


def test_atomic_write_rejects_relative_destination() -> None:
    with pytest.raises(UnsafeStoragePathError, match="must be absolute"):
        atomic_write_private(Path("relative/summary.json"), b"content")


def test_atomic_write_replaces_existing_content(tmp_path: Path) -> None:
    destination = tmp_path / "cache" / "summary.json"
    atomic_write_private(destination, b"old")

    atomic_write_private(destination, b"new")

    assert destination.read_bytes() == b"new"
    assert _mode(destination) == PRIVATE_FILE_MODE


def test_atomic_write_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    destination_parent = ensure_private_directory(tmp_path / "cache")
    target = tmp_path / "unrelated"
    target.write_bytes(b"keep")
    destination = destination_parent / "summary.json"
    destination.symlink_to(target)

    atomic_write_private(destination, b"replacement")

    assert destination.is_symlink() is False
    assert destination.read_bytes() == b"replacement"
    assert target.read_bytes() == b"keep"


def test_failed_replace_preserves_existing_file_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "cache" / "summary.json"
    atomic_write_private(destination, b"existing")

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        atomic_write_private(destination, b"new")

    assert destination.read_bytes() == b"existing"
    assert list(destination.parent.iterdir()) == [destination]
