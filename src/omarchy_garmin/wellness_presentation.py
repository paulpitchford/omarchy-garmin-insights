"""Bounded wellness presentation model and private JSON cache writing."""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from omarchy_garmin.storage import UnsafeStoragePathError, atomic_write_private
from omarchy_garmin.wellness import (
    DailyWellness,
    WellnessFailureClassification,
    WellnessSource,
)
from omarchy_garmin.wellness_database import (
    WELLNESS_RETENTION_DAYS,
    WellnessSourceFreshness,
)

WELLNESS_PRESENTATION_SCHEMA_VERSION = 1
MAX_WELLNESS_PRESENTATION_BYTES = 65_536
WELLNESS_PERIODS = (("7Days", 7), ("30Days", 30))
PARTIAL_CURRENT_DAY_SOURCES = ("steps", "bodyBattery")


class WellnessPresentationError(RuntimeError):
    """Base class for safe wellness presentation failures."""


class WellnessPresentationDataError(WellnessPresentationError):
    """Raised when normalized wellness values cannot produce a safe contract."""


class WellnessPresentationStorageError(WellnessPresentationError):
    """Raised when the private wellness cache cannot be replaced safely."""


@dataclass(frozen=True, slots=True)
class WellnessSourcePresentation:
    """Freshness and redacted failure state for one reviewed Garmin source."""

    source: WellnessSource
    refreshed_at: datetime | None
    latest_value_date: date | None
    failure: WellnessFailureClassification | None

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON representation of one source state."""
        return {
            "source": self.source.value,
            "refreshedAt": _optional_timestamp_text(self.refreshed_at),
            "latestValueDate": (
                self.latest_value_date.isoformat() if self.latest_value_date is not None else None
            ),
            "failure": self.failure.value if self.failure is not None else None,
        }


@dataclass(frozen=True, slots=True)
class WellnessDayPresentation:
    """One local date containing only reviewed display wellness scalars."""

    values: DailyWellness

    def to_payload(self) -> dict[str, object]:
        """Return the stable nested JSON representation of one day."""
        day = self.values
        return {
            "date": day.calendar_date.isoformat(),
            "steps": _group(
                {"value": day.steps, "goal": day.step_goal},
            ),
            "bodyBattery": _group(
                {
                    "charged": day.body_battery_charged,
                    "drained": day.body_battery_drained,
                    "lowest": day.body_battery_lowest,
                    "highest": day.body_battery_highest,
                    "latest": day.body_battery_latest,
                }
            ),
            "sleep": _group(
                {
                    "score": day.sleep_score,
                    "totalSeconds": day.sleep_total_seconds,
                    "deepSeconds": day.sleep_deep_seconds,
                    "lightSeconds": day.sleep_light_seconds,
                    "remSeconds": day.sleep_rem_seconds,
                    "awakeSeconds": day.sleep_awake_seconds,
                }
            ),
            "trainingReadiness": _group(
                {
                    "score": day.training_readiness_score,
                    "level": day.training_readiness_level,
                }
            ),
            "hrv": _group(
                {
                    "weeklyAverageMs": day.hrv_weekly_average_ms,
                    "lastNightAverageMs": day.hrv_last_night_average_ms,
                    "status": day.hrv_status,
                    "balancedLowMs": day.hrv_balanced_low_ms,
                    "balancedUpperMs": day.hrv_balanced_upper_ms,
                }
            ),
            "restingHeartRate": _group(
                {"beatsPerMinute": day.resting_heart_rate_bpm},
            ),
        }


@dataclass(frozen=True, slots=True)
class WellnessContributorCounts:
    """Contributor-day counts for every scalar in one trend period."""

    steps: int = 0
    step_goal: int = 0
    body_battery_charged: int = 0
    body_battery_drained: int = 0
    body_battery_lowest: int = 0
    body_battery_highest: int = 0
    body_battery_latest: int = 0
    sleep_score: int = 0
    sleep_total_seconds: int = 0
    sleep_deep_seconds: int = 0
    sleep_light_seconds: int = 0
    sleep_rem_seconds: int = 0
    sleep_awake_seconds: int = 0
    training_readiness_score: int = 0
    training_readiness_level: int = 0
    hrv_weekly_average_ms: int = 0
    hrv_last_night_average_ms: int = 0
    hrv_status: int = 0
    hrv_balanced_low_ms: int = 0
    hrv_balanced_upper_ms: int = 0
    resting_heart_rate_bpm: int = 0

    def to_payload(self) -> dict[str, object]:
        """Return contributor counts in the same semantic groups as daily values."""
        return {
            "steps": {"value": self.steps, "goal": self.step_goal},
            "bodyBattery": {
                "charged": self.body_battery_charged,
                "drained": self.body_battery_drained,
                "lowest": self.body_battery_lowest,
                "highest": self.body_battery_highest,
                "latest": self.body_battery_latest,
            },
            "sleep": {
                "score": self.sleep_score,
                "totalSeconds": self.sleep_total_seconds,
                "deepSeconds": self.sleep_deep_seconds,
                "lightSeconds": self.sleep_light_seconds,
                "remSeconds": self.sleep_rem_seconds,
                "awakeSeconds": self.sleep_awake_seconds,
            },
            "trainingReadiness": {
                "score": self.training_readiness_score,
                "level": self.training_readiness_level,
            },
            "hrv": {
                "weeklyAverageMs": self.hrv_weekly_average_ms,
                "lastNightAverageMs": self.hrv_last_night_average_ms,
                "status": self.hrv_status,
                "balancedLowMs": self.hrv_balanced_low_ms,
                "balancedUpperMs": self.hrv_balanced_upper_ms,
            },
            "restingHeartRate": {"beatsPerMinute": self.resting_heart_rate_bpm},
        }


@dataclass(frozen=True, slots=True)
class WellnessPeriodPresentation:
    """One fixed calendar period and its contributor-day counts."""

    key: str
    start_date: date
    end_date: date
    contributing_days: WellnessContributorCounts

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON representation of one wellness period."""
        return {
            "key": self.key,
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "contributingDays": self.contributing_days.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class WellnessPresentation:
    """Complete versioned wellness display contract consumed by QML."""

    generated_at: datetime
    as_of_local_date: date
    collection_enabled: bool
    sources: tuple[WellnessSourcePresentation, ...]
    periods: tuple[WellnessPeriodPresentation, ...]
    days: tuple[WellnessDayPresentation, ...]

    def to_payload(self) -> dict[str, object]:
        """Return the stable bounded JSON payload."""
        return {
            "schemaVersion": WELLNESS_PRESENTATION_SCHEMA_VERSION,
            "generatedAt": _timestamp_text(self.generated_at),
            "asOfLocalDate": self.as_of_local_date.isoformat(),
            "collectionEnabled": self.collection_enabled,
            "partialCurrentDaySources": list(PARTIAL_CURRENT_DAY_SOURCES),
            "sources": [source.to_payload() for source in self.sources],
            "periods": [period.to_payload() for period in self.periods],
            "days": [day.to_payload() for day in self.days],
        }


def _group(values: dict[str, object | None]) -> dict[str, object | None] | None:
    return values if any(value is not None for value in values.values()) else None


def _timestamp_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise WellnessPresentationDataError("wellness generation time must include a timezone")
    utc_value = value.astimezone(UTC).isoformat(timespec="seconds")
    return utc_value.replace("+00:00", "Z")


def _optional_timestamp_text(value: datetime | None) -> str | None:
    return _timestamp_text(value) if value is not None else None


def _optional_integer(value: object, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise WellnessPresentationDataError("wellness integer is invalid")
    return value


def _optional_real(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise WellnessPresentationDataError("wellness number is invalid")
    try:
        result = float(value)
    except OverflowError as error:
        raise WellnessPresentationDataError("wellness number is invalid") from error
    if not math.isfinite(result) or not 0 <= result <= 1_000:
        raise WellnessPresentationDataError("wellness number is invalid")
    return result


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 64
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise WellnessPresentationDataError("wellness text is invalid")
    return value


def _validated_day(day: DailyWellness) -> DailyWellness:
    if not isinstance(day, DailyWellness) or type(day.calendar_date) is not date:
        raise WellnessPresentationDataError("wellness day is invalid")
    lowest = _optional_integer(day.body_battery_lowest, 0, 100)
    highest = _optional_integer(day.body_battery_highest, 0, 100)
    if lowest is not None and highest is not None and lowest > highest:
        raise WellnessPresentationDataError("Body Battery range is invalid")
    baseline_low = _optional_real(day.hrv_balanced_low_ms)
    baseline_upper = _optional_real(day.hrv_balanced_upper_ms)
    if baseline_low is not None and baseline_upper is not None and baseline_low > baseline_upper:
        raise WellnessPresentationDataError("HRV baseline is invalid")
    sleep_parts = tuple(
        _optional_integer(value, 0, 86_400)
        for value in (
            day.sleep_deep_seconds,
            day.sleep_light_seconds,
            day.sleep_rem_seconds,
            day.sleep_awake_seconds,
        )
    )
    if sum(value or 0 for value in sleep_parts) > 86_400:
        raise WellnessPresentationDataError("Sleep composition is invalid")
    return DailyWellness(
        calendar_date=day.calendar_date,
        steps=_optional_integer(day.steps, 0, 1_000_000),
        step_goal=_optional_integer(day.step_goal, 0, 1_000_000),
        body_battery_charged=_optional_integer(day.body_battery_charged, 0, 1_000),
        body_battery_drained=_optional_integer(day.body_battery_drained, 0, 1_000),
        body_battery_lowest=lowest,
        body_battery_highest=highest,
        body_battery_latest=_optional_integer(day.body_battery_latest, 0, 100),
        sleep_score=_optional_integer(day.sleep_score, 0, 100),
        sleep_total_seconds=_optional_integer(day.sleep_total_seconds, 0, 86_400),
        sleep_deep_seconds=sleep_parts[0],
        sleep_light_seconds=sleep_parts[1],
        sleep_rem_seconds=sleep_parts[2],
        sleep_awake_seconds=sleep_parts[3],
        training_readiness_score=_optional_integer(day.training_readiness_score, 0, 100),
        training_readiness_level=_optional_text(day.training_readiness_level),
        hrv_weekly_average_ms=_optional_real(day.hrv_weekly_average_ms),
        hrv_last_night_average_ms=_optional_real(day.hrv_last_night_average_ms),
        hrv_status=_optional_text(day.hrv_status),
        hrv_balanced_low_ms=baseline_low,
        hrv_balanced_upper_ms=baseline_upper,
        resting_heart_rate_bpm=_optional_integer(day.resting_heart_rate_bpm, 20, 300),
    )


def _bounded_days(days: Sequence[DailyWellness], as_of_date: date) -> tuple[DailyWellness, ...]:
    if len(days) > WELLNESS_RETENTION_DAYS:
        raise WellnessPresentationDataError("wellness day count exceeds retention")
    start_date = as_of_date - timedelta(days=WELLNESS_RETENTION_DAYS - 1)
    by_date: dict[date, DailyWellness] = {}
    for supplied in days:
        day = _validated_day(supplied)
        if not start_date <= day.calendar_date <= as_of_date:
            raise WellnessPresentationDataError("wellness date is outside retention")
        if day.calendar_date in by_date:
            raise WellnessPresentationDataError("wellness dates are duplicated")
        by_date[day.calendar_date] = day
    return tuple(
        by_date.get(current, DailyWellness(calendar_date=current))
        for current in (
            start_date + timedelta(days=offset) for offset in range(WELLNESS_RETENTION_DAYS)
        )
    )


def _contributor_counts(days: Sequence[DailyWellness]) -> WellnessContributorCounts:
    counts = {
        field.name: sum(getattr(day, field.name) is not None for day in days)
        for field in fields(DailyWellness)
        if field.name != "calendar_date"
    }
    return WellnessContributorCounts(**counts)


def _latest_value_date(source: WellnessSource, days: Sequence[DailyWellness]) -> date | None:
    names = {
        WellnessSource.USER_SUMMARY: ("steps", "step_goal", "resting_heart_rate_bpm"),
        WellnessSource.STEPS: ("steps",),
        WellnessSource.BODY_BATTERY: tuple(
            name
            for name in WellnessContributorCounts.__dataclass_fields__
            if name.startswith("body_")
        ),
        WellnessSource.SLEEP: tuple(
            name
            for name in WellnessContributorCounts.__dataclass_fields__
            if name.startswith("sleep_")
        ),
        WellnessSource.HRV: tuple(
            name
            for name in WellnessContributorCounts.__dataclass_fields__
            if name.startswith("hrv_")
        ),
        WellnessSource.RESTING_HEART_RATE: ("resting_heart_rate_bpm",),
        WellnessSource.TRAINING_READINESS: (
            "training_readiness_score",
            "training_readiness_level",
        ),
    }[source]
    matching = [
        day.calendar_date for day in days if any(getattr(day, name) is not None for name in names)
    ]
    return max(matching, default=None)


def build_wellness_presentation(
    days: Sequence[DailyWellness],
    source_freshness: Sequence[WellnessSourceFreshness],
    *,
    as_of_date: date,
    generated_at: datetime,
    collection_enabled: bool,
    source_failures: Mapping[WellnessSource, WellnessFailureClassification | None] | None = None,
) -> WellnessPresentation:
    """Build the fixed 30-day typed presentation model.

    Missing stored dates become explicit all-null daily points. A valid zero remains
    a contributor. Source failures are stable classifications only; exception text
    and remote values cannot enter this contract.

    Args:
        days: Validated retained wellness rows, with no duplicate dates.
        source_freshness: Successful source refresh timestamps for the account.
        as_of_date: Inclusive local date ending the presentation periods.
        generated_at: Time at which local wellness state was read.
        collection_enabled: Whether future wellness requests are enabled.
        source_failures: Optional redacted failures from the current command.

    Returns:
        A complete typed presentation model.

    Raises:
        WellnessPresentationDataError: If any input is malformed or inconsistent.
    """
    if type(as_of_date) is not date:
        raise WellnessPresentationDataError("wellness local date is invalid")
    if not isinstance(collection_enabled, bool):
        raise WellnessPresentationDataError("wellness collection state is invalid")
    _timestamp_text(generated_at)
    bounded_days = _bounded_days(days, as_of_date)
    freshness_by_source: dict[WellnessSource, datetime] = {}
    for item in source_freshness:
        if not isinstance(item, WellnessSourceFreshness) or not isinstance(
            item.source, WellnessSource
        ):
            raise WellnessPresentationDataError("wellness source freshness is invalid")
        if item.source in freshness_by_source:
            raise WellnessPresentationDataError("wellness source freshness is duplicated")
        _timestamp_text(item.refreshed_at)
        if item.refreshed_at > generated_at:
            raise WellnessPresentationDataError("wellness freshness is after generation")
        freshness_by_source[item.source] = item.refreshed_at
    failures = source_failures or {}
    if any(
        not isinstance(source, WellnessSource)
        or (failure is not None and not isinstance(failure, WellnessFailureClassification))
        for source, failure in failures.items()
    ):
        raise WellnessPresentationDataError("wellness source failure is invalid")

    sources = tuple(
        WellnessSourcePresentation(
            source=source,
            refreshed_at=freshness_by_source.get(source),
            latest_value_date=_latest_value_date(source, bounded_days),
            failure=failures.get(source),
        )
        for source in WellnessSource
    )
    periods = tuple(
        WellnessPeriodPresentation(
            key=key,
            start_date=as_of_date - timedelta(days=period_days - 1),
            end_date=as_of_date,
            contributing_days=_contributor_counts(bounded_days[-period_days:]),
        )
        for key, period_days in WELLNESS_PERIODS
    )
    return WellnessPresentation(
        generated_at=generated_at,
        as_of_local_date=as_of_date,
        collection_enabled=collection_enabled,
        sources=sources,
        periods=periods,
        days=tuple(WellnessDayPresentation(day) for day in bounded_days),
    )


def render_wellness_presentation(
    days: Sequence[DailyWellness],
    source_freshness: Sequence[WellnessSourceFreshness],
    *,
    as_of_date: date,
    generated_at: datetime,
    collection_enabled: bool,
    source_failures: Mapping[WellnessSource, WellnessFailureClassification | None] | None = None,
) -> bytes:
    """Serialize a bounded typed wellness presentation as compact UTF-8 JSON."""
    model = build_wellness_presentation(
        days,
        source_freshness,
        as_of_date=as_of_date,
        generated_at=generated_at,
        collection_enabled=collection_enabled,
        source_failures=source_failures,
    )
    try:
        content = (
            json.dumps(model.to_payload(), allow_nan=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode()
    except (TypeError, ValueError) as error:
        raise WellnessPresentationDataError(
            "wellness presentation cannot be serialized safely"
        ) from error
    if len(content) > MAX_WELLNESS_PRESENTATION_BYTES:
        raise WellnessPresentationDataError("wellness presentation exceeds the byte limit")
    return content


class WellnessPresentationCache:
    """Render and atomically replace the private wellness display cache."""

    def __init__(self, path: Path) -> None:
        """Initialize the cache with an absolute private destination path."""
        self._path = path

    def write(
        self,
        days: Sequence[DailyWellness],
        source_freshness: Sequence[WellnessSourceFreshness],
        *,
        as_of_date: date,
        generated_at: datetime,
        collection_enabled: bool,
        source_failures: Mapping[WellnessSource, WellnessFailureClassification | None]
        | None = None,
    ) -> None:
        """Write a complete contract while preserving any previous valid file."""
        content = render_wellness_presentation(
            days,
            source_freshness,
            as_of_date=as_of_date,
            generated_at=generated_at,
            collection_enabled=collection_enabled,
            source_failures=source_failures,
        )
        try:
            atomic_write_private(self._path, content)
        except (OSError, UnsafeStoragePathError) as error:
            raise WellnessPresentationStorageError(
                "wellness presentation cache could not be written safely"
            ) from error
