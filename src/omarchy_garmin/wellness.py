"""Typed daily wellness values admitted from reviewed Garmin responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class WellnessSource(StrEnum):
    """Reviewed Garmin wellness source categories."""

    USER_SUMMARY = "user_summary"
    STEPS = "steps"
    BODY_BATTERY = "body_battery"
    SLEEP = "sleep"
    HRV = "hrv"
    RESTING_HEART_RATE = "resting_heart_rate"
    TRAINING_READINESS = "training_readiness"


class WellnessFailureClassification(StrEnum):
    """Stable redacted classifications emitted by the wellness boundary."""

    INVALID_DATA = "invalid_data"
    UNSUPPORTED = "unsupported"


class InvalidWellnessDataError(ValueError):
    """Report malformed remote wellness data without retaining remote values."""

    classification = WellnessFailureClassification.INVALID_DATA

    def __init__(self, source: WellnessSource) -> None:
        """Initialize a fixed-message error for one reviewed source."""
        self.source = source
        super().__init__(f"Garmin {source.value} data is invalid.")


class UnsupportedWellnessSourceError(RuntimeError):
    """Report a source-level unsupported response without dependency details."""

    classification = WellnessFailureClassification.UNSUPPORTED

    def __init__(self, source: WellnessSource) -> None:
        """Initialize a fixed-message error for one reviewed source."""
        self.source = source
        super().__init__(f"Garmin {source.value} data is unsupported.")


@dataclass(frozen=True, slots=True)
class UserSummaryDay:
    """Current-date Steps, goal, and resting heart rate from user summary."""

    calendar_date: date
    steps: float | None
    step_goal: float | None
    resting_heart_rate_bpm: float | None


@dataclass(frozen=True, slots=True)
class StepsDay:
    """One daily Steps range value."""

    calendar_date: date
    steps: float | None


@dataclass(frozen=True, slots=True)
class BodyBatteryDay:
    """One Body Battery day after ephemeral samples have been reduced."""

    calendar_date: date
    charged: float | None
    drained: float | None
    lowest: int | None
    highest: int | None
    latest: int | None


@dataclass(frozen=True, slots=True)
class SleepRangeDay:
    """One daily score from the bounded Sleep range response."""

    calendar_date: date
    score: float | None


@dataclass(frozen=True, slots=True)
class SleepDay:
    """Reviewed detailed Sleep scalars for one Garmin calendar date."""

    calendar_date: date
    score: float | None
    total_seconds: float | None
    deep_seconds: float | None
    light_seconds: float | None
    rem_seconds: float | None
    awake_seconds: float | None


@dataclass(frozen=True, slots=True)
class HrvDay:
    """Reviewed HRV values and Garmin-provided balanced baseline bounds."""

    calendar_date: date
    weekly_average_ms: float | None
    last_night_average_ms: float | None
    status: str | None
    balanced_low_ms: float | None
    balanced_upper_ms: float | None


@dataclass(frozen=True, slots=True)
class RestingHeartRateDay:
    """One resting-heart-rate range value."""

    calendar_date: date
    beats_per_minute: float | None


@dataclass(frozen=True, slots=True)
class TrainingReadinessDay:
    """Canonical Garmin morning Training Readiness values for one date."""

    calendar_date: date
    score: float | None
    level: str | None
