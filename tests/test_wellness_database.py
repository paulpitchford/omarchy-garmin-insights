import sqlite3
import stat
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import omarchy_garmin.database as database_module
from omarchy_garmin.auth import AuthStore
from omarchy_garmin.database import SCHEMA_VERSION, ActivityRepository
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.storage import ensure_private_directory
from omarchy_garmin.wellness import (
    BodyBatteryDay,
    HrvDay,
    RestingHeartRateDay,
    SleepDay,
    SleepRangeDay,
    StepsDay,
    TrainingReadinessDay,
    UserSummaryDay,
    WellnessSource,
)
from omarchy_garmin.wellness_database import (
    MAX_WELLNESS_UPSERT_DAYS,
    WellnessAccountMismatchError,
    WellnessDatabaseError,
    WellnessRepository,
)

TODAY = date(2026, 8, 26)
REFRESHED_AT = datetime(2026, 8, 26, 12, 30, tzinfo=UTC)
ACCOUNT_A = "a" * 64
ACCOUNT_B = "b" * 64


def _repository(tmp_path: Path, fingerprint: str = ACCOUNT_A) -> WellnessRepository:
    return WellnessRepository(tmp_path / "private" / "activities.sqlite3", fingerprint)


def _upsert_steps(
    repository: WellnessRepository,
    calendar_date: date,
    steps: int | None,
    *,
    as_of_date: date = TODAY,
) -> None:
    repository.upsert_source(
        WellnessSource.STEPS,
        [StepsDay(calendar_date, steps)],
        as_of_date=as_of_date,
        refreshed_at=REFRESHED_AT,
    )


def _schema_one_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(database_module._MIGRATION_1)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            """
            INSERT INTO activities (
                activity_id, name, type_key, started_at_local, local_date,
                duration_seconds, synced_at
            ) VALUES ('101', 'Fabricated run', 'running', '2026-08-25 08:00:00',
                      '2026-08-25', 1800.0, '2026-08-26T12:00:00+00:00')
            """
        )
        connection.commit()


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        state=tmp_path / "state",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
    )


def test_schema_one_migration_preserves_activity_rows_and_adds_only_reviewed_wellness_columns(
    tmp_path: Path,
) -> None:
    database = tmp_path / "private" / "activities.sqlite3"
    _schema_one_database(database)
    repository = WellnessRepository(database, ACCOUNT_A)

    repository.set_collection_enabled(False)

    with closing(sqlite3.connect(database)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        activity = connection.execute(
            "SELECT activity_id, name, type_key, local_date FROM activities"
        ).fetchone()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(wellness_daily)").fetchall()
        }
    assert version == SCHEMA_VERSION
    assert activity == ("101", "Fabricated run", "running", "2026-08-25")
    assert "body_battery_latest" in columns
    assert "training_readiness_score" in columns
    assert "body_battery_values_array" not in columns
    assert "timestamp_local" not in columns
    assert "input_context" not in columns
    assert "raw_response" not in columns


