import getpass
import warnings
from collections.abc import Iterator
from io import StringIO
from typing import TextIO

import pytest

from omarchy_garmin.auth import AuthenticationRejectedError, InteractiveTerminalRequiredError
from omarchy_garmin.prompts import TerminalCredentialProvider


class _TerminalInput(StringIO):
    def isatty(self) -> bool:
        return True


class _Secrets:
    def __init__(self, values: list[str]) -> None:
        self._values: Iterator[str] = iter(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, stream: TextIO | None) -> str:
        self.prompts.append(prompt)
        return next(self._values)


def test_credentials_require_an_interactive_terminal() -> None:
    provider = TerminalCredentialProvider(StringIO("runner@example.test\n"), StringIO())

    with pytest.raises(InteractiveTerminalRequiredError):
        provider.read_credentials()


def test_getpass_echo_fallback_is_rejected() -> None:
    def echoed_fallback(prompt: str, stream: TextIO | None) -> str:
        warnings.warn("hidden input unavailable", getpass.GetPassWarning, stacklevel=2)
        return "would-have-been-echoed"

    provider = TerminalCredentialProvider(
        _TerminalInput("runner@example.test\n"), StringIO(), echoed_fallback
    )

    with pytest.raises(InteractiveTerminalRequiredError):
        provider.read_credentials()


def test_credentials_read_email_and_hidden_password() -> None:
    stderr = StringIO()
    secrets = _Secrets(["fabricated-password"])
    provider = TerminalCredentialProvider(_TerminalInput("runner@example.test\n"), stderr, secrets)

    credentials = provider.read_credentials()

    assert credentials.email == "runner@example.test"
    assert credentials.password == "fabricated-password"  # noqa: S105
    assert stderr.getvalue() == "Garmin email: "
    assert secrets.prompts == ["Garmin password: "]
    assert "fabricated-password" not in stderr.getvalue()


@pytest.mark.parametrize(
    "email",
    [
        pytest.param("", id="empty"),
        pytest.param("missing-at", id="missing-at"),
        pytest.param("x" * 255 + "@example.test", id="too-long"),
        pytest.param("runner@example.test\x00", id="control-character"),
    ],
)
def test_invalid_email_is_rejected_before_password_prompt(email: str) -> None:
    secrets = _Secrets(["unused"])
    provider = TerminalCredentialProvider(_TerminalInput(email + "\n"), StringIO(), secrets)

    with pytest.raises(AuthenticationRejectedError):
        provider.read_credentials()

    assert secrets.prompts == []


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("", id="empty"),
        pytest.param("x" * 1_025, id="too-long"),
    ],
)
def test_invalid_password_is_rejected(password: str) -> None:
    provider = TerminalCredentialProvider(
        _TerminalInput("runner@example.test\n"), StringIO(), _Secrets([password])
    )

    with pytest.raises(AuthenticationRejectedError):
        provider.read_credentials()


def test_mfa_code_is_hidden_and_trimmed() -> None:
    stderr = StringIO()
    secrets = _Secrets([" 123456 "])
    provider = TerminalCredentialProvider(_TerminalInput(), stderr, secrets)

    code = provider.read_mfa_code()

    assert code == "123456"
    assert secrets.prompts == ["Garmin MFA code: "]
    assert "123456" not in stderr.getvalue()


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("", id="empty"),
        pytest.param("1" * 65, id="too-long"),
        pytest.param("12\x0034", id="control-character"),
    ],
)
def test_invalid_mfa_code_is_rejected(code: str) -> None:
    provider = TerminalCredentialProvider(_TerminalInput(), StringIO(), _Secrets([code]))

    with pytest.raises(AuthenticationRejectedError):
        provider.read_mfa_code()
