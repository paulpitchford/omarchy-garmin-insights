import math
from datetime import date
from typing import Any

import pytest

from omarchy_garmin.activities import (
    MAX_ACTIVITIES_PER_REFRESH,
    InvalidActivityDataError,
    normalize_activities,
)


def _raw_activity(**overrides: object) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "activityId": 101,
        "activityName": "Synthetic Park Run",
        "activityType": {"typeKey": "running", "typeId": 1},
        "startTimeLocal": "2026-08-25 06:30:15.123",
        "duration": 1800.5,
        "movingDuration": 1750,
        "distance": 5000.0,
        "elevationGain": 45.5,
        "calories": 320,
        "averageHR": 145,
        "maxHR": 175,
        "averageSpeed": 2.85,
        "avgPower": 250,
        "totalSets": None,
        "totalReps": None,
        "latitude": "must-not-persist",
        "longitude": "must-not-persist",
        "map": {"private": "ignored"},
    }
    activity.update(overrides)
    return activity


def test_activity_response_is_normalized_to_reviewed_fields_and_si_units() -> None:
    raw = _raw_activity()

    activities = normalize_activities(
        [raw],
        date(2026, 8, 20),
        date(2026, 8, 26),
    )

    assert len(activities) == 1
    activity = activities[0]
    assert activity.activity_id == "101"
    assert activity.name == "Synthetic Park Run"
    assert activity.type_key == "running"
    assert activity.started_at_local == "2026-08-25 06:30:15"
    assert activity.local_date == date(2026, 8, 25)
    assert activity.energy_joules == 320 * 4184
    assert activity.distance_metres == 5000
    assert not hasattr(activity, "latitude")
    assert "private" not in repr(activity)


def test_missing_optional_values_remain_none_and_unfamiliar_type_is_preserved() -> None:
    raw = _raw_activity(
        activityName=None,
        activityType={"typeKey": "synthetic_new_sport"},
        duration=None,
        movingDuration=None,
        distance=None,
        elevationGain=None,
        calories=None,
        averageHR=None,
        maxHR=None,
        averageSpeed=None,
        avgPower=None,
        totalSets=None,
        totalReps=None,
    )

    activity = normalize_activities([raw], date(2026, 8, 25), date(2026, 8, 25))[0]

    assert activity.type_key == "synthetic_new_sport"
    assert activity.name is None
    assert activity.duration_seconds is None
    assert activity.distance_metres is None
    assert activity.energy_joules is None
    assert activity.total_sets is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="response-not-list"),
        pytest.param([[]], id="activity-not-object"),
        pytest.param([_raw_activity(activityId=True)], id="boolean-id"),
        pytest.param([_raw_activity(activityId=0)], id="nonpositive-id"),
        pytest.param([_raw_activity(activityName="")], id="empty-name"),
        pytest.param([_raw_activity(activityName="x" * 257)], id="oversized-name"),
        pytest.param([_raw_activity(activityType=None)], id="missing-type"),
        pytest.param([_raw_activity(activityType={})], id="missing-type-key"),
        pytest.param(
            [_raw_activity(activityType={"typeKey": "x" * 101})],
            id="oversized-type-key",
        ),
        pytest.param([_raw_activity(startTimeLocal="invalid")], id="invalid-local-start"),
        pytest.param([_raw_activity(startTimeLocal="2026-08-25")], id="date-without-time"),
        pytest.param([_raw_activity(duration=True)], id="boolean-number"),
        pytest.param([_raw_activity(distance=math.inf)], id="infinite-number"),
        pytest.param([_raw_activity(averageHR=301)], id="number-above-range"),
        pytest.param([_raw_activity(totalSets=1.5)], id="noninteger-count"),
        pytest.param([_raw_activity(totalReps=-1)], id="negative-count"),
    ],
)
def test_malformed_activity_response_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidActivityDataError):
        normalize_activities(payload, date(2026, 8, 20), date(2026, 8, 26))


def test_activity_outside_requested_local_dates_is_rejected() -> None:
    raw = _raw_activity(startTimeLocal="2026-08-19 23:59:59")

    with pytest.raises(InvalidActivityDataError, match="outside"):
        normalize_activities([raw], date(2026, 8, 20), date(2026, 8, 26))


def test_identical_duplicate_is_collapsed() -> None:
    raw = _raw_activity()

    activities = normalize_activities([raw, raw.copy()], date(2026, 8, 20), date(2026, 8, 26))

    assert len(activities) == 1


def test_conflicting_duplicate_is_rejected() -> None:
    first = _raw_activity()
    changed = _raw_activity(activityName="Changed synthetic name")

    with pytest.raises(InvalidActivityDataError, match="conflicting"):
        normalize_activities([first, changed], date(2026, 8, 20), date(2026, 8, 26))


def test_oversized_response_is_rejected_before_item_validation() -> None:
    payload = [None] * (MAX_ACTIVITIES_PER_REFRESH + 1)

    with pytest.raises(InvalidActivityDataError, match="item limit"):
        normalize_activities(payload, date(2026, 8, 20), date(2026, 8, 26))


def test_invalid_requested_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="start_date"):
        normalize_activities([], date(2026, 8, 27), date(2026, 8, 26))
