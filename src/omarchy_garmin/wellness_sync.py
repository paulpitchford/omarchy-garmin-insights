"""Bounded wellness refresh planning and source-isolated orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Protocol

from omarchy_garmin.auth import (
    AccountMismatchError,
    AuthenticatedSession,
    AuthStorageError,
)
from omarchy_garmin.locking import (
    RefreshInProgressError,
    RefreshLockStorageError,
    RefreshRuntimeUnavailableError,
    sync_refresh_lock,
)
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.wellness import (
    DailyWellness,
    InvalidWellnessDataError,
    UnsupportedWellnessSourceError,
    WellnessFailureClassification,
    WellnessSource,
    WellnessWriteDay,
)
from omarchy_garmin.wellness_boundaries import (
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
from omarchy_garmin.wellness_database import (
    WELLNESS_RETENTION_DAYS,
    WellnessAccountMismatchError,
    WellnessCadenceState,
    WellnessDatabaseError,
    WellnessRepository,
    WellnessUpsertResult,
)

HISTORICAL_OVERLAP_DAYS = 7
FULL_RECONCILIATION_INTERVAL_DAYS = 7
CURRENT_FAST_INTERVAL = timedelta(minutes=30)
CURRENT_SLOW_INTERVAL = timedelta(hours=4)
BACKFILL_INTERVAL = timedelta(hours=1)
SLEEP_BACKFILL_DAYS = 7
MAX_BACKFILL_DATES_PER_SOURCE = 2
MAX_SINGLE_DATE_BACKFILL_CALLS = 4
MAX_WELLNESS_DATA_CALLS = 18


class WellnessSyncError(RuntimeError):
    """Base class for stable wellness-refresh failures."""


class WellnessAuthenticationError(WellnessSyncError):
    """Raised when wellness requests cannot use stored Garmin authentication."""

    classification = WellnessFailureClassification.AUTHENTICATION


class WellnessAccountScopeError(WellnessAuthenticationError):
    """Raised when authenticated and stored wellness account scopes differ."""


class WellnessRateLimitedError(WellnessSyncError):
    """Raised when Garmin rate-limits a wellness request."""

    classification = WellnessFailureClassification.RATE_LIMIT


class WellnessNetworkError(WellnessSyncError):
    """Raised for offline transport or complete wellness deadline failures."""

    classification = WellnessFailureClassification.OFFLINE_TRANSPORT


class WellnessRemoteServiceError(WellnessSyncError):
    """Raised when a reachable Garmin wellness service fails."""

    classification = WellnessFailureClassification.REMOTE_SERVICE


class WellnessInvalidDataError(WellnessSyncError):
    """Raised when account verification or session data is malformed."""

    classification = WellnessFailureClassification.INVALID_DATA


class WellnessStorageError(WellnessSyncError):
    """Raised when private wellness state cannot be read or committed safely."""

    classification = WellnessFailureClassification.LOCAL_STORAGE


class WellnessRefreshInProgressError(WellnessSyncError):
    """Raised when another activity or wellness refresh owns the shared lock."""


class WellnessSyncConfigurationError(WellnessSyncError):
    """Raised when safe wellness refresh prerequisites are unavailable."""


class WellnessAuthStore(Protocol):
    """Authentication operations required by wellness synchronization."""

    def read_token(self) -> bytes | None:
        """Return validated dedicated Garmin tokens when configured."""
        ...

    def read_scope(self) -> str | None:
        """Return the validated pseudonymous local account scope."""
        ...

    def persist(self, session: AuthenticatedSession) -> None:
        """Persist refreshed tokens after enforcing the account scope."""
        ...


class WellnessRepositoryOperations(Protocol):
    """Private persistence and cadence operations used by one refresh."""

    def collection_enabled(self) -> bool:
        """Return whether future wellness requests are enabled."""
        ...

    def cadence_state(self) -> WellnessCadenceState:
        """Return validated private request-attempt metadata."""
        ...

    def wellness_between(self, start_date: date, end_date: date) -> list[DailyWellness]:
        """Return retained daily values used to select bounded backfill."""
        ...

    def reserve_cadence(
        self,
        *,
        today: date,
        attempted_at: datetime,
        historical: bool,
        full_reconciliation: bool,
        backfill: bool,
        current_steps: bool,
        current_body_battery: bool,
        current_sleep: bool,
        current_training_readiness: bool,
    ) -> None:
        """Record planned groups before making their first data request."""
        ...

    def upsert_source(
        self,
        source: WellnessSource,
        days: Sequence[WellnessWriteDay],
        *,
        as_of_date: date,
        refreshed_at: datetime,
    ) -> WellnessUpsertResult:
        """Commit one completely validated source operation."""
        ...


class WellnessGatewayConnection(Protocol):
    """One verified Garmin client with a command-wide retry and attempt budget."""

    @property
    def request_attempts(self) -> int:
        """Return Garmin HTTP attempts made by this connection."""
        ...

    def refreshed_session(self) -> AuthenticatedSession:
        """Return current validated account and token material."""
        ...

    def user_summary(self, requested_date: date) -> object:
        """Fetch current user summary."""
        ...

    def daily_steps(self, start_date: date, end_date: date) -> object:
        """Fetch at most one 28-day Steps range request."""
        ...

    def body_battery(self, start_date: date, end_date: date) -> object:
        """Fetch at most seven Body Battery dates."""
        ...

    def sleep_range(self, start_date: date, end_date: date) -> object:
        """Fetch at most one 28-day Sleep range request."""
        ...

    def sleep_detail(self, requested_date: date) -> object:
        """Fetch one detailed Sleep date."""
        ...

    def hrv_range(self, start_date: date, end_date: date) -> object:
        """Fetch one HRV range."""
        ...

    def hrv_detail(self, requested_date: date) -> object:
        """Fetch one current HRV date."""
        ...

    def resting_heart_rate(self, start_date: date, end_date: date) -> object:
        """Fetch one resting-heart-rate range."""
        ...

    def training_readiness(self, requested_date: date) -> object:
        """Fetch one Training Readiness date."""
        ...


class WellnessGateway(Protocol):
    """Open one bounded, verified external Garmin wellness connection."""

    def connect(self, token_json: bytes) -> AbstractContextManager[WellnessGatewayConnection]:
        """Verify the account and bound all calls by one command deadline."""
        ...


@dataclass(frozen=True, slots=True)
class WellnessRefreshPlan:
    """Deterministic bounded request plan reserved before data calls begin."""

    historical_start: date | None
    full_reconciliation: bool
    current_steps: bool
    current_body_battery: bool
    current_sleep: bool
    current_training_readiness: bool
    backfill: bool
    sleep_dates: tuple[date, ...]
    training_readiness_dates: tuple[date, ...]

    @property
    def historical(self) -> bool:
        """Return whether range-capable sources are planned."""
        return self.historical_start is not None

    @property
    def has_requests(self) -> bool:
        """Return whether the plan contains at least one Garmin data call."""
        return any(
            (
                self.historical,
                self.current_steps,
                self.current_body_battery and not self.historical,
                bool(self.sleep_dates),
                bool(self.training_readiness_dates),
            )
        )

    def data_call_count(self, today: date) -> int:
        """Return the exact maximum data calls represented by this plan."""
        calls = len(self.sleep_dates) + len(self.training_readiness_dates)
        if self.current_steps:
            calls += 1
        if self.current_body_battery and not self.historical:
            calls += 1
        if self.historical_start is not None:
            days = (today - self.historical_start).days + 1
            calls += _chunk_count(days, 28)  # Steps
            calls += _chunk_count(days, 7)  # Body Battery
            calls += _chunk_count(days, 28)  # Sleep range
            calls += 3  # HRV range, HRV detail, and resting heart rate
        return calls


@dataclass(frozen=True, slots=True)
class WellnessSourceRefreshResult:
    """Bounded source-specific result without remote values or exception text."""

    source: WellnessSource
    attempted: bool
    refreshed: bool
    stored_count: int
    failure: WellnessFailureClassification | None


@dataclass(frozen=True, slots=True)
class WellnessRefreshResult:
    """Bounded result of one composed wellness refresh command."""

    collection_enabled: bool
    full_reconciliation: bool
    request_attempts: int
    sources: tuple[WellnessSourceRefreshResult, ...]


@dataclass(slots=True)
class _SourceAccumulator:
    attempted: bool = False
    refreshed: bool = False
    stored_count: int = 0
    failure: WellnessFailureClassification | None = None


RepositoryFactory = Callable[[str], WellnessRepositoryOperations]


def _chunk_count(days: int, size: int) -> int:
    return (days + size - 1) // size


def _date_chunks(start_date: date, end_date: date, size: int) -> tuple[tuple[date, date], ...]:
    result: list[tuple[date, date]] = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=size - 1), end_date)
        result.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return tuple(result)


def _due(last_attempt: datetime | None, now: datetime, interval: timedelta) -> bool:
    return last_attempt is None or now >= last_attempt + interval


def _missing_sleep_detail(day: DailyWellness | None) -> bool:
    return day is None or all(
        value is None
        for value in (
            day.sleep_total_seconds,
            day.sleep_deep_seconds,
            day.sleep_light_seconds,
            day.sleep_rem_seconds,
            day.sleep_awake_seconds,
        )
    )


def _missing_training_readiness(day: DailyWellness | None) -> bool:
    return day is None or (
        day.training_readiness_score is None and day.training_readiness_level is None
    )


def _bounded_targets(
    *,
    today: date,
    current_due: bool,
    backfill_due: bool,
    oldest_date: date,
    stored: dict[date, DailyWellness],
    missing: Callable[[DailyWellness | None], bool],
) -> tuple[tuple[date, ...], bool]:
    targets: list[date] = [today] if current_due else []
    backfill_selected = False
    if backfill_due:
        candidate = today - timedelta(days=1)
        while candidate >= oldest_date and len(targets) < MAX_BACKFILL_DATES_PER_SOURCE:
            if missing(stored.get(candidate)):
                targets.append(candidate)
                backfill_selected = True
            candidate -= timedelta(days=1)
    return tuple(targets), backfill_selected


def build_refresh_plan(
    *,
    today: date,
    now: datetime,
    manual: bool,
    cadence: WellnessCadenceState,
    stored_days: Sequence[DailyWellness],
) -> WellnessRefreshPlan:
    """Build a deterministic plan from private cadence and retained local values."""
    if type(today) is not date or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("wellness refresh clocks are invalid")
    historical = cadence.historical_date != today
    full = historical and (
        cadence.full_reconciliation_date is None
        or (today - cadence.full_reconciliation_date).days >= FULL_RECONCILIATION_INTERVAL_DAYS
    )
    historical_days = WELLNESS_RETENTION_DAYS if full else HISTORICAL_OVERLAP_DAYS
    historical_start = today - timedelta(days=historical_days - 1) if historical else None
    current_steps = manual or _due(cadence.current_steps_at, now, CURRENT_FAST_INTERVAL)
    current_body_battery = manual or _due(
        cadence.current_body_battery_at, now, CURRENT_FAST_INTERVAL
    )
    current_sleep = manual or _due(cadence.current_sleep_at, now, CURRENT_SLOW_INTERVAL)
    current_readiness = manual or _due(
        cadence.current_training_readiness_at, now, CURRENT_SLOW_INTERVAL
    )
    backfill_due = _due(cadence.backfill_at, now, BACKFILL_INTERVAL)
    stored = {day.calendar_date: day for day in stored_days}
    sleep_dates, sleep_backfill = _bounded_targets(
        today=today,
        current_due=current_sleep,
        backfill_due=backfill_due,
        oldest_date=today - timedelta(days=SLEEP_BACKFILL_DAYS - 1),
        stored=stored,
        missing=_missing_sleep_detail,
    )
    readiness_dates, readiness_backfill = _bounded_targets(
        today=today,
        current_due=current_readiness,
        backfill_due=backfill_due,
        oldest_date=today - timedelta(days=WELLNESS_RETENTION_DAYS - 1),
        stored=stored,
        missing=_missing_training_readiness,
    )
    if len(sleep_dates) + len(readiness_dates) > MAX_SINGLE_DATE_BACKFILL_CALLS:
        raise WellnessSyncConfigurationError("wellness single-date request plan is excessive")
    plan = WellnessRefreshPlan(
        historical_start=historical_start,
        full_reconciliation=full,
        current_steps=current_steps,
        current_body_battery=current_body_battery,
        current_sleep=current_sleep,
        current_training_readiness=current_readiness,
        backfill=sleep_backfill or readiness_backfill,
        sleep_dates=sleep_dates,
        training_readiness_dates=readiness_dates,
    )
    if plan.data_call_count(today) > MAX_WELLNESS_DATA_CALLS:
        raise WellnessSyncConfigurationError("wellness data request plan is excessive")
    return plan


class WellnessSyncService:
    """Coordinate one account-scoped wellness command under the shared refresh lock."""

    def __init__(
        self,
        *,
        paths: AppPaths,
        auth_store: WellnessAuthStore,
        gateway: WellnessGateway,
        repository_factory: RepositoryFactory | None = None,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Initialize explicit filesystem, Garmin, persistence, and clock boundaries."""
        self._paths = paths
        self._auth_store = auth_store
        self._gateway = gateway
        self._repository_factory = repository_factory or self._default_repository
        self._today = today
        self._now = now

    def _default_repository(self, account_fingerprint: str) -> WellnessRepository:
        return WellnessRepository(self._paths.activity_database, account_fingerprint)

    def refresh(self, *, manual: bool = False) -> WellnessRefreshResult:
        """Run one bounded refresh while preserving independent source successes."""
        try:
            with sync_refresh_lock(self._paths.sync_lock_file):
                return self._refresh_locked(manual=manual)
        except RefreshInProgressError as error:
            raise WellnessRefreshInProgressError("a Garmin refresh is already running") from error
        except RefreshRuntimeUnavailableError as error:
            raise WellnessSyncConfigurationError("XDG runtime storage is required") from error
        except RefreshLockStorageError as error:
            raise WellnessStorageError("wellness refresh lock is unavailable") from error

    def _refresh_locked(self, *, manual: bool) -> WellnessRefreshResult:
        try:
            token_json = self._auth_store.read_token()
            account_fingerprint = self._auth_store.read_scope()
        except AuthStorageError as error:
            raise WellnessStorageError("wellness authentication state is unavailable") from error
        if token_json is None:
            raise WellnessAuthenticationError("Garmin authentication is required")
        if account_fingerprint is None:
            raise WellnessStorageError("wellness account scope is unavailable")

        try:
            repository = self._repository_factory(account_fingerprint)
            if not repository.collection_enabled():
                return self._result(False, False, 0, {})
            today = self._today()
            now = self._now()
            retention_start = today - timedelta(days=WELLNESS_RETENTION_DAYS - 1)
            plan = build_refresh_plan(
                today=today,
                now=now,
                manual=manual,
                cadence=repository.cadence_state(),
                stored_days=repository.wellness_between(retention_start, today),
            )
        except WellnessAccountMismatchError as error:
            raise WellnessAccountScopeError("wellness data belongs to another account") from error
        except WellnessDatabaseError as error:
            raise WellnessStorageError("wellness refresh state is unavailable") from error
        if not plan.has_requests:
            return self._result(True, plan.full_reconciliation, 0, {})

        accumulators: dict[WellnessSource, _SourceAccumulator] = {}
        request_attempts = 0
        with self._gateway.connect(token_json) as connection:
            self._persist_verified_session(connection.refreshed_session())
            try:
                repository.reserve_cadence(
                    today=today,
                    attempted_at=now,
                    historical=plan.historical,
                    full_reconciliation=plan.full_reconciliation,
                    backfill=plan.backfill,
                    current_steps=plan.current_steps,
                    current_body_battery=plan.current_body_battery,
                    current_sleep=plan.current_sleep,
                    current_training_readiness=plan.current_training_readiness,
                )
            except WellnessAccountMismatchError as error:
                raise WellnessAccountScopeError(
                    "wellness data belongs to another account"
                ) from error
            except WellnessDatabaseError as error:
                raise WellnessStorageError("wellness cadence could not be reserved") from error

            aborted = self._run_plan(
                connection=connection,
                repository=repository,
                plan=plan,
                today=today,
                refreshed_at=now,
                accumulators=accumulators,
            )
            request_attempts = connection.request_attempts
            if not aborted:
                self._persist_verified_session(connection.refreshed_session())

        return self._result(
            True,
            plan.full_reconciliation,
            request_attempts,
            accumulators,
        )

    def _persist_verified_session(self, session: AuthenticatedSession) -> None:
        try:
            self._auth_store.persist(session)
        except AccountMismatchError as error:
            raise WellnessAccountScopeError("authenticated Garmin account changed") from error
        except AuthStorageError as error:
            raise WellnessStorageError("refreshed Garmin session could not be stored") from error

    def _run_plan(
        self,
        *,
        connection: WellnessGatewayConnection,
        repository: WellnessRepositoryOperations,
        plan: WellnessRefreshPlan,
        today: date,
        refreshed_at: datetime,
        accumulators: dict[WellnessSource, _SourceAccumulator],
    ) -> bool:
        if plan.historical_start is not None:
            start = plan.historical_start
            operations: tuple[
                tuple[WellnessSource, Callable[[], Sequence[WellnessWriteDay]]], ...
            ] = (
                (
                    WellnessSource.STEPS,
                    lambda: self._load_steps(connection, start, today),
                ),
                (
                    WellnessSource.BODY_BATTERY,
                    lambda: self._load_body_battery(connection, start, today),
                ),
                (
                    WellnessSource.SLEEP,
                    lambda: self._load_sleep_range(connection, start, today),
                ),
                (
                    WellnessSource.HRV,
                    lambda: parse_hrv_range(connection.hrv_range(start, today), start, today),
                ),
                (
                    WellnessSource.RESTING_HEART_RATE,
                    lambda: parse_resting_heart_rate(
                        connection.resting_heart_rate(start, today), start, today
                    ),
                ),
                (
                    WellnessSource.HRV,
                    lambda: self._optional_day(
                        parse_hrv_detail(connection.hrv_detail(today), today)
                    ),
                ),
            )
            for source, loader in operations:
                if self._run_source(
                    source,
                    loader,
                    repository,
                    today,
                    refreshed_at,
                    accumulators,
                ):
                    return True

        if plan.current_steps and self._run_source(
            WellnessSource.USER_SUMMARY,
            lambda: self._optional_day(parse_user_summary(connection.user_summary(today), today)),
            repository,
            today,
            refreshed_at,
            accumulators,
        ):
            return True

        if (
            plan.current_body_battery
            and not plan.historical
            and self._run_source(
                WellnessSource.BODY_BATTERY,
                lambda: parse_body_battery(connection.body_battery(today, today), today, today),
                repository,
                today,
                refreshed_at,
                accumulators,
            )
        ):
            return True

        for requested_date in plan.sleep_dates:
            if self._run_source(
                WellnessSource.SLEEP,
                partial(self._load_sleep_detail, connection, requested_date),
                repository,
                today,
                refreshed_at,
                accumulators,
            ):
                return True

        for requested_date in plan.training_readiness_dates:
            if self._run_source(
                WellnessSource.TRAINING_READINESS,
                partial(self._load_training_readiness, connection, requested_date),
                repository,
                today,
                refreshed_at,
                accumulators,
            ):
                return True
        return False

    @classmethod
    def _load_sleep_detail(
        cls,
        connection: WellnessGatewayConnection,
        requested_date: date,
    ) -> tuple[WellnessWriteDay, ...]:
        return cls._optional_day(
            parse_sleep_detail(connection.sleep_detail(requested_date), requested_date)
        )

    @classmethod
    def _load_training_readiness(
        cls,
        connection: WellnessGatewayConnection,
        requested_date: date,
    ) -> tuple[WellnessWriteDay, ...]:
        return cls._optional_day(
            parse_training_readiness(connection.training_readiness(requested_date), requested_date)
        )

    @staticmethod
    def _optional_day(day: WellnessWriteDay | None) -> tuple[WellnessWriteDay, ...]:
        return () if day is None else (day,)

    @staticmethod
    def _load_steps(
        connection: WellnessGatewayConnection,
        start_date: date,
        end_date: date,
    ) -> tuple[WellnessWriteDay, ...]:
        result: list[WellnessWriteDay] = []
        for chunk_start, chunk_end in _date_chunks(start_date, end_date, 28):
            result.extend(
                parse_daily_steps(
                    connection.daily_steps(chunk_start, chunk_end), chunk_start, chunk_end
                )
            )
        return tuple(result)

    @staticmethod
    def _load_body_battery(
        connection: WellnessGatewayConnection,
        start_date: date,
        end_date: date,
    ) -> tuple[WellnessWriteDay, ...]:
        result: list[WellnessWriteDay] = []
        for chunk_start, chunk_end in _date_chunks(start_date, end_date, 7):
            result.extend(
                parse_body_battery(
                    connection.body_battery(chunk_start, chunk_end), chunk_start, chunk_end
                )
            )
        return tuple(result)

    @staticmethod
    def _load_sleep_range(
        connection: WellnessGatewayConnection,
        start_date: date,
        end_date: date,
    ) -> tuple[WellnessWriteDay, ...]:
        result: list[WellnessWriteDay] = []
        for chunk_start, chunk_end in _date_chunks(start_date, end_date, 28):
            result.extend(
                parse_sleep_range(
                    connection.sleep_range(chunk_start, chunk_end), chunk_start, chunk_end
                )
            )
        return tuple(result)

    @staticmethod
    def _run_source(
        source: WellnessSource,
        loader: Callable[[], Sequence[WellnessWriteDay]],
        repository: WellnessRepositoryOperations,
        today: date,
        refreshed_at: datetime,
        accumulators: dict[WellnessSource, _SourceAccumulator],
    ) -> bool:
        accumulator = accumulators.setdefault(source, _SourceAccumulator())
        accumulator.attempted = True
        try:
            days = loader()
            result = repository.upsert_source(
                source,
                days,
                as_of_date=today,
                refreshed_at=refreshed_at,
            )
        except UnsupportedWellnessSourceError:
            accumulator.failure = WellnessFailureClassification.UNSUPPORTED
        except InvalidWellnessDataError:
            accumulator.failure = WellnessFailureClassification.INVALID_DATA
        except WellnessAuthenticationError:
            accumulator.failure = WellnessFailureClassification.AUTHENTICATION
            return True
        except WellnessRateLimitedError:
            accumulator.failure = WellnessFailureClassification.RATE_LIMIT
            return True
        except WellnessNetworkError:
            accumulator.failure = WellnessFailureClassification.OFFLINE_TRANSPORT
        except WellnessRemoteServiceError:
            accumulator.failure = WellnessFailureClassification.REMOTE_SERVICE
        except WellnessDatabaseError:
            accumulator.failure = WellnessFailureClassification.LOCAL_STORAGE
        else:
            accumulator.refreshed = True
            accumulator.stored_count += result.stored_count
        return False

    @staticmethod
    def _result(
        collection_enabled: bool,
        full_reconciliation: bool,
        request_attempts: int,
        accumulators: dict[WellnessSource, _SourceAccumulator],
    ) -> WellnessRefreshResult:
        sources = tuple(
            WellnessSourceRefreshResult(
                source=source,
                attempted=(accumulator := accumulators.get(source, _SourceAccumulator())).attempted,
                refreshed=accumulator.refreshed,
                stored_count=accumulator.stored_count,
                failure=accumulator.failure,
            )
            for source in WellnessSource
        )
        return WellnessRefreshResult(
            collection_enabled=collection_enabled,
            full_reconciliation=full_reconciliation,
            request_attempts=request_attempts,
            sources=sources,
        )
