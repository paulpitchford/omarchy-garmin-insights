import json
import stat
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

import omarchy_garmin.summary as summary_module
from omarchy_garmin.activities import Activity
from omarchy_garmin.summary import (
    MAX_SUMMARY_ACTIVITIES,
    MAX_SUMMARY_TYPES,
    SUMMARY_SCHEMA_VERSION,
    SummaryCache,
    SummaryDataError,
    SummaryStorageError,
    render_summary,
)

_AS_OF = date(2026, 8, 26)
_GENERATED_AT = datetime(2026, 8, 26, 23, 30, tzinfo=timezone(timedelta(hours=-4)))


def _activity(
    activity_id: str,
    local_date: date,
    *,
    type_key: str = "synthetic_sport",
    duration_seconds: float | None = None,
    moving_duration_seconds: float | None = None,
    distance_metres: float | None = None,
    elevation_gain_metres: float | None = None,
    energy_joules: float | None = None,
    average_heart_rate_bpm: float | None = None,
    maximum_heart_rate_bpm: float | None = None,
    average_speed_metres_per_second: float | None = None,
    average_power_watts: float | None = None,
    total_sets: int | None = None,
    total_repetitions: int | None = None,
) -> Activity:
    return Activity(
        activity_id=activity_id,
        name=f"Private synthetic name {activity_id}",
        type_key=type_key,
        started_at_local=f"{local_date.isoformat()} 23:45:00",
        local_date=local_date,
        duration_seconds=duration_seconds,
        moving_duration_seconds=moving_duration_seconds,
        distance_metres=distance_metres,
        elevation_gain_metres=elevation_gain_metres,
        energy_joules=energy_joules,
        average_heart_rate_bpm=average_heart_rate_bpm,
        maximum_heart_rate_bpm=maximum_heart_rate_bpm,
        average_speed_metres_per_second=average_speed_metres_per_second,
        average_power_watts=average_power_watts,
        total_sets=total_sets,
        total_repetitions=total_repetitions,
    )


def _payload(activities: list[Activity]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(render_summary(activities, as_of_date=_AS_OF, generated_at=_GENERATED_AT)),
    )


def test_summary_uses_inclusive_local_calendar_period_boundaries() -> None:
    activities = [
        _activity("today", _AS_OF),
        _activity("six-days", _AS_OF - timedelta(days=6)),
        _activity("seven-days", _AS_OF - timedelta(days=7)),
        _activity("twenty-nine-days", _AS_OF - timedelta(days=29)),
        _activity("thirty-days", _AS_OF - timedelta(days=30)),
        _activity("eighty-nine-days", _AS_OF - timedelta(days=89)),
    ]

    payload = _payload(activities)

    periods = payload["periods"]
    assert payload["schemaVersion"] == SUMMARY_SCHEMA_VERSION
    assert payload["asOfLocalDate"] == "2026-08-26"
    assert payload["generatedAt"] == "2026-08-27T03:30:00Z"
    assert [period["key"] for period in periods] == ["today", "7Days", "30Days", "90Days"]
    assert [period["startDate"] for period in periods] == [
        "2026-08-26",
        "2026-08-20",
        "2026-07-28",
        "2026-05-29",
    ]
    assert [period["overall"]["activityCount"] for period in periods] == [1, 2, 4, 6]


def test_summary_keeps_original_mixed_activity_types_in_stable_order() -> None:
    activities = [
        _activity("1", _AS_OF, type_key="synthetic_new_sport"),
        _activity("2", _AS_OF, type_key="running"),
        _activity("3", _AS_OF, type_key="running"),
        _activity("4", _AS_OF, type_key="cycling"),
    ]

    payload = _payload(activities)

    today_types = payload["periods"][0]["byType"]
    assert [(item["typeKey"], item["activityCount"]) for item in today_types] == [
        ("running", 2),
        ("cycling", 1),
        ("synthetic_new_sport", 1),
    ]


def test_summary_sums_known_values_and_reports_missing_value_contributors() -> None:
    activities = [
        _activity("1", _AS_OF, duration_seconds=10, distance_metres=100),
        _activity("2", _AS_OF, duration_seconds=None, distance_metres=200),
        _activity("3", _AS_OF, duration_seconds=0, distance_metres=None),
    ]

    overall = _payload(activities)["periods"][0]["overall"]

    assert overall["activityCount"] == 3
    assert overall["durationSeconds"] == {
        "value": 10.0,
        "contributingActivityCount": 2,
    }
    assert overall["distanceMetres"] == {
        "value": 300.0,
        "contributingActivityCount": 2,
    }
    assert overall["energyJoules"] == {
        "value": None,
        "contributingActivityCount": 0,
    }


def test_summary_uses_documented_duration_weighted_averages_and_maximum() -> None:
    activities = [
        _activity(
            "1",
            _AS_OF,
            duration_seconds=10,
            moving_duration_seconds=20,
            average_heart_rate_bpm=100,
            maximum_heart_rate_bpm=150,
            average_speed_metres_per_second=2,
            average_power_watts=200,
            total_sets=3,
            total_repetitions=10,
        ),
        _activity(
            "2",
            _AS_OF,
            duration_seconds=30,
            moving_duration_seconds=10,
            average_heart_rate_bpm=200,
            maximum_heart_rate_bpm=180,
            average_speed_metres_per_second=5,
            average_power_watts=400,
            total_sets=None,
            total_repetitions=20,
        ),
        _activity(
            "3",
            _AS_OF,
            average_heart_rate_bpm=250,
            average_speed_metres_per_second=9,
            average_power_watts=600,
            total_sets=0,
            total_repetitions=0,
        ),
        _activity(
            "4",
            _AS_OF,
            duration_seconds=0,
            moving_duration_seconds=0,
            average_heart_rate_bpm=300,
            average_speed_metres_per_second=10,
            average_power_watts=700,
        ),
    ]

    overall = _payload(activities)["periods"][0]["overall"]

    assert overall["averageHeartRateBpm"] == {
        "value": 175.0,
        "contributingActivityCount": 2,
    }
    assert overall["maximumHeartRateBpm"] == {
        "value": 180.0,
        "contributingActivityCount": 2,
    }
    assert overall["averageSpeedMetresPerSecond"] == {
        "value": 3.0,
        "contributingActivityCount": 2,
    }
    assert overall["averagePowerWatts"] == {
        "value": 350.0,
        "contributingActivityCount": 2,
    }
    assert overall["totalSets"] == {"value": 3, "contributingActivityCount": 2}
    assert overall["totalRepetitions"] == {
        "value": 30,
        "contributingActivityCount": 3,
    }


