import math
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from omarchy_garmin.wellness import (
    InvalidWellnessDataError,
    UnsupportedWellnessSourceError,
    WellnessFailureClassification,
    WellnessSource,
)
from omarchy_garmin.wellness_boundaries import (
    MAX_BODY_BATTERY_DATES,
    MAX_BODY_BATTERY_SAMPLES,
    MAX_RANGE_ROWS,
    MAX_TRAINING_READINESS_SNAPSHOTS,
    parse_body_battery,
    parse_daily_steps,
    parse_hrv_detail,
    parse_hrv_range,
    parse_resting_heart_rate,
    parse_sleep_detail,
    parse_sleep_range,
    parse_training_readiness,
    parse_user_summary,
)

DAY = date(2026, 8, 25)
START = date(2026, 8, 20)
END = date(2026, 8, 26)


def _body_timestamp(*, hours: int = 12) -> int:
    instant = datetime(2026, 8, 25, tzinfo=UTC) + timedelta(hours=hours)
    return int(instant.timestamp() * 1_000)


def _readiness(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "calendarDate": DAY.isoformat(),
        "timestampLocal": "2026-08-25T07:30:00",
        "inputContext": "AFTER_WAKEUP_RESET",
        "score": 74,
        "level": "HIGH",
        "deviceId": "discard-me",
        "feedbackLong": "discard-me-too",
    }
    row.update(overrides)
    return row


def test_wellness_errors_have_stable_redacted_classifications() -> None:
    invalid = InvalidWellnessDataError(WellnessSource.SLEEP)
    unsupported = UnsupportedWellnessSourceError(WellnessSource.HRV)

    assert invalid.classification is WellnessFailureClassification.INVALID_DATA
    assert invalid.source is WellnessSource.SLEEP
    assert str(invalid) == "Garmin sleep data is invalid."
    assert unsupported.classification is WellnessFailureClassification.UNSUPPORTED
    assert unsupported.source is WellnessSource.HRV
    assert str(unsupported) == "Garmin hrv data is unsupported."


def test_user_summary_copies_only_reviewed_values_into_frozen_domain_data() -> None:
    payload = {
        "calendarDate": DAY.isoformat(),
        "totalSteps": 8_765,
        "dailyStepGoal": 10_000,
        "restingHeartRate": 54,
        "stressLevel": "discard-me",
        "privateProfile": {"secret": "discard-me"},
    }

    result = parse_user_summary(payload, DAY)

    assert result is not None
    assert result.calendar_date == DAY
    assert result.steps == 8_765
    assert result.step_goal == 10_000
    assert result.resting_heart_rate_bpm == 54
    assert not hasattr(result, "stressLevel")
    assert "secret" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.steps = 1  # type: ignore[misc]


def test_user_summary_missing_payload_or_date_is_missing_and_valid_zero_is_preserved() -> None:
    assert parse_user_summary(None, DAY) is None
    assert parse_user_summary({"totalSteps": 0, "dailyStepGoal": 0}, DAY) is None

    result = parse_user_summary(
        {"calendarDate": DAY.isoformat(), "totalSteps": 0, "dailyStepGoal": 0}, DAY
    )

    assert result is not None
    assert result.steps == 0
    assert result.step_goal == 0
    assert result.resting_heart_rate_bpm is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="not-object"),
        pytest.param({"calendarDate": True}, id="boolean-date"),
        pytest.param({"calendarDate": "20260825"}, id="compact-date"),
        pytest.param({"calendarDate": "2026-99-99"}, id="invalid-calendar-date"),
        pytest.param({"calendarDate": "2026-W35-2"}, id="week-date"),
        pytest.param({"calendarDate": "2026-08-24"}, id="wrong-date"),
        pytest.param({"calendarDate": DAY.isoformat(), "totalSteps": True}, id="boolean-number"),
        pytest.param({"calendarDate": DAY.isoformat(), "totalSteps": math.inf}, id="non-finite"),
        pytest.param({"calendarDate": DAY.isoformat(), "totalSteps": 10**400}, id="excessive-int"),
        pytest.param({"calendarDate": DAY.isoformat(), "dailyStepGoal": 1_000_001}, id="goal-high"),
        pytest.param({"calendarDate": DAY.isoformat(), "restingHeartRate": 19}, id="rhr-low"),
    ],
)
def test_malformed_user_summary_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidWellnessDataError) as raised:
        parse_user_summary(payload, DAY)

    assert raised.value.source is WellnessSource.USER_SUMMARY


