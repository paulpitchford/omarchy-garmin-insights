"""Bounded activity-trend aggregation and private JSON cache writing."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from omarchy_garmin.activities import Activity
from omarchy_garmin.storage import UnsafeStoragePathError, atomic_write_private

ACTIVITY_TRENDS_SCHEMA_VERSION = 1
MAX_TREND_ACTIVITIES = 20_000
MAX_TREND_POINTS = 50
MAX_ACTIVITY_TRENDS_BYTES = 65_536

_TREND_PERIODS = (
    ("7Days", 7),
    ("30Days", 30),
    ("90Days", 90),
)


class ActivityTrendsError(RuntimeError):
    """Base class for safe activity-trend failures."""


class ActivityTrendsDataError(ActivityTrendsError):
    """Raised when stored activities cannot produce a safe trend contract."""


class ActivityTrendsStorageError(ActivityTrendsError):
    """Raised when the private trend cache cannot be replaced safely."""


@dataclass(frozen=True, slots=True)
class TrendMetric:
    """One summed trend metric and its contributing activity count."""

    value: float | None
    contributing_activity_count: int

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON representation of the metric."""
        return {
            "value": self.value,
            "contributingActivityCount": self.contributing_activity_count,
        }


@dataclass(slots=True)
class _TrendTotal:
    value: float = 0.0
    contributors: int = 0

    def add(self, value: float | None, field_name: str) -> None:
        if value is None:
            return
        measured = _finite_nonnegative(value, field_name)
        self.value += measured
        if not math.isfinite(self.value):
            raise ActivityTrendsDataError(f"{field_name} trend aggregate is outside the limit")
        self.contributors += 1

    def merge(self, other: _TrendTotal, field_name: str) -> None:
        self.value += other.value
        if not math.isfinite(self.value):
            raise ActivityTrendsDataError(f"{field_name} trend aggregate is outside the limit")
        self.contributors += other.contributors

    def result(self, activity_count: int) -> TrendMetric:
        if activity_count == 0:
            return TrendMetric(value=0.0, contributing_activity_count=0)
        return TrendMetric(
            value=self.value if self.contributors else None,
            contributing_activity_count=self.contributors,
        )


@dataclass(slots=True)
class _TrendAccumulator:
    activity_count: int = 0
    duration_seconds: _TrendTotal = field(default_factory=_TrendTotal)
    distance_metres: _TrendTotal = field(default_factory=_TrendTotal)
    elevation_gain_metres: _TrendTotal = field(default_factory=_TrendTotal)
    energy_joules: _TrendTotal = field(default_factory=_TrendTotal)

    def add(self, activity: Activity) -> None:
        self.activity_count += 1
        self.duration_seconds.add(activity.duration_seconds, "duration_seconds")
        self.distance_metres.add(activity.distance_metres, "distance_metres")
        self.elevation_gain_metres.add(activity.elevation_gain_metres, "elevation_gain_metres")
        self.energy_joules.add(activity.energy_joules, "energy_joules")

    def merge(self, other: _TrendAccumulator) -> None:
        self.activity_count += other.activity_count
        self.duration_seconds.merge(other.duration_seconds, "duration_seconds")
        self.distance_metres.merge(other.distance_metres, "distance_metres")
        self.elevation_gain_metres.merge(other.elevation_gain_metres, "elevation_gain_metres")
        self.energy_joules.merge(other.energy_joules, "energy_joules")

    def to_payload(self, *, start_date: date, end_date: date, partial: bool) -> dict[str, object]:
        """Return one bounded point for a day or trailing calendar bucket."""
        return {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "partial": partial,
            "activityCount": self.activity_count,
            "durationSeconds": self.duration_seconds.result(self.activity_count).to_payload(),
            "distanceMetres": self.distance_metres.result(self.activity_count).to_payload(),
            "elevationGainMetres": self.elevation_gain_metres.result(
                self.activity_count
            ).to_payload(),
            "energyJoules": self.energy_joules.result(self.activity_count).to_payload(),
        }


def _finite_nonnegative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ActivityTrendsDataError(f"{field_name} is invalid")
    measured = float(value)
    if not math.isfinite(measured) or measured < 0:
        raise ActivityTrendsDataError(f"{field_name} is invalid")
    return measured


def _generated_at_text(generated_at: datetime) -> str:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ActivityTrendsDataError("trend generation time must include a timezone")
    utc_value = generated_at.astimezone(UTC).isoformat(timespec="seconds")
    return utc_value.replace("+00:00", "Z")


