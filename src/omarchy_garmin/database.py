"""Versioned private SQLite storage for normalized Garmin activities."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from omarchy_garmin.activities import Activity
from omarchy_garmin.storage import (
    PRIVATE_FILE_MODE,
    UnsafeStoragePathError,
    ensure_private_directory,
    private_file_exists,
)

SCHEMA_VERSION = 1


class ActivityDatabaseError(RuntimeError):
    """Raised when the activity database cannot be used safely."""


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Observable result of one transactional reconciliation."""

    stored_count: int
    deleted_count: int


_MIGRATION_1 = """
CREATE TABLE activities (
    activity_id TEXT PRIMARY KEY NOT NULL,
    name TEXT,
    type_key TEXT NOT NULL,
    started_at_local TEXT NOT NULL,
    local_date TEXT NOT NULL,
    duration_seconds REAL,
    moving_duration_seconds REAL,
    distance_metres REAL,
    elevation_gain_metres REAL,
    energy_joules REAL,
    average_heart_rate_bpm REAL,
    maximum_heart_rate_bpm REAL,
    average_speed_metres_per_second REAL,
    average_power_watts REAL,
    total_sets INTEGER,
    total_repetitions INTEGER,
    synced_at TEXT NOT NULL,
    CHECK (length(activity_id) BETWEEN 1 AND 19),
    CHECK (length(type_key) BETWEEN 1 AND 100),
    CHECK (name IS NULL OR length(name) BETWEEN 1 AND 256),
    CHECK (length(started_at_local) BETWEEN 19 AND 40),
    CHECK (length(local_date) = 10)
) STRICT;
CREATE INDEX activities_local_date_idx ON activities(local_date);
CREATE TABLE sync_state (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
) STRICT;
"""
_MIGRATIONS = {1: _MIGRATION_1}

_UPSERT_ACTIVITY = """
INSERT INTO activities (
    activity_id,
    name,
    type_key,
    started_at_local,
    local_date,
    duration_seconds,
    moving_duration_seconds,
    distance_metres,
    elevation_gain_metres,
    energy_joules,
    average_heart_rate_bpm,
    maximum_heart_rate_bpm,
    average_speed_metres_per_second,
    average_power_watts,
    total_sets,
    total_repetitions,
    synced_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(activity_id) DO UPDATE SET
    name = excluded.name,
    type_key = excluded.type_key,
    started_at_local = excluded.started_at_local,
    local_date = excluded.local_date,
    duration_seconds = excluded.duration_seconds,
    moving_duration_seconds = excluded.moving_duration_seconds,
    distance_metres = excluded.distance_metres,
    elevation_gain_metres = excluded.elevation_gain_metres,
    energy_joules = excluded.energy_joules,
    average_heart_rate_bpm = excluded.average_heart_rate_bpm,
    maximum_heart_rate_bpm = excluded.maximum_heart_rate_bpm,
    average_speed_metres_per_second = excluded.average_speed_metres_per_second,
    average_power_watts = excluded.average_power_watts,
    total_sets = excluded.total_sets,
    total_repetitions = excluded.total_repetitions,
    synced_at = excluded.synced_at
"""


class ActivityRepository:
    """Own schema migration and transactional activity reconciliation."""

    def __init__(self, database_path: Path) -> None:
        """Initialize the repository with an absolute private database path."""
        self._database_path = database_path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self._prepare_database_file()
            connection = sqlite3.connect(self._database_path, timeout=0, isolation_level=None)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA journal_mode = DELETE")
            self._migrate(connection)
            yield connection
        except (OSError, sqlite3.Error, UnsafeStoragePathError) as error:
            raise ActivityDatabaseError("activity database is unsafe or unavailable") from error
        finally:
            if connection is not None:
                connection.close()

    def _prepare_database_file(self) -> None:
        ensure_private_directory(self._database_path.parent)
        if private_file_exists(self._database_path):
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(self._database_path, flags, PRIVATE_FILE_MODE)
        except FileExistsError:
            if not private_file_exists(self._database_path):  # pragma: no cover - race guard
                raise
            return
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise UnsafeStoragePathError("activity database file is unsafe")
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        finally:
            os.close(descriptor)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise ActivityDatabaseError("activity database schema is newer than this backend")
        if current_version == SCHEMA_VERSION:
            return

        migration_sql = "\n".join(
            _MIGRATIONS[version] for version in range(current_version + 1, SCHEMA_VERSION + 1)
        )
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{migration_sql}\n"
                f"PRAGMA user_version = {SCHEMA_VERSION};\n"
                "COMMIT;"
            )
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")

    def full_reconciliation_due(self, today: date) -> bool:
        """Return whether no successful full reconciliation exists for today."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM sync_state WHERE key = 'last_full_reconcile_date'"
            ).fetchone()
        if row is None:
            return True
        try:
            return date.fromisoformat(str(row[0])) != today
        except ValueError as error:
            raise ActivityDatabaseError("full reconciliation state is invalid") from error

    def reconcile(
        self,
        activities: Sequence[Activity],
        *,
        start_date: date,
        end_date: date,
        completed_at: datetime,
        full: bool,
    ) -> ReconcileResult:
        """Upsert and reconcile one fetched period in a single transaction."""
        synced_at = completed_at.isoformat(timespec="seconds")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TEMP TABLE incoming_activity_ids (activity_id TEXT PRIMARY KEY) STRICT"
                )
                connection.executemany(
                    "INSERT INTO incoming_activity_ids (activity_id) VALUES (?)",
                    ((activity.activity_id,) for activity in activities),
                )
                connection.executemany(
                    _UPSERT_ACTIVITY,
                    (self._activity_row(activity, synced_at) for activity in activities),
                )
                deleted = connection.execute(
                    """
                    DELETE FROM activities
                    WHERE local_date BETWEEN ? AND ?
                      AND NOT EXISTS (
                          SELECT 1 FROM incoming_activity_ids incoming
                          WHERE incoming.activity_id = activities.activity_id
                      )
                    """,
                    (start_date.isoformat(), end_date.isoformat()),
                ).rowcount
                if full:
                    deleted += connection.execute(
                        "DELETE FROM activities WHERE local_date < ? OR local_date > ?",
                        (start_date.isoformat(), end_date.isoformat()),
                    ).rowcount
                    connection.execute(
                        """
                        INSERT INTO sync_state (key, value)
                        VALUES ('last_full_reconcile_date', ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """,
                        (end_date.isoformat(),),
                    )
                connection.execute(
                    """
                    INSERT INTO sync_state (key, value)
                    VALUES ('last_successful_refresh_at', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (synced_at,),
                )
                connection.execute("COMMIT")
            finally:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
        return ReconcileResult(stored_count=len(activities), deleted_count=deleted)

    @staticmethod
    def _activity_row(activity: Activity, synced_at: str) -> tuple[object, ...]:
        return (
            activity.activity_id,
            activity.name,
            activity.type_key,
            activity.started_at_local,
            activity.local_date.isoformat(),
            activity.duration_seconds,
            activity.moving_duration_seconds,
            activity.distance_metres,
            activity.elevation_gain_metres,
            activity.energy_joules,
            activity.average_heart_rate_bpm,
            activity.maximum_heart_rate_bpm,
            activity.average_speed_metres_per_second,
            activity.average_power_watts,
            activity.total_sets,
            activity.total_repetitions,
            synced_at,
        )
