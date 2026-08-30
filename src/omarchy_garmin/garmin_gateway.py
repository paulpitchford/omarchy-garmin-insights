"""Narrow authentication adapter for the pinned python-garminconnect dependency."""

from __future__ import annotations

import signal
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from types import FrameType
from typing import Any, TypeVar, cast

from garminconnect import Garmin  # type: ignore[import-untyped]
from garminconnect.exceptions import (  # type: ignore[import-untyped]
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from omarchy_garmin.auth import (
    AuthenticatedSession,
    AuthenticationRejectedError,
    AuthNetworkError,
    AuthRateLimitedError,
    AuthRemoteServiceError,
    Credentials,
    InvalidAuthResponseError,
    validate_token_json,
)
from omarchy_garmin.sync import (
    ActivityAuthenticationRequiredError,
    ActivityDataError,
    ActivityFetch,
    ActivityNetworkError,
    ActivityRateLimitedError,
    ActivityRemoteServiceError,
)
from omarchy_garmin.wellness import (
    InvalidWellnessDataError,
    UnsupportedWellnessSourceError,
    WellnessSource,
)
from omarchy_garmin.wellness_sync import (
    WellnessAuthenticationError,
    WellnessGatewayConnection,
    WellnessInvalidDataError,
    WellnessNetworkError,
    WellnessRateLimitedError,
    WellnessRemoteServiceError,
    WellnessSyncConfigurationError,
    WellnessSyncError,
)

_SOCIAL_PROFILE_PATH = "/userprofile-service/socialProfile"
_ACCOUNT_ID_MAX_LENGTH = 64
_EMPTY_INLINE_TOKENSTORE = "{}"
_ACTIVITY_RETRY_ATTEMPTS = 1
_ACTIVITY_DEADLINE_SECONDS = 120
_WELLNESS_DEADLINE_SECONDS = 120
_WELLNESS_MAX_HTTP_ATTEMPTS = 20
_WELLNESS_RETRY_DELAY_SECONDS = 1.0
_MAX_DISPLAY_NAME_LENGTH = 100

_ResultT = TypeVar("_ResultT")


class _RequestDeadlineExpired(TimeoutError):
    """Raised when the complete Garmin refresh exceeds its deadline."""


@contextmanager
def _request_deadline(seconds: int) -> Iterator[None]:
    """Bound all requests made by one short-lived Linux backend process."""
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def expire(signum: int, frame: FrameType | None) -> None:
        raise _RequestDeadlineExpired("Garmin request deadline expired")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


class GarminAuthGateway:
    """Use only reviewed read-only authentication behavior from Garmin Connect."""

    def restore(self, token_json: bytes) -> AuthenticatedSession:
        """Verify stored tokens with Garmin and return refreshed token material."""
        try:
            token_text = token_json.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidAuthResponseError("stored Garmin tokens are not UTF-8") from error
        client = Garmin(retry_attempts=0, verify_login=True)
        return self._login(client, tokenstore=token_text)

    def authenticate(
        self,
        credentials: Credentials,
        prompt_mfa: Callable[[], str],
    ) -> AuthenticatedSession:
        """Authenticate credentials and complete MFA through a same-process callback."""
        client = Garmin(
            credentials.email,
            credentials.password,
            prompt_mfa=prompt_mfa,
            retry_attempts=0,
            verify_login=True,
        )
        # A truthy empty inline store prevents python-garminconnect from falling
        # back to GARMINTOKENS and adopting tokens outside this application.
        return self._login(client, tokenstore=_EMPTY_INLINE_TOKENSTORE)

    def _login(self, client: Any, *, tokenstore: str | None = None) -> AuthenticatedSession:
        """Map the untyped dependency boundary into validated domain data."""
        try:
            client.login(tokenstore=tokenstore)
            profile: object = client.connectapi(_SOCIAL_PROFILE_PATH)
            return self._session(client, profile)
        except GarminConnectAuthenticationError as error:
            nested_error = self._nested_dependency_error(error)
            if isinstance(nested_error, GarminConnectTooManyRequestsError):
                raise AuthRateLimitedError("Garmin authentication was rate limited") from error
            if isinstance(nested_error, GarminConnectConnectionError):
                raise self._connection_failure(nested_error) from error
            raise AuthenticationRejectedError("Garmin authentication failed") from error
        except GarminConnectTooManyRequestsError as error:
            raise AuthRateLimitedError("Garmin authentication was rate limited") from error
        except GarminConnectConnectionError as error:
            raise self._connection_failure(error) from error

    @staticmethod
    def _nested_dependency_error(error: BaseException) -> BaseException | None:
        """Find a rate-limit or connection cause hidden by the dependency wrapper."""
        seen: set[int] = set()
        current = error.__cause__ or error.__context__
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(
                current,
                GarminConnectTooManyRequestsError | GarminConnectConnectionError,
            ):
                return cast(BaseException, current)
            current = current.__cause__ or current.__context__
        return None

    @staticmethod
    def _connection_failure(error: BaseException) -> AuthNetworkError | AuthRemoteServiceError:
        """Distinguish transport failures from HTTP service failures without message parsing."""
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return AuthRemoteServiceError("Garmin Connect request failed")
        return AuthNetworkError("Garmin Connect could not be reached")

    @classmethod
    def _session(cls, client: Any, profile: object) -> AuthenticatedSession:
        """Build validated account and refreshed-token session material."""
        account_id = cls._account_id(profile)
        token_text: object = client.client.dumps()
        if not isinstance(token_text, str):
            raise InvalidAuthResponseError("Garmin returned non-text token material")
        token_json = token_text.encode("utf-8")
        try:
            validate_token_json(token_json)
        except ValueError as error:
            raise InvalidAuthResponseError("Garmin returned invalid token material") from error
        return AuthenticatedSession(account_id=account_id, token_json=token_json)

    @staticmethod
    def _account_id(profile: object) -> str:
        """Allowlist and normalize only the stable account identifier."""
        if not isinstance(profile, dict):
            raise InvalidAuthResponseError("Garmin profile response is not an object")
        raw_account_id = profile.get("profileId")
        if isinstance(raw_account_id, bool) or not isinstance(raw_account_id, int | str):
            raise InvalidAuthResponseError("Garmin profile has no stable account identifier")
        account_id = str(raw_account_id).strip()
        if not account_id or len(account_id) > _ACCOUNT_ID_MAX_LENGTH:
            raise InvalidAuthResponseError("Garmin account identifier is invalid")
        return account_id


class GarminActivityGateway:
    """Fetch only reviewed read-only activity summaries with bounded retries and time."""

    def fetch(self, token_json: bytes, start_date: date, end_date: date) -> ActivityFetch:
        """Restore tokens and call ``get_activities_by_date`` without a type filter."""
        try:
            token_text = token_json.decode("utf-8")
            validate_token_json(token_json)
        except UnicodeDecodeError as error:
            raise ActivityDataError("stored Garmin tokens are not UTF-8") from error
        except ValueError as error:
            raise ActivityDataError("stored Garmin tokens are invalid") from error

        client = Garmin(
            retry_attempts=_ACTIVITY_RETRY_ATTEMPTS,
            retry_min_wait=1,
            retry_max_wait=2,
            verify_login=True,
        )
        try:
            with _request_deadline(_ACTIVITY_DEADLINE_SECONDS):
                # Garmin.login() falls back to credential authentication when an
                # offline proactive token refresh fails, hiding the transport
                # error as "credentials required". Load the already validated
                # dedicated token material directly so the first reviewed API
                # request retains its network or authentication classification.
                client.client.loads(token_text)
                profile: object = client.connectapi(_SOCIAL_PROFILE_PATH)
                payload: object = client.get_activities_by_date(
                    start_date.isoformat(),
                    end_date.isoformat(),
                    sortorder="asc",
                )
                try:
                    session = GarminAuthGateway._session(client, profile)
                except InvalidAuthResponseError as error:
                    raise ActivityDataError("Garmin returned invalid session data") from error
                return ActivityFetch(session=session, payload=payload)
        except GarminConnectAuthenticationError as error:
            raise ActivityAuthenticationRequiredError(
                "stored Garmin tokens were rejected"
            ) from error
        except GarminConnectTooManyRequestsError as error:
            raise ActivityRateLimitedError("Garmin activity request was rate limited") from error
        except GarminConnectConnectionError as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
            if isinstance(status, int):
                raise ActivityRemoteServiceError("Garmin activity request failed") from error
            raise ActivityNetworkError("Garmin Connect could not be reached") from error
        except _RequestDeadlineExpired as error:
            raise ActivityNetworkError("Garmin activity request exceeded its deadline") from error


class _GarminWellnessConnection:
    """Expose only approved read-only wellness methods for one verified client."""

    def __init__(
        self,
        client: Any,
        account_id: str,
        *,
        sleeper: Callable[[float], None],
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._sleeper = sleeper
        self._request_attempts = 0
        self._retry_used = False

    @property
    def request_attempts(self) -> int:
        """Return all verification and data HTTP attempts in this command."""
        return self._request_attempts

    def refreshed_session(self) -> AuthenticatedSession:
        """Return validated refreshed token material without retaining profile data."""
        token_text: object = self._client.client.dumps()
        if not isinstance(token_text, str):
            raise WellnessInvalidDataError("Garmin returned invalid session data")
        token_json = token_text.encode("utf-8")
        try:
            validate_token_json(token_json)
        except ValueError as error:
            raise WellnessInvalidDataError("Garmin returned invalid session data") from error
        return AuthenticatedSession(account_id=self._account_id, token_json=token_json)

    def user_summary(self, requested_date: date) -> object:
        return self._call(
            WellnessSource.USER_SUMMARY,
            lambda: self._client.get_user_summary(requested_date.isoformat()),
        )

    def daily_steps(self, start_date: date, end_date: date) -> object:
        return self._call(
            WellnessSource.STEPS,
            lambda: self._client.get_daily_steps(start_date.isoformat(), end_date.isoformat()),
        )

    def body_battery(self, start_date: date, end_date: date) -> object:
        return self._call(
            WellnessSource.BODY_BATTERY,
            lambda: self._client.get_body_battery(start_date.isoformat(), end_date.isoformat()),
        )

    def sleep_range(self, start_date: date, end_date: date) -> object:
        return self._call(
            WellnessSource.SLEEP,
            lambda: self._client.get_sleep_daily(start_date.isoformat(), end_date.isoformat()),
        )

    def sleep_detail(self, requested_date: date) -> object:
        return self._call(
            WellnessSource.SLEEP,
            lambda: self._client.get_sleep_data(requested_date.isoformat()),
        )

    def hrv_range(self, start_date: date, end_date: date) -> object:
        return self._call(
            WellnessSource.HRV,
            lambda: self._client.get_hrv_data_range(start_date.isoformat(), end_date.isoformat()),
        )

    def hrv_detail(self, requested_date: date) -> object:
        return self._call(
            WellnessSource.HRV,
            lambda: self._client.get_hrv_data(requested_date.isoformat()),
        )

    def resting_heart_rate(self, start_date: date, end_date: date) -> object:
        return self._call(
            WellnessSource.RESTING_HEART_RATE,
            lambda: self._client.get_rhr_daily(start_date.isoformat(), end_date.isoformat()),
        )

    def training_readiness(self, requested_date: date) -> object:
        return self._call(
            WellnessSource.TRAINING_READINESS,
            lambda: self._client.get_training_readiness(requested_date.isoformat()),
        )

    def verify_profile(self) -> object:
        """Make the one fixed public account-verification request."""
        return self._call(None, lambda: self._client.connectapi(_SOCIAL_PROFILE_PATH))

    def _call(
        self,
        source: WellnessSource | None,
        operation: Callable[[], _ResultT],
    ) -> _ResultT:
        while True:
            if self._request_attempts >= _WELLNESS_MAX_HTTP_ATTEMPTS:
                raise WellnessSyncConfigurationError("wellness HTTP attempt budget exhausted")
            self._request_attempts += 1
            try:
                return operation()
            except (
                GarminConnectAuthenticationError,
                GarminConnectTooManyRequestsError,
                GarminConnectConnectionError,
            ) as error:
                if self._handle_dependency_error(error, source):
                    continue
            except _RequestDeadlineExpired as error:
                raise WellnessNetworkError(
                    "Garmin wellness request exceeded its deadline"
                ) from error
            except (AttributeError, TypeError, ValueError) as error:
                if source is None:
                    raise WellnessInvalidDataError(
                        "Garmin account verification data is invalid"
                    ) from error
                raise InvalidWellnessDataError(source) from error

    def _handle_dependency_error(
        self,
        error: BaseException,
        source: WellnessSource | None,
    ) -> bool:
        original = error
        if isinstance(error, GarminConnectAuthenticationError):
            nested = GarminAuthGateway._nested_dependency_error(error)
            if nested is None:
                raise WellnessAuthenticationError("stored Garmin tokens were rejected") from error
            error = nested
        if isinstance(error, GarminConnectTooManyRequestsError):
            raise WellnessRateLimitedError("Garmin wellness request was rate limited") from original
        if not isinstance(error, GarminConnectConnectionError):  # pragma: no cover - guarded union
            raise WellnessRemoteServiceError("Garmin wellness request failed") from original
        if self._retryable(error):
            return True
        raise self._connection_error(error, source) from original

    def _retryable(self, error: BaseException) -> bool:
        status = self._status(error)
        retryable = status is None or status >= 500
        if not retryable or self._retry_used:
            return False
        self._retry_used = True
        self._sleeper(_WELLNESS_RETRY_DELAY_SECONDS)
        return True

    @classmethod
    def _connection_error(
        cls,
        error: BaseException,
        source: WellnessSource | None,
    ) -> WellnessSyncError | UnsupportedWellnessSourceError:
        status = cls._status(error)
        if status == 404 and source is not None:
            return UnsupportedWellnessSourceError(source)
        if status in {401, 403}:
            return WellnessAuthenticationError("stored Garmin tokens were rejected")
        if status == 429:
            return WellnessRateLimitedError("Garmin wellness request was rate limited")
        if status is None:
            return WellnessNetworkError("Garmin Connect could not be reached")
        return WellnessRemoteServiceError("Garmin wellness request failed")

    @staticmethod
    def _status(error: BaseException) -> int | None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        return status if isinstance(status, int) and not isinstance(status, bool) else None


class GarminWellnessGateway:
    """Create one deadline-bound Garmin client for approved wellness requests."""

    def __init__(self, *, sleeper: Callable[[float], None] = time.sleep) -> None:
        """Initialize the explicit retry-delay boundary."""
        self._sleeper = sleeper

    @contextmanager
    def connect(self, token_json: bytes) -> Iterator[WellnessGatewayConnection]:
        """Load dedicated tokens, verify the account, and enforce one deadline."""
        try:
            token_text = token_json.decode("utf-8")
            validate_token_json(token_json)
        except UnicodeDecodeError as error:
            raise WellnessInvalidDataError("stored Garmin tokens are not UTF-8") from error
        except ValueError as error:
            raise WellnessInvalidDataError("stored Garmin tokens are invalid") from error

        client = Garmin(retry_attempts=0, verify_login=True)
        connection = _GarminWellnessConnection(
            client,
            "",
            sleeper=self._sleeper,
        )
        try:
            with _request_deadline(_WELLNESS_DEADLINE_SECONDS):
                try:
                    client.client.loads(token_text)
                except (
                    GarminConnectAuthenticationError,
                    GarminConnectConnectionError,
                    GarminConnectTooManyRequestsError,
                ) as error:
                    raise WellnessInvalidDataError(
                        "stored Garmin tokens could not be loaded"
                    ) from error
                profile = connection.verify_profile()
                try:
                    session = GarminAuthGateway._session(client, profile)
                    client.display_name = self._display_name(profile)
                except InvalidAuthResponseError as error:
                    raise WellnessInvalidDataError(
                        "Garmin account verification data is invalid"
                    ) from error
                connection._account_id = session.account_id
                yield connection
        except _RequestDeadlineExpired as error:
            raise WellnessNetworkError("Garmin wellness request exceeded its deadline") from error

    @staticmethod
    def _display_name(profile: object) -> str:
        if not isinstance(profile, dict):
            raise InvalidAuthResponseError("Garmin profile response is not an object")
        value = profile.get("displayName")
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_DISPLAY_NAME_LENGTH
            or any(character in "/?#\\" for character in value)
            or any(unicodedata.category(character).startswith("C") for character in value)
        ):
            raise InvalidAuthResponseError("Garmin profile display name is invalid")
        return value
