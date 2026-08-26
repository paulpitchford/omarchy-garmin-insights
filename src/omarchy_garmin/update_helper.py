"""Validate update support and persist the bounded update-check cadence."""

from __future__ import annotations

import configparser
import errno
import fcntl
import json
import os
import stat
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__:
    from omarchy_garmin.storage import (
        PRIVATE_FILE_MODE,
        UnsafeStoragePathError,
        atomic_write_private,
        ensure_private_directory,
        read_private_file,
    )
else:  # Direct stdlib-only invocation before the locked environment exists.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from omarchy_garmin.storage import (
        PRIVATE_FILE_MODE,
        UnsafeStoragePathError,
        atomic_write_private,
        ensure_private_directory,
        read_private_file,
    )

UPDATE_REPOSITORY_URL = "https://github.com/paulpitchford/omarchy-garmin-insights.git"
UPDATE_CADENCE_SECONDS = 24 * 60 * 60
MAX_CHECKOUT_CONFIG_BYTES = 16 * 1024
MAX_STATE_BYTES = 512
MAX_EPOCH_SECONDS = 253_402_300_799
STATE_FILE_NAME = "update-check.json"
LOCK_FILE_NAME = "update-check.lock"


class UpdateHelperError(RuntimeError):
    """Raised when local update-check validation or storage is unsafe."""


class UpdateCheckBusyError(UpdateHelperError):
    """Raised when another process is claiming or recording an update check."""


@dataclass(frozen=True)
class UpdateCheckState:
    """Persisted non-sensitive update-check metadata."""

    schemaVersion: int
    lastAttemptEpochSeconds: int
    localCommit: str
    remoteCommit: str | None


@dataclass(frozen=True)
class UpdateCheckClaim:
    """Result of atomically claiming the automatic update-check cadence."""

    schemaVersion: int
    due: bool
    localCommit: str
    remoteCommit: str | None


def valid_commit(value: object) -> bool:
    """Return whether a value is one canonical lowercase SHA-1 commit ID."""
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_normal_absolute(path: Path) -> bool:
    return path.is_absolute() and Path(os.path.normpath(path)) == path


def _read_checkout_config(source_dir: Path) -> bytes:
    if not _is_normal_absolute(source_dir):
        raise UpdateHelperError("the checkout path must be absolute")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    source_descriptor: int | None = None
    git_descriptor: int | None = None
    config_descriptor: int | None = None
    try:
        source_descriptor = os.open(source_dir, directory_flags)
        source_metadata = os.fstat(source_descriptor)
        if source_metadata.st_uid != os.geteuid():
            raise UpdateHelperError("the checkout has a different owner")

        git_descriptor = os.open(".git", directory_flags, dir_fd=source_descriptor)
        git_metadata = os.fstat(git_descriptor)
        if git_metadata.st_uid != os.geteuid():
            raise UpdateHelperError("the Git directory has a different owner")

        config_descriptor = os.open("config", file_flags, dir_fd=git_descriptor)
        config_metadata = os.fstat(config_descriptor)
        if not stat.S_ISREG(config_metadata.st_mode) or config_metadata.st_uid != os.geteuid():
            raise UpdateHelperError("the Git configuration is not an owner-owned regular file")
        with os.fdopen(config_descriptor, "rb", closefd=False) as config_file:
            content = config_file.read(MAX_CHECKOUT_CONFIG_BYTES + 1)
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise UpdateHelperError("the checkout contains a symlink or non-directory") from error
        raise UpdateHelperError("the checkout cannot be inspected safely") from error
    finally:
        for descriptor in (config_descriptor, git_descriptor, source_descriptor):
            if descriptor is not None:
                os.close(descriptor)

    if len(content) > MAX_CHECKOUT_CONFIG_BYTES:
        raise UpdateHelperError("the Git configuration exceeds its size limit")
    return content


def checkout_is_supported(source_dir: Path, expected_dir: Path) -> bool:
    """Return whether a checkout has the fixed supported path and origin.

    Copied checkouts, worktrees, final symlinks, changed origins, Git includes,
    malformed configuration, and checkout metadata owned by another user are
    unsupported.
    """
    if (
        source_dir != expected_dir
        or not _is_normal_absolute(source_dir)
        or not _is_normal_absolute(expected_dir)
    ):
        return False

    try:
        raw_config = _read_checkout_config(source_dir)
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(raw_config.decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error, UpdateHelperError):
        return False

    if any(section.casefold().startswith(("include", "url ")) for section in parser.sections()):
        return False
    origin_section = 'remote "origin"'
    if not parser.has_section(origin_section):
        return False
    try:
        origin_url = parser.get(origin_section, "url", raw=True)
    except (configparser.Error, KeyError):
        return False
    return origin_url == UPDATE_REPOSITORY_URL


def _parse_state(raw: bytes) -> UpdateCheckState | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "lastAttemptEpochSeconds",
        "localCommit",
        "remoteCommit",
    }:
        return None
    schema_version = value["schemaVersion"]
    timestamp = value["lastAttemptEpochSeconds"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
        or not isinstance(timestamp, int)
        or isinstance(timestamp, bool)
        or not 0 <= timestamp <= MAX_EPOCH_SECONDS
        or not valid_commit(value["localCommit"])
        or (value["remoteCommit"] is not None and not valid_commit(value["remoteCommit"]))
    ):
        return None
    return UpdateCheckState(
        schemaVersion=1,
        lastAttemptEpochSeconds=timestamp,
        localCommit=value["localCommit"],
        remoteCommit=value["remoteCommit"],
    )


