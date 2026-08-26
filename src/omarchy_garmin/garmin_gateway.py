"""Narrow authentication adapter for the pinned python-garminconnect dependency."""

from __future__ import annotations

from collections.abc import Callable
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

_SOCIAL_PROFILE_PATH = "/userprofile-service/socialProfile"
_ACCOUNT_ID_MAX_LENGTH = 64
_EMPTY_INLINE_TOKENSTORE = "{}"


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
            account_id = self._account_id(profile)
            token_text: object = client.client.dumps()
            if not isinstance(token_text, str):
                raise InvalidAuthResponseError("Garmin returned non-text token material")
            token_json = token_text.encode("utf-8")
            try:
                validate_token_json(token_json)
            except ValueError as error:
                raise InvalidAuthResponseError("Garmin returned invalid token material") from error
            return AuthenticatedSession(account_id=account_id, token_json=token_json)
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
