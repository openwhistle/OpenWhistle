"""LDAP login via python-ldap: TLS verified, StartTLS before any bind, filter escaped."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import ldap
import pytest

from app.config import settings
from app.services import ldap_auth


@pytest.fixture
def ldap_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "ldap_enabled": True, "ldap_server": "dir.example.org", "ldap_port": 389,
        "ldap_use_ssl": False, "ldap_start_tls": False, "ldap_bind_dn": "cn=svc",
        "ldap_bind_password": "svc-pw", "ldap_base_dn": "dc=example,dc=org",
        "ldap_user_filter": "(uid={username})", "ldap_attr_username": "uid",
        "ldap_attr_email": "mail",
    }.items():
        monkeypatch.setattr(settings, name, value)


def _conn(entries: list[tuple[str | None, dict[str, list[bytes]]]] | None = None) -> MagicMock:
    conn = MagicMock()
    conn.search_s.return_value = entries if entries is not None else [
        ("uid=alice,dc=example,dc=org", {"uid": [b"alice"], "mail": [b"alice@example.org"]})
    ]
    return conn


def test_disabled_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ldap_enabled", False)
    with pytest.raises(ldap_auth.LDAPAuthError):
        ldap_auth._authenticate_ldap_sync("alice", "pw")


def test_success_returns_directory_attributes(ldap_on: None) -> None:
    conn = _conn()
    with patch("ldap.initialize", return_value=conn):
        info = ldap_auth._authenticate_ldap_sync("alice", "pw")
    assert (info.username, info.email) == ("alice", "alice@example.org")
    assert conn.simple_bind_s.call_args_list[-1].args == ("uid=alice,dc=example,dc=org", "pw")


def test_filter_escapes_the_username(ldap_on: None) -> None:
    conn = _conn()
    with patch("ldap.initialize", return_value=conn):
        ldap_auth._authenticate_ldap_sync("a*)(uid=*", "pw")
    assert conn.search_s.call_args.args[2] == r"(uid=a\2a\29\28uid=\2a)"


def test_empty_password_never_binds(ldap_on: None) -> None:
    with patch("ldap.initialize") as init, pytest.raises(ldap_auth.LDAPAuthError):
        ldap_auth._authenticate_ldap_sync("alice", "")
    init.assert_not_called()


@pytest.mark.parametrize("error", [ldap.INVALID_CREDENTIALS, ldap.SERVER_DOWN])
def test_bind_errors_become_auth_errors(ldap_on: None, error: type[Exception]) -> None:
    conn = _conn()
    conn.simple_bind_s.side_effect = error({"desc": "x"})
    with patch("ldap.initialize", return_value=conn), pytest.raises(ldap_auth.LDAPAuthError):
        ldap_auth._authenticate_ldap_sync("alice", "pw")


def test_unknown_user_is_refused(ldap_on: None) -> None:
    with patch("ldap.initialize", return_value=_conn([(None, {})])), \
         pytest.raises(ldap_auth.LDAPAuthError):
        ldap_auth._authenticate_ldap_sync("nobody", "pw")


def test_ldaps_demands_a_valid_certificate(ldap_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ldap_use_ssl", True)
    conn = _conn()
    with patch("ldap.initialize", return_value=conn) as init:
        ldap_auth._authenticate_ldap_sync("alice", "pw")
    assert init.call_args.args[0] == "ldaps://dir.example.org:389"
    conn.set_option.assert_any_call(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
    conn.start_tls_s.assert_not_called()


def test_start_tls_happens_before_any_bind(ldap_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ldap_start_tls", True)
    calls: list[str] = []
    conn = _conn()
    conn.start_tls_s.side_effect = lambda: calls.append("starttls")
    conn.simple_bind_s.side_effect = lambda *a: calls.append("bind")
    with patch("ldap.initialize", return_value=conn):
        ldap_auth._authenticate_ldap_sync("alice", "pw")
    assert calls[0] == "starttls" and calls.count("starttls") == 2
    conn.set_option.assert_any_call(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)


def test_plain_ldap_does_not_start_tls(ldap_on: None) -> None:
    conn = _conn()
    with patch("ldap.initialize", return_value=conn):
        ldap_auth._authenticate_ldap_sync("alice", "pw")
    conn.start_tls_s.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_ldap_runs_in_a_thread(ldap_on: None) -> None:
    from unittest.mock import AsyncMock

    to_thread = AsyncMock(return_value=ldap_auth.LDAPUserInfo("alice", None))
    with patch("asyncio.to_thread", new=to_thread):
        await ldap_auth.authenticate_ldap("alice", "pw")
    assert to_thread.call_args.args[0] is ldap_auth._authenticate_ldap_sync


def test_missing_extra_names_it(ldap_on: None) -> None:
    with patch.dict("sys.modules", {"ldap": None}), \
         pytest.raises(RuntimeError, match="'ldap' extra"):
        ldap_auth._authenticate_ldap_sync("alice", "pw")
