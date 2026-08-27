import json
import stat
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

import omarchy_garmin.trends as trends_module
from omarchy_garmin.activities import Activity
from omarchy_garmin.trends import (
    ACTIVITY_TRENDS_SCHEMA_VERSION,
    MAX_TREND_ACTIVITIES,
    ActivityTrendsCache,
    ActivityTrendsDataError,
    ActivityTrendsStorageError,
    render_activity_trends,
)

_AS_OF = date(2026, 8, 26)
_GENERATED_AT = datetime(2026, 8, 26, 23, 30, tzinfo=timezone(timedelta(hours=-4)))


def _activity(
    activity_id: str,
    local_date: date,
    *,
    duration_seconds: float | None = None,
    distance_metres: float | None = None,
    elevation_gain_metres: float | None = None,
    energy_joules: float | None = None,
) -> Activity:
    return Activity(
        activity_id=activity_id,
        name=f"Private synthetic name {activity_id}",
        type_key="synthetic_sport",
        started_at_local=f"{local_date.isoformat()} 07:30:00",
        local_date=local_date,
        duration_seconds=duration_seconds,
        moving_duration_seconds=None,
        distance_metres=distance_metres,
        elevation_gain_metres=elevation_gain_metres,
        energy_joules=energy_joules,
        average_heart_rate_bpm=None,
        maximum_heart_rate_bpm=None,
        average_speed_metres_per_second=None,
        average_power_watts=None,
        total_sets=None,
        total_repetitions=None,
    )


def _payload(activities: list[Activity]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            render_activity_trends(
                activities,
                as_of_date=_AS_OF,
                generated_at=_GENERATED_AT,
            )
        ),
    )


def test_trends_use_daily_points_for_seven_and_thirty_days() -> None:
    payload = _payload([])

    seven_days, thirty_days, _ = payload["periods"]

    assert payload["schemaVersion"] == ACTIVITY_TRENDS_SCHEMA_VERSION
    assert payload["generatedAt"] == "2026-08-27T03:30:00Z"
    assert len(seven_days["points"]) == 7
    assert seven_days["points"][0]["startDate"] == "2026-08-20"
    assert seven_days["points"][-1]["endDate"] == "2026-08-26"
    assert len(thirty_days["points"]) == 30
    assert all(point["startDate"] == point["endDate"] for point in thirty_days["points"])


def test_ninety_day_trends_use_one_six_day_and_twelve_seven_day_buckets() -> None:
    quarter = _payload([])["periods"][2]

    points = quarter["points"]

    assert len(points) == 13
    assert points[0]["startDate"] == "2026-05-29"
    assert points[0]["endDate"] == "2026-06-03"
    assert points[1]["startDate"] == "2026-06-04"
    assert points[1]["endDate"] == "2026-06-10"
    assert points[-1]["startDate"] == "2026-08-20"
    assert points[-1]["endDate"] == "2026-08-26"


def test_empty_dates_are_zero_while_missing_activity_measurements_remain_null() -> None:
    activity = _activity("1", _AS_OF, duration_seconds=None)

    points = _payload([activity])["periods"][0]["points"]

    assert points[-2]["activityCount"] == 0
    assert points[-2]["durationSeconds"] == {
        "value": 0.0,
        "contributingActivityCount": 0,
    }
    assert points[-1]["activityCount"] == 1
    assert points[-1]["durationSeconds"] == {
        "value": None,
        "contributingActivityCount": 0,
    }


def test_bucket_metrics_sum_values_and_count_only_contributors() -> None:
    activities = [
        _activity(
            "1",
            _AS_OF,
            duration_seconds=600,
            distance_metres=1000,
            elevation_gain_metres=25,
            energy_joules=500_000,
        ),
        _activity("2", _AS_OF, duration_seconds=300, distance_metres=None),
    ]

    point = _payload(activities)["periods"][0]["points"][-1]

    assert point["activityCount"] == 2
    assert point["durationSeconds"] == {
        "value": 900.0,
        "contributingActivityCount": 2,
    }
    assert point["distanceMetres"] == {
        "value": 1000.0,
        "contributingActivityCount": 1,
    }
    assert point["elevationGainMetres"]["value"] == 25.0
    assert point["energyJoules"]["value"] == 500_000.0


def test_only_the_current_trailing_point_is_marked_partial() -> None:
    payload = _payload([])

    partial_values = [
        point["partial"] for period in payload["periods"] for point in period["points"]
    ]

    assert partial_values.count(True) == 3
    assert all(period["points"][-1]["partial"] is True for period in payload["periods"])


