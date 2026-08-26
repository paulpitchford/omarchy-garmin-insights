import fcntl
import json
import os
import stat
from pathlib import Path
from typing import cast

import pytest

from omarchy_garmin.storage import UnsafeStoragePathError
from omarchy_garmin.update_helper import (
    LOCK_FILE_NAME,
    STATE_FILE_NAME,
    UPDATE_CADENCE_SECONDS,
    UPDATE_REPOSITORY_URL,
    UpdateCheckBusyError,
    UpdateHelperError,
    checkout_is_supported,
    claim_update_check,
    record_update_result,
    run,
    valid_commit,
)

LOCAL_COMMIT = "1" * 40
REMOTE_COMMIT = "2" * 40
NEW_LOCAL_COMMIT = "3" * 40
NOW = 1_800_000_000


def make_checkout(path: Path, *, config: str | None = None) -> Path:
    path.mkdir(parents=True)
    git_dir = path / ".git"
    git_dir.mkdir()
    content = config or (
        "[core]\n\trepositoryformatversion = 0\n"
        '[remote "origin"]\n'
        f"\turl = {UPDATE_REPOSITORY_URL}\n"
    )
    (git_dir / "config").write_text(content)
    return path


def state_payload(cache_root: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((cache_root / STATE_FILE_NAME).read_text()))


def test_supported_checkout_requires_fixed_owned_git_configuration(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "installed")

    supported = checkout_is_supported(checkout, checkout)

    assert supported is True


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(
            '[remote "origin"]\n\turl = https://example.invalid/plugin.git\n',
            id="changed-origin",
        ),
        pytest.param("[include]\n\tpath = /synthetic/config\n", id="included-config"),
        pytest.param(
            f'[url "https://example.invalid/"]\n\tinsteadOf = {UPDATE_REPOSITORY_URL}\n'
            '[remote "origin"]\n'
            f"\turl = {UPDATE_REPOSITORY_URL}\n",
            id="url-rewrite",
        ),
        pytest.param("not a git configuration", id="malformed"),
        pytest.param("[core]\n\trepositoryformatversion = 0\n", id="missing-origin"),
    ],
)
def test_checkout_with_untrusted_configuration_is_unsupported(tmp_path: Path, config: str) -> None:
    checkout = make_checkout(tmp_path / "installed", config=config)

    supported = checkout_is_supported(checkout, checkout)

    assert supported is False


def test_copied_checkout_is_unsupported(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "copied")

    supported = checkout_is_supported(checkout, tmp_path / "expected")

    assert supported is False


def test_checkout_path_with_traversal_is_unsupported() -> None:
    checkout = Path("/synthetic/../checkout")

    supported = checkout_is_supported(checkout, checkout)

    assert supported is False


def test_checkout_owned_by_another_user_is_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = make_checkout(tmp_path / "installed")
    other_owner = os.geteuid() + 1
    monkeypatch.setattr("omarchy_garmin.update_helper.os.geteuid", lambda: other_owner)

    supported = checkout_is_supported(checkout, checkout)

    assert supported is False


def test_symlinked_git_directory_is_unsupported(tmp_path: Path) -> None:
    real_git = tmp_path / "real-git"
    real_git.mkdir()
    (real_git / "config").write_text(f'[remote "origin"]\n\turl = {UPDATE_REPOSITORY_URL}\n')
    checkout = tmp_path / "installed"
    checkout.mkdir()
    (checkout / ".git").symlink_to(real_git, target_is_directory=True)

    supported = checkout_is_supported(checkout, checkout)

    assert supported is False


def test_symlinked_git_configuration_is_unsupported(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "installed")
    target = tmp_path / "target-config"
    target.write_text(f'[remote "origin"]\n\turl = {UPDATE_REPOSITORY_URL}\n')
    (checkout / ".git" / "config").unlink()
    (checkout / ".git" / "config").symlink_to(target)

    supported = checkout_is_supported(checkout, checkout)

    assert supported is False


def test_oversized_git_configuration_is_unsupported(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "installed", config="x" * (16 * 1024 + 1))

    supported = checkout_is_supported(checkout, checkout)

    assert supported is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(LOCAL_COMMIT, True, id="canonical"),
        pytest.param("A" * 40, False, id="uppercase"),
        pytest.param("g" * 40, False, id="non-hex"),
        pytest.param("1" * 39, False, id="short"),
        pytest.param(None, False, id="non-string"),
    ],
)
def test_commit_validation_is_strict(value: object, expected: bool) -> None:
    assert valid_commit(value) is expected


