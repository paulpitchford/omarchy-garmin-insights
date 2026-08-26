"""Bounded local activity-list and detail contracts for panel drill-down."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Final, Protocol

from omarchy_garmin.activities import (
    Activity,
    InvalidActivityDataError,
    validate_normalized_activity,
)
from omarchy_garmin.database import ActivityDatabaseError

MAX_ACTIVITY_PAGE_SIZE = 20
MAX_ACTIVITY_PAGE_OFFSET = 19_980
MAX_ACTIVITY_VIEW_BYTES = 65_536
_MAX_ACTIVITY_ID = 9_223_372_036_854_775_807
_PERIOD_DAYS: Final = MappingProxyType(
    {
        "today": 1,
        "7Days": 7,
        "30Days": 30,
        "90Days": 90,
    }
)


class ActivityViewError(RuntimeError):
    """Base class for safe local activity-view failures."""


class ActivityViewRequestError(ActivityViewError):
    """Raised when an activity-view request is outside the public contract."""


class ActivityViewDataError(ActivityViewError):
    """Raised when locally stored activity data is invalid."""


class ActivityViewStorageError(ActivityViewError):
    """Raised when the private activity database cannot be read safely."""


class ActivityViewRepository(Protocol):
    """Read-only repository operations required by activity drill-down."""

    def activity_page(
        self,
        start_date: date,
        end_date: date,
        *,
        type_key: str | None,
        offset: int,
        limit: int,
    ) -> list[Activity]:
        """Return a bounded newest-first activity page."""
        ...

    def activity_by_id(self, activity_id: str) -> Activity | None:
        """Return one activity or None when reconciliation removed it."""
        ...


@dataclass(frozen=True, slots=True)
class ActivityPage:
    """One fixed-size local activity page and its continuation metadata."""

    period_key: str
    start_date: date
    end_date: date
    type_key: str | None
    offset: int
    activities: tuple[Activity, ...]
    has_more: bool
    next_offset: int | None
    stale: bool


@dataclass(frozen=True, slots=True)
class ActivityDetail:
    """Stable local detail result, including a reconciled-away activity."""

    activity: Activity | None


class ActivityViewOperations(Protocol):
    """Local activity views consumed by the CLI composition root."""

    def list_activities(
        self,
        *,
        period_key: str,
        as_of_date: date,
        type_key: str | None,
        offset: int,
    ) -> ActivityPage:
        """Return one bounded activity page."""
        ...

    def activity_detail(self, activity_id: str) -> ActivityDetail:
        """Return one local activity detail result."""
        ...


def validate_activity_id(activity_id: str) -> str:
    """Return a canonical bounded decimal Garmin activity identifier."""
    if (
        not isinstance(activity_id, str)
        or not activity_id
        or len(activity_id) > 19
        or not activity_id.isascii()
        or not activity_id.isdecimal()
        or activity_id.startswith("0")
    ):
        raise ActivityViewRequestError("activity identifier is invalid")
    if int(activity_id) > _MAX_ACTIVITY_ID:
        raise ActivityViewRequestError("activity identifier is invalid")
    return activity_id


def validate_type_key(type_key: str | None) -> str | None:
    """Validate an optional original Garmin activity type used as a filter."""
    if type_key is None:
        return None
    if (
        not isinstance(type_key, str)
        or not type_key
        or len(type_key) > 100
        or any(ord(character) < 32 or ord(character) == 127 for character in type_key)
    ):
        raise ActivityViewRequestError("activity type filter is invalid")
    return type_key


def _period_start(period_key: str, as_of_date: date) -> date:
    days = _PERIOD_DAYS.get(period_key)
    if days is None:
        raise ActivityViewRequestError("activity period is invalid")
    if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        raise ActivityViewRequestError("activity period date is invalid")
    try:
        return as_of_date - timedelta(days=days - 1)
    except OverflowError as error:
        raise ActivityViewRequestError("activity period date is invalid") from error


def _validate_offset(offset: int) -> None:
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or offset > MAX_ACTIVITY_PAGE_OFFSET
        or offset % MAX_ACTIVITY_PAGE_SIZE != 0
    ):
        raise ActivityViewRequestError("activity page offset is invalid")


def _validated_activity(activity: Activity) -> Activity:
    try:
        return validate_normalized_activity(activity)
    except InvalidActivityDataError as error:
        raise ActivityViewDataError("stored activity data is invalid") from error


def _validated_page_activities(
    rows: list[Activity],
    *,
    start_date: date,
    end_date: date,
    type_key: str | None,
) -> tuple[Activity, ...]:
    activities = tuple(_validated_activity(activity) for activity in rows)
    seen: set[str] = set()
    previous_key: tuple[str, int, str] | None = None
    for activity in activities:
        if (
            activity.local_date < start_date
            or activity.local_date > end_date
            or (type_key is not None and activity.type_key != type_key)
            or activity.activity_id in seen
        ):
            raise ActivityViewDataError("stored activity page is inconsistent")
        ordering_key = (
            activity.started_at_local,
            len(activity.activity_id),
            activity.activity_id,
        )
        if previous_key is not None and ordering_key > previous_key:
            raise ActivityViewDataError("stored activity page is not newest first")
        seen.add(activity.activity_id)
        previous_key = ordering_key
    return activities


class ActivityViewService:
    """Read bounded activity views from the normalized local database only."""

    def __init__(
        self,
        repository: ActivityViewRepository,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        """Initialize the repository and local-calendar clock boundaries."""
        self._repository = repository
        self._today = today

    def list_activities(
        self,
        *,
        period_key: str,
        as_of_date: date,
        type_key: str | None,
        offset: int,
    ) -> ActivityPage:
        """Return at most 20 matching activities ordered newest first."""
        start_date = _period_start(period_key, as_of_date)
        today = self._today()
        if as_of_date > today:
            raise ActivityViewRequestError("activity period date is in the future")
        validated_type = validate_type_key(type_key)
        _validate_offset(offset)
        try:
            rows = self._repository.activity_page(
                start_date,
                as_of_date,
                type_key=validated_type,
                offset=offset,
                limit=MAX_ACTIVITY_PAGE_SIZE + 1,
            )
        except ActivityDatabaseError as error:
            raise ActivityViewStorageError("local activities are unavailable") from error
        activities = _validated_page_activities(
            rows,
            start_date=start_date,
            end_date=as_of_date,
            type_key=validated_type,
        )
        has_more = len(activities) > MAX_ACTIVITY_PAGE_SIZE
        if has_more and offset == MAX_ACTIVITY_PAGE_OFFSET:
            raise ActivityViewDataError("activity continuation exceeds the retained-data bound")
        visible = activities[:MAX_ACTIVITY_PAGE_SIZE]
        return ActivityPage(
            period_key=period_key,
            start_date=start_date,
            end_date=as_of_date,
            type_key=validated_type,
            offset=offset,
            activities=visible,
            has_more=has_more,
            next_offset=offset + MAX_ACTIVITY_PAGE_SIZE if has_more else None,
            stale=as_of_date < today,
        )

    def activity_detail(self, activity_id: str) -> ActivityDetail:
        """Return one validated local detail without authenticating or refreshing."""
        validated_id = validate_activity_id(activity_id)
        try:
            activity = self._repository.activity_by_id(validated_id)
        except ActivityDatabaseError as error:
            raise ActivityViewStorageError("local activity detail is unavailable") from error
        if activity is None:
            return ActivityDetail(None)
        validated_activity = _validated_activity(activity)
        if validated_activity.activity_id != validated_id:
            raise ActivityViewDataError("stored activity detail has an unexpected identifier")
        return ActivityDetail(validated_activity)


def _list_item_payload(activity: Activity) -> dict[str, object]:
    return {
        "activityId": activity.activity_id,
        "name": activity.name,
        "typeKey": activity.type_key,
        "startedAtLocal": activity.started_at_local,
        "localDate": activity.local_date.isoformat(),
        "durationSeconds": activity.duration_seconds,
        "distanceMetres": activity.distance_metres,
        "energyJoules": activity.energy_joules,
        "totalSets": activity.total_sets,
        "totalRepetitions": activity.total_repetitions,
    }


def activity_page_payload(page: ActivityPage) -> dict[str, object]:
    """Serialize a page without adding fields outside the reviewed contract."""
    return {
        "periodKey": page.period_key,
        "startDate": page.start_date.isoformat(),
        "endDate": page.end_date.isoformat(),
        "typeKey": page.type_key,
        "offset": page.offset,
        "pageSize": MAX_ACTIVITY_PAGE_SIZE,
        "activities": [_list_item_payload(activity) for activity in page.activities],
        "hasMore": page.has_more,
        "nextOffset": page.next_offset,
        "stale": page.stale,
    }


def activity_detail_payload(detail: ActivityDetail) -> dict[str, object]:
    """Serialize all allowlisted local fields for one activity detail."""
    activity = detail.activity
    if activity is None:
        return {"found": False, "activity": None}
    return {
        "found": True,
        "activity": {
            "activityId": activity.activity_id,
            "name": activity.name,
            "typeKey": activity.type_key,
            "startedAtLocal": activity.started_at_local,
            "localDate": activity.local_date.isoformat(),
            "durationSeconds": activity.duration_seconds,
            "movingDurationSeconds": activity.moving_duration_seconds,
            "distanceMetres": activity.distance_metres,
            "elevationGainMetres": activity.elevation_gain_metres,
            "energyJoules": activity.energy_joules,
            "averageHeartRateBpm": activity.average_heart_rate_bpm,
            "maximumHeartRateBpm": activity.maximum_heart_rate_bpm,
            "averageSpeedMetresPerSecond": activity.average_speed_metres_per_second,
            "averagePowerWatts": activity.average_power_watts,
            "totalSets": activity.total_sets,
            "totalRepetitions": activity.total_repetitions,
        },
    }
