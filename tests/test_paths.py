from pathlib import Path

import pytest

from omarchy_garmin.paths import (
    ACCOUNT_SCOPE_FILE_NAME,
    ACTIVITY_DATABASE_FILE_NAME,
    APP_DIRECTORY,
    SUMMARY_FILE_NAME,
    SYNC_LOCK_FILE_NAME,
    TOKEN_FILE_NAME,
    AppPaths,
)


def test_defaults_follow_home_directory() -> None:
    paths = AppPaths.from_environment({}, Path("/home/example"))

    assert paths.state == Path("/home/example/.local/state") / APP_DIRECTORY
    assert paths.data == Path("/home/example/.local/share") / APP_DIRECTORY
    assert paths.cache == Path("/home/example/.cache") / APP_DIRECTORY
    assert paths.runtime is None


def test_application_file_paths_use_dedicated_xdg_scopes() -> None:
    paths = AppPaths.from_environment({}, Path("/home/example"))

    assert paths.auth == paths.state / "auth"
    assert paths.token_file == paths.auth / TOKEN_FILE_NAME
    assert paths.account_scope_file == paths.data / ACCOUNT_SCOPE_FILE_NAME
    assert paths.activity_database == paths.data / ACTIVITY_DATABASE_FILE_NAME
    assert paths.summary_file == paths.cache / SUMMARY_FILE_NAME
    assert paths.sync_lock_file is None


def test_absolute_xdg_overrides_are_used() -> None:
    environment = {
        "XDG_STATE_HOME": "/private/state",
        "XDG_DATA_HOME": "/private/data",
        "XDG_CACHE_HOME": "/private/cache",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }

    paths = AppPaths.from_environment(environment, Path("/home/example"))

    assert paths.state == Path("/private/state") / APP_DIRECTORY
    assert paths.data == Path("/private/data") / APP_DIRECTORY
    assert paths.cache == Path("/private/cache") / APP_DIRECTORY
    assert paths.runtime == Path("/run/user/1000") / APP_DIRECTORY
    assert paths.sync_lock_file == paths.runtime / SYNC_LOCK_FILE_NAME


@pytest.mark.parametrize(
    "variable",
    [
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR",
    ],
)
def test_relative_xdg_override_is_ignored(variable: str) -> None:
    paths = AppPaths.from_environment({variable: "relative/path"}, Path("/home/example"))

    defaults = AppPaths.from_environment({}, Path("/home/example"))
    assert paths == defaults


def test_relative_home_is_rejected() -> None:
    with pytest.raises(ValueError, match="home must be an absolute path"):
        AppPaths.from_environment({}, Path("relative/home"))
