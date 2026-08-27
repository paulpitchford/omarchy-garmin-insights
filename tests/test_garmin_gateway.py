import json
import signal
from collections.abc import Iterator
from datetime import date
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
from omarchy_garmin.garmin_gateway import (
    GarminActivityGateway,
    GarminAuthGateway,
    _request_deadline,
    _RequestDeadlineExpired,
)
from omarchy_garmin.sync import (
    ActivityAuthenticationRequiredError,
    ActivityDataError,
    ActivityNetworkError,
    ActivityRateLimitedError,
    ActivityRemoteServiceError,
)


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


def test_activity_fetch_uses_all_types_and_bounded_client_settings(
    garmin_constructor: Mock,
) -> None:
    garmin = garmin_constructor.return_value
    garmin.get_activities_by_date.return_value = [
        {
            "activityId": 101,
            "privateLocation": "ignored later",
        }
    ]

    result = GarminActivityGateway().fetch(
        _token().encode(),
        date(2026, 5, 29),
        date(2026, 8, 26),
    )

    garmin_constructor.assert_called_once_with(
        retry_attempts=1,
        retry_min_wait=1,
        retry_max_wait=2,
        verify_login=True,
    )
    garmin.get_activities_by_date.assert_called_once_with(
        "2026-05-29",
        "2026-08-26",
        sortorder="asc",
    )
    assert result.session.account_id == "10101"
    assert result.payload == [{"activityId": 101, "privateLocation": "ignored later"}]


def test_activity_fetch_loads_validated_tokens_without_dependency_login_fallback(
    garmin_constructor: Mock,
) -> None:
    garmin = garmin_constructor.return_value

    GarminActivityGateway().fetch(
        _token().encode(),
        date(2026, 8, 20),
        date(2026, 8, 26),
    )

    garmin.login.assert_not_called()
    garmin.client.loads.assert_called_once_with(_token())


@pytest.mark.parametrize(
    ("external_error", "domain_error"),
    [
        pytest.param(
            GarminConnectAuthenticationError("private"),
            ActivityAuthenticationRequiredError,
            id="authentication",
        ),
        pytest.param(
            GarminConnectTooManyRequestsError("private"),
            ActivityRateLimitedError,
            id="rate-limit",
        ),
        pytest.param(
            GarminConnectConnectionError("private"),
            ActivityNetworkError,
            id="network",
        ),
    ],
)
def test_activity_dependency_errors_are_mapped(
    garmin_constructor: Mock,
    external_error: Exception,
    domain_error: type[Exception],
) -> None:
    garmin_constructor.return_value.connectapi.side_effect = external_error

    with pytest.raises(domain_error) as caught:
        GarminActivityGateway().fetch(
            _token().encode(),
            date(2026, 8, 20),
            date(2026, 8, 26),
        )

    assert "private" not in str(caught.value)


def test_activity_http_failure_is_remote_service_error(garmin_constructor: Mock) -> None:
    error = GarminConnectConnectionError("private")
    error.response = SimpleNamespace(status_code=503)
    garmin_constructor.return_value.get_activities_by_date.side_effect = error

    with pytest.raises(ActivityRemoteServiceError):
        GarminActivityGateway().fetch(
            _token().encode(),
            date(2026, 8, 20),
            date(2026, 8, 26),
        )


def test_activity_fetch_rejects_invalid_local_or_refreshed_tokens(
    garmin_constructor: Mock,
) -> None:
    with pytest.raises(ActivityDataError):
        GarminActivityGateway().fetch(b"\xff", date(2026, 8, 20), date(2026, 8, 26))
    with pytest.raises(ActivityDataError):
        GarminActivityGateway().fetch(b"{}", date(2026, 8, 20), date(2026, 8, 26))

    garmin_constructor.return_value.client.dumps.return_value = "{}"
    with pytest.raises(ActivityDataError):
        GarminActivityGateway().fetch(
            _token().encode(),
            date(2026, 8, 20),
            date(2026, 8, 26),
        )


def test_complete_activity_request_deadline_maps_to_network_failure(
    garmin_constructor: Mock,
) -> None:
    with (
        patch(
            "omarchy_garmin.garmin_gateway._request_deadline",
            side_effect=_RequestDeadlineExpired("expired"),
        ),
        pytest.raises(ActivityNetworkError),
    ):
        GarminActivityGateway().fetch(
            _token().encode(),
            date(2026, 8, 20),
            date(2026, 8, 26),
        )

    garmin_constructor.return_value.login.assert_not_called()


def test_request_deadline_restores_existing_signal_state() -> None:
    previous_handler = Mock()
    with (
        patch("omarchy_garmin.garmin_gateway.signal.getsignal", return_value=previous_handler),
        patch("omarchy_garmin.garmin_gateway.signal.getitimer", return_value=(5.0, 0.5)),
        patch("omarchy_garmin.garmin_gateway.signal.signal") as set_signal,
        patch("omarchy_garmin.garmin_gateway.signal.setitimer") as set_timer,
        pytest.raises(_RequestDeadlineExpired),
        _request_deadline(120),
    ):
        deadline_handler = set_signal.call_args_list[0].args[1]
        deadline_handler(signal.SIGALRM, None)

    assert set_timer.call_args_list[-1].args == (signal.ITIMER_REAL, 5.0, 0.5)
    assert set_signal.call_args_list[-1].args == (signal.SIGALRM, previous_handler)
