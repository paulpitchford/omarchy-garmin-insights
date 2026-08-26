"""Narrow authentication adapter for the pinned python-garminconnect dependency."""

from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from types import FrameType
from typing import Any, cast

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

_SOCIAL_PROFILE_PATH = "/userprofile-service/socialProfile"
_ACCOUNT_ID_MAX_LENGTH = 64
_EMPTY_INLINE_TOKENSTORE = "{}"
_ACTIVITY_RETRY_ATTEMPTS = 1
_ACTIVITY_DEADLINE_SECONDS = 120


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
        except UnicodeDecodeError as error:
            raise ActivityDataError("stored Garmin tokens are not UTF-8") from error

        client = Garmin(
            retry_attempts=_ACTIVITY_RETRY_ATTEMPTS,
            retry_min_wait=1,
            retry_max_wait=2,
            verify_login=True,
        )
        try:
            with _request_deadline(_ACTIVITY_DEADLINE_SECONDS):
                client.login(tokenstore=token_text)
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