def test_daily_steps_range_is_typed_bounded_and_discards_extra_fields() -> None:
    payload = [
        {"calendarDate": "2026-08-24", "totalSteps": 0, "distance": "discard-me"},
        {"calendarDate": "2026-08-25", "totalSteps": 12_345, "owner": "discard-me"},
    ]

    result = parse_daily_steps(payload, START, END)

    assert [day.calendar_date for day in result] == [date(2026, 8, 24), DAY]
    assert [day.steps for day in result] == [0, 12_345]
    assert all(not hasattr(day, "distance") for day in result)
    assert "owner" not in repr(result)


def test_daily_steps_empty_response_or_missing_date_is_missing() -> None:
    assert parse_daily_steps(None, START, END) == ()
    assert parse_daily_steps([{"calendarDate": None, "totalSteps": 500}], START, END) == ()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="not-list"),
        pytest.param([None], id="row-not-object"),
        pytest.param([{"calendarDate": "invalid"}], id="invalid-date"),
        pytest.param([{"calendarDate": "2026-08-19"}], id="outside-period"),
        pytest.param([{"calendarDate": DAY.isoformat(), "totalSteps": -1}], id="negative"),
        pytest.param(
            [
                {"calendarDate": DAY.isoformat(), "totalSteps": 1},
                {"calendarDate": DAY.isoformat(), "totalSteps": 2},
            ],
            id="duplicate-date",
        ),
        pytest.param([None] * (MAX_RANGE_ROWS + 1), id="excessive-rows"),
    ],
)
def test_malformed_daily_steps_range_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidWellnessDataError) as raised:
        parse_daily_steps(payload, START, END)

    assert raised.value.source is WellnessSource.STEPS


def test_body_battery_samples_reduce_to_daily_values_and_become_unreachable() -> None:
    first_timestamp = _body_timestamp(hours=1)
    samples = [
        [first_timestamp, 42],
        [_body_timestamp(hours=4), None],
        [_body_timestamp(hours=8), 78],
        [_body_timestamp(hours=12), 55],
    ]
    payload = [
        {
            "date": DAY.isoformat(),
            "charged": 48,
            "drained": 31,
            "bodyBatteryValuesArray": samples,
            "bodyBatteryValueDescriptorDTOList": [{"private": "discard-me"}],
        }
    ]

    result = parse_body_battery(payload, DAY, DAY)

    assert len(result) == 1
    day = result[0]
    assert (day.charged, day.drained) == (48, 31)
    assert (day.lowest, day.highest, day.latest) == (42, 78, 55)
    assert not hasattr(day, "body_battery_values_array")
    assert "private" not in repr(day)
    assert str(first_timestamp) not in repr(day)


def test_body_battery_accepts_null_samples_and_equal_ordered_timestamps() -> None:
    timestamp = _body_timestamp()
    result = parse_body_battery(
        [
            {
                "date": DAY.isoformat(),
                "charged": 0,
                "drained": 0,
                "bodyBatteryValuesArray": [[timestamp, None], [timestamp, None]],
            }
        ],
        DAY,
        DAY,
    )

    assert result[0].charged == 0
    assert result[0].drained == 0
    assert result[0].lowest is None
    assert result[0].highest is None
    assert result[0].latest is None


def test_body_battery_empty_response_or_missing_date_without_samples_is_missing() -> None:
    assert parse_body_battery(None, DAY, DAY) == ()
    assert parse_body_battery([{"charged": 10, "bodyBatteryValuesArray": []}], DAY, DAY) == ()


@pytest.mark.parametrize(
    "sample",
    [
        pytest.param("not-a-list", id="sample-not-list"),
        pytest.param([_body_timestamp()], id="wrong-sample-length"),
        pytest.param([True, 50], id="boolean-timestamp"),
        pytest.param([_body_timestamp(hours=-15), 50], id="before-timezone-envelope"),
        pytest.param([_body_timestamp(hours=39), 50], id="after-timezone-envelope"),
        pytest.param([_body_timestamp(), True], id="boolean-level"),
        pytest.param([_body_timestamp(), 50.0], id="noninteger-level"),
        pytest.param([_body_timestamp(), -1], id="negative-level"),
        pytest.param([_body_timestamp(), 101], id="high-level"),
    ],
)
def test_malformed_body_battery_sample_is_rejected(sample: object) -> None:
    payload = [{"date": DAY.isoformat(), "bodyBatteryValuesArray": [sample]}]

    with pytest.raises(InvalidWellnessDataError) as raised:
        parse_body_battery(payload, DAY, DAY)

    assert raised.value.source is WellnessSource.BODY_BATTERY


