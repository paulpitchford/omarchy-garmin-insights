"""Visible-terminal credential collection for Garmin authentication."""

from __future__ import annotations

import getpass
import warnings
from collections.abc import Callable
from typing import TextIO

from omarchy_garmin.auth import (
    AuthenticationRejectedError,
    Credentials,
    InteractiveTerminalRequiredError,
)

_EMAIL_MAX_LENGTH = 254
_PASSWORD_MAX_LENGTH = 1_024
_MFA_CODE_MAX_LENGTH = 64


class TerminalCredentialProvider:
    """Read transient credentials from a visible interactive terminal."""

    def __init__(
        self,
        stdin: TextIO,
        stderr: TextIO,
        secret_reader: Callable[[str, TextIO | None], str] = getpass.getpass,
    ) -> None:
        """Initialize terminal streams and the hidden-input boundary."""
        self._stdin = stdin
        self._stderr = stderr
        self._secret_reader = secret_reader

    def _require_terminal(self) -> None:
        """Reject redirected credential input before displaying a prompt."""
        if not self._stdin.isatty():
            raise InteractiveTerminalRequiredError("Garmin login requires an interactive terminal")

    def _read_hidden(self, prompt: str) -> str:
        """Read hidden input while refusing getpass's echoed fallback."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                return self._secret_reader(prompt, self._stderr)
        except getpass.GetPassWarning as error:
            raise InteractiveTerminalRequiredError(
                "terminal cannot provide hidden credential input"
            ) from error

    def read_credentials(self) -> Credentials:
        """Read an email and hidden password without retaining either."""
        self._require_terminal()
        self._stderr.write("Garmin email: ")
        self._stderr.flush()
        email = self._stdin.readline(_EMAIL_MAX_LENGTH + 2).strip()
        if (
            not email
            or len(email) > _EMAIL_MAX_LENGTH
            or "@" not in email
            or any(not character.isprintable() for character in email)
        ):
            raise AuthenticationRejectedError("Garmin email is invalid")

        password = self._read_hidden("Garmin password: ")
        if not password or len(password) > _PASSWORD_MAX_LENGTH:
            raise AuthenticationRejectedError("Garmin password is invalid")
        return Credentials(email=email, password=password)

    def read_mfa_code(self) -> str:
        """Read a hidden, bounded MFA code in the same process as login."""
        self._require_terminal()
        code = self._read_hidden("Garmin MFA code: ").strip()
        if (
            not code
            or len(code) > _MFA_CODE_MAX_LENGTH
            or any(not character.isprintable() for character in code)
        ):
            raise AuthenticationRejectedError("Garmin MFA code is invalid")
        return code
