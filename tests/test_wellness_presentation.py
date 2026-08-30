import json
import stat
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

import omarchy_garmin.wellness_presentation as presentation_module
from omarchy_garmin.wellness import (
    DailyWellness,
    WellnessFailureClassification,
    WellnessSource,
)
from omarchy_garmin.wellness_database import WellnessSourceFreshness
from omarchy_garmin.wellness_presentation import (
    MAX_WELLNESS_PRESENTATION_BYTES,
    WELLNESS_PRESENTATION_SCHEMA_VERSION,
    WellnessPresentationCache,
    WellnessPresentationDataError,
    WellnessPresentationStorageError,
    build_wellness_presentation,
    render_wellness_presentation,
)

_AS_OF = date(2026, 8, 30)
_GENERATED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _complete_day(calendar_date: date = _AS_OF) -> DailyWellness:
    return DailyWellness(
        calendar_date=calendar_date,
        steps=0,
        step_goal=8_000,
        body_battery_charged=42,
        body_battery_drained=31,
        body_battery_lowest=28,
        body_battery_highest=76,
        body_battery_latest=64,
        sleep_score=84,
        sleep_total_seconds=27_000,
        sleep_deep_seconds=4_500,
        sleep_light_seconds=15_000,
        sleep_rem_seconds=6_000,
        sleep_awake_seconds=1_500,
        training_readiness_score=71,
        training_readiness_level="High <plain text>",
        hrv_weekly_average_ms=48.5,
        hrv_last_night_average_ms=52.0,
        hrv_status="Balanced & synthetic",
        hrv_balanced_low_ms=40.0,
        hrv_balanced_upper_ms=60.0,
        resting_heart_rate_bpm=54,
    )


def _freshness() -> list[WellnessSourceFreshness]:
    return [
        WellnessSourceFreshness(
            source=source,
            refreshed_at=_GENERATED_AT - timedelta(minutes=index + 1),
        )
        for index, source in enumerate(WellnessSource)
    ]


def _payload(
    days: list[DailyWellness],
    freshness: list[WellnessSourceFreshness] | None = None,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            render_wellness_presentation(
                days,
                _freshness() if freshness is None else freshness,
                as_of_date=_AS_OF,
                generated_at=_GENERATED_AT,
                collection_enabled=True,
                source_failures={
                    WellnessSource.BODY_BATTERY: WellnessFailureClassification.REMOTE_SERVICE
                },
            )
        ),
    )


def test_contract_contains_only_fixed_daily_wellness_fields() -> None:
    payload = _payload([_complete_day()])

    today = payload["days"][-1]
    assert payload["schemaVersion"] == WELLNESS_PRESENTATION_SCHEMA_VERSION
    assert payload["generatedAt"] == "2026-08-30T12:00:00Z"
    assert payload["asOfLocalDate"] == "2026-08-30"
    assert payload["collectionEnabled"] is True
    assert payload["partialCurrentDaySources"] == ["steps", "bodyBattery"]
    assert today == {
        "date": "2026-08-30",
        "steps": {"value": 0, "goal": 8_000},
        "bodyBattery": {
            "charged": 42,
            "drained": 31,
            "lowest": 28,
            "highest": 76,
            "latest": 64,
        },
        "sleep": {
            "score": 84,
            "totalSeconds": 27_000,
            "deepSeconds": 4_500,
            "lightSeconds": 15_000,
            "remSeconds": 6_000,
            "awakeSeconds": 1_500,
        },
        "trainingReadiness": {"score": 71, "level": "High <plain text>"},
        "hrv": {
            "weeklyAverageMs": 48.5,
            "lastNightAverageMs": 52.0,
            "status": "Balanced & synthetic",
            "balancedLowMs": 40.0,
            "balancedUpperMs": 60.0,
        },
        "restingHeartRate": {"beatsPerMinute": 54},
    }
    serialized = json.dumps(payload)
    assert "account" not in serialized.lower()
    assert "timestampLocal" not in serialized
    assert "bodyBatteryValuesArray" not in serialized


