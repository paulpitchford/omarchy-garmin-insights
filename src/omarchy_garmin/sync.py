"""Activity refresh orchestration across Garmin, validation, locking, and SQLite."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from omarchy_garmin.activities import Activity, InvalidActivityDataError, normalize_activities
from omarchy_garmin.auth import AuthenticatedSession, AuthStore
from omarchy_garmin.database import ActivityDatabaseError, ReconcileResult
from omarchy_garmin.locking import (
    RefreshInProgressError,
    RefreshLockStorageError,
    RefreshRuntimeUnavailableError,
    activity_refresh_lock,
)
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.summary import (
    MAX_SUMMARY_ACTIVITIES,
    SummaryDataError,
    SummaryStorageError,
)
from omarchy_garmin.trends import ActivityTrendsDataError, ActivityTrendsStorageError

INCREMENTAL_DAYS = 7
FULL_RECONCILIATION_DAYS = 90


class ActivitySyncError(RuntimeError):
    """Base class for safe activity-sync domain failures."""


class ActivityAuthenticationRequiredError(ActivitySyncError):
    """Raised when stored Garmin authentication is absent or rejected."""


class ActivityRateLimitedError(ActivitySyncError):
    """Raised when Garmin rate-limits an activity refresh."""


class ActivityNetworkError(ActivitySyncError):
    """Raised when Garmin cannot be reached before the refresh deadline."""


class ActivityRemoteServiceError(ActivitySyncError):
    """Raised when a reachable Garmin service rejects an activity request."""


class ActivityStorageError(ActivitySyncError):
    """Raised when normalized activities cannot be stored safely."""


class ActivityDataError(ActivitySyncError):
    """Raised when Garmin returns malformed or excessive activity data."""


class ActivityRefreshInProgressError(ActivitySyncError):
    """Raised when another process already owns the refresh lock."""


class ActivitySyncConfigurationError(ActivitySyncError):
    """Raised when safe refresh prerequisites are unavailable."""


@dataclass(frozen=True, slots=True)
class ActivityFetch:
    """Untrusted Garmin activities plus verified refreshed session material."""

    session: AuthenticatedSession
    payload: object


class ActivityRepositoryOperations(Protocol):
    """Persistence operations required by activity synchronization."""

    def full_reconciliation_due(self, today: date) -> bool:
        """Return whether a full reconciliation is due."""
        ...

    def reconcile(
        self,
        activities: Sequence[Activity],
        *,
        start_date: date,
        end_date: date,
        completed_at: datetime,
        full: bool,
    ) -> ReconcileResult:
        """Persist a validated fetched period transactionally."""
        ...

    def activities_between(
        self,
        start_date: date,
        end_date: date,
        *,
        limit: int,
    ) -> list[Activity]:
        """Return a bounded activity snapshot for summary generation."""
        ...


class DisplayCacheOperations(Protocol):
    """One bounded display-cache operation run after reconciliation."""

    def write(
        self,
        activities: Sequence[Activity],
        *,
        as_of_date: date,
        generated_at: datetime,
    ) -> None:
        """Atomically replace a display cache from a complete snapshot."""
        ...


class ActivityGateway(Protocol):
    """Fetch activity summaries through the external Garmin boundary."""

    def fetch(self, token_json: bytes, start_date: date, end_date: date) -> ActivityFetch:
        """Restore a session and fetch all activity types for an inclusive period."""
        ...


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Bounded public result of one successful activity refresh."""

    mode: str
    start_date: date
    end_date: date
    fetched_count: int
    deleted_count: int
    trends_updated: bool


class RefreshOperations(Protocol):
    """Activity refresh operation consumed by the CLI."""

    def refresh(self, *, force_full: bool = False) -> RefreshResult:
        """Refresh and reconcile recent activity data."""
        ...


class ActivitySyncService:
    """Coordinate one non-overlapping, account-scoped activity refresh."""

    def __init__(
        self,
        *,
        paths: AppPaths,
        auth_store: AuthStore,
        gateway: ActivityGateway,
        repository: ActivityRepositoryOperations,
        summary: DisplayCacheOperations,
        trends: DisplayCacheOperations,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Initialize explicit filesystem, Garmin, repository, and clock boundaries."""
        self._paths = paths
        self._auth_store = auth_store
        self._gateway = gateway
        self._repository = repository
        self._summary = summary
        self._trends = trends
        self._today = today
        self._now = now

    def refresh(self, *, force_full: bool = False) -> RefreshResult:
        """Run an incremental refresh or the daily full 90-day reconciliation."""
        try:
            with activity_refresh_lock(self._paths.sync_lock_file):
                return self._refresh_locked(force_full=force_full)
        except RefreshInProgressError as error:
            raise ActivityRefreshInProgressError("activity refresh is already running") from error
        except RefreshRuntimeUnavailableError as error:
            raise ActivitySyncConfigurationError("XDG runtime storage is required") from error
        except RefreshLockStorageError as error:
            raise ActivityStorageError("activity refresh lock is unavailable") from error

    def _refresh_locked(self, *, force_full: bool) -> RefreshResult:
        token_json = self._auth_store.read_token()
        if token_json is None:
            raise ActivityAuthenticationRequiredError("Garmin authentication is required")

        today = self._today()
        try:
            full = force_full or self._repository.full_reconciliation_due(today)
        except ActivityDatabaseError as error:
            raise ActivityStorageError("activity reconciliation state is unavailable") from error
        days = FULL_RECONCILIATION_DAYS if full else INCREMENTAL_DAYS
        start_date = today - timedelta(days=days - 1)

        fetched = self._gateway.fetch(token_json, start_date, today)
        try:
            activities = normalize_activities(fetched.payload, start_date, today)
        except InvalidActivityDataError as error:
            raise ActivityDataError("Garmin returned invalid activity data") from error

        # Persisting the verified session first enforces the account scope before
        # any fetched activity can reach SQLite.
        self._auth_store.persist(fetched.session)
        completed_at = self._now()
        try:
            result = self._repository.reconcile(
                activities,
                start_date=start_date,
                end_date=today,
                completed_at=completed_at,
                full=full,
            )
            rolling_start = today - timedelta(days=FULL_RECONCILIATION_DAYS - 1)
            snapshot = self._repository.activities_between(
                rolling_start,
                today,
                limit=MAX_SUMMARY_ACTIVITIES + 1,
            )
        except ActivityDatabaseError as error:
            raise ActivityStorageError("activity reconciliation failed") from error
        try:
            self._summary.write(
                snapshot,
                as_of_date=today,
                generated_at=completed_at,
            )
        except SummaryDataError as error:
            raise ActivityDataError("activity summary data is invalid") from error
        except SummaryStorageError as error:
            raise ActivityStorageError("activity summary cache could not be written") from error

        trends_updated = True
        try:
            self._trends.write(
                snapshot,
                as_of_date=today,
                generated_at=completed_at,
            )
        except (ActivityTrendsDataError, ActivityTrendsStorageError):
            # Trends are an optional presentation cache. The returned flag makes
            # degraded generation observable while the valid primary summary and
            # any previous matching trend cache remain available.
            trends_updated = False
        return RefreshResult(
            mode="full" if full else "incremental",
            start_date=start_date,
            end_date=today,
            fetched_count=result.stored_count,
            deleted_count=result.deleted_count,
            trends_updated=trends_updated,
        )
