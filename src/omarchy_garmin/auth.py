"""Authentication use cases and private account-scoped state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from omarchy_garmin.paths import AppPaths
from omarchy_garmin.storage import (
    UnsafeStoragePathError,
    atomic_write_private,
    ensure_private_directory,
    private_directory_exists,
    private_file_exists,
    read_private_file,
    remove_private_file,
)

TOKEN_MAX_BYTES = 65_536
ACCOUNT_SCOPE_MAX_BYTES = 512
ACCOUNT_SCOPE_SCHEMA_VERSION = 1
_TOKEN_FIELDS = frozenset({"di_token", "di_refresh_token", "di_client_id"})
_TOKEN_VALUE_MAX_LENGTH = 16_384


class AuthError(RuntimeError):
    """Base class for safe authentication-domain failures."""


class AuthenticationRejectedError(AuthError):
    """Raised when Garmin rejects credentials or stored tokens."""


class AccountMismatchError(AuthError):
    """Raised before data from a different Garmin account can be adopted."""


class AuthRateLimitedError(AuthError):
    """Raised when Garmin rate-limits authentication."""


class AuthNetworkError(AuthError):
    """Raised when Garmin cannot be reached during authentication."""


class AuthRemoteServiceError(AuthError):
    """Raised when a reachable Garmin service rejects a request unexpectedly."""


class InvalidAuthResponseError(AuthError):
    """Raised when Garmin returns an unusable authentication response."""


class AuthStorageError(AuthError):
    """Raised when private authentication state cannot be used safely."""


class InteractiveTerminalRequiredError(AuthError):
    """Raised when credential input is attempted without a terminal."""


@dataclass(frozen=True, slots=True)
class Credentials:
    """Ephemeral credentials read from an interactive terminal."""

    email: str
    password: str


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Validated account identity and token material returned by the Garmin boundary."""

    account_id: str
    token_json: bytes


@dataclass(frozen=True, slots=True)
class AuthStatus:
    """Local authentication status that makes no Garmin request."""

    configured: bool
    verified: bool
    account_scoped: bool


class CredentialProvider(Protocol):
    """Collect credentials and MFA codes without persisting them."""

    def read_credentials(self) -> Credentials:
        """Read a Garmin email and hidden password."""
        ...

    def read_mfa_code(self) -> str:
        """Read one hidden Garmin MFA code."""
        ...


class AuthGateway(Protocol):
    """Authenticate through the external Garmin client."""

    def restore(self, token_json: bytes) -> AuthenticatedSession:
        """Verify and refresh a serialized Garmin session."""
        ...

    def authenticate(
        self,
        credentials: Credentials,
        prompt_mfa: Callable[[], str],
    ) -> AuthenticatedSession:
        """Authenticate credentials, resolving MFA in the same call."""
        ...


class AuthOperations(Protocol):
    """Authentication operations consumed by the CLI."""

    def status(self) -> AuthStatus:
        """Return local configuration state without contacting Garmin."""
        ...

    def login(self) -> AuthStatus:
        """Verify stored tokens or run an interactive credential login."""
        ...

    def logout(self) -> None:
        """Remove tokens while retaining account-scoped activity data."""
        ...

    def purge(self) -> None:
        """Remove all known local Garmin state."""
        ...


def validate_token_json(content: bytes) -> bytes:
    """Validate the pinned Garmin client's bounded token contract."""
    if len(content) > TOKEN_MAX_BYTES:
        raise ValueError("Garmin tokens exceed the size limit")
    try:
        value: object = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Garmin tokens are malformed") from error
    if not isinstance(value, dict) or set(value) != _TOKEN_FIELDS:
        raise ValueError("Garmin tokens have an unexpected structure")
    if any(
        not isinstance(value[field], str)
        or not value[field]
        or len(value[field]) > _TOKEN_VALUE_MAX_LENGTH
        for field in _TOKEN_FIELDS
    ):
        raise ValueError("Garmin tokens have invalid values")
    return content


def _account_fingerprint(account_id: str) -> str:
    """Create a pseudonymous local account identifier."""
    return hashlib.sha256(f"garmin.com\0{account_id}".encode()).hexdigest()


def _scope_payload(fingerprint: str) -> bytes:
    """Serialize bounded account-scope metadata."""
    payload = {
        "schemaVersion": ACCOUNT_SCOPE_SCHEMA_VERSION,
        "accountFingerprint": fingerprint,
    }
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _parse_scope(content: bytes) -> str:
    """Validate and return a stored account fingerprint."""
    if len(content) > ACCOUNT_SCOPE_MAX_BYTES:
        raise AuthStorageError("account scope exceeds the size limit")
    try:
        value: object = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthStorageError("account scope is malformed") from error
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "accountFingerprint"}:
        raise AuthStorageError("account scope has an unexpected structure")
    if value["schemaVersion"] != ACCOUNT_SCOPE_SCHEMA_VERSION:
        raise AuthStorageError("account scope has an unsupported schema")
    fingerprint = value["accountFingerprint"]
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise AuthStorageError("account scope has an invalid fingerprint")
    return fingerprint