def test_missing_dates_are_explicit_null_points_not_zero_values() -> None:
    payload = _payload([])

    assert len(payload["days"]) == 30
    assert payload["days"][0]["date"] == "2026-08-01"
    assert payload["days"][-1]["date"] == "2026-08-30"
    assert payload["days"][-1] == {
        "date": "2026-08-30",
        "steps": None,
        "bodyBattery": None,
        "sleep": None,
        "trainingReadiness": None,
        "hrv": None,
        "restingHeartRate": None,
    }
    assert payload["periods"][0]["contributingDays"]["steps"] == {
        "value": 0,
        "goal": 0,
    }


def test_valid_zero_contributes_while_missing_value_does_not() -> None:
    payload = _payload(
        [
            DailyWellness(calendar_date=_AS_OF - timedelta(days=1), steps=None),
            DailyWellness(calendar_date=_AS_OF, steps=0, body_battery_latest=0),
        ]
    )

    week = payload["periods"][0]
    assert week["key"] == "7Days"
    assert week["startDate"] == "2026-08-24"
    assert week["endDate"] == "2026-08-30"
    assert week["contributingDays"]["steps"]["value"] == 1
    assert week["contributingDays"]["bodyBattery"]["latest"] == 1


def test_seven_and_thirty_day_counts_are_derived_from_matching_dates() -> None:
    days = [
        DailyWellness(calendar_date=_AS_OF - timedelta(days=8), sleep_score=60),
        DailyWellness(calendar_date=_AS_OF - timedelta(days=6), sleep_score=70),
        DailyWellness(calendar_date=_AS_OF, sleep_score=80),
    ]

    periods = _payload(days)["periods"]

    assert [period["key"] for period in periods] == ["7Days", "30Days"]
    assert periods[0]["contributingDays"]["sleep"]["score"] == 2
    assert periods[1]["contributingDays"]["sleep"]["score"] == 3


def test_source_contract_is_complete_ordered_and_redacted() -> None:
    payload = _payload([_complete_day()])

    sources = payload["sources"]
    assert [item["source"] for item in sources] == [source.value for source in WellnessSource]
    assert sources[0]["latestValueDate"] == "2026-08-30"
    assert sources[2]["failure"] == "remote_service"
    assert all(
        set(item) == {"source", "refreshedAt", "latestValueDate", "failure"} for item in sources
    )


def test_missing_source_freshness_remains_null() -> None:
    payload = _payload([_complete_day()], [])

    assert all(source["refreshedAt"] is None for source in payload["sources"])
    assert payload["sources"][0]["latestValueDate"] == "2026-08-30"


@pytest.mark.parametrize(
    "day",
    [
        pytest.param(replace(_complete_day(), steps=cast(Any, True)), id="boolean-count"),
        pytest.param(replace(_complete_day(), body_battery_lowest=90), id="reversed-range"),
        pytest.param(replace(_complete_day(), sleep_awake_seconds=86_400), id="stage-sum"),
        pytest.param(replace(_complete_day(), hrv_weekly_average_ms=float("nan")), id="nan"),
        pytest.param(replace(_complete_day(), hrv_balanced_low_ms=70), id="baseline-order"),
        pytest.param(replace(_complete_day(), hrv_status="unsafe\ntext"), id="control-text"),
        pytest.param(replace(_complete_day(), resting_heart_rate_bpm=19), id="heart-rate"),
    ],
)
def test_malformed_daily_value_is_rejected(day: DailyWellness) -> None:
    with pytest.raises(WellnessPresentationDataError):
        _payload([day])


@pytest.mark.parametrize(
    "days",
    [
        pytest.param(
            [DailyWellness(calendar_date=_AS_OF)] * 2,
            id="duplicate-date",
        ),
        pytest.param(
            [DailyWellness(calendar_date=_AS_OF - timedelta(days=30))],
            id="outside-retention",
        ),
        pytest.param(
            [DailyWellness(calendar_date=_AS_OF)] * 31,
            id="excessive-days",
        ),
    ],
)
def test_malformed_day_collection_is_rejected(days: list[DailyWellness]) -> None:
    with pytest.raises(WellnessPresentationDataError):
        _payload(days)


