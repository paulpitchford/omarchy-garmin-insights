import sqlite3
import stat
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from omarchy_garmin.activities import Activity
from omarchy_garmin.database import (
    SCHEMA_VERSION,
    ActivityDatabaseError,
    ActivityRepository,
)

_COMPLETED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _activity(
    activity_id: str,
    local_date: date,
    *,
    name: str | None = "Synthetic activity",
    type_key: str = "synthetic_sport",
) -> Activity:
    return Activity(
        activity_id=activity_id,
        name=name,
        type_key=type_key,
        started_at_local=f"{local_date.isoformat()} 08:15:00",
        local_date=local_date,
        duration_seconds=1800,
        moving_duration_seconds=None,
        distance_metres=5000,
        elevation_gain_metres=None,
        energy_joules=None,
        average_heart_rate_bpm=None,
        maximum_heart_rate_bpm=None,
        average_speed_metres_per_second=None,
        average_power_watts=None,
        total_sets=None,
        total_repetitions=None,
    )


def _rows(path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT activity_id, name, type_key, local_date FROM activities ORDER BY activity_id"
        ).fetchall()


def test_first_reconcile_creates_versioned_owner_only_database(tmp_path: Path) -> None:
    database = tmp_path / "private" / "activities.sqlite3"
    repository = ActivityRepository(database)

    result = repository.reconcile(
        [_activity("101", date(2026, 8, 25), type_key="unfamiliar_sport")],
        start_date=date(2026, 5, 29),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=True,
    )

    with closing(sqlite3.connect(database)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(activities)").fetchall()}
    assert result.stored_count == 1
    assert result.deleted_count == 0
    assert version == SCHEMA_VERSION
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
    assert "latitude" not in columns
    assert "longitude" not in columns
    assert "raw_response" not in columns
    assert _rows(database) == [("101", "Synthetic activity", "unfamiliar_sport", "2026-08-25")]
    assert repository.full_reconciliation_due(date(2026, 8, 26)) is False
    assert repository.full_reconciliation_due(date(2026, 8, 27)) is True


def test_incremental_reconcile_updates_changes_and_removes_remote_deletions(
    tmp_path: Path,
) -> None:
    database = tmp_path / "activities.sqlite3"
    repository = ActivityRepository(database)
    repository.reconcile(
        [
            _activity("101", date(2026, 8, 24), name="Old name"),
            _activity("102", date(2026, 8, 25)),
            _activity("90", date(2026, 8, 1), name="Older retained"),
        ],
        start_date=date(2026, 5, 29),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=True,
    )

    result = repository.reconcile(
        [_activity("101", date(2026, 8, 24), name="Changed name")],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=False,
    )

    assert result.stored_count == 1
    assert result.deleted_count == 1
    assert _rows(database) == [
        ("101", "Changed name", "synthetic_sport", "2026-08-24"),
        ("90", "Older retained", "synthetic_sport", "2026-08-01"),
    ]


def test_full_reconcile_removes_activities_outside_rolling_90_days(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    repository = ActivityRepository(database)
    repository.reconcile(
        [
            _activity("89", date(2026, 5, 28)),
            _activity("103", date(2026, 8, 27)),
        ],
        start_date=date(2026, 5, 1),
        end_date=date(2026, 8, 25),
        completed_at=_COMPLETED_AT,
        full=False,
    )

    result = repository.reconcile(
        [],
        start_date=date(2026, 5, 29),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=True,
    )

    assert result.deleted_count == 2
    assert _rows(database) == []


def test_activity_snapshot_is_bounded_to_requested_local_dates(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    repository = ActivityRepository(database)
    repository.reconcile(
        [
            _activity("101", date(2026, 8, 24), type_key="running"),
            _activity("102", date(2026, 8, 25), type_key="cycling"),
            _activity("103", date(2026, 8, 26), type_key="walking"),
        ],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=False,
    )

    activities = repository.activities_between(
        date(2026, 8, 25),
        date(2026, 8, 26),
        limit=1,
    )

    assert [(activity.activity_id, activity.type_key) for activity in activities] == [
        ("102", "cycling")
    ]


def test_malformed_stored_measurement_is_rejected_from_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    repository = ActivityRepository(database)
    repository.reconcile(
        [_activity("101", date(2026, 8, 25))],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=False,
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE activities SET distance_metres = -1")

    with pytest.raises(ActivityDatabaseError, match="stored activity"):
        repository.activities_between(
            date(2026, 8, 20),
            date(2026, 8, 26),
            limit=100,
        )


def test_failed_reconcile_rolls_back_all_activity_changes(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    repository = ActivityRepository(database)
    repository.reconcile(
        [_activity("101", date(2026, 8, 25), name="Original")],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=False,
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            CREATE TRIGGER reject_synthetic_insert
            BEFORE INSERT ON activities
            WHEN NEW.activity_id = '102'
            BEGIN
                SELECT RAISE(ABORT, 'fabricated failure');
            END
            """
        )

    with pytest.raises(ActivityDatabaseError):
        repository.reconcile(
            [
                _activity("101", date(2026, 8, 25), name="Changed"),
                _activity("102", date(2026, 8, 26)),
            ],
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 26),
            completed_at=_COMPLETED_AT,
            full=False,
        )

    assert _rows(database) == [("101", "Original", "synthetic_sport", "2026-08-25")]


def test_database_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"keep")
    private = tmp_path / "private"
    private.mkdir()
    database = private / "activities.sqlite3"
    database.symlink_to(target)

    with pytest.raises(ActivityDatabaseError):
        ActivityRepository(database).full_reconciliation_due(date(2026, 8, 26))

    assert target.read_bytes() == b"keep"


def test_newer_database_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(ActivityDatabaseError, match="newer"):
        ActivityRepository(database).full_reconciliation_due(date(2026, 8, 26))


def test_malformed_full_reconcile_state_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    repository = ActivityRepository(database)
    repository.reconcile(
        [],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 26),
        completed_at=_COMPLETED_AT,
        full=False,
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "INSERT INTO sync_state (key, value) VALUES ('last_full_reconcile_date', 'invalid')"
        )

    with pytest.raises(ActivityDatabaseError, match="state"):
        repository.full_reconciliation_due(date(2026, 8, 26))