def _validate_activity_date(activity: Activity, start_date: date, end_date: date) -> None:
    if not isinstance(activity.local_date, date) or isinstance(activity.local_date, datetime):
        raise ActivityTrendsDataError("activity local date is invalid")
    if activity.local_date < start_date or activity.local_date > end_date:
        raise ActivityTrendsDataError("activity local date is outside the trend period")


def _bucket_ranges(period_key: str, start_date: date, end_date: date) -> list[tuple[date, date]]:
    if period_key != "90Days":
        days = (end_date - start_date).days + 1
        return [
            (start_date + timedelta(days=offset), start_date + timedelta(days=offset))
            for offset in range(days)
        ]

    ranges = [(start_date, start_date + timedelta(days=5))]
    next_start = ranges[0][1] + timedelta(days=1)
    while next_start <= end_date:
        bucket_end = min(next_start + timedelta(days=6), end_date)
        ranges.append((next_start, bucket_end))
        next_start = bucket_end + timedelta(days=1)
    return ranges


def _period_payload(
    *,
    key: str,
    start_date: date,
    end_date: date,
    daily: dict[date, _TrendAccumulator],
) -> dict[str, object]:
    points: list[dict[str, object]] = []
    for bucket_start, bucket_end in _bucket_ranges(key, start_date, end_date):
        bucket = _TrendAccumulator()
        current_date = bucket_start
        while current_date <= bucket_end:
            bucket.merge(daily[current_date])
            current_date += timedelta(days=1)
        points.append(
            bucket.to_payload(
                start_date=bucket_start,
                end_date=bucket_end,
                partial=bucket_end == end_date,
            )
        )
    return {
        "key": key,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "points": points,
    }


def render_activity_trends(
    activities: Sequence[Activity],
    *,
    as_of_date: date,
    generated_at: datetime,
) -> bytes:
    """Aggregate a rolling activity snapshot into the versioned trend contract.

    The 7- and 30-day periods use daily points. The 90-day period uses one
    six-day oldest bucket followed by twelve seven-day buckets. Empty calendar
    dates are explicit zero points; a metric remains null when activities exist
    but none supplied that measurement.

    Args:
        activities: Complete normalized activity snapshot for the rolling 90 days.
        as_of_date: Inclusive local calendar date ending every trend period.
        generated_at: Time at which the database snapshot was aggregated.

    Returns:
        Compact UTF-8 JSON ending in one newline.

    Raises:
        ActivityTrendsDataError: If input or serialized output is invalid or excessive.
    """
    if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        raise ActivityTrendsDataError("trend local date is invalid")
    if len(activities) > MAX_TREND_ACTIVITIES:
        raise ActivityTrendsDataError("activity count exceeds the trend limit")

    rolling_start = as_of_date - timedelta(days=89)
    daily = {rolling_start + timedelta(days=offset): _TrendAccumulator() for offset in range(90)}
    for activity in activities:
        _validate_activity_date(activity, rolling_start, as_of_date)
        daily[activity.local_date].add(activity)

    periods = [
        _period_payload(
            key=key,
            start_date=as_of_date - timedelta(days=days - 1),
            end_date=as_of_date,
            daily=daily,
        )
        for key, days in _TREND_PERIODS
    ]
    point_count = 0
    for period in periods:
        points = period["points"]
        if not isinstance(points, list):  # pragma: no cover - built internally
            raise ActivityTrendsDataError("trend points are invalid")
        point_count += len(points)
    if point_count > MAX_TREND_POINTS:
        raise ActivityTrendsDataError("trend point count exceeds the limit")
    payload = {
        "schemaVersion": ACTIVITY_TRENDS_SCHEMA_VERSION,
        "generatedAt": _generated_at_text(generated_at),
        "asOfLocalDate": as_of_date.isoformat(),
        "periods": periods,
    }
    try:
        content = (
            json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    except (TypeError, ValueError) as error:
        raise ActivityTrendsDataError("activity trends cannot be serialized safely") from error
    if len(content) > MAX_ACTIVITY_TRENDS_BYTES:
        raise ActivityTrendsDataError("activity trends exceed the byte limit")
    return content


class ActivityTrendsCache:
    """Render and atomically replace the private activity-trends cache."""

    def __init__(self, path: Path) -> None:
        """Initialize the cache with an absolute private destination path."""
        self._path = path

    def write(
        self,
        activities: Sequence[Activity],
        *,
        as_of_date: date,
        generated_at: datetime,
    ) -> None:
        """Write complete trends while preserving any previous valid file."""
        content = render_activity_trends(
            activities,
            as_of_date=as_of_date,
            generated_at=generated_at,
        )
        try:
            atomic_write_private(self._path, content)
        except (OSError, UnsafeStoragePathError) as error:
            raise ActivityTrendsStorageError(
                "activity-trends cache could not be written safely"
            ) from error