def test_body_battery_validation_error_does_not_retain_sample_timestamp() -> None:
    timestamp = _body_timestamp(hours=-15)

    with pytest.raises(InvalidWellnessDataError) as raised:
        parse_body_battery(
            [{"date": DAY.isoformat(), "bodyBatteryValuesArray": [[timestamp, 50]]}],
            DAY,
            DAY,
        )

    assert str(timestamp) not in repr(raised.value)
    assert raised.value.__cause__ is None


def test_body_battery_samples_must_be_monotonically_ordered() -> None:
    payload = [
        {
            "date": DAY.isoformat(),
            "bodyBatteryValuesArray": [
                [_body_timestamp(hours=12), 50],
                [_body_timestamp(hours=11), 51],
            ],
        }
    ]

    with pytest.raises(InvalidWellnessDataError):
        parse_body_battery(payload, DAY, DAY)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="not-list"),
        pytest.param([None], id="row-not-object"),
        pytest.param([{"date": DAY.isoformat(), "charged": True}], id="boolean-total"),
        pytest.param([{"date": DAY.isoformat(), "drained": 1_001}], id="total-high"),
        pytest.param([{"date": "2026-08-24"}], id="wrong-date"),
        pytest.param([{"date": DAY.isoformat()}, {"date": DAY.isoformat()}], id="duplicate-date"),
        pytest.param([None] * (MAX_BODY_BATTERY_DATES + 1), id="excessive-dates"),
        pytest.param(
            [
                {
                    "date": DAY.isoformat(),
                    "bodyBatteryValuesArray": [[_body_timestamp(), 50]]
                    * (MAX_BODY_BATTERY_SAMPLES + 1),
                }
            ],
            id="excessive-samples",
        ),
        pytest.param([{"charged": 1, "bodyBatteryValuesArray": [[1, 50]]}], id="sample-no-date"),
    ],
)
def test_malformed_body_battery_response_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidWellnessDataError):
        parse_body_battery(payload, DAY, DAY)


def test_body_battery_request_range_is_limited_to_seven_dates() -> None:
    with pytest.raises(ValueError, match="seven"):
        parse_body_battery([], DAY, DAY + timedelta(days=7))


def test_sleep_range_admits_only_dated_score_rows() -> None:
    result = parse_sleep_range(
        [
            {"calendarDate": None, "overallSleepScore": 50},
            {"calendarDate": "2026-08-24", "overallSleepScore": 0, "feedback": "discard"},
            {"calendarDate": DAY.isoformat(), "overallSleepScore": 88},
        ],
        START,
        END,
    )

    assert [(day.calendar_date, day.score) for day in result] == [
        (date(2026, 8, 24), 0),
        (DAY, 88),
    ]
    assert not hasattr(result[0], "feedback")


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="not-list"),
        pytest.param([{"calendarDate": DAY.isoformat(), "overallSleepScore": math.nan}], id="nan"),
        pytest.param([{"calendarDate": DAY.isoformat(), "overallSleepScore": 101}], id="high"),
        pytest.param(
            [{"calendarDate": DAY.isoformat()}, {"calendarDate": DAY.isoformat()}],
            id="duplicate",
        ),
        pytest.param([{}] * (MAX_RANGE_ROWS + 1), id="excessive"),
    ],
)
def test_malformed_sleep_range_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidWellnessDataError):
        parse_sleep_range(payload, START, END)


def test_empty_sleep_range_is_missing() -> None:
    assert parse_sleep_range(None, START, END) == ()


def test_sleep_detail_admits_reviewed_score_and_stage_values_only() -> None:
    payload = {
        "dailySleepDTO": {
            "calendarDate": DAY.isoformat(),
            "sleepTimeSeconds": 28_800,
            "deepSleepSeconds": 5_400,
            "lightSleepSeconds": 15_000,
            "remSleepSeconds": 6_000,
            "awakeSleepSeconds": 2_400,
            "sleepScores": {"overall": {"value": 91, "qualifierKey": "discard"}},
            "sleepStartTimestampLocal": "must-not-survive",
            "heartRateSamples": ["must-not-survive"],
        },
        "wellnessSpO2SleepSummaryDTO": {"private": "must-not-survive"},
    }

    result = parse_sleep_detail(payload, DAY)

    assert result is not None
    assert result.score == 91
    assert result.total_seconds == 28_800
    assert (result.deep_seconds, result.light_seconds, result.rem_seconds) == (5_400, 15_000, 6_000)
    assert result.awake_seconds == 2_400
    assert not hasattr(result, "sleep_start_timestamp_local")
    assert "must-not-survive" not in repr(result)


