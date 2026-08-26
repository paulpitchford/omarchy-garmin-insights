"""Allowlisted Garmin activity validation and normalized domain models."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

MAX_ACTIVITIES_PER_REFRESH = 20_000
_MAX_ACTIVITY_ID = 9_223_372_036_854_775_807
_MAX_NAME_LENGTH = 256
_MAX_TYPE_KEY_LENGTH = 100
_MAX_DURATION_SECONDS = 366 * 24 * 60 * 60
_MAX_DISTANCE_METRES = 50_000_000.0
_MAX_ELEVATION_METRES = 1_000_000.0
_MAX_SPEED_METRES_PER_SECOND = 200.0
_MAX_HEART_RATE_BPM = 300.0
_MAX_POWER_WATTS = 100_000.0
_MAX_ENERGY_KILOCALORIES = 1_000_000.0
_MAX_STRENGTH_COUNT = 1_000_000
_KILOCALORIE_TO_JOULES = 4_184.0


class InvalidActivityDataError(ValueError):
    """Raised when an untrusted Garmin activity response is invalid."""


@dataclass(frozen=True, slots=True)
class Activity:
    """One normalized activity containing only reviewed non-location fields."""

    activity_id: str
    name: str | None
    type_key: str
    started_at_local: str
    local_date: date
    duration_seconds: float | None
    moving_duration_seconds: float | None
    distance_metres: float | None
    elevation_gain_metres: float | None
    energy_joules: float | None
    average_heart_rate_bpm: float | None
    maximum_heart_rate_bpm: float | None
    average_speed_metres_per_second: float | None
    average_power_watts: float | None
    total_sets: int | None
    total_repetitions: int | None


def _required_mapping(value: object, field: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise InvalidActivityDataError(f"{field} must be an object")
    return value


def _activity_id(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidActivityDataError("activityId must be an integer")
    if value < 1 or value > _MAX_ACTIVITY_ID:
        raise InvalidActivityDataError("activityId is outside the accepted range")
    return str(value)


def _optional_string(value: object, field: str, *, max_length: int) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise InvalidActivityDataError(f"{field} is invalid")
    return value


def _required_string(value: object, field: str, *, max_length: int) -> str:
    result = _optional_string(value, field, max_length=max_length)
    if result is None:
        raise InvalidActivityDataError(f"{field} is required")
    return result


def _local_start(value: object) -> tuple[str, date]:
    text = _required_string(value, "startTimeLocal", max_length=40)
    if len(text) < 19 or text[10] not in {" ", "T"}:
        raise InvalidActivityDataError("startTimeLocal is invalid")
    try:
        started_at = datetime.fromisoformat(text)
    except ValueError as error:
        raise InvalidActivityDataError("startTimeLocal is invalid") from error
    return started_at.isoformat(sep=" ", timespec="seconds"), started_at.date()


def _optional_number(
    value: object,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidActivityDataError(f"{field} must be numeric or null")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise InvalidActivityDataError(f"{field} is outside the accepted range")
    return result


def _optional_count(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidActivityDataError(f"{field} must be an integer or null")
    if value < 0 or value > _MAX_STRENGTH_COUNT:
        raise InvalidActivityDataError(f"{field} is outside the accepted range")
    return value


def _normalize_activity(raw: object, start_date: date, end_date: date) -> Activity:
    activity = _required_mapping(raw, "activity")
    activity_type = _required_mapping(activity.get("activityType"), "activityType")
    started_at_local, local_date = _local_start(activity.get("startTimeLocal"))
    if local_date < start_date or local_date > end_date:
        raise InvalidActivityDataError("activity local date is outside the requested period")

    kilocalories = _optional_number(
        activity.get("calories"),
        "calories",
        minimum=0,
        maximum=_MAX_ENERGY_KILOCALORIES,
    )
    return Activity(
        activity_id=_activity_id(activity.get("activityId")),
        name=_optional_string(
            activity.get("activityName"), "activityName", max_length=_MAX_NAME_LENGTH
        ),
        type_key=_required_string(
            activity_type.get("typeKey"), "activityType.typeKey", max_length=_MAX_TYPE_KEY_LENGTH
        ),
        started_at_local=started_at_local,
        local_date=local_date,
        duration_seconds=_optional_number(
            activity.get("duration"),
            "duration",
            minimum=0,
            maximum=_MAX_DURATION_SECONDS,
        ),
        moving_duration_seconds=_optional_number(
            activity.get("movingDuration"),
            "movingDuration",
            minimum=0,
            maximum=_MAX_DURATION_SECONDS,
        ),
        distance_metres=_optional_number(
            activity.get("distance"),
            "distance",
            minimum=0,
            maximum=_MAX_DISTANCE_METRES,
        ),
        elevation_gain_metres=_optional_number(
            activity.get("elevationGain"),
            "elevationGain",
            minimum=0,
            maximum=_MAX_ELEVATION_METRES,
        ),
        energy_joules=None if kilocalories is None else kilocalories * _KILOCALORIE_TO_JOULES,
        average_heart_rate_bpm=_optional_number(
            activity.get("averageHR"),
            "averageHR",
            minimum=0,
            maximum=_MAX_HEART_RATE_BPM,
        ),
        maximum_heart_rate_bpm=_optional_number(
            activity.get("maxHR"),
            "maxHR",
            minimum=0,
            maximum=_MAX_HEART_RATE_BPM,
        ),
        average_speed_metres_per_second=_optional_number(
            activity.get("averageSpeed"),
            "averageSpeed",
            minimum=0,
            maximum=_MAX_SPEED_METRES_PER_SECOND,
        ),
        average_power_watts=_optional_number(
            activity.get("avgPower"),
            "avgPower",
            minimum=0,
            maximum=_MAX_POWER_WATTS,
        ),
        total_sets=_optional_count(activity.get("totalSets"), "totalSets"),
        total_repetitions=_optional_count(activity.get("totalReps"), "totalReps"),
    )


def validate_normalized_activity(activity: Activity) -> Activity:
    """Validate every field in an activity loaded from local storage.

    Args:
        activity: Activity reconstructed from the private SQLite database.

    Returns:
        The unchanged validated activity.

    Raises:
        InvalidActivityDataError: If any stored field is malformed or outside the
            reviewed Garmin activity bounds.
    """
    if not isinstance(activity.activity_id, str) or not activity.activity_id.isascii():
        raise InvalidActivityDataError("stored activityId is invalid")
    try:
        numeric_id = int(activity.activity_id)
    except ValueError as error:
        raise InvalidActivityDataError("stored activityId is invalid") from error
    if _activity_id(numeric_id) != activity.activity_id:
        raise InvalidActivityDataError("stored activityId is invalid")

    _optional_string(activity.name, "stored activityName", max_length=_MAX_NAME_LENGTH)
    _required_string(
        activity.type_key, "stored activityType.typeKey", max_length=_MAX_TYPE_KEY_LENGTH
    )
    normalized_start, normalized_date = _local_start(activity.started_at_local)
    if normalized_start != activity.started_at_local or normalized_date != activity.local_date:
        raise InvalidActivityDataError("stored local start is invalid")
    if not isinstance(activity.local_date, date) or isinstance(activity.local_date, datetime):
        raise InvalidActivityDataError("stored local date is invalid")

    _optional_number(
        activity.duration_seconds,
        "stored duration",
        minimum=0,
        maximum=_MAX_DURATION_SECONDS,
    )
    _optional_number(
        activity.moving_duration_seconds,
        "stored movingDuration",
        minimum=0,
        maximum=_MAX_DURATION_SECONDS,
    )
    _optional_number(
        activity.distance_metres,
        "stored distance",
        minimum=0,
        maximum=_MAX_DISTANCE_METRES,
    )
    _optional_number(
        activity.elevation_gain_metres,
        "stored elevationGain",
        minimum=0,
        maximum=_MAX_ELEVATION_METRES,
    )
    _optional_number(
        activity.energy_joules,
        "stored energy",
        minimum=0,
        maximum=_MAX_ENERGY_KILOCALORIES * _KILOCALORIE_TO_JOULES,
    )
    _optional_number(
        activity.average_heart_rate_bpm,
        "stored averageHR",
        minimum=0,
        maximum=_MAX_HEART_RATE_BPM,
    )
    _optional_number(
        activity.maximum_heart_rate_bpm,
        "stored maxHR",
        minimum=0,
        maximum=_MAX_HEART_RATE_BPM,
    )
    _optional_number(
        activity.average_speed_metres_per_second,
        "stored averageSpeed",
        minimum=0,
        maximum=_MAX_SPEED_METRES_PER_SECOND,
    )
    _optional_number(
        activity.average_power_watts,
        "stored avgPower",
        minimum=0,
        maximum=_MAX_POWER_WATTS,
    )
    _optional_count(activity.total_sets, "stored totalSets")
    _optional_count(activity.total_repetitions, "stored totalReps")
    return activity


def normalize_activities(payload: object, start_date: date, end_date: date) -> list[Activity]:
    """Validate a bounded Garmin response and discard all non-allowlisted fields.

    Args:
        payload: Untrusted return value from ``get_activities_by_date``.
        start_date: Inclusive beginning of the requested local-date period.
        end_date: Inclusive end of the requested local-date period.

    Returns:
        Validated activities in response order.

    Raises:
        InvalidActivityDataError: If the response is malformed, oversized, contains
            conflicting duplicates, or includes an activity outside the request period.
    """
    if start_date > end_date:
        raise ValueError("start_date must not follow end_date")
    if not isinstance(payload, list):
        raise InvalidActivityDataError("activities response must be a list")
    if len(payload) > MAX_ACTIVITIES_PER_REFRESH:
        raise InvalidActivityDataError("activities response exceeds the item limit")

    normalized: list[Activity] = []
    by_id: dict[str, Activity] = {}
    for raw_activity in payload:
        activity = _normalize_activity(raw_activity, start_date, end_date)
        existing = by_id.get(activity.activity_id)
        if existing is not None:
            if existing != activity:
                raise InvalidActivityDataError("duplicate activityId has conflicting values")
            continue
        by_id[activity.activity_id] = activity
        normalized.append(activity)
    return normalized
