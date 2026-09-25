"""LDAP login via python-ldap: TLS verified, StartTLS before any bind, filter escaped."""

from __future__ import annotations

import datetime
import ipaddress
import os
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import ldap
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

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


def test_options_bound_referrals_and_timeout(ldap_on: None) -> None:
    conn = _conn()
    with patch("ldap.initialize", return_value=conn):
        ldap_auth._authenticate_ldap_sync("alice", "pw")
    conn.set_option.assert_any_call(ldap.OPT_REFERRALS, 0)
    conn.set_option.assert_any_call(ldap.OPT_NETWORK_TIMEOUT, 10)


def test_wrong_password_still_closes_both_connections(ldap_on: None) -> None:
    service, user = _conn(), _conn()
    user.simple_bind_s.side_effect = ldap.INVALID_CREDENTIALS({"desc": "x"})
    with patch("ldap.initialize", side_effect=[service, user]), \
         pytest.raises(ldap_auth.LDAPAuthError, match="Invalid LDAP credentials"):
        ldap_auth._authenticate_ldap_sync("alice", "wrong")
    service.unbind_s.assert_called_once()
    user.unbind_s.assert_called_once()


def test_failed_search_still_closes_the_service_connection(ldap_on: None) -> None:
    service = _conn()
    service.search_s.side_effect = ldap.SERVER_DOWN({"desc": "x"})
    with patch("ldap.initialize", return_value=service), \
         pytest.raises(ldap_auth.LDAPAuthError):
        ldap_auth._authenticate_ldap_sync("alice", "pw")
    service.unbind_s.assert_called_once()


def test_failed_start_tls_closes_and_a_failing_unbind_is_swallowed(
    ldap_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ldap_start_tls", True)
    service = _conn()
    service.start_tls_s.side_effect = ldap.CONNECT_ERROR({"desc": "x"})
    service.unbind_s.side_effect = ldap.SERVER_DOWN({"desc": "x"})
    with patch("ldap.initialize", return_value=service), \
         pytest.raises(ldap_auth.LDAPAuthError, match="service bind failed"):
        ldap_auth._authenticate_ldap_sync("alice", "pw")
    service.unbind_s.assert_called_once()
    service.simple_bind_s.assert_not_called()


# ── Real TLS: libldap against a local TLS server ─────────────────────────────


def _pki(directory: Path, san: x509.GeneralName) -> None:
    """A throwaway CA (ca.pem) and a server certificate for ``san`` it signed."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenWhistle test CA")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ldap test")]))
        .issuer_name(ca_name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (directory / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory / "cert.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (directory / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))


# A subprocess: libldap reads LDAPTLS_CACERT once per process, and a global
# set_option would leak into every later test.
_CLIENT = """
import sys, types, ldap
from app.services.ldap_auth import _connection
cfg = types.SimpleNamespace(
    ldap_use_ssl=True, ldap_start_tls=False, ldap_server="127.0.0.1", ldap_port=int(sys.argv[1])
)
try:
    with _connection(cfg) as conn:
        conn.simple_bind_s("cn=x", "pw")
except ldap.LDAPError as exc:
    print(type(exc).__name__, exc.args[0].get("info", ""))
"""


def _ldaps_attempt(
    tmp_path: Path,
    san: x509.GeneralName,
    *,
    trust_ca: bool,
    extra_env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Connect via ``_connection`` to a TLS server that is not LDAP.

    Returns whether the bind request (the password) reached the server, and the
    client's error. libldap checks the name after the TLS handshake, so a
    finished handshake alone proves nothing; the bind being withheld does.
    """
    _pki(tmp_path, san)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(20)
    received = {"bind": False}

    def serve() -> None:
        try:
            sock, _ = server.accept()
            with ctx.wrap_socket(sock, server_side=True) as tls:
                received["bind"] = bool(tls.recv(1024))
                tls.sendall(b"not ldap\n")
        except OSError:  # ssl.SSLError included: the client refused the handshake
            pass

    thread = threading.Thread(target=serve)
    thread.start()
    env = {**os.environ, "HOME": str(tmp_path)}  # no ~/.ldaprc
    for name in ("LDAPTLS_CACERT", "LDAPTLS_REQCERT"):
        env.pop(name, None)
    if trust_ca:
        env["LDAPTLS_CACERT"] = str(tmp_path / "ca.pem")
    env.update(extra_env or {})
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _CLIENT, str(server.getsockname()[1])],
            env=env, capture_output=True, text=True, timeout=60, check=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
    finally:
        thread.join(30)
        server.close()
    return received["bind"], result.stdout.strip()


# LDAPTLS_REQCERT=never stands for a host ldap.conf that weakens the default:
# the per-connection DEMAND context still wins.
@pytest.mark.parametrize("extra_env", [{}, {"LDAPTLS_REQCERT": "never"}])
def test_ldaps_refuses_a_certificate_for_another_name(
    tmp_path: Path, extra_env: dict[str, str]
) -> None:
    # The right-name tests use 127.0.0.1, not "localhost": libldap swaps
    # "localhost" for the machine's hostname before the name check.
    bind_sent, error = _ldaps_attempt(
        tmp_path, x509.DNSName("wrong.example"), trust_ca=True, extra_env=extra_env
    )
    # Same CA as the right-name test, which passes: the name is what is refused.
    # No message check: OpenSSL says "hostname does not match", GnuTLS
    # (Ubuntu's libldap) says "(unknown error code)".
    assert not bind_sent
    assert error.startswith(("SERVER_DOWN", "CONNECT_ERROR")), error


def test_ldaps_accepts_the_right_name_signed_by_ldaptls_cacert(tmp_path: Path) -> None:
    bind_sent, error = _ldaps_attempt(
        tmp_path, x509.IPAddress(ipaddress.ip_address("127.0.0.1")), trust_ca=True
    )
    assert bind_sent  # TLS accepted; the bind then fails only because it is not LDAP
    assert error.startswith("SERVER_DOWN"), error
    assert "hostname" not in error.lower(), error


@pytest.mark.parametrize("extra_env", [{}, {"LDAPTLS_REQCERT": "never"}])
def test_ldaps_without_the_private_ca_refuses_the_handshake(
    tmp_path: Path, extra_env: dict[str, str]
) -> None:
    bind_sent, error = _ldaps_attempt(
        tmp_path, x509.IPAddress(ipaddress.ip_address("127.0.0.1")), trust_ca=False,
        extra_env=extra_env,
    )
    assert not bind_sent
    assert error.startswith(("SERVER_DOWN", "CONNECT_ERROR")), error