@pytest.mark.parametrize(
    "sleep_scores",
    [
        pytest.param(None, id="missing-scores"),
        pytest.param({"overall": None}, id="missing-overall"),
    ],
)
def test_sparse_sleep_detail_preserves_missing_values(sleep_scores: object) -> None:
    result = parse_sleep_detail(
        {
            "dailySleepDTO": {
                "calendarDate": DAY.isoformat(),
                "sleepScores": sleep_scores,
            }
        },
        DAY,
    )

    assert result is not None
    assert result.score is None
    assert result.total_seconds is None
    assert result.deep_seconds is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="response-not-object"),
        pytest.param({"dailySleepDTO": []}, id="dto-not-object"),
        pytest.param(
            {"dailySleepDTO": {"calendarDate": DAY.isoformat(), "sleepScores": []}},
            id="scores-not-object",
        ),
        pytest.param(
            {"dailySleepDTO": {"calendarDate": DAY.isoformat(), "sleepScores": {"overall": []}}},
            id="overall-not-object",
        ),
        pytest.param(
            {
                "dailySleepDTO": {
                    "calendarDate": DAY.isoformat(),
                    "sleepScores": {"overall": {"value": True}},
                }
            },
            id="boolean-score",
        ),
        pytest.param(
            {"dailySleepDTO": {"calendarDate": DAY.isoformat(), "sleepTimeSeconds": 86_401}},
            id="duration-high",
        ),
        pytest.param(
            {
                "dailySleepDTO": {
                    "calendarDate": DAY.isoformat(),
                    "deepSleepSeconds": 30_000,
                    "lightSleepSeconds": 30_000,
                    "remSleepSeconds": 30_000,
                }
            },
            id="stage-sum-high",
        ),
        pytest.param({"dailySleepDTO": {"calendarDate": "2026-08-24"}}, id="wrong-date"),
    ],
)
def test_malformed_sleep_detail_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidWellnessDataError):
        parse_sleep_detail(payload, DAY)


def test_empty_sleep_detail_is_missing() -> None:
    assert parse_sleep_detail(None, DAY) is None
    assert parse_sleep_detail({}, DAY) is None
    assert parse_sleep_detail({"dailySleepDTO": None}, DAY) is None
    assert parse_sleep_detail({"dailySleepDTO": {"sleepTimeSeconds": 0}}, DAY) is None


def _hrv_summary(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "calendarDate": DAY.isoformat(),
        "weeklyAvg": 47,
        "lastNightAvg": 51.5,
        "status": "BALANCED",
        "baseline": {"balancedLow": 39, "balancedUpper": 58, "markerValue": "discard"},
        "feedbackPhrase": "discard-me",
    }
    row.update(overrides)
    return row


def test_hrv_range_and_detail_admit_same_reviewed_domain_shape() -> None:
    summary = _hrv_summary()

    ranged = parse_hrv_range({"hrvSummaries": [summary], "userProfileId": "discard"}, DAY, DAY)
    detailed = parse_hrv_detail({"hrvSummary": summary, "hrvReadings": [["must-not-survive"]]}, DAY)

    assert len(ranged) == 1
    assert detailed == ranged[0]
    assert detailed.weekly_average_ms == 47
    assert detailed.last_night_average_ms == 51.5
    assert (detailed.balanced_low_ms, detailed.balanced_upper_ms) == (39, 58)
    assert not hasattr(detailed, "hrv_readings")
    assert "must-not-survive" not in repr(detailed)


def test_sparse_hrv_values_remain_missing() -> None:
    result = parse_hrv_detail({"hrvSummary": {"calendarDate": DAY.isoformat()}}, DAY)

    assert result is not None
    assert result.weekly_average_ms is None
    assert result.last_night_average_ms is None
    assert result.status is None
    assert result.balanced_low_ms is None


def test_undated_hrv_rows_are_not_admitted() -> None:
    assert parse_hrv_detail({"hrvSummary": {"weeklyAvg": 50}}, DAY) is None
    assert parse_hrv_range({"hrvSummaries": [{"weeklyAvg": 50}]}, START, END) == ()


