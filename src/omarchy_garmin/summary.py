"""Bounded display-summary aggregation and private JSON cache writing."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from omarchy_garmin.activities import Activity
from omarchy_garmin.storage import UnsafeStoragePathError, atomic_write_private

SUMMARY_SCHEMA_VERSION = 1
MAX_SUMMARY_ACTIVITIES = 20_000
MAX_SUMMARY_TYPES = 256
MAX_SUMMARY_BYTES = 1_048_576

_PERIODS = (
    ("today", 1),
    ("7Days", 7),
    ("30Days", 30),
    ("90Days", 90),
)


class SummaryError(RuntimeError):
    """Base class for safe summary-generation failures."""


class SummaryDataError(SummaryError):
    """Raised when stored activities cannot produce a safe bounded summary."""


class SummaryStorageError(SummaryError):
    """Raised when the private summary cache cannot be replaced safely."""


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One aggregate metric and the number of activities that contributed to it."""

    value: float | int | None
    contributing_activity_count: int

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON representation of this metric."""
        return {
            "value": self.value,
            "contributingActivityCount": self.contributing_activity_count,
        }


@dataclass(frozen=True, slots=True)
class Aggregate:
    """Reviewed metrics for an overall period or one original activity type."""

    activity_count: int
    duration_seconds: MetricValue
    moving_duration_seconds: MetricValue
    distance_metres: MetricValue
    elevation_gain_metres: MetricValue
    energy_joules: MetricValue
    average_heart_rate_bpm: MetricValue
    maximum_heart_rate_bpm: MetricValue
    average_speed_metres_per_second: MetricValue
    average_power_watts: MetricValue
    total_sets: MetricValue
    total_repetitions: MetricValue

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON representation of this aggregate."""
        return {
            "activityCount": self.activity_count,
            "durationSeconds": self.duration_seconds.to_payload(),
            "movingDurationSeconds": self.moving_duration_seconds.to_payload(),
            "distanceMetres": self.distance_metres.to_payload(),
            "elevationGainMetres": self.elevation_gain_metres.to_payload(),
            "energyJoules": self.energy_joules.to_payload(),
            "averageHeartRateBpm": self.average_heart_rate_bpm.to_payload(),
            "maximumHeartRateBpm": self.maximum_heart_rate_bpm.to_payload(),
            "averageSpeedMetresPerSecond": self.average_speed_metres_per_second.to_payload(),
            "averagePowerWatts": self.average_power_watts.to_payload(),
            "totalSets": self.total_sets.to_payload(),
            "totalRepetitions": self.total_repetitions.to_payload(),
        }


@dataclass(slots=True)
class _Total:
    value: float = 0.0
    contributors: int = 0

    def add(self, value: float | None, field_name: str) -> None:
        if value is None:
            return
        measured = _finite_nonnegative(value, field_name)
        self.value += measured
        if not math.isfinite(self.value):
            raise SummaryDataError(f"{field_name} aggregate is outside the accepted range")
        self.contributors += 1

    def result(self) -> MetricValue:
        return MetricValue(
            value=self.value if self.contributors else None,
            contributing_activity_count=self.contributors,
        )


@dataclass(slots=True)
class _CountTotal:
    value: int = 0
    contributors: int = 0

    def add(self, value: int | None, field_name: str) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SummaryDataError(f"{field_name} is invalid")
        self.value += value
        self.contributors += 1

    def result(self) -> MetricValue:
        return MetricValue(
            value=self.value if self.contributors else None,
            contributing_activity_count=self.contributors,
        )


@dataclass(slots=True)
class _Maximum:
    value: float | None = None
    contributors: int = 0

    def add(self, value: float | None, field_name: str) -> None:
        if value is None:
            return
        measured = _finite_nonnegative(value, field_name)
        self.value = measured if self.value is None else max(self.value, measured)
        self.contributors += 1

    def result(self) -> MetricValue:
        return MetricValue(self.value, self.contributors)


