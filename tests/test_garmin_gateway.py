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
    GarminWellnessGateway,
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
from omarchy_garmin.wellness import (
    InvalidWellnessDataError,
    UnsupportedWellnessSourceError,
    WellnessSource,
)
from omarchy_garmin.wellness_sync import (
    WellnessAuthenticationError,
    WellnessInvalidDataError,
    WellnessNetworkError,
    WellnessRateLimitedError,
    WellnessRemoteServiceError,
    WellnessSyncConfigurationError,
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
        garmin.connectapi.return_value = {
            "profileId": 10101,
            "displayName": "synthetic_runner",
            "email": "ignored@example.test",
        }
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


def test_wellness_connection_uses_only_approved_methods_and_zero_dependency_retries(
    garmin_constructor: Mock,
) -> None:
    garmin = garmin_constructor.return_value
    garmin.get_user_summary.return_value = {"calendarDate": "2026-08-26"}
    garmin.get_daily_steps.return_value = []
    garmin.get_body_battery.return_value = []
    garmin.get_sleep_daily.return_value = []
    garmin.get_sleep_data.return_value = None
    garmin.get_hrv_data_range.return_value = None
    garmin.get_hrv_data.return_value = None
    garmin.get_rhr_daily.return_value = []
    garmin.get_training_readiness.return_value = []

    with GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()) as connection:
        assert connection.user_summary(date(2026, 8, 26)) == {"calendarDate": "2026-08-26"}
        assert connection.daily_steps(date(2026, 8, 1), date(2026, 8, 26)) == []
        assert connection.body_battery(date(2026, 8, 20), date(2026, 8, 26)) == []
        assert connection.sleep_range(date(2026, 8, 1), date(2026, 8, 26)) == []
        assert connection.sleep_detail(date(2026, 8, 26)) is None
        assert connection.hrv_range(date(2026, 8, 1), date(2026, 8, 26)) is None
        assert connection.hrv_detail(date(2026, 8, 26)) is None
        assert connection.resting_heart_rate(date(2026, 8, 1), date(2026, 8, 26)) == []
        assert connection.training_readiness(date(2026, 8, 26)) == []
        assert connection.request_attempts == 10

    garmin_constructor.assert_called_once_with(retry_attempts=0, verify_login=True)
    garmin.client.loads.assert_called_once_with(_token())
    garmin.connectapi.assert_called_once_with("/userprofile-service/socialProfile")
    assert garmin.display_name == "synthetic_runner"
    garmin.get_user_summary.assert_called_once_with("2026-08-26")
    garmin.get_daily_steps.assert_called_once_with("2026-08-01", "2026-08-26")
    garmin.get_body_battery.assert_called_once_with("2026-08-20", "2026-08-26")
    garmin.get_sleep_daily.assert_called_once_with("2026-08-01", "2026-08-26")
    garmin.get_sleep_data.assert_called_once_with("2026-08-26")
    garmin.get_hrv_data_range.assert_called_once_with("2026-08-01", "2026-08-26")
    garmin.get_hrv_data.assert_called_once_with("2026-08-26")
    garmin.get_rhr_daily.assert_called_once_with("2026-08-01", "2026-08-26")
    garmin.get_training_readiness.assert_called_once_with("2026-08-26")


def test_wellness_retries_one_http_5xx_then_succeeds(garmin_constructor: Mock) -> None:
    failure = GarminConnectConnectionError("private server body")
    failure.response = SimpleNamespace(status_code=503)
    garmin = garmin_constructor.return_value
    garmin.get_daily_steps.side_effect = [failure, []]
    sleeper = Mock()

    with GarminWellnessGateway(sleeper=sleeper).connect(_token().encode()) as connection:
        assert connection.daily_steps(date(2026, 8, 1), date(2026, 8, 26)) == []
        assert connection.request_attempts == 3

    sleeper.assert_called_once_with(1.0)
    assert garmin.get_daily_steps.call_count == 2


def test_wellness_uses_only_one_explicit_retry_across_complete_command(
    garmin_constructor: Mock,
) -> None:
    first_failure = GarminConnectConnectionError("private first failure")
    second_failure = GarminConnectConnectionError("private second failure")
    garmin = garmin_constructor.return_value
    garmin.get_daily_steps.side_effect = [first_failure, []]
    garmin.get_body_battery.side_effect = second_failure
    sleeper = Mock()

    with GarminWellnessGateway(sleeper=sleeper).connect(_token().encode()) as connection:
        assert connection.daily_steps(date(2026, 8, 1), date(2026, 8, 26)) == []
        with pytest.raises(WellnessNetworkError) as caught:
            connection.body_battery(date(2026, 8, 26), date(2026, 8, 26))
        assert connection.request_attempts == 4

    sleeper.assert_called_once_with(1.0)
    assert "private" not in str(caught.value)
    assert garmin.get_daily_steps.call_count == 2
    assert garmin.get_body_battery.call_count == 1


@pytest.mark.parametrize(
    ("external_error", "domain_error"),
    [
        pytest.param(
            GarminConnectAuthenticationError("private"),
            WellnessAuthenticationError,
            id="authentication",
        ),
        pytest.param(
            GarminConnectTooManyRequestsError("private"),
            WellnessRateLimitedError,
            id="rate-limit",
        ),
    ],
)
def test_wellness_authentication_and_rate_limit_fail_without_retry(
    garmin_constructor: Mock,
    external_error: Exception,
    domain_error: type[Exception],
) -> None:
    garmin_constructor.return_value.get_sleep_data.side_effect = external_error
    sleeper = Mock()

    with (
        GarminWellnessGateway(sleeper=sleeper).connect(_token().encode()) as connection,
        pytest.raises(domain_error) as caught,
    ):
        connection.sleep_detail(date(2026, 8, 26))

    sleeper.assert_not_called()
    assert "private" not in str(caught.value)