def test_empty_hrv_responses_are_missing() -> None:
    assert parse_hrv_range(None, START, END) == ()
    assert parse_hrv_range({}, START, END) == ()
    assert parse_hrv_range({"hrvSummaries": None}, START, END) == ()
    assert parse_hrv_detail(None, DAY) is None
    assert parse_hrv_detail({}, DAY) is None
    assert parse_hrv_detail({"hrvSummary": None}, DAY) is None


@pytest.mark.parametrize(
    "summary",
    [
        pytest.param([], id="summary-not-object"),
        pytest.param(_hrv_summary(weeklyAvg=True), id="boolean-average"),
        pytest.param(_hrv_summary(lastNightAvg=1_001), id="average-high"),
        pytest.param(_hrv_summary(status="UNSAFE\nSTATUS"), id="ascii-control-status"),
        pytest.param(_hrv_summary(status="UNSAFE\u0085STATUS"), id="unicode-control-status"),
        pytest.param(_hrv_summary(status="UNSAFE\u202eSTATUS"), id="unicode-format-status"),
        pytest.param(_hrv_summary(status="x" * 65), id="long-status"),
        pytest.param(_hrv_summary(baseline=[]), id="baseline-not-object"),
        pytest.param(
            _hrv_summary(baseline={"balancedLow": 60, "balancedUpper": 40}),
            id="inverted-baseline",
        ),
        pytest.param(_hrv_summary(calendarDate="2026-08-24"), id="wrong-date"),
    ],
)
def test_malformed_hrv_detail_is_rejected(summary: object) -> None:
    with pytest.raises(InvalidWellnessDataError):
        parse_hrv_detail({"hrvSummary": summary}, DAY)


def test_duplicate_or_excessive_hrv_range_is_rejected() -> None:
    with pytest.raises(InvalidWellnessDataError):
        parse_hrv_range({"hrvSummaries": [_hrv_summary(), _hrv_summary()]}, DAY, DAY)
    with pytest.raises(InvalidWellnessDataError):
        parse_hrv_range({"hrvSummaries": [{}] * (MAX_RANGE_ROWS + 1)}, START, END)


def test_resting_heart_rate_range_admits_only_reviewed_dated_rows() -> None:
    result = parse_resting_heart_rate(
        [
            {"calendarDate": None, "value": 50},
            {"calendarDate": "2026-08-24", "value": None, "owner": "discard"},
            {"calendarDate": DAY.isoformat(), "value": 52},
        ],
        START,
        END,
    )

    assert [(day.calendar_date, day.beats_per_minute) for day in result] == [
        (date(2026, 8, 24), None),
        (DAY, 52),
    ]
    assert not hasattr(result[0], "owner")


def test_empty_resting_heart_rate_range_is_missing() -> None:
    assert parse_resting_heart_rate(None, START, END) == ()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="not-list"),
        pytest.param([[]], id="row-not-object"),
        pytest.param([{"calendarDate": DAY.isoformat(), "value": True}], id="boolean"),
        pytest.param([{"calendarDate": DAY.isoformat(), "value": 0}], id="below-range"),
        pytest.param([{"calendarDate": DAY.isoformat(), "value": 301}], id="above-range"),
        pytest.param(
            [{"calendarDate": DAY.isoformat()}, {"calendarDate": DAY.isoformat()}],
            id="duplicate",
        ),
        pytest.param([{}] * (MAX_RANGE_ROWS + 1), id="excessive"),
    ],
)
def test_malformed_resting_heart_rate_range_is_rejected(payload: object) -> None:
    with pytest.raises(InvalidWellnessDataError):
        parse_resting_heart_rate(payload, START, END)


def test_training_readiness_prefers_earliest_after_wakeup_snapshot() -> None:
    payload = [
        _readiness(timestampLocal="2026-08-25T05:00:00", inputContext="SCHEDULED", score=99),
        _readiness(timestampLocal="2026-08-25T08:00:00", score=80, level="MEDIUM"),
        _readiness(timestampLocal="2026-08-25T07:00:00", score=72, level="HIGH"),
    ]

    result = parse_training_readiness(payload, DAY)

    assert result is not None
    assert result.calendar_date == DAY
    assert result.score == 72
    assert result.level == "HIGH"
    assert not hasattr(result, "timestamp_local")
    assert not hasattr(result, "input_context")
    assert "deviceId" not in repr(result)
    assert "2026-08-25T07:00:00" not in repr(result)


def test_training_readiness_without_context_uses_earliest_timestamp() -> None:
    payload = [
        _readiness(timestampLocal="2026-08-25T09:00:00", inputContext=None, score=90),
        _readiness(timestampLocal="2026-08-25T06:00:00", inputContext=None, score=60),
    ]

    result = parse_training_readiness(payload, DAY)

    assert result is not None
    assert result.score == 60