def _load_state(path: Path) -> UpdateCheckState | None:
    try:
        return _parse_state(read_private_file(path, max_bytes=MAX_STATE_BYTES))
    except FileNotFoundError:
        return None


def _write_state(path: Path, state: UpdateCheckState) -> None:
    payload = (
        json.dumps(asdict(state), separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
    )
    atomic_write_private(path, payload)


@contextmanager
def _update_check_lock(runtime_root: Path) -> Iterator[None]:
    ensure_private_directory(runtime_root)
    lock_path = runtime_root / LOCK_FILE_NAME
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(lock_path, flags, PRIVATE_FILE_MODE)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise UnsafeStoragePathError("the update lock is not an owner-owned regular file")
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateCheckBusyError("another update-check helper is running") from error
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)


def claim_update_check(
    cache_root: Path,
    runtime_root: Path,
    local_commit: str,
    now_epoch_seconds: int,
    *,
    force: bool = False,
) -> UpdateCheckClaim:
    """Atomically claim a due update check and preserve a known comparison.

    Args:
        cache_root: Absolute private application cache root.
        runtime_root: Absolute private application runtime root.
        local_commit: Validated installed commit.
        now_epoch_seconds: Current Unix timestamp supplied by the caller.
        force: Whether an explicit user action bypasses the 24-hour cadence.

    Returns:
        Whether a network query is due and any prior remote comparison for the
        same local commit.

    Raises:
        UpdateHelperError: If an argument or local path is invalid.
        UpdateCheckBusyError: If another helper owns the update lock.
        OSError: If safe state persistence fails.
    """
    if (
        not _is_normal_absolute(cache_root)
        or not _is_normal_absolute(runtime_root)
        or not valid_commit(local_commit)
        or isinstance(now_epoch_seconds, bool)
        or not 0 <= now_epoch_seconds <= MAX_EPOCH_SECONDS
    ):
        raise UpdateHelperError("the update-check claim is invalid")

    ensure_private_directory(cache_root)
    state_path = cache_root / STATE_FILE_NAME
    with _update_check_lock(runtime_root):
        state = _load_state(state_path)
        if state is not None and state.localCommit == local_commit:
            prior_remote = state.remoteCommit
            elapsed: int | None = now_epoch_seconds - state.lastAttemptEpochSeconds
        else:
            prior_remote = None
            elapsed = None
        due = force or elapsed is None or elapsed >= UPDATE_CADENCE_SECONDS
        if due:
            state = UpdateCheckState(1, now_epoch_seconds, local_commit, prior_remote)
            _write_state(state_path, state)

    return UpdateCheckClaim(1, due, local_commit, prior_remote)


def record_update_result(
    cache_root: Path,
    runtime_root: Path,
    local_commit: str,
    remote_commit: str,
    now_epoch_seconds: int,
) -> None:
    """Persist one successful fixed-repository commit comparison."""
    if (
        not _is_normal_absolute(cache_root)
        or not _is_normal_absolute(runtime_root)
        or not valid_commit(local_commit)
        or not valid_commit(remote_commit)
        or isinstance(now_epoch_seconds, bool)
        or not 0 <= now_epoch_seconds <= MAX_EPOCH_SECONDS
    ):
        raise UpdateHelperError("the update-check result is invalid")

    ensure_private_directory(cache_root)
    state_path = cache_root / STATE_FILE_NAME
    with _update_check_lock(runtime_root):
        state = _load_state(state_path)
        timestamp = (
            state.lastAttemptEpochSeconds
            if state is not None and state.localCommit == local_commit
            else now_epoch_seconds
        )
        _write_state(state_path, UpdateCheckState(1, timestamp, local_commit, remote_commit))


def _claim_payload(claim: UpdateCheckClaim) -> str:
    return json.dumps(asdict(claim), separators=(",", ":"), sort_keys=True) + "\n"


def run(argv: Sequence[str], *, now_epoch_seconds: int | None = None) -> int:
    """Run one stdlib-only update helper operation with bounded output."""
    current_time = int(time.time()) if now_epoch_seconds is None else now_epoch_seconds
    try:
        if len(argv) == 3 and argv[0] == "validate-checkout":
            return 0 if checkout_is_supported(Path(argv[1]), Path(argv[2])) else 1
        if len(argv) in {4, 5} and argv[0] == "claim":
            if len(argv) == 5 and argv[4] != "--force":
                return 2
            claim = claim_update_check(
                Path(argv[1]),
                Path(argv[2]),
                argv[3],
                current_time,
                force=len(argv) == 5,
            )
            sys.stdout.write(_claim_payload(claim))
            return 0
        if len(argv) == 5 and argv[0] == "record":
            record_update_result(Path(argv[1]), Path(argv[2]), argv[3], argv[4], current_time)
            return 0
        return 2
    except (OSError, UnsafeStoragePathError, UpdateHelperError, ValueError):
        return 1


def main() -> int:
    """Run the update helper with the current process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