def test_wellness_nested_dependency_failures_keep_safe_classification(
    garmin_constructor: Mock,
) -> None:
    nested = GarminConnectTooManyRequestsError("private nested detail")
    wrapped = GarminConnectAuthenticationError("private wrapper")
    wrapped.__cause__ = nested
    garmin_constructor.return_value.get_sleep_data.side_effect = wrapped

    with (
        GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()) as connection,
        pytest.raises(WellnessRateLimitedError) as caught,
    ):
        connection.sleep_detail(date(2026, 8, 26))

    assert "private" not in str(caught.value)


def test_wellness_source_404_is_unsupported_and_other_4xx_is_remote_failure(
    garmin_constructor: Mock,
) -> None:
    unsupported = GarminConnectConnectionError("private unsupported body")
    unsupported.response = SimpleNamespace(status_code=404)
    remote = GarminConnectConnectionError("private remote body")
    remote.response = SimpleNamespace(status_code=422)
    garmin = garmin_constructor.return_value
    garmin.get_hrv_data.side_effect = unsupported
    garmin.get_sleep_data.side_effect = remote

    with GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()) as connection:
        with pytest.raises(UnsupportedWellnessSourceError) as caught_unsupported:
            connection.hrv_detail(date(2026, 8, 26))
        with pytest.raises(WellnessRemoteServiceError) as caught_remote:
            connection.sleep_detail(date(2026, 8, 26))

    assert caught_unsupported.value.source is WellnessSource.HRV
    assert "private" not in str(caught_unsupported.value)
    assert "private" not in str(caught_remote.value)


def test_wellness_dependency_shape_failure_maps_to_redacted_source_data_error(
    garmin_constructor: Mock,
) -> None:
    garmin_constructor.return_value.get_sleep_daily.side_effect = ValueError(
        "private malformed response"
    )

    with (
        GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()) as connection,
        pytest.raises(InvalidWellnessDataError) as caught,
    ):
        connection.sleep_range(date(2026, 8, 1), date(2026, 8, 26))

    assert caught.value.source is WellnessSource.SLEEP
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "token_json",
    [
        pytest.param(b"\xff", id="non-utf8"),
        pytest.param(b"{}", id="invalid-contract"),
    ],
)
def test_wellness_rejects_invalid_tokens_before_constructing_client(
    garmin_constructor: Mock,
    token_json: bytes,
) -> None:
    with (
        pytest.raises(WellnessInvalidDataError),
        GarminWellnessGateway(sleeper=Mock()).connect(token_json),
    ):
        pytest.fail("invalid tokens must not yield a connection")

    garmin_constructor.assert_not_called()


def test_wellness_rejects_dependency_token_load_failure_without_exposing_detail(
    garmin_constructor: Mock,
) -> None:
    garmin = garmin_constructor.return_value
    garmin.client.loads.side_effect = GarminConnectConnectionError("private token detail")

    with (
        pytest.raises(WellnessInvalidDataError) as caught,
        GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()),
    ):
        pytest.fail("failed token load must not yield a connection")

    assert "private" not in str(caught.value)
    garmin.connectapi.assert_not_called()


def test_wellness_rejects_invalid_refreshed_tokens(garmin_constructor: Mock) -> None:
    garmin_constructor.return_value.client.dumps.side_effect = [_token(), "{}"]

    with (
        GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()) as connection,
        pytest.raises(WellnessInvalidDataError),
    ):
        connection.refreshed_session()


@pytest.mark.parametrize(
    "display_name",
    [
        pytest.param("unsafe/name", id="path-separator"),
        pytest.param("unsafe?query", id="query-separator"),
        pytest.param("unsafe#fragment", id="fragment-separator"),
        pytest.param("unsafe\\name", id="backslash"),
        pytest.param("unsafe\nname", id="control-character"),
    ],
)
def test_wellness_verification_rejects_unsafe_display_name_without_data_calls(
    garmin_constructor: Mock,
    display_name: str,
) -> None:
    garmin = garmin_constructor.return_value
    garmin.connectapi.return_value = {"profileId": 10101, "displayName": display_name}

    with (
        pytest.raises(WellnessInvalidDataError),
        GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()),
    ):
        pytest.fail("invalid verification must not yield a connection")

    garmin.get_user_summary.assert_not_called()


def test_complete_wellness_deadline_maps_to_network_failure(
    garmin_constructor: Mock,
) -> None:
    with (
        patch(
            "omarchy_garmin.garmin_gateway._request_deadline",
            side_effect=_RequestDeadlineExpired("expired"),
        ),
        pytest.raises(WellnessNetworkError),
        GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()),
    ):
        pytest.fail("expired deadline must not yield a connection")

    garmin_constructor.return_value.connectapi.assert_not_called()


def test_wellness_attempt_budget_fails_closed_before_twenty_first_http_attempt(
    garmin_constructor: Mock,
) -> None:
    garmin = garmin_constructor.return_value
    garmin.get_daily_steps.return_value = []

    with GarminWellnessGateway(sleeper=Mock()).connect(_token().encode()) as connection:
        for _ in range(19):
            connection.daily_steps(date(2026, 8, 26), date(2026, 8, 26))
        with pytest.raises(WellnessSyncConfigurationError):
            connection.daily_steps(date(2026, 8, 26), date(2026, 8, 26))

    assert garmin.get_daily_steps.call_count == 19


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
