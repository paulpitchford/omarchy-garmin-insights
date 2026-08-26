import json
from collections.abc import Callable
from pathlib import Path

import pytest

from omarchy_garmin.auth import (
    TOKEN_MAX_BYTES,
    AccountMismatchError,
    AuthenticatedSession,
    AuthenticationRejectedError,
    AuthGateway,
    AuthRateLimitedError,
    AuthRefreshInProgressError,
    AuthService,
    AuthStatus,
    AuthStorageError,
    AuthStore,
    CredentialProvider,
    Credentials,
    InvalidAuthResponseError,
    validate_token_json,
)
from omarchy_garmin.locking import activity_refresh_lock
from omarchy_garmin.paths import AppPaths
from omarchy_garmin.storage import atomic_write_private, ensure_private_directory


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        state=tmp_path / "state",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
    )


def _token(marker: str = "one") -> bytes:
    return json.dumps(
        {
            "di_token": f"access-{marker}",
            "di_refresh_token": f"refresh-{marker}",
            "di_client_id": f"client-{marker}",
        },
        separators=(",", ":"),
    ).encode()


def _session(
    account_id: str = "synthetic-account-101", marker: str = "one"
) -> AuthenticatedSession:
    return AuthenticatedSession(account_id=account_id, token_json=_token(marker))


class _FakeCredentials(CredentialProvider):
    def __init__(self) -> None:
        self.read_count = 0
        self.mfa_count = 0

    def read_credentials(self) -> Credentials:
        self.read_count += 1
        return Credentials(
            email="runner@example.test",
            password="fabricated-password",  # noqa: S106 - fabricated test credential
        )

    def read_mfa_code(self) -> str:
        self.mfa_count += 1
        return "123456"


class _FakeGateway(AuthGateway):
    def __init__(
        self,
        *,
        restored: AuthenticatedSession | Exception | None = None,
        authenticated: AuthenticatedSession | Exception | None = None,
    ) -> None:
        self.restored = restored or _session(marker="restored")
        self.authenticated = authenticated or _session(marker="authenticated")
        self.restore_calls: list[bytes] = []
        self.authenticate_calls: list[Credentials] = []

    def restore(self, token_json: bytes) -> AuthenticatedSession:
        self.restore_calls.append(token_json)
        if isinstance(self.restored, Exception):
            raise self.restored
        return self.restored

    def authenticate(
        self, credentials: Credentials, prompt_mfa: Callable[[], str]
    ) -> AuthenticatedSession:
        self.authenticate_calls.append(credentials)
        if isinstance(self.authenticated, Exception):
            raise self.authenticated
        return self.authenticated


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"not-json", id="malformed-json"),
        pytest.param(b"[]", id="not-object"),
        pytest.param(b'{"di_token":"only"}', id="missing-fields"),
        pytest.param(
            b'{"di_token":"","di_refresh_token":"refresh","di_client_id":"client"}',
            id="empty-value",
        ),
        pytest.param(
            b'{"di_token":1,"di_refresh_token":"refresh","di_client_id":"client"}',
            id="non-string-value",
        ),
        pytest.param(b"{" + b"x" * TOKEN_MAX_BYTES + b"}", id="oversized"),
    ],
)
def test_invalid_token_contract_is_rejected(content: bytes) -> None:
    with pytest.raises(ValueError, match="Garmin tokens"):
        validate_token_json(content)


def test_valid_token_contract_is_preserved() -> None:
    content = _token()

    result = validate_token_json(content)

    assert result == content


def test_empty_store_status_does_not_create_directories(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)

    status = store.status()

    assert status == AuthStatus(configured=False, verified=False, account_scoped=False)
    assert paths.state.exists() is False
    assert paths.data.exists() is False


def test_persist_writes_tokens_and_pseudonymous_scope(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)

    store.persist(_session())

    assert paths.token_file.read_bytes() == _token()
    scope = paths.account_scope_file.read_bytes()
    assert b"synthetic-account-101" not in scope
    assert len(json.loads(scope)["accountFingerprint"]) == 64
    assert store.status() == AuthStatus(configured=True, verified=False, account_scoped=True)


def test_same_account_can_replace_tokens_idempotently(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session(marker="old"))

    store.persist(_session(marker="new"))

    assert paths.token_file.read_bytes() == _token("new")


def test_different_account_cannot_replace_tokens(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session(marker="existing"))

    with pytest.raises(AccountMismatchError):
        store.persist(_session(account_id="synthetic-account-202", marker="replacement"))

    assert paths.token_file.read_bytes() == _token("existing")


def test_invalid_session_tokens_are_not_persisted(tmp_path: Path) -> None:
    store = AuthStore(_paths(tmp_path))
    session = AuthenticatedSession(account_id="synthetic-account-101", token_json=b"invalid")

    with pytest.raises(InvalidAuthResponseError):
        store.persist(session)