def test_single_timestamp_less_training_readiness_is_valid_fallback() -> None:
    result = parse_training_readiness(
        [_readiness(timestampLocal=None, inputContext=None, score=0, level=None)], DAY
    )

    assert result is not None
    assert result.score == 0
    assert result.level is None


def test_single_preferred_timestamp_less_readiness_beats_other_contexts() -> None:
    result = parse_training_readiness(
        [
            _readiness(timestampLocal=None, score=70),
            _readiness(inputContext="SCHEDULED", timestampLocal="2026-08-25T06:00:00", score=90),
        ],
        DAY,
    )

    assert result is not None
    assert result.score == 70


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(None, id="empty-response"),
        pytest.param([], id="empty-list"),
        pytest.param([_readiness(inputContext="SCHEDULED")], id="context-without-after-wakeup"),
        pytest.param(
            [
                _readiness(inputContext=None, timestampLocal=None),
                _readiness(inputContext=None, timestampLocal="2026-08-25T07:00:00"),
            ],
            id="multiple-with-timestamp-less-candidate",
        ),
        pytest.param(
            [
                _readiness(inputContext=None, timestampLocal="2026-08-25T07:00:00"),
                _readiness(inputContext=None, timestampLocal="2026-08-25T07:00:00"),
            ],
            id="tied-earliest-candidates",
        ),
        pytest.param([_readiness(calendarDate=None)], id="missing-date"),
    ],
)
def test_ambiguous_or_missing_training_readiness_returns_missing(payload: object) -> None:
    assert parse_training_readiness(payload, DAY) is None


@pytest.mark.parametrize(
    "row",
    [
        pytest.param([], id="row-not-object"),
        pytest.param(_readiness(calendarDate="2026-08-24"), id="wrong-date"),
        pytest.param(_readiness(score=True), id="boolean-score"),
        pytest.param(_readiness(score=101), id="score-high"),
        pytest.param(_readiness(level="unsafe\nlevel"), id="unsafe-level"),
        pytest.param(_readiness(level="x" * 65), id="long-level"),
        pytest.param(_readiness(inputContext=True), id="context-not-text"),
        pytest.param(_readiness(inputContext="unsafe\u0000context"), id="unsafe-context"),
        pytest.param(_readiness(timestampLocal=True), id="timestamp-not-text"),
        pytest.param(_readiness(timestampLocal="2026-08-25"), id="timestamp-without-time"),
        pytest.param(_readiness(timestampLocal="2026-08-25Tbad-time"), id="malformed-timestamp"),
        pytest.param(_readiness(timestampLocal="2026-08-24T23:59:59"), id="timestamp-wrong-date"),
        pytest.param(_readiness(timestampLocal="2026-08-25T07:00:00+01:00"), id="timestamp-aware"),
        pytest.param(_readiness(timestampLocal="2026-08-25T" + "1" * 41), id="timestamp-long"),
    ],
)
def test_malformed_training_readiness_snapshot_is_rejected(row: object) -> None:
    with pytest.raises(InvalidWellnessDataError) as raised:
        parse_training_readiness([row], DAY)

    assert raised.value.source is WellnessSource.TRAINING_READINESS


def test_training_readiness_validation_error_does_not_retain_transient_fields() -> None:
    timestamp = "2026-08-25Tprivate-invalid"
    context = "PRIVATE\nCONTEXT"

    with pytest.raises(InvalidWellnessDataError) as raised:
        parse_training_readiness(
            [_readiness(timestampLocal=timestamp, inputContext=context)],
            DAY,
        )

    assert timestamp not in repr(raised.value)
    assert context not in repr(raised.value)
    assert raised.value.__cause__ is None


def test_excessive_training_readiness_snapshots_are_rejected() -> None:
    payload: list[Any] = [None] * (MAX_TRAINING_READINESS_SNAPSHOTS + 1)

    with pytest.raises(InvalidWellnessDataError):
        parse_training_readiness(payload, DAY)


@pytest.mark.parametrize(
    "parser",
    [parse_daily_steps, parse_sleep_range, parse_hrv_range, parse_resting_heart_rate],
)
def test_invalid_range_arguments_are_rejected(parser: Any) -> None:
    payload: object = {} if parser is parse_hrv_range else []

    with pytest.raises(ValueError, match="start_date"):
        parser(payload, END, START)
