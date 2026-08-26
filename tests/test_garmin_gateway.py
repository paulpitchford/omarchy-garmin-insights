import json
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec, patch

import pytest
from garminconnect.client import Client  # type: ignore[import-untyped]
from garminconnect.exceptions import (  # type: ignore[import-untyped]
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from omarchy_garmin.auth import (
    AuthenticationRejectedError,
    AuthNetworkError,
    AuthRateLimitedError,
    AuthRemoteServiceError,
    Credentials,
    InvalidAuthResponseError,
)
from omarchy_garmin.garmin_gateway import GarminAuthGateway


def _token() -> str:
    return json.dumps(
        {
            "di_token": "synthetic-access",
            "di_refresh_token": "synthetic-refresh",
            "di_client_id": "synthetic-client",
        }
    )


@pytest.fixture
def garmin_constructor() -> Iterator[Mock]:
    with patch("omarchy_garmin.garmin_gateway.Garmin", autospec=True) as constructor:
        garmin = constructor.return_value
        token_client = create_autospec(Client, instance=True)
        token_client.dumps.return_value = _token()
        garmin.client = token_client
        garmin.connectapi.return_value = {"profileId": 10101, "email": "ignored@example.test"}
        yield constructor


def test_authenticate_uses_hidden_mfa_callback_and_ignores_external_token_environment(
    garmin_constructor: Mock,
) -> None:
    callback = create_autospec(lambda: "123456")
    callback.return_value = "123456"
    garmin_constructor.return_value.login.side_effect = lambda *, tokenstore: callback()
    credentials = Credentials(
        email="runner@example.test",
        password="fabricated-password",  # noqa: S106 - fabricated test credential
    )

    session = GarminAuthGateway().authenticate(credentials, callback)

    garmin_constructor.assert_called_once_with(
        "runner@example.test",
        "fabricated-password",
        prompt_mfa=callback,
        retry_attempts=0,
        verify_login=True,
    )
    garmin_constructor.return_value.login.assert_called_once_with(tokenstore="{}")
    callback.assert_called_once_with()
    assert session.account_id == "10101"
    assert (
        json.loads(session.token_json)["di_token"] == "synthetic-access"  # noqa: S105 - fabricated token boundary value
    )
    assert b"ignored@example.test" not in session.token_json


def test_restore_passes_inline_tokens_to_garmin(garmin_constructor: Mock) -> None:
    token_json = _token().encode()

    session = GarminAuthGateway().restore(token_json)

    garmin_constructor.assert_called_once_with(retry_attempts=0, verify_login=True)
    garmin_constructor.return_value.login.assert_called_once_with(tokenstore=token_json.decode())
    assert session.account_id == "10101"


def test_restore_rejects_non_utf8_before_constructing_client(
    garmin_constructor: Mock,
) -> None:
    with pytest.raises(InvalidAuthResponseError):
        GarminAuthGateway().restore(b"\xff")

    garmin_constructor.assert_not_called()


@pytest.mark.parametrize(
    ("external_error", "domain_error"),
    [
        pytest.param(
            GarminConnectAuthenticationError("synthetic private detail"),
            AuthenticationRejectedError,
            id="authentication",
        ),
        pytest.param(
            GarminConnectTooManyRequestsError("synthetic private detail"),
            AuthRateLimitedError,
            id="rate-limit",
        ),
        pytest.param(
            GarminConnectConnectionError("synthetic private detail"),
            AuthNetworkError,
            id="network",
        ),
    ],
)
def test_dependency_errors_are_mapped_to_domain_errors(
    garmin_constructor: Mock,
    external_error: Exception,
    domain_error: type[Exception],
) -> None:
    garmin_constructor.return_value.login.side_effect = external_error

    with pytest.raises(domain_error) as caught:
        GarminAuthGateway().restore(_token().encode())

    assert "synthetic private detail" not in str(caught.value)


@pytest.mark.parametrize(
    "profile",
    [
        pytest.param([], id="not-object"),
        pytest.param({}, id="missing-id"),
        pytest.param({"profileId": True}, id="boolean-id"),
        pytest.param({"profileId": ""}, id="empty-id"),
        pytest.param({"profileId": "x" * 65}, id="oversized-id"),
    ],
)
def test_invalid_profile_identity_is_rejected(garmin_constructor: Mock, profile: object) -> None:
    garmin_constructor.return_value.connectapi.return_value = profile

    with pytest.raises(InvalidAuthResponseError):
        GarminAuthGateway().restore(_token().encode())


def test_http_connection_error_maps_to_remote_service_failure(
    garmin_constructor: Mock,
) -> None:
    external_error = GarminConnectConnectionError("synthetic private detail")
    external_error.response = SimpleNamespace(status_code=503)
    garmin_constructor.return_value.login.side_effect = external_error

    with pytest.raises(AuthRemoteServiceError) as caught:
        GarminAuthGateway().restore(_token().encode())

    assert "synthetic private detail" not in str(caught.value)


@pytest.mark.parametrize(
    ("nested_error", "domain_error"),
    [
        pytest.param(
            GarminConnectTooManyRequestsError("private"),
            AuthRateLimitedError,
            id="nested-rate-limit",
        ),
        pytest.param(
            GarminConnectConnectionError("private"),
            AuthNetworkError,
            id="nested-network",
        ),
    ],
)
def test_dependency_auth_wrapper_preserves_nested_failure_classification(
    garmin_constructor: Mock,
    nested_error: Exception,
    domain_error: type[Exception],
) -> None:
    wrapped_error = GarminConnectAuthenticationError("wrapped")
    wrapped_error.__cause__ = nested_error
    garmin_constructor.return_value.login.side_effect = wrapped_error

    with pytest.raises(domain_error):
        GarminAuthGateway().restore(_token().encode())


def test_profile_request_uses_reviewed_read_only_endpoint(
    garmin_constructor: Mock,
) -> None:
    GarminAuthGateway().restore(_token().encode())

    garmin_constructor.return_value.connectapi.assert_called_once_with(
        "/userprofile-service/socialProfile"
    )


@pytest.mark.parametrize(
    "token_value",
    [
        pytest.param(None, id="not-text"),
        pytest.param("{}", id="invalid-contract"),
    ],
)
def test_invalid_dependency_token_material_is_rejected(
    garmin_constructor: Mock, token_value: object
) -> None:
    garmin_constructor.return_value.client.dumps.return_value = token_value

    with pytest.raises(InvalidAuthResponseError):
        GarminAuthGateway().restore(_token().encode())
