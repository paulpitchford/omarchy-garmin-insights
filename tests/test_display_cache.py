import os
from pathlib import Path

import pytest

from omarchy_garmin.display_cache import (
    DisplayCacheDataError,
    DisplayCacheKind,
    DisplayCacheReader,
    DisplayCacheStorageError,
)
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.storage import ensure_private_directory
from omarchy_garmin.summary import MAX_SUMMARY_BYTES
from omarchy_garmin.trends import MAX_ACTIVITY_TRENDS_BYTES


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        state=tmp_path / "state",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
    )


@pytest.mark.parametrize(
    ("kind", "filename", "content"),
    [
        pytest.param(
            DisplayCacheKind.SUMMARY, "summary.json", b'{"schemaVersion":1}\n', id="summary"
        ),
        pytest.param(
            DisplayCacheKind.ACTIVITY_TRENDS,
            "activity-trends.json",
            b'{"schemaVersion":1,"periods":[]}\n',
            id="activity-trends",
        ),
    ],
)
def test_reader_returns_reviewed_cache_as_utf8_text(
    tmp_path: Path,
    kind: DisplayCacheKind,
    filename: str,
    content: bytes,
) -> None:
    paths = _paths(tmp_path)
    cache = ensure_private_directory(paths.cache)
    (cache / filename).write_bytes(content)

    result = DisplayCacheReader(paths).read(kind)

    assert result == content.decode()


@pytest.mark.parametrize(
    ("kind", "filename", "limit"),
    [
        pytest.param(DisplayCacheKind.SUMMARY, "summary.json", MAX_SUMMARY_BYTES, id="summary"),
        pytest.param(
            DisplayCacheKind.ACTIVITY_TRENDS,
            "activity-trends.json",
            MAX_ACTIVITY_TRENDS_BYTES,
            id="activity-trends",
        ),
    ],
)
def test_reader_rejects_cache_above_its_contract_limit(
    tmp_path: Path,
    kind: DisplayCacheKind,
    filename: str,
    limit: int,
) -> None:
    paths = _paths(tmp_path)
    cache = ensure_private_directory(paths.cache)
    (cache / filename).write_bytes(b"x" * (limit + 1))

    with pytest.raises(DisplayCacheStorageError, match="read safely"):
        DisplayCacheReader(paths).read(kind)


def test_reader_rejects_invalid_utf8(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    cache = ensure_private_directory(paths.cache)
    (cache / "summary.json").write_bytes(b"\xff")

    with pytest.raises(DisplayCacheDataError, match="UTF-8"):
        DisplayCacheReader(paths).read(DisplayCacheKind.SUMMARY)


def test_reader_rejects_symlink_without_reading_target(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    cache = ensure_private_directory(paths.cache)
    target = tmp_path / "target.json"
    target.write_text("synthetic target")
    (cache / "summary.json").symlink_to(target)

    with pytest.raises(DisplayCacheStorageError, match="read safely"):
        DisplayCacheReader(paths).read(DisplayCacheKind.SUMMARY)

    assert target.read_text() == "synthetic target"


def test_reader_rejects_fifo_as_non_regular(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    cache = ensure_private_directory(paths.cache)
    fifo = cache / "summary.json"
    os.mkfifo(fifo)

    with pytest.raises(DisplayCacheStorageError, match="read safely"):
        DisplayCacheReader(paths).read(DisplayCacheKind.SUMMARY)