def test_first_claim_is_due_and_writes_owner_only_state(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    assert claim.due is True
    assert claim.remoteCommit is None
    assert state_payload(cache_root)["lastAttemptEpochSeconds"] == NOW
    assert stat.S_IMODE(cache_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((cache_root / STATE_FILE_NAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((runtime_root / LOCK_FILE_NAME).stat().st_mode) == 0o600


def test_repeated_claim_within_24_hours_is_not_due(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    claim = claim_update_check(
        cache_root, runtime_root, LOCAL_COMMIT, NOW + UPDATE_CADENCE_SECONDS - 1
    )

    assert claim.due is False
    assert state_payload(cache_root)["lastAttemptEpochSeconds"] == NOW


def test_claim_at_24_hours_is_due(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW + UPDATE_CADENCE_SECONDS)

    assert claim.due is True
    assert state_payload(cache_root)["lastAttemptEpochSeconds"] == NOW + UPDATE_CADENCE_SECONDS


def test_manual_claim_bypasses_cadence(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW + 10, force=True)

    assert claim.due is True
    assert state_payload(cache_root)["lastAttemptEpochSeconds"] == NOW + 10


def test_clock_rollback_does_not_repeat_automatic_check(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW - 10)

    assert claim.due is False


def test_successful_result_is_restored_for_same_local_commit(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)
    record_update_result(cache_root, runtime_root, LOCAL_COMMIT, REMOTE_COMMIT, NOW + 1)

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW + 10)

    assert claim.due is False
    assert claim.remoteCommit == REMOTE_COMMIT
    assert state_payload(cache_root)["lastAttemptEpochSeconds"] == NOW


def test_changed_local_commit_requires_new_check_and_drops_old_comparison(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)
    record_update_result(cache_root, runtime_root, LOCAL_COMMIT, REMOTE_COMMIT, NOW)

    claim = claim_update_check(cache_root, runtime_root, NEW_LOCAL_COMMIT, NOW + 10)

    assert claim.due is True
    assert claim.remoteCommit is None
    assert state_payload(cache_root)["localCommit"] == NEW_LOCAL_COMMIT


def test_record_without_prior_claim_uses_current_time(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"

    record_update_result(cache_root, runtime_root, LOCAL_COMMIT, REMOTE_COMMIT, NOW)

    assert state_payload(cache_root) == {
        "schemaVersion": 1,
        "lastAttemptEpochSeconds": NOW,
        "localCommit": LOCAL_COMMIT,
        "remoteCommit": REMOTE_COMMIT,
    }


def test_malformed_state_is_replaced_by_due_claim(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    cache_root.mkdir()
    (cache_root / STATE_FILE_NAME).write_text("not-json")

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    assert claim.due is True
    assert state_payload(cache_root)["localCommit"] == LOCAL_COMMIT


@pytest.mark.parametrize(
    "schema_version",
    [
        pytest.param(True, id="boolean"),
        pytest.param(1.0, id="float"),
        pytest.param("1", id="string"),
    ],
)
def test_non_integer_state_schema_is_replaced_by_due_claim(
    tmp_path: Path, schema_version: object
) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    cache_root.mkdir()
    (cache_root / STATE_FILE_NAME).write_text(
        json.dumps(
            {
                "schemaVersion": schema_version,
                "lastAttemptEpochSeconds": NOW,
                "localCommit": LOCAL_COMMIT,
                "remoteCommit": REMOTE_COMMIT,
            }
        )
    )

    claim = claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW + 10)

    assert claim.due is True
    assert claim.remoteCommit is None
    assert state_payload(cache_root)["schemaVersion"] == 1


def test_symlinked_state_is_rejected_without_touching_target(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    cache_root.mkdir()
    target = tmp_path / "target"
    target.write_text("synthetic")
    (cache_root / STATE_FILE_NAME).symlink_to(target)

    with pytest.raises(UnsafeStoragePathError):
        claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)

    assert target.read_text() == "synthetic"


def test_concurrent_claim_is_rejected_without_waiting(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    lock_path = runtime_root / LOCK_FILE_NAME
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(UpdateCheckBusyError):
            claim_update_check(cache_root, runtime_root, LOCAL_COMMIT, NOW)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("cache_root", "runtime_root", "commit", "timestamp"),
    [
        pytest.param(Path("relative"), Path("/runtime"), LOCAL_COMMIT, NOW, id="cache"),
        pytest.param(Path("/cache"), Path("relative"), LOCAL_COMMIT, NOW, id="runtime"),
        pytest.param(Path("/cache/../other"), Path("/runtime"), LOCAL_COMMIT, NOW, id="traversal"),
        pytest.param(Path("/cache"), Path("/runtime"), "invalid", NOW, id="commit"),
        pytest.param(Path("/cache"), Path("/runtime"), LOCAL_COMMIT, -1, id="timestamp"),
    ],
)
def test_invalid_claim_arguments_are_rejected(
    cache_root: Path, runtime_root: Path, commit: str, timestamp: int
) -> None:
    with pytest.raises(UpdateHelperError):
        claim_update_check(cache_root, runtime_root, commit, timestamp)


def test_run_claim_returns_bounded_machine_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"

    exit_status = run(
        ["claim", str(cache_root), str(runtime_root), LOCAL_COMMIT],
        now_epoch_seconds=NOW,
    )

    output = capsys.readouterr().out
    assert exit_status == 0
    assert len(output) < 256
    assert json.loads(output)["due"] is True


def test_run_validates_checkout_and_records_result(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "installed")
    cache_root = tmp_path / "cache"
    runtime_root = tmp_path / "runtime"

    validate_status = run(["validate-checkout", str(checkout), str(checkout)])
    record_status = run(
        ["record", str(cache_root), str(runtime_root), LOCAL_COMMIT, REMOTE_COMMIT],
        now_epoch_seconds=NOW,
    )

    assert validate_status == 0
    assert record_status == 0
    assert state_payload(cache_root)["remoteCommit"] == REMOTE_COMMIT


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param([], id="empty"),
        pytest.param(["unknown"], id="unknown-command"),
        pytest.param(["claim", "/cache", "/runtime", LOCAL_COMMIT, "--bad"], id="bad-option"),
    ],
)
def test_run_rejects_unknown_arguments(arguments: list[str]) -> None:
    assert run(arguments, now_epoch_seconds=NOW) == 2


def test_run_maps_unsafe_storage_to_failure(tmp_path: Path) -> None:
    cache_target = tmp_path / "cache-target"
    cache_target.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.symlink_to(cache_target, target_is_directory=True)

    exit_status = run(
        ["claim", str(cache_root), str(tmp_path / "runtime"), LOCAL_COMMIT],
        now_epoch_seconds=NOW,
    )

    assert exit_status == 1
