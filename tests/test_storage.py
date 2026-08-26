import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from omarchy_garmin.storage import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    UnsafeStoragePathError,
    atomic_write_private,
    ensure_private_directory,
    private_directory_exists,
    private_file_exists,
    read_private_file,
    remove_private_file,
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


def test_private_directory_exists_validates_and_restricts_directory(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir(mode=0o755)

    exists = private_directory_exists(directory)

    assert exists is True
    assert _mode(directory) == PRIVATE_DIRECTORY_MODE


def test_private_directory_exists_returns_false_when_missing(tmp_path: Path) -> None:
    assert private_directory_exists(tmp_path / "missing") is False


def test_private_directory_exists_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "state"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(UnsafeStoragePathError):
        private_directory_exists(link)


def test_private_file_can_be_inspected_and_read_with_restricted_mode(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    private_file = directory / "private.json"
    private_file.write_bytes(b"synthetic")
    private_file.chmod(0o644)

    exists = private_file_exists(private_file)
    content = read_private_file(private_file, max_bytes=32)

    assert exists is True
    assert content == b"synthetic"
    assert _mode(private_file) == PRIVATE_FILE_MODE


def test_private_file_exists_returns_false_when_missing(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")

    assert private_file_exists(directory / "missing") is False


def test_private_file_symlink_is_rejected(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    target = tmp_path / "target"
    target.write_bytes(b"private")
    link = directory / "private.json"
    link.symlink_to(target)

    with pytest.raises(UnsafeStoragePathError):
        private_file_exists(link)


def test_private_file_directory_is_rejected(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    nested_directory = directory / "private.json"
    nested_directory.mkdir()

    with pytest.raises(UnsafeStoragePathError, match="regular file"):
        private_file_exists(nested_directory)


def test_private_file_owned_by_another_user_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    private_file = directory / "private.json"
    private_file.write_bytes(b"private")
    original_fstat = os.fstat
    call_count = 0

    def different_file_owner(descriptor: int) -> os.stat_result | SimpleNamespace:
        nonlocal call_count
        call_count += 1
        metadata = original_fstat(descriptor)
        if call_count == 2:
            return SimpleNamespace(st_uid=metadata.st_uid + 1, st_mode=metadata.st_mode)
        return metadata

    monkeypatch.setattr(os, "fstat", different_file_owner)

    with pytest.raises(UnsafeStoragePathError, match="different owner"):
        private_file_exists(private_file)


def test_private_file_read_is_bounded(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    private_file = directory / "private.json"
    private_file.write_bytes(b"too large")

    with pytest.raises(UnsafeStoragePathError, match="size limit"):
        read_private_file(private_file, max_bytes=3)


def test_private_file_read_rejects_nonpositive_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        read_private_file(tmp_path / "private.json", max_bytes=0)


def test_private_file_remove_is_idempotent(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    private_file = directory / "private.json"
    private_file.write_bytes(b"synthetic")

    first_result = remove_private_file(private_file)
    second_result = remove_private_file(private_file)

    assert first_result is True
    assert second_result is False
    assert private_file.exists() is False


def test_private_file_remove_rejects_different_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    private_file = directory / "private.json"
    private_file.write_bytes(b"keep")
    original_stat = os.stat

    def different_owner(
        path: str,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result | SimpleNamespace:
        metadata = original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if dir_fd is not None:
            return SimpleNamespace(st_uid=metadata.st_uid + 1, st_mode=metadata.st_mode)
        return metadata

    monkeypatch.setattr(os, "stat", different_owner)

    with pytest.raises(UnsafeStoragePathError, match="different owner"):
        remove_private_file(private_file)


def test_private_file_remove_rejects_symlink(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "state")
    target = tmp_path / "target"
    target.write_bytes(b"keep")
    link = directory / "private.json"
    link.symlink_to(target)

    with pytest.raises(UnsafeStoragePathError):
        remove_private_file(link)

    assert target.read_bytes() == b"keep"


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