def test_malformed_generation_inputs_are_rejected() -> None:
    with pytest.raises(WellnessPresentationDataError, match="local date"):
        build_wellness_presentation(
            [],
            [],
            as_of_date=cast(Any, _GENERATED_AT),
            generated_at=_GENERATED_AT,
            collection_enabled=True,
        )
    with pytest.raises(WellnessPresentationDataError, match="timezone"):
        build_wellness_presentation(
            [],
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT.replace(tzinfo=None),
            collection_enabled=True,
        )
    with pytest.raises(WellnessPresentationDataError, match="collection"):
        build_wellness_presentation(
            [],
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
            collection_enabled=cast(Any, 1),
        )


def test_duplicate_or_future_source_freshness_is_rejected() -> None:
    duplicate = WellnessSourceFreshness(WellnessSource.STEPS, _GENERATED_AT)
    future = WellnessSourceFreshness(
        WellnessSource.BODY_BATTERY,
        _GENERATED_AT + timedelta(seconds=1),
    )

    with pytest.raises(WellnessPresentationDataError, match="duplicated"):
        _payload([], [duplicate, duplicate])
    with pytest.raises(WellnessPresentationDataError, match="after generation"):
        _payload([], [future])


def test_invalid_source_failure_is_rejected_without_reflection() -> None:
    with pytest.raises(WellnessPresentationDataError, match="source failure"):
        render_wellness_presentation(
            [],
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
            collection_enabled=True,
            source_failures=cast(Any, {"private-source": "private failure"}),
        )


def test_serialized_byte_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(presentation_module, "MAX_WELLNESS_PRESENTATION_BYTES", 1)

    with pytest.raises(WellnessPresentationDataError, match="byte limit"):
        _payload([])


def test_contract_stays_within_reviewed_byte_limit() -> None:
    content = render_wellness_presentation(
        [_complete_day(_AS_OF - timedelta(days=offset)) for offset in range(30)],
        _freshness(),
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
        collection_enabled=False,
    )

    assert len(content) < MAX_WELLNESS_PRESENTATION_BYTES


def test_wellness_cache_is_atomic_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "wellness.json"

    WellnessPresentationCache(path).write(
        [_complete_day()],
        _freshness(),
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
        collection_enabled=True,
    )

    assert json.loads(path.read_bytes())["schemaVersion"] == WELLNESS_PRESENTATION_SCHEMA_VERSION
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_wellness_cache_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"keep")
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    path = cache_directory / "wellness.json"
    path.symlink_to(target)

    WellnessPresentationCache(path).write(
        [],
        [],
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
        collection_enabled=True,
    )

    assert target.read_bytes() == b"keep"
    assert path.is_symlink() is False


def test_failed_wellness_cache_generation_preserves_previous_file(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "wellness.json"
    cache = WellnessPresentationCache(path)
    cache.write(
        [_complete_day()],
        _freshness(),
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
        collection_enabled=True,
    )
    original = path.read_bytes()

    with pytest.raises(WellnessPresentationDataError):
        cache.write(
            [replace(_complete_day(), steps=cast(Any, True))],
            _freshness(),
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
            collection_enabled=True,
        )

    assert path.read_bytes() == original


def test_interrupted_wellness_cache_write_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache" / "wellness.json"
    cache = WellnessPresentationCache(path)
    cache.write(
        [],
        [],
        as_of_date=_AS_OF,
        generated_at=_GENERATED_AT,
        collection_enabled=True,
    )
    original = path.read_bytes()

    def fail_write(destination: Path, content: bytes) -> None:
        raise OSError("fabricated interrupted write")

    monkeypatch.setattr(presentation_module, "atomic_write_private", fail_write)

    with pytest.raises(WellnessPresentationStorageError):
        cache.write(
            [_complete_day()],
            _freshness(),
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
            collection_enabled=True,
        )

    assert path.read_bytes() == original


def test_relative_wellness_cache_path_is_rejected() -> None:
    with pytest.raises(WellnessPresentationStorageError):
        WellnessPresentationCache(Path("relative/wellness.json")).write(
            [],
            [],
            as_of_date=_AS_OF,
            generated_at=_GENERATED_AT,
            collection_enabled=True,
        )
