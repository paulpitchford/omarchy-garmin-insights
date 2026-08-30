"""Strict project-owned validation for reviewed Garmin wellness responses."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import cast

from omarchy_garmin.wellness import (
    BodyBatteryDay,
    HrvDay,
    InvalidWellnessDataError,
    RestingHeartRateDay,
    SleepDay,
    SleepRangeDay,
    StepsDay,
    TrainingReadinessDay,
    UserSummaryDay,
    WellnessSource,
)

MAX_RANGE_ROWS = 31
MAX_BODY_BATTERY_DATES = 7
MAX_BODY_BATTERY_SAMPLES = 2_000
MAX_TRAINING_READINESS_SNAPSHOTS = 64

_MAX_STEPS = 1_000_000.0
_MAX_BODY_BATTERY_TOTAL = 1_000.0
_MAX_SCORE = 100.0
_MAX_SLEEP_SECONDS = 86_400.0
_MAX_HRV_MS = 1_000.0
_MIN_RESTING_HEART_RATE = 20.0
_MAX_RESTING_HEART_RATE = 300.0
_MAX_REMOTE_TEXT = 64
_AFTER_WAKEUP_CONTEXT = "AFTER_WAKEUP_RESET"
_MAX_TIMESTAMP_LENGTH = 40


def _invalid(source: WellnessSource) -> InvalidWellnessDataError:
    return InvalidWellnessDataError(source)


def _mapping(value: object, source: WellnessSource) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise _invalid(source)
    return value


def _optional_number(
    value: object,
    source: WellnessSource,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(source)
    try:
        normalized = float(value)
    except OverflowError:
        raise _invalid(source) from None
    if not math.isfinite(normalized) or normalized < minimum or normalized > maximum:
        raise _invalid(source)
    return normalized


def _optional_text(value: object, source: WellnessSource) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_REMOTE_TEXT
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise _invalid(source)
    return value


def _calendar_date(
    value: object,
    source: WellnessSource,
    start_date: date,
    end_date: date,
) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise _invalid(source)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _invalid(source) from None
    if parsed.isoformat() != value:
        raise _invalid(source)
    if parsed < start_date or parsed > end_date:
        raise _invalid(source)
    return parsed


def _validate_period(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValueError("start_date must not follow end_date")


def _bounded_list(value: object, source: WellnessSource, maximum: int) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise _invalid(source)
    return value


def _reject_duplicate(seen: set[date], calendar_date: date, source: WellnessSource) -> None:
    if calendar_date in seen:
        raise _invalid(source)
    seen.add(calendar_date)


def parse_user_summary(payload: object, requested_date: date) -> UserSummaryDay | None:
    """Validate current-date Steps, goal, and resting heart rate from user summary."""
    source = WellnessSource.USER_SUMMARY
    if payload is None:
        return None
    row = _mapping(payload, source)
    steps = _optional_number(row.get("totalSteps"), source, minimum=0, maximum=_MAX_STEPS)
    goal = _optional_number(row.get("dailyStepGoal"), source, minimum=0, maximum=_MAX_STEPS)
    resting = _optional_number(
        row.get("restingHeartRate"),
        source,
        minimum=_MIN_RESTING_HEART_RATE,
        maximum=_MAX_RESTING_HEART_RATE,
    )
    calendar_date = _calendar_date(row.get("calendarDate"), source, requested_date, requested_date)
    if calendar_date is None:
        return None
    return UserSummaryDay(calendar_date, steps, goal, resting)


def parse_daily_steps(
    payload: object,
    start_date: date,
    end_date: date,
) -> tuple[StepsDay, ...]:
    """Validate a bounded daily Steps range and discard every extra field."""
    _validate_period(start_date, end_date)
    source = WellnessSource.STEPS
    if payload is None:
        return ()
    rows = _bounded_list(payload, source, MAX_RANGE_ROWS)
    result: list[StepsDay] = []
    seen: set[date] = set()
    for raw_row in rows:
        row = _mapping(raw_row, source)
        steps = _optional_number(row.get("totalSteps"), source, minimum=0, maximum=_MAX_STEPS)
        calendar_date = _calendar_date(row.get("calendarDate"), source, start_date, end_date)
        if calendar_date is None:
            continue
        _reject_duplicate(seen, calendar_date, source)
        result.append(StepsDay(calendar_date, steps))
    return tuple(result)


def _sample_bounds(calendar_date: date) -> tuple[int, int]:
    midnight = datetime.combine(calendar_date, time.min, tzinfo=UTC)
    first = midnight - timedelta(hours=14)
    last_exclusive = midnight + timedelta(days=1, hours=14)
    return int(first.timestamp() * 1_000), int(last_exclusive.timestamp() * 1_000)


def _body_battery_levels(
    value: object,
    source: WellnessSource,
    calendar_date: date | None,
) -> tuple[int | None, int | None, int | None]:
    if value is None:
        return None, None, None
    samples = _bounded_list(value, source, MAX_BODY_BATTERY_SAMPLES)
    if calendar_date is None:
        if samples:
            raise _invalid(source)
        return None, None, None

    first_timestamp, last_timestamp = _sample_bounds(calendar_date)
    previous_timestamp: int | None = None
    levels: list[int] = []
    for sample in samples:
        if not isinstance(sample, list) or len(sample) != 2:
            raise _invalid(source)
        timestamp, level = sample
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise _invalid(source)
        if timestamp < first_timestamp or timestamp >= last_timestamp:
            raise _invalid(source)
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise _invalid(source)
        previous_timestamp = timestamp
        if level is None:
            continue
        if isinstance(level, bool) or not isinstance(level, int) or level < 0 or level > 100:
            raise _invalid(source)
        levels.append(level)

    if not levels:
        return None, None, None
    return min(levels), max(levels), levels[-1]


def parse_body_battery(
    payload: object,
    start_date: date,
    end_date: date,
) -> tuple[BodyBatteryDay, ...]:
    """Validate Body Battery days and retain only reduced daily scalar values."""
    _validate_period(start_date, end_date)
    if (end_date - start_date).days >= MAX_BODY_BATTERY_DATES:
        raise ValueError("Body Battery requests may cover at most seven dates")
    source = WellnessSource.BODY_BATTERY
    if payload is None:
        return ()
    rows = _bounded_list(payload, source, MAX_BODY_BATTERY_DATES)
    result: list[BodyBatteryDay] = []
    seen: set[date] = set()
    for raw_row in rows:
        row = _mapping(raw_row, source)
        charged = _optional_number(
            row.get("charged"), source, minimum=0, maximum=_MAX_BODY_BATTERY_TOTAL
        )
        drained = _optional_number(
            row.get("drained"), source, minimum=0, maximum=_MAX_BODY_BATTERY_TOTAL
        )
        calendar_date = _calendar_date(row.get("date"), source, start_date, end_date)
        lowest, highest, latest = _body_battery_levels(
            row.get("bodyBatteryValuesArray"), source, calendar_date
        )
        if calendar_date is None:
            continue
        _reject_duplicate(seen, calendar_date, source)
        result.append(
            BodyBatteryDay(
                calendar_date=calendar_date,
                charged=charged,
                drained=drained,
                lowest=lowest,
                highest=highest,
                latest=latest,
            )
        )
    return tuple(result)


def parse_sleep_range(
    payload: object,
    start_date: date,
    end_date: date,
) -> tuple[SleepRangeDay, ...]:
    """Validate bounded daily Sleep scores returned by the range endpoint."""
    _validate_period(start_date, end_date)
    source = WellnessSource.SLEEP
    if payload is None:
        return ()
    rows = _bounded_list(payload, source, MAX_RANGE_ROWS)
    result: list[SleepRangeDay] = []
    seen: set[date] = set()
    for raw_row in rows:
        row = _mapping(raw_row, source)
        score = _optional_number(
            row.get("overallSleepScore"), source, minimum=0, maximum=_MAX_SCORE
        )
        calendar_date = _calendar_date(row.get("calendarDate"), source, start_date, end_date)
        if calendar_date is None:
            continue
        _reject_duplicate(seen, calendar_date, source)
        result.append(SleepRangeDay(calendar_date, score))
    return tuple(result)


def _sleep_score(row: Mapping[object, object], source: WellnessSource) -> float | None:
    raw_scores = row.get("sleepScores")
    if raw_scores is None:
        return None
    scores = _mapping(raw_scores, source)
    raw_overall = scores.get("overall")
    if raw_overall is None:
        return None
    overall = _mapping(raw_overall, source)
    return _optional_number(overall.get("value"), source, minimum=0, maximum=_MAX_SCORE)


def parse_sleep_detail(payload: object, requested_date: date) -> SleepDay | None:
    """Validate one detailed Sleep response and discard samples and timestamps."""
    source = WellnessSource.SLEEP
    if payload is None:
        return None
    response = _mapping(payload, source)
    raw_row = response.get("dailySleepDTO")
    if raw_row is None:
        return None
    row = _mapping(raw_row, source)
    score = _sleep_score(row, source)
    total = _optional_number(
        row.get("sleepTimeSeconds"), source, minimum=0, maximum=_MAX_SLEEP_SECONDS
    )
    deep = _optional_number(
        row.get("deepSleepSeconds"), source, minimum=0, maximum=_MAX_SLEEP_SECONDS
    )
    light = _optional_number(
        row.get("lightSleepSeconds"), source, minimum=0, maximum=_MAX_SLEEP_SECONDS
    )
    rem = _optional_number(
        row.get("remSleepSeconds"), source, minimum=0, maximum=_MAX_SLEEP_SECONDS
    )
    awake = _optional_number(
        row.get("awakeSleepSeconds"), source, minimum=0, maximum=_MAX_SLEEP_SECONDS
    )
    if sum(value for value in (deep, light, rem, awake) if value is not None) > _MAX_SLEEP_SECONDS:
        raise _invalid(source)
    calendar_date = _calendar_date(row.get("calendarDate"), source, requested_date, requested_date)
    if calendar_date is None:
        return None
    return SleepDay(calendar_date, score, total, deep, light, rem, awake)


def _hrv_day(
    raw_row: object,
    source: WellnessSource,
    start_date: date,
    end_date: date,
) -> HrvDay | None:
    row = _mapping(raw_row, source)
    weekly = _optional_number(row.get("weeklyAvg"), source, minimum=0, maximum=_MAX_HRV_MS)
    last_night = _optional_number(row.get("lastNightAvg"), source, minimum=0, maximum=_MAX_HRV_MS)
    status = _optional_text(row.get("status"), source)
    raw_baseline = row.get("baseline")
    balanced_low: float | None = None
    balanced_upper: float | None = None
    if raw_baseline is not None:
        baseline = _mapping(raw_baseline, source)
        balanced_low = _optional_number(
            baseline.get("balancedLow"), source, minimum=0, maximum=_MAX_HRV_MS
        )
        balanced_upper = _optional_number(
            baseline.get("balancedUpper"), source, minimum=0, maximum=_MAX_HRV_MS
        )
        if (
            balanced_low is not None
            and balanced_upper is not None
            and balanced_low > balanced_upper
        ):
            raise _invalid(source)
    calendar_date = _calendar_date(row.get("calendarDate"), source, start_date, end_date)
    if calendar_date is None:
        return None
    return HrvDay(calendar_date, weekly, last_night, status, balanced_low, balanced_upper)


def parse_hrv_range(
    payload: object,
    start_date: date,
    end_date: date,
) -> tuple[HrvDay, ...]:
    """Validate HRV range summaries and Garmin-provided balanced baselines."""
    _validate_period(start_date, end_date)
    source = WellnessSource.HRV
    if payload is None:
        return ()
    response = _mapping(payload, source)
    raw_rows = response.get("hrvSummaries")
    if raw_rows is None:
        return ()
    rows = _bounded_list(raw_rows, source, MAX_RANGE_ROWS)
    result: list[HrvDay] = []
    seen: set[date] = set()
    for raw_row in rows:
        day = _hrv_day(raw_row, source, start_date, end_date)
        if day is None:
            continue
        _reject_duplicate(seen, day.calendar_date, source)
        result.append(day)
    return tuple(result)


def parse_hrv_detail(payload: object, requested_date: date) -> HrvDay | None:
    """Validate one HRV response while discarding readings and timestamps."""
    source = WellnessSource.HRV
    if payload is None:
        return None
    response = _mapping(payload, source)
    raw_row = response.get("hrvSummary")
    if raw_row is None:
        return None
    return _hrv_day(raw_row, source, requested_date, requested_date)


def parse_resting_heart_rate(
    payload: object,
    start_date: date,
    end_date: date,
) -> tuple[RestingHeartRateDay, ...]:
    """Validate the dependency's bounded resting-heart-rate row wrapper."""
    _validate_period(start_date, end_date)
    source = WellnessSource.RESTING_HEART_RATE
    if payload is None:
        return ()
    rows = _bounded_list(payload, source, MAX_RANGE_ROWS)
    result: list[RestingHeartRateDay] = []
    seen: set[date] = set()
    for raw_row in rows:
        row = _mapping(raw_row, source)
        beats_per_minute = _optional_number(
            row.get("value"),
            source,
            minimum=_MIN_RESTING_HEART_RATE,
            maximum=_MAX_RESTING_HEART_RATE,
        )
        calendar_date = _calendar_date(row.get("calendarDate"), source, start_date, end_date)
        if calendar_date is None:
            continue
        _reject_duplicate(seen, calendar_date, source)
        result.append(RestingHeartRateDay(calendar_date, beats_per_minute))
    return tuple(result)