class AuthStore:
    """Own private token, account-scope, logout, and purge filesystem behavior."""

    def __init__(self, paths: AppPaths) -> None:
        """Initialize the store with resolved application paths."""
        self._paths = paths

    def _auth_directory_exists(self) -> bool:
        if not private_directory_exists(self._paths.state):
            return False
        return private_directory_exists(self._paths.auth)

    def _data_directory_exists(self) -> bool:
        return private_directory_exists(self._paths.data)

    def _cache_directory_exists(self) -> bool:
        return private_directory_exists(self._paths.cache)

    def read_token(self) -> bytes | None:
        """Return validated token material, or None when not configured."""
        try:
            if not self._auth_directory_exists() or not private_file_exists(self._paths.token_file):
                return None
            content = read_private_file(self._paths.token_file, max_bytes=TOKEN_MAX_BYTES)
            try:
                return validate_token_json(content)
            except ValueError as error:
                raise AuthStorageError("stored Garmin tokens are invalid") from error
        except (OSError, UnsafeStoragePathError) as error:
            raise AuthStorageError("Garmin token storage is unsafe or unavailable") from error

    def read_scope(self) -> str | None:
        """Return the validated account fingerprint, or None when not scoped."""
        try:
            if not self._data_directory_exists() or not private_file_exists(
                self._paths.account_scope_file
            ):
                return None
            content = read_private_file(
                self._paths.account_scope_file, max_bytes=ACCOUNT_SCOPE_MAX_BYTES
            )
            return _parse_scope(content)
        except (OSError, UnsafeStoragePathError) as error:
            raise AuthStorageError("account-scope storage is unsafe or unavailable") from error

    def status(self) -> AuthStatus:
        """Inspect local state without treating stored tokens as verified."""
        return AuthStatus(
            configured=self.read_token() is not None,
            verified=False,
            account_scoped=self.read_scope() is not None,
        )

    def persist(self, session: AuthenticatedSession) -> None:
        """Persist tokens only after enforcing the existing account scope."""
        try:
            token_json = validate_token_json(session.token_json)
        except ValueError as error:
            raise InvalidAuthResponseError("Garmin returned invalid token material") from error
        fingerprint = _account_fingerprint(session.account_id)
        try:
            ensure_private_directory(self._paths.state)
            ensure_private_directory(self._paths.auth)
            ensure_private_directory(self._paths.data)
            existing_fingerprint = self.read_scope()
            if existing_fingerprint is not None and existing_fingerprint != fingerprint:
                raise AccountMismatchError(
                    "authenticated Garmin account does not match local activity data"
                )
            if existing_fingerprint is None:
                atomic_write_private(
                    self._paths.account_scope_file,
                    _scope_payload(fingerprint),
                )
            atomic_write_private(self._paths.token_file, token_json)
        except AccountMismatchError:
            raise
        except (OSError, UnsafeStoragePathError) as error:
            raise AuthStorageError("Garmin authentication state could not be persisted") from error

    def logout(self) -> None:
        """Delete only the dedicated token file."""
        try:
            if self._auth_directory_exists():
                remove_private_file(self._paths.token_file)
        except (OSError, UnsafeStoragePathError) as error:
            raise AuthStorageError("Garmin tokens could not be removed safely") from error

    def purge(self) -> None:
        """Delete all currently known private Garmin data files."""
        try:
            if self._auth_directory_exists():
                remove_private_file(self._paths.token_file)
            if self._data_directory_exists():
                for path in self._data_files():
                    remove_private_file(path)
            if self._cache_directory_exists():
                remove_private_file(self._paths.summary_file)
        except (OSError, UnsafeStoragePathError) as error:
            raise AuthStorageError("local Garmin data could not be purged safely") from error

    def _data_files(self) -> tuple[Path, ...]:
        """Return the allowlisted data files removed by purge."""
        database = self._paths.activity_database
        return (
            self._paths.account_scope_file,
            database,
            database.with_name(f"{database.name}-wal"),
            database.with_name(f"{database.name}-shm"),
            database.with_name(f"{database.name}-journal"),
        )


class AuthService:
    """Coordinate local state, interactive credentials, and the Garmin boundary."""

    def __init__(
        self,
        store: AuthStore,
        gateway: AuthGateway,
        credential_provider: CredentialProvider,
    ) -> None:
        """Initialize explicit authentication dependencies."""
        self._store = store
        self._gateway = gateway
        self._credential_provider = credential_provider

    def status(self) -> AuthStatus:
        """Return local authentication status without a Garmin request."""
        return self._store.status()

    def login(self) -> AuthStatus:
        """Verify stored tokens or complete credential and MFA login."""
        token_json = self._store.read_token()
        session: AuthenticatedSession
        if token_json is not None:
            try:
                session = self._gateway.restore(token_json)
            except AuthenticationRejectedError:
                session = self._authenticate_credentials()
        else:
            session = self._authenticate_credentials()

        self._store.persist(session)
        return AuthStatus(configured=True, verified=True, account_scoped=True)

    def _authenticate_credentials(self) -> AuthenticatedSession:
        """Collect credentials and authenticate in the current process."""
        credentials = self._credential_provider.read_credentials()
        return self._gateway.authenticate(
            credentials,
            self._credential_provider.read_mfa_code,
        )

    def logout(self) -> None:
        """Remove tokens while retaining account-scoped local data."""
        self._store.logout()

    def purge(self) -> None:
        """Remove all known local Garmin files."""
        self._store.purge()