def test_failed_schema_one_migration_rolls_back_and_preserves_activity_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "private" / "activities.sqlite3"
    _schema_one_database(database)
    failing_migrations = {
        **database_module._MIGRATIONS,
        2: "CREATE TABLE migration_probe (value TEXT) STRICT; INVALID SQL;",
    }
    monkeypatch.setattr(database_module, "_MIGRATIONS", failing_migrations)

    with pytest.raises(WellnessDatabaseError):
        WellnessRepository(database, ACCOUNT_A).set_collection_enabled(False)

    with closing(sqlite3.connect(database)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        activity = connection.execute("SELECT activity_id, name FROM activities").fetchone()
        probe = connection.execute(
            "SELECT name FROM sqlite_schema WHERE name = 'migration_probe'"
        ).fetchone()
        wellness = connection.execute(
            "SELECT name FROM sqlite_schema WHERE name = 'wellness_daily'"
        ).fetchone()
    assert version == (1,)
    assert activity == ("101", "Fabricated run")
    assert probe is None
    assert wellness is None


def test_repeated_migration_is_idempotent_across_activity_and_wellness_repositories(
    tmp_path: Path,
) -> None:
    database = tmp_path / "private" / "activities.sqlite3"
    _schema_one_database(database)

    WellnessRepository(database, ACCOUNT_A).set_collection_enabled(True)
    ActivityRepository(database).full_reconciliation_due(TODAY)
    WellnessRepository(database, ACCOUNT_A).set_collection_enabled(True)

    with closing(sqlite3.connect(database)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
        ).fetchall()
        account_rows = connection.execute("SELECT count(*) FROM wellness_account_scope").fetchone()
    assert tables == [
        ("activities",),
        ("sync_state",),
        ("wellness_account_scope",),
        ("wellness_collection_state",),
        ("wellness_daily",),
        ("wellness_source_state",),
    ]
    assert account_rows == (1,)


def test_all_approved_daily_scalars_merge_by_date_and_freshness_is_source_specific(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    day = TODAY

    repository.upsert_source(
        WellnessSource.STEPS,
        [StepsDay(day, 9_500)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )
    repository.upsert_source(
        WellnessSource.USER_SUMMARY,
        [UserSummaryDay(day, 9_750, 10_000, 52)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT + timedelta(minutes=1),
    )
    repository.upsert_source(
        WellnessSource.BODY_BATTERY,
        [BodyBatteryDay(day, 44, 31, 28, 76, 61)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )
    repository.upsert_source(
        WellnessSource.SLEEP,
        [SleepRangeDay(day, 79)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )
    repository.upsert_source(
        WellnessSource.SLEEP,
        [SleepDay(day, 82, 27_000, 4_000, 16_000, 6_000, 1_000)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT + timedelta(minutes=2),
    )
    repository.upsert_source(
        WellnessSource.HRV,
        [HrvDay(day, 46.5, 49.0, "BALANCED", 38.0, 55.0)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )
    repository.upsert_source(
        WellnessSource.RESTING_HEART_RATE,
        [RestingHeartRateDay(day, 51)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )
    repository.upsert_source(
        WellnessSource.TRAINING_READINESS,
        [TrainingReadinessDay(day, 74, "HIGH")],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )

    stored = repository.wellness_between(day, day)
    freshness = repository.source_freshness()

    assert len(stored) == 1
    assert stored[0].steps == 9_750
    assert stored[0].step_goal == 10_000
    assert stored[0].body_battery_charged == 44
    assert stored[0].body_battery_drained == 31
    assert stored[0].body_battery_lowest == 28
    assert stored[0].body_battery_highest == 76
    assert stored[0].body_battery_latest == 61
    assert stored[0].sleep_score == 82
    assert stored[0].sleep_total_seconds == 27_000
    assert stored[0].sleep_deep_seconds == 4_000
    assert stored[0].sleep_light_seconds == 16_000
    assert stored[0].sleep_rem_seconds == 6_000
    assert stored[0].sleep_awake_seconds == 1_000
    assert stored[0].training_readiness_score == 74
    assert stored[0].training_readiness_level == "HIGH"
    assert stored[0].hrv_weekly_average_ms == 46.5
    assert stored[0].hrv_last_night_average_ms == 49.0
    assert stored[0].hrv_status == "BALANCED"
    assert stored[0].hrv_balanced_low_ms == 38.0
    assert stored[0].hrv_balanced_upper_ms == 55.0
    assert stored[0].resting_heart_rate_bpm == 51
    assert {item.source for item in freshness} == set(WellnessSource)
    sleep_freshness = next(item for item in freshness if item.source is WellnessSource.SLEEP)
    assert sleep_freshness.refreshed_at == REFRESHED_AT + timedelta(minutes=2)


def test_null_upsert_does_not_replace_retained_non_null_scalar(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _upsert_steps(repository, TODAY, 8_765)

    _upsert_steps(repository, TODAY, None)

    assert repository.wellness_between(TODAY, TODAY)[0].steps == 8_765


def test_upsert_is_idempotent_and_keeps_one_account_date_row(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    _upsert_steps(repository, TODAY, 1_000)
    _upsert_steps(repository, TODAY, 2_000)

    stored = repository.wellness_between(TODAY, TODAY)
    assert len(stored) == 1
    assert stored[0].steps == 2_000


def test_successful_source_transaction_enforces_rolling_thirty_day_retention(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    oldest_retained = TODAY - timedelta(days=29)
    expired = TODAY - timedelta(days=30)
    _upsert_steps(repository, expired, 100, as_of_date=expired)

    result = repository.upsert_source(
        WellnessSource.STEPS,
        [StepsDay(oldest_retained, 200)],
        as_of_date=TODAY,
        refreshed_at=REFRESHED_AT,
    )

    assert result.stored_count == 1
    assert result.deleted_count == 1
    assert repository.wellness_between(oldest_retained, TODAY)[0].steps == 200


def test_collection_stop_is_idempotent_and_retains_stored_values(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _upsert_steps(repository, TODAY, 7_500)

    repository.set_collection_enabled(False)
    repository.set_collection_enabled(False)

    assert repository.collection_enabled() is False
    assert repository.wellness_between(TODAY, TODAY)[0].steps == 7_500
    repository.set_collection_enabled(True)
    assert repository.collection_enabled() is True


def test_collection_setting_repairs_missing_account_state_row(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.set_collection_enabled(True)
    database = tmp_path / "private" / "activities.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM wellness_collection_state")
        connection.commit()

    repository.set_collection_enabled(False)

    assert repository.collection_enabled() is False


def test_account_mismatch_is_rejected_before_rows_or_settings_change(tmp_path: Path) -> None:
    database = tmp_path / "private" / "activities.sqlite3"
    first = WellnessRepository(database, ACCOUNT_A)
    _upsert_steps(first, TODAY, 4_000)
    second = WellnessRepository(database, ACCOUNT_B)

    with pytest.raises(WellnessAccountMismatchError):
        second.set_collection_enabled(False)

    assert first.collection_enabled() is True
    assert first.wellness_between(TODAY, TODAY)[0].steps == 4_000


def test_failed_source_transaction_rolls_back_values_retention_and_freshness(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    _upsert_steps(repository, TODAY, 4_000)
    database = tmp_path / "private" / "activities.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_steps_freshness
            BEFORE UPDATE ON wellness_source_state
            WHEN NEW.source = 'steps'
            BEGIN
                SELECT RAISE(ABORT, 'fabricated interruption');
            END
            """
        )
        connection.commit()

    with pytest.raises(WellnessDatabaseError):
        _upsert_steps(repository, TODAY, 9_999)

    assert repository.wellness_between(TODAY, TODAY)[0].steps == 4_000
    assert repository.source_freshness()[0].refreshed_at == REFRESHED_AT


def test_busy_database_fails_without_waiting_and_preserves_existing_values(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _upsert_steps(repository, TODAY, 4_000)
    database = tmp_path / "private" / "activities.sqlite3"

    with closing(sqlite3.connect(database, isolation_level=None)) as blocker:
        blocker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(WellnessDatabaseError, match="unsafe or unavailable"):
            _upsert_steps(repository, TODAY, 5_000)
        blocker.execute("ROLLBACK")

    assert repository.wellness_between(TODAY, TODAY)[0].steps == 4_000


def test_malformed_schema_one_database_is_rejected_without_migration(tmp_path: Path) -> None:
    database = tmp_path / "private" / "activities.sqlite3"
    database.parent.mkdir()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE activities (activity_id TEXT PRIMARY KEY) STRICT")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    with pytest.raises(WellnessDatabaseError, match="unsafe or unavailable"):
        WellnessRepository(database, ACCOUNT_A).set_collection_enabled(False)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert (
            connection.execute(
                "SELECT name FROM sqlite_schema WHERE name = 'wellness_daily'"
            ).fetchone()
            is None
        )


def test_malformed_stored_wellness_value_is_rejected_on_read(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _upsert_steps(repository, TODAY, 4_000)
    database = tmp_path / "private" / "activities.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE wellness_daily SET steps = -1 WHERE calendar_date = ?",
            (TODAY.isoformat(),),
        )
        connection.commit()

    with pytest.raises(WellnessDatabaseError, match="stored wellness"):
        repository.wellness_between(TODAY, TODAY)


def test_database_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"keep")
    private = ensure_private_directory(tmp_path / "private")
    database = private / "activities.sqlite3"
    database.symlink_to(target)

    with pytest.raises(WellnessDatabaseError):
        WellnessRepository(database, ACCOUNT_A).set_collection_enabled(False)

    assert target.read_bytes() == b"keep"


def test_wellness_database_and_parent_are_owner_only(tmp_path: Path) -> None:
    database = tmp_path / "private" / "activities.sqlite3"

    WellnessRepository(database, ACCOUNT_A).set_collection_enabled(True)

    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700


def test_purge_removes_wellness_rows_collection_state_and_account_scope(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = WellnessRepository(paths.activity_database, ACCOUNT_A)
    _upsert_steps(repository, TODAY, 6_000)
    repository.set_collection_enabled(False)

    AuthStore(paths).purge()
    AuthStore(paths).purge()

    assert paths.activity_database.exists() is False
    assert repository.collection_enabled() is True
    assert repository.wellness_between(TODAY, TODAY) == []


@pytest.mark.parametrize(
    ("source", "day"),
    [
        pytest.param(WellnessSource.STEPS, UserSummaryDay(TODAY, 1, 1, 50), id="wrong-type"),
        pytest.param(WellnessSource.STEPS, StepsDay(TODAY, -1), id="out-of-range"),
        pytest.param(
            WellnessSource.TRAINING_READINESS,
            TrainingReadinessDay(TODAY, 50, "unsafe\nlevel"),
            id="control-text",
        ),
        pytest.param(
            WellnessSource.HRV,
            HrvDay(TODAY, 10**400, None, None, None, None),
            id="excessive-number",
        ),
        pytest.param(
            WellnessSource.SLEEP,
            SleepDay(TODAY, 80, 1, 30_000, 30_000, 20_000, 10_000),
            id="excessive-sleep-composition",
        ),
    ],
)
def test_malformed_domain_values_are_rejected_before_persistence(
    tmp_path: Path,
    source: WellnessSource,
    day: object,
) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError):
        repository.upsert_source(
            source,
            [day],  # type: ignore[list-item]
            as_of_date=TODAY,
            refreshed_at=REFRESHED_AT,
        )

    assert (tmp_path / "private").exists() is False


@pytest.mark.parametrize(
    "fingerprint",
    [
        pytest.param("short", id="short"),
        pytest.param("A" * 64, id="uppercase"),
        pytest.param(1, id="not-text"),
    ],
)
def test_invalid_account_fingerprint_is_rejected_before_storage(
    tmp_path: Path, fingerprint: object
) -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        WellnessRepository(
            tmp_path / "private" / "activities.sqlite3",
            fingerprint,  # type: ignore[arg-type]
        )

    assert (tmp_path / "private").exists() is False


@pytest.mark.parametrize(
    ("days", "message"),
    [
        pytest.param(
            [StepsDay(TODAY, 1)] * (MAX_WELLNESS_UPSERT_DAYS + 1),
            "too many",
            id="excessive",
        ),
        pytest.param(
            [StepsDay(TODAY, 1), StepsDay(TODAY, 2)],
            "duplicate",
            id="duplicate",
        ),
        pytest.param(
            [StepsDay(TODAY - timedelta(days=30), 1)],
            "outside",
            id="outside-retention",
        ),
    ],
)
def test_invalid_source_day_sets_are_rejected_before_persistence(
    tmp_path: Path,
    days: list[StepsDay],
    message: str,
) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match=message):
        repository.upsert_source(
            WellnessSource.STEPS,
            days,
            as_of_date=TODAY,
            refreshed_at=REFRESHED_AT,
        )

    assert (tmp_path / "private").exists() is False