def _local_timestamp(
    value: object, source: WellnessSource, requested_date: date
) -> datetime | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > _MAX_TIMESTAMP_LENGTH
        or len(value) < 16
        or value[10] not in {" ", "T"}
    ):
        raise _invalid(source)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _invalid(source) from None
    if parsed.tzinfo is not None or parsed.date() != requested_date:
        raise _invalid(source)
    return parsed


def _select_readiness(
    candidates: list[tuple[datetime | None, str | None, float | None, str | None]],
) -> tuple[float | None, str | None] | None:
    preferred = [candidate for candidate in candidates if candidate[1] == _AFTER_WAKEUP_CONTEXT]
    if preferred:
        selectable = preferred
    elif any(candidate[1] is not None for candidate in candidates):
        return None
    else:
        selectable = candidates

    if len(selectable) == 1:
        return selectable[0][2], selectable[0][3]
    if not selectable or any(candidate[0] is None for candidate in selectable):
        return None
    ordered = sorted(selectable, key=lambda candidate: cast(datetime, candidate[0]))
    if ordered[0][0] == ordered[1][0]:
        return None
    return ordered[0][2], ordered[0][3]


def parse_training_readiness(
    payload: object,
    requested_date: date,
) -> TrainingReadinessDay | None:
    """Select and validate Garmin's canonical morning Training Readiness snapshot."""
    source = WellnessSource.TRAINING_READINESS
    if payload is None:
        return None
    rows = _bounded_list(payload, source, MAX_TRAINING_READINESS_SNAPSHOTS)
    candidates: list[tuple[datetime | None, str | None, float | None, str | None]] = []
    for raw_row in rows:
        row = _mapping(raw_row, source)
        score = _optional_number(row.get("score"), source, minimum=0, maximum=_MAX_SCORE)
        level = _optional_text(row.get("level"), source)
        context = _optional_text(row.get("inputContext"), source)
        timestamp = _local_timestamp(row.get("timestampLocal"), source, requested_date)
        calendar_date = _calendar_date(
            row.get("calendarDate"), source, requested_date, requested_date
        )
        if calendar_date is not None:
            candidates.append((timestamp, context, score, level))

    selected = _select_readiness(candidates)
    if selected is None:
        return None
    score, level = selected
    return TrainingReadinessDay(requested_date, score, level)