def test_empty_period_has_zero_activities_and_null_metrics() -> None:
    payload = _payload([_activity("old", _AS_OF - timedelta(days=20))])

    today = payload["periods"][0]

    assert today["overall"]["activityCount"] == 0
    assert today["overall"]["distanceMetres"] == {
        "value": None,
        "contributingActivityCount": 0,
    }
    assert today["byType"] == []


def test_summary_excludes_activity_names_identifiers_and_start_times() -> None:
    content = render_summary(
        [_activity("private-identifier", _AS_OF)],
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
    )

    assert b"Private synthetic name" not in content
    assert b"private-identifier" not in content
    assert b"23:45:00" not in content


@pytest.mark.parametrize(
    "activity",
    [
        pytest.param(
            replace(_activity("1", _AS_OF), distance_metres=float("inf")),
            id="infinite-measurement",
        ),
        pytest.param(_activity("1", _AS_OF, type_key=""), id="empty-type-key"),
        pytest.param(
            replace(_activity("1", _AS_OF), total_sets=cast(Any, True)),
            id="boolean-strength-count",
        ),
        pytest.param(
            _activity("1", _AS_OF - timedelta(days=90)),
            id="outside-rolling-period",
        ),
        pytest.param(
            replace(_activity("1", _AS_OF), local_date=cast(Any, _GENERATED_AT)),
            id="datetime-instead-of-local-date",
        ),
    ],
)
def test_invalid_summary_activity_is_rejected(activity: Activity) -> None:
    with pytest.raises(SummaryDataError):
        _payload([activity])


def test_datetime_as_summary_local_date_is_rejected() -> None:
    with pytest.raises(SummaryDataError, match="local date"):
        render_summary(
            [],
            as_of_date=cast(Any, _GENERATED_AT),
            generated_at=_GENERATED_AT,
        )


def test_naive_generation_timestamp_is_rejected() -> None:
    with pytest.raises(SummaryDataError, match="timezone"):
        render_summary([], as_of_date=_AS_OF, generated_at=_GENERATED_AT.replace(tzinfo=None))


def test_activity_count_at_limit_is_aggregated() -> None:
    repeated_activity = _activity("1", _AS_OF)
    activities = [repeated_activity] * MAX_SUMMARY_ACTIVITIES

    payload = _payload(activities)

    assert payload["periods"][0]["overall"]["activityCount"] == MAX_SUMMARY_ACTIVITIES


def test_activity_count_above_limit_is_rejected_before_aggregation() -> None:
    repeated_activity = _activity("1", _AS_OF)
    activities = [repeated_activity] * (MAX_SUMMARY_ACTIVITIES + 1)

    with pytest.raises(SummaryDataError, match="activity count"):
        _payload(activities)


def test_distinct_type_count_above_limit_is_rejected() -> None:
    activities = [
        _activity(str(index), _AS_OF, type_key=f"synthetic_type_{index}")
        for index in range(MAX_SUMMARY_TYPES + 1)
    ]

    with pytest.raises(SummaryDataError, match="type count"):
        _payload(activities)


def test_serialized_byte_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(summary_module, "MAX_SUMMARY_BYTES", 1)

    with pytest.raises(SummaryDataError, match="byte limit"):
        _payload([])


def test_relative_summary_cache_path_is_rejected() -> None:
    with pytest.raises(SummaryStorageError):
        SummaryCache(Path("relative/summary.json")).write(
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
        )


def test_summary_cache_is_atomic_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "summary.json"

    SummaryCache(path).write([], as_of_date=_AS_OF, generated_at=_GENERATED_AT)

    assert json.loads(path.read_bytes())["schemaVersion"] == SUMMARY_SCHEMA_VERSION
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_summary_cache_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"keep")
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    path = cache_directory / "summary.json"
    path.symlink_to(target)

    SummaryCache(path).write([], as_of_date=_AS_OF, generated_at=_GENERATED_AT)

    assert target.read_bytes() == b"keep"
    assert path.is_symlink() is False
    assert json.loads(path.read_bytes())["schemaVersion"] == SUMMARY_SCHEMA_VERSION


def test_failed_cache_replacement_preserves_previous_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache" / "summary.json"
    cache = SummaryCache(path)
    cache.write([], as_of_date=_AS_OF, generated_at=_GENERATED_AT)
    original = path.read_bytes()

    def fail_write(destination: Path, content: bytes) -> None:
        raise OSError("fabricated interrupted write")

    monkeypatch.setattr(summary_module, "atomic_write_private", fail_write)

    with pytest.raises(SummaryStorageError):
        cache.write([_activity("1", _AS_OF)], as_of_date=_AS_OF, generated_at=_GENERATED_AT)

    assert path.read_bytes() == original
