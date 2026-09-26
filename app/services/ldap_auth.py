"""LDAP / Active Directory authentication service.

Authentication flow:
  1. Bind with service account (LDAP_BIND_DN / LDAP_BIND_PASSWORD).
  2. Search for the user entry matching LDAP_USER_FILTER with {username} substituted.
  3. Re-bind with the found user's DN and the supplied password to verify credentials.
  4. Return the user's username and email from their LDAP attributes.

TOTP verification is performed by the caller after a successful LDAP bind.
The local AdminUser record is created on first login and kept in sync on every login.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings

log = logging.getLogger(__name__)


@dataclass
class LDAPUserInfo:
    username: str
    email: str | None


class LDAPAuthError(Exception):
    """Raised when LDAP authentication fails for any reason."""


@contextmanager
def _connection(cfg: Settings) -> Iterator[Any]:
    """A connection with certificate verification; StartTLS done before any bind.

    Always unbound on exit, also when StartTLS, a bind or a search fails.
    """
    import ldap  # noqa: PLC0415

    scheme = "ldaps" if cfg.ldap_use_ssl else "ldap"
    conn = ldap.initialize(f"{scheme}://{cfg.ldap_server}:{cfg.ldap_port}")
    try:
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 10)
        if cfg.ldap_use_ssl or cfg.ldap_start_tls:
            conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
            # System CA store; a private CA via the standard LDAPTLS_CACERT(DIR)
            # variables. libldap does not copy those paths to a new connection,
            # so a per-connection context would silently ignore them.
            for option in (ldap.OPT_X_TLS_CACERTFILE, ldap.OPT_X_TLS_CACERTDIR):
                if path := ldap.get_option(option):
                    conn.set_option(option, path)
            # The new context also drops a host TLS_PROTOCOL_MIN; set the floor here.
            # Client certificates (TLS_CERT/TLS_KEY) are not supported and not copied.
            conn.set_option(ldap.OPT_X_TLS_PROTOCOL_MIN, ldap.OPT_X_TLS_PROTOCOL_TLS1_2)
            conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)  # must follow the other TLS options
        if cfg.ldap_start_tls and not cfg.ldap_use_ssl:
            conn.start_tls_s()
        yield conn
    finally:
        try:
            conn.unbind_s()
        except ldap.LDAPError:
            pass  # closing a connection that already failed


def _first(attrs: dict[str, list[bytes]], name: str) -> str | None:
    values = attrs.get(name)
    return values[0].decode() if values else None


async def authenticate_ldap(username: str, password: str) -> LDAPUserInfo:
    """Verify LDAP credentials and return user info. Raises LDAPAuthError on failure.

    Runs python-ldap (sync) in asyncio.to_thread to avoid blocking the event loop.
    """
    import asyncio

    return await asyncio.to_thread(_authenticate_ldap_sync, username, password)


def _authenticate_ldap_sync(username: str, password: str) -> LDAPUserInfo:
    from app.config import settings  # noqa: PLC0415

    if not settings.ldap_enabled:
        raise LDAPAuthError("LDAP is not enabled")
    if not password:
        # A simple bind with an empty password is an anonymous bind and succeeds.
        raise LDAPAuthError("Empty password")

    try:
        import ldap  # noqa: PLC0415
        from ldap.filter import escape_filter_chars  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("LDAP_ENABLED needs the 'ldap' extra (python-ldap).") from exc

    try:
        with _connection(settings) as service:
            service.simple_bind_s(settings.ldap_bind_dn, settings.ldap_bind_password)
            found = service.search_s(
                settings.ldap_base_dn,
                ldap.SCOPE_SUBTREE,
                settings.ldap_user_filter.replace("{username}", escape_filter_chars(username)),
                [settings.ldap_attr_username, settings.ldap_attr_email],
            )
    except ldap.LDAPError as exc:
        log.error("LDAP service bind or search failed: %s", type(exc).__name__)
        raise LDAPAuthError("LDAP service bind failed") from exc

    entries = [(dn, attrs) for dn, attrs in found if dn]  # referrals have no DN
    if not entries:
        raise LDAPAuthError("LDAP user not found")
    user_dn, attrs = entries[0]

    try:
        with _connection(settings) as user_conn:
            user_conn.simple_bind_s(user_dn, password)
    except ldap.LDAPError as exc:
        raise LDAPAuthError("Invalid LDAP credentials") from exc

    return LDAPUserInfo(
        username=_first(attrs, settings.ldap_attr_username) or username,
        email=_first(attrs, settings.ldap_attr_email),
    )
