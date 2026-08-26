import stat
from pathlib import Path

from omarchy_garmin.cache_bootstrap import run


def test_cache_bootstrap_creates_owner_only_application_root(tmp_path: Path) -> None:
    cache_root = tmp_path / "generic-cache" / "omarchy-garmin-insights"

    exit_status = run([str(cache_root)])

    assert exit_status == 0
    assert stat.S_IMODE(cache_root.stat().st_mode) == 0o700


def test_cache_bootstrap_tightens_existing_application_root(tmp_path: Path) -> None:
    cache_root = tmp_path / "omarchy-garmin-insights"
    cache_root.mkdir(mode=0o755)

    exit_status = run([str(cache_root)])

    assert exit_status == 0
    assert stat.S_IMODE(cache_root.stat().st_mode) == 0o700


def test_cache_bootstrap_rejects_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    target.chmod(0o755)
    cache_root = tmp_path / "omarchy-garmin-insights"
    cache_root.symlink_to(target, target_is_directory=True)

    exit_status = run([str(cache_root)])

    assert exit_status == 1
    assert cache_root.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) != 0o700


def test_cache_bootstrap_rejects_relative_or_extra_arguments() -> None:
    assert run(["relative/cache"]) == 1
    assert run([]) == 2
    assert run(["/first", "/second"]) == 2