@dataclass(slots=True)
class _WeightedAverage:
    weighted_total: float = 0.0
    total_weight: float = 0.0
    contributors: int = 0

    def add(
        self,
        value: float | None,
        weight: float | None,
        *,
        field_name: str,
        weight_name: str,
    ) -> None:
        if value is None:
            return
        measured = _finite_nonnegative(value, field_name)
        if weight is None:
            return
        measured_weight = _finite_nonnegative(weight, weight_name)
        if measured_weight == 0:
            return
        self.weighted_total += measured * measured_weight
        self.total_weight += measured_weight
        if not math.isfinite(self.weighted_total) or not math.isfinite(self.total_weight):
            raise SummaryDataError(f"{field_name} aggregate is outside the accepted range")
        self.contributors += 1

    def result(self) -> MetricValue:
        return MetricValue(
            value=self.weighted_total / self.total_weight if self.contributors else None,
            contributing_activity_count=self.contributors,
        )


@dataclass(slots=True)
class _AggregateAccumulator:
    activity_count: int = 0
    duration_seconds: _Total = field(default_factory=_Total)
    moving_duration_seconds: _Total = field(default_factory=_Total)
    distance_metres: _Total = field(default_factory=_Total)
    elevation_gain_metres: _Total = field(default_factory=_Total)
    energy_joules: _Total = field(default_factory=_Total)
    average_heart_rate_bpm: _WeightedAverage = field(default_factory=_WeightedAverage)
    maximum_heart_rate_bpm: _Maximum = field(default_factory=_Maximum)
    average_speed_metres_per_second: _WeightedAverage = field(default_factory=_WeightedAverage)
    average_power_watts: _WeightedAverage = field(default_factory=_WeightedAverage)
    total_sets: _CountTotal = field(default_factory=_CountTotal)
    total_repetitions: _CountTotal = field(default_factory=_CountTotal)

    def add(self, activity: Activity) -> None:
        self.activity_count += 1
        self.duration_seconds.add(activity.duration_seconds, "duration_seconds")
        self.moving_duration_seconds.add(
            activity.moving_duration_seconds, "moving_duration_seconds"
        )
        self.distance_metres.add(activity.distance_metres, "distance_metres")
        self.elevation_gain_metres.add(activity.elevation_gain_metres, "elevation_gain_metres")
        self.energy_joules.add(activity.energy_joules, "energy_joules")
        self.average_heart_rate_bpm.add(
            activity.average_heart_rate_bpm,
            activity.duration_seconds,
            field_name="average_heart_rate_bpm",
            weight_name="duration_seconds",
        )
        self.maximum_heart_rate_bpm.add(activity.maximum_heart_rate_bpm, "maximum_heart_rate_bpm")
        self.average_speed_metres_per_second.add(
            activity.average_speed_metres_per_second,
            activity.moving_duration_seconds,
            field_name="average_speed_metres_per_second",
            weight_name="moving_duration_seconds",
        )
        self.average_power_watts.add(
            activity.average_power_watts,
            activity.duration_seconds,
            field_name="average_power_watts",
            weight_name="duration_seconds",
        )
        self.total_sets.add(activity.total_sets, "total_sets")
        self.total_repetitions.add(activity.total_repetitions, "total_repetitions")

    def result(self) -> Aggregate:
        return Aggregate(
            activity_count=self.activity_count,
            duration_seconds=self.duration_seconds.result(),
            moving_duration_seconds=self.moving_duration_seconds.result(),
            distance_metres=self.distance_metres.result(),
            elevation_gain_metres=self.elevation_gain_metres.result(),
            energy_joules=self.energy_joules.result(),
            average_heart_rate_bpm=self.average_heart_rate_bpm.result(),
            maximum_heart_rate_bpm=self.maximum_heart_rate_bpm.result(),
            average_speed_metres_per_second=self.average_speed_metres_per_second.result(),
            average_power_watts=self.average_power_watts.result(),
            total_sets=self.total_sets.result(),
            total_repetitions=self.total_repetitions.result(),
        )