def test_malformed_stored_tokens_raise_storage_error(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    ensure_private_directory(paths.state)
    ensure_private_directory(paths.auth)
    atomic_write_private(paths.token_file, b"invalid")

    with pytest.raises(AuthStorageError):
        AuthStore(paths).read_token()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"x" * 513, id="oversized"),
        pytest.param(b"not-json", id="malformed"),
        pytest.param(b'{"schemaVersion":99}', id="unexpected-structure"),
        pytest.param(
            b'{"schemaVersion":99,"accountFingerprint":"' + b"a" * 64 + b'"}',
            id="unsupported-schema",
        ),
        pytest.param(
            b'{"schemaVersion":1,"accountFingerprint":"invalid"}',
            id="invalid-fingerprint",
        ),
    ],
)
def test_malformed_account_scope_raises_storage_error(tmp_path: Path, content: bytes) -> None:
    paths = _paths(tmp_path)
    ensure_private_directory(paths.data)
    atomic_write_private(paths.account_scope_file, content)

    with pytest.raises(AuthStorageError):
        AuthStore(paths).read_scope()


def test_symlinked_auth_directory_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    ensure_private_directory(paths.state)
    target = tmp_path / "target"
    target.mkdir()
    paths.auth.symlink_to(target, target_is_directory=True)

    with pytest.raises(AuthStorageError):
        AuthStore(paths).read_token()


def test_persist_rejects_symlinked_data_directory(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    target = tmp_path / "target-data"
    target.mkdir()
    paths.data.symlink_to(target, target_is_directory=True)

    with pytest.raises(AuthStorageError):
        AuthStore(paths).persist(_session())

    assert list(target.iterdir()) == []


def test_logout_is_idempotent_and_retains_scope(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session())

    store.logout()
    store.logout()

    assert paths.token_file.exists() is False
    assert paths.account_scope_file.exists() is True


def test_logout_rejects_symlinked_token_file_without_touching_target(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session())
    paths.token_file.unlink()
    target = tmp_path / "target-token"
    target.write_bytes(b"keep")
    paths.token_file.symlink_to(target)

    with pytest.raises(AuthStorageError):
        store.logout()

    assert target.read_bytes() == b"keep"


def test_purge_removes_allowlisted_files_but_not_unrelated_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session())
    ensure_private_directory(paths.cache)
    for path in (
        paths.activity_database,
        paths.activity_database.with_name("activities.sqlite3-wal"),
        paths.activity_database.with_name("activities.sqlite3-shm"),
        paths.activity_database.with_name("activities.sqlite3-journal"),
        paths.summary_file,
    ):
        atomic_write_private(path, b"synthetic")
    unrelated = paths.data / "keep.txt"
    atomic_write_private(unrelated, b"keep")

    store.purge()
    store.purge()

    assert paths.token_file.exists() is False
    assert paths.account_scope_file.exists() is False
    assert paths.activity_database.exists() is False
    assert paths.summary_file.exists() is False
    assert unrelated.read_bytes() == b"keep"


def test_empty_purge_is_idempotent_and_non_mutating(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    AuthStore(paths).purge()

    assert paths.state.exists() is False
    assert paths.data.exists() is False
    assert paths.cache.exists() is False


def test_purge_rejects_symlinked_summary_without_touching_target(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    ensure_private_directory(paths.cache)
    target = tmp_path / "target-summary"
    target.write_bytes(b"keep")
    paths.summary_file.symlink_to(target)

    with pytest.raises(AuthStorageError):
        AuthStore(paths).purge()

    assert target.read_bytes() == b"keep"


def test_login_without_tokens_uses_interactive_credentials(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    gateway = _FakeGateway()
    credentials = _FakeCredentials()
    service = AuthService(AuthStore(paths), gateway, credentials)

    status = service.login()

    assert status == AuthStatus(configured=True, verified=True, account_scoped=True)
    assert gateway.restore_calls == []
    assert gateway.authenticate_calls == [
        Credentials(
            email="runner@example.test",
            password="fabricated-password",  # noqa: S106 - fabricated test credential
        )
    ]
    assert credentials.read_count == 1


def test_login_with_tokens_restores_without_reading_credentials(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session(marker="stored"))
    gateway = _FakeGateway(restored=_session(marker="refreshed"))
    credentials = _FakeCredentials()
    service = AuthService(store, gateway, credentials)

    service.login()

    assert gateway.restore_calls == [_token("stored")]
    assert gateway.authenticate_calls == []
    assert credentials.read_count == 0
    assert paths.token_file.read_bytes() == _token("refreshed")


def test_rejected_stored_tokens_fall_back_to_interactive_login(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session(marker="stored"))
    gateway = _FakeGateway(restored=AuthenticationRejectedError("rejected"))
    credentials = _FakeCredentials()
    service = AuthService(store, gateway, credentials)

    service.login()

    assert len(gateway.restore_calls) == 1
    assert len(gateway.authenticate_calls) == 1
    assert credentials.read_count == 1


def test_rate_limited_restore_does_not_prompt_for_credentials(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session(marker="stored"))
    gateway = _FakeGateway(restored=AuthRateLimitedError("rate limited"))
    credentials = _FakeCredentials()
    service = AuthService(store, gateway, credentials)

    with pytest.raises(AuthRateLimitedError):
        service.login()

    assert credentials.read_count == 0


def test_authentication_mutations_do_not_overlap_activity_refresh(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = AuthService(AuthStore(paths), _FakeGateway(), _FakeCredentials())

    with activity_refresh_lock(paths.sync_lock_file), pytest.raises(AuthRefreshInProgressError):
        service.login()


def test_service_status_logout_and_purge_delegate_to_store(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = AuthStore(paths)
    store.persist(_session())
    service = AuthService(store, _FakeGateway(), _FakeCredentials())

    assert service.status().configured is True
    service.logout()
    assert service.status().configured is False
    service.purge()
    assert service.status().account_scoped is False