def test_trends_exclude_activity_identity_and_type_text() -> None:
    content = render_activity_trends(
        [_activity("private-identifier", _AS_OF, duration_seconds=60)],
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
    )

    assert b"Private synthetic name" not in content
    assert b"private-identifier" not in content
    assert b"synthetic_sport" not in content
    assert b"07:30:00" not in content


@pytest.mark.parametrize(
    "activity",
    [
        pytest.param(
            replace(_activity("1", _AS_OF), duration_seconds=float("inf")),
            id="infinite-duration",
        ),
        pytest.param(
            replace(_activity("1", _AS_OF), distance_metres=cast(Any, True)),
            id="boolean-distance",
        ),
        pytest.param(
            _activity("1", _AS_OF - timedelta(days=90)),
            id="outside-rolling-period",
        ),
        pytest.param(
            replace(_activity("1", _AS_OF), local_date=cast(Any, _GENERATED_AT)),
            id="datetime-local-date",
        ),
    ],
)
def test_invalid_activity_trend_input_is_rejected(activity: Activity) -> None:
    with pytest.raises(ActivityTrendsDataError):
        _payload([activity])


def test_invalid_trend_dates_and_generation_times_are_rejected() -> None:
    with pytest.raises(ActivityTrendsDataError, match="local date"):
        render_activity_trends(
            [],
            as_of_date=cast(Any, _GENERATED_AT),
            generated_at=_GENERATED_AT,
        )
    with pytest.raises(ActivityTrendsDataError, match="timezone"):
        render_activity_trends(
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT.replace(tzinfo=None),
        )


def test_activity_count_above_trend_limit_is_rejected() -> None:
    repeated_activity = _activity("1", _AS_OF)

    with pytest.raises(ActivityTrendsDataError, match="activity count"):
        _payload([repeated_activity] * (MAX_TREND_ACTIVITIES + 1))


def test_daily_trend_aggregate_overflow_is_rejected() -> None:
    activities = [
        _activity("1", _AS_OF, duration_seconds=1e308),
        _activity("2", _AS_OF, duration_seconds=1e308),
    ]

    with pytest.raises(ActivityTrendsDataError, match="outside the limit"):
        _payload(activities)


def test_bucket_merge_overflow_is_rejected() -> None:
    activities = [
        _activity("1", _AS_OF, duration_seconds=1e308),
        _activity("2", _AS_OF - timedelta(days=1), duration_seconds=1e308),
    ]

    with pytest.raises(ActivityTrendsDataError, match="outside the limit"):
        _payload(activities)


def test_trend_point_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trends_module, "MAX_TREND_POINTS", 49)

    with pytest.raises(ActivityTrendsDataError, match="point count"):
        _payload([])


def test_trend_serialization_failure_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_serialization(*args: object, **kwargs: object) -> str:
        raise TypeError("fabricated serialization failure")

    monkeypatch.setattr("omarchy_garmin.trends.json.dumps", fail_serialization)

    with pytest.raises(ActivityTrendsDataError, match="serialized safely"):
        _payload([])


def test_serialized_trend_byte_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trends_module, "MAX_ACTIVITY_TRENDS_BYTES", 1)

    with pytest.raises(ActivityTrendsDataError, match="byte limit"):
        _payload([])


def test_relative_activity_trends_cache_path_is_rejected() -> None:
    with pytest.raises(ActivityTrendsStorageError):
        ActivityTrendsCache(Path("relative/activity-trends.json")).write(
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
        )


def test_activity_trends_cache_is_atomic_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "activity-trends.json"

    ActivityTrendsCache(path).write([], as_of_date=_AS_OF, generated_at=_GENERATED_AT)

    assert json.loads(path.read_bytes())["schemaVersion"] == ACTIVITY_TRENDS_SCHEMA_VERSION
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_activity_trends_cache_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"keep")
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    path = cache_directory / "activity-trends.json"
    path.symlink_to(target)

    ActivityTrendsCache(path).write([], as_of_date=_AS_OF, generated_at=_GENERATED_AT)

    assert target.read_bytes() == b"keep"
    assert path.is_symlink() is False
    assert json.loads(path.read_bytes())["schemaVersion"] == ACTIVITY_TRENDS_SCHEMA_VERSION


def test_failed_trend_replacement_preserves_previous_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache" / "activity-trends.json"
    cache = ActivityTrendsCache(path)
    cache.write([], as_of_date=_AS_OF, generated_at=_GENERATED_AT)
    original = path.read_bytes()

    def fail_write(destination: Path, content: bytes) -> None:
        raise OSError("fabricated interrupted write")

    monkeypatch.setattr(trends_module, "atomic_write_private", fail_write)

    with pytest.raises(ActivityTrendsStorageError):
        cache.write(
            [_activity("1", _AS_OF, duration_seconds=60)],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
        )

    assert path.read_bytes() == original