@dataclass(slots=True)
class _PeriodAccumulator:
    overall: _AggregateAccumulator = field(default_factory=_AggregateAccumulator)
    by_type: dict[str, _AggregateAccumulator] = field(default_factory=dict)

    def add(self, activity: Activity) -> None:
        self.overall.add(activity)
        aggregate = self.by_type.get(activity.type_key)
        if aggregate is None:
            if len(self.by_type) >= MAX_SUMMARY_TYPES:
                raise SummaryDataError("activity type count exceeds the summary limit")
            aggregate = _AggregateAccumulator()
            self.by_type[activity.type_key] = aggregate
        aggregate.add(activity)

    def type_payloads(self) -> list[dict[str, object]]:
        ordered = sorted(
            self.by_type.items(),
            key=lambda item: (-item[1].activity_count, item[0]),
        )
        return [
            {"typeKey": type_key, **accumulator.result().to_payload()}
            for type_key, accumulator in ordered
        ]


def _finite_nonnegative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SummaryDataError(f"{field_name} is invalid")
    measured = float(value)
    if not math.isfinite(measured) or measured < 0:
        raise SummaryDataError(f"{field_name} is invalid")
    return measured


def _validate_activity_identity(activity: Activity, start_date: date, end_date: date) -> None:
    if (
        not isinstance(activity.type_key, str)
        or not activity.type_key
        or len(activity.type_key) > 100
    ):
        raise SummaryDataError("activity type key is invalid")
    if not isinstance(activity.local_date, date) or isinstance(activity.local_date, datetime):
        raise SummaryDataError("activity local date is invalid")
    if activity.local_date < start_date or activity.local_date > end_date:
        raise SummaryDataError("activity local date is outside the summary period")


def _generated_at_text(generated_at: datetime) -> str:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise SummaryDataError("summary generation time must include a timezone")
    utc_value = generated_at.astimezone(UTC).isoformat(timespec="seconds")
    return utc_value.replace("+00:00", "Z")


def render_summary(
    activities: Sequence[Activity],
    *,
    as_of_date: date,
    generated_at: datetime,
) -> bytes:
    """Aggregate one bounded activity snapshot into the versioned QML contract.

    Activities are visited once. Each activity contributes to every calendar period
    containing its local start date. Missing measurements do not contribute a zero;
    each metric carries its contributing activity count and remains null when none
    supplied a usable value.

    Args:
        activities: Complete normalized activity snapshot for the rolling 90 days.
        as_of_date: Inclusive local calendar date ending every period.
        generated_at: Time at which the database snapshot was summarized.

    Returns:
        Compact UTF-8 JSON ending in one newline.

    Raises:
        SummaryDataError: If input or serialized output exceeds a bound or is invalid.
    """
    if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        raise SummaryDataError("summary local date is invalid")
    if len(activities) > MAX_SUMMARY_ACTIVITIES:
        raise SummaryDataError("activity count exceeds the summary limit")

    period_states = [
        (key, as_of_date - timedelta(days=days - 1), _PeriodAccumulator()) for key, days in _PERIODS
    ]
    rolling_start = period_states[-1][1]
    for activity in activities:
        _validate_activity_identity(activity, rolling_start, as_of_date)
        for _, start_date, accumulator in period_states:
            if activity.local_date >= start_date:
                accumulator.add(activity)

    periods: list[dict[str, object]] = []
    for (key, _), (_, start_date, accumulator) in zip(_PERIODS, period_states, strict=True):
        periods.append(
            {
                "key": key,
                "startDate": start_date.isoformat(),
                "endDate": as_of_date.isoformat(),
                "overall": accumulator.overall.result().to_payload(),
                "byType": accumulator.type_payloads(),
            }
        )
    payload = {
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "generatedAt": _generated_at_text(generated_at),
        "asOfLocalDate": as_of_date.isoformat(),
        "periods": periods,
    }
    try:
        content = (
            json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    except (TypeError, ValueError) as error:
        raise SummaryDataError("summary cannot be serialized safely") from error
    if len(content) > MAX_SUMMARY_BYTES:
        raise SummaryDataError("summary exceeds the byte limit")
    return content


class SummaryCache:
    """Render and atomically replace the private display-summary cache."""

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
        """Write one complete summary while preserving any previous valid file."""
        content = render_summary(
            activities,
            as_of_date=as_of_date,
            generated_at=generated_at,
        )
        try:
            atomic_write_private(self._path, content)
        except (OSError, UnsafeStoragePathError) as error:
            raise SummaryStorageError("summary cache could not be written safely") from error
