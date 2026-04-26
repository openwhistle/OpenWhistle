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
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class LDAPUserInfo:
    username: str
    email: str | None


class LDAPAuthError(Exception):
    """Raised when LDAP authentication fails for any reason."""


def _make_server(cfg: object) -> object:
    import ssl  # noqa: PLC0415

    from ldap3 import Server, Tls  # noqa: PLC0415

    from app.config import Settings  # noqa: PLC0415
    c: Settings = cfg  # type: ignore[assignment]

    tls = Tls(validate=ssl.CERT_NONE) if c.ldap_use_ssl else None
    return Server(c.ldap_server, port=c.ldap_port, use_ssl=c.ldap_use_ssl, tls=tls)


async def authenticate_ldap(username: str, password: str) -> LDAPUserInfo:
    """Verify LDAP credentials and return user info. Raises LDAPAuthError on failure.

    Runs ldap3 (sync) in asyncio.to_thread to avoid blocking the event loop.
    """
    import asyncio

    return await asyncio.to_thread(_authenticate_ldap_sync, username, password)


def _authenticate_ldap_sync(username: str, password: str) -> LDAPUserInfo:
    from ldap3 import ALL_ATTRIBUTES, SYNC, Connection  # noqa: PLC0415
    from ldap3.core.exceptions import LDAPException  # noqa: PLC0415

    from app.config import settings

    if not settings.ldap_enabled:
        raise LDAPAuthError("LDAP is not enabled")

    server = _make_server(settings)

    # Step 1: service-account bind to find the user entry
    try:
        service_conn = Connection(
            server,
            user=settings.ldap_bind_dn,
            password=settings.ldap_bind_password,
            auto_bind=True,
            client_strategy=SYNC,
            raise_exceptions=True,
        )
    except LDAPException as exc:
        log.error("LDAP service bind failed: %s", exc)
        raise LDAPAuthError("LDAP service bind failed") from exc

    search_filter = settings.ldap_user_filter.replace("{username}", username)
    service_conn.search(
        search_base=settings.ldap_base_dn,
        search_filter=search_filter,
        attributes=ALL_ATTRIBUTES,
    )

    if not service_conn.entries:
        raise LDAPAuthError(f"LDAP user not found: {username}")

    entry = service_conn.entries[0]
    user_dn = entry.entry_dn
    service_conn.unbind()

    # Step 2: re-bind as the user to verify the password
    try:
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=True,
            client_strategy=SYNC,
            raise_exceptions=True,
        )
        user_conn.unbind()
    except LDAPException as exc:
        raise LDAPAuthError("Invalid LDAP credentials") from exc

    # Extract attributes
    attr_username = settings.ldap_attr_username
    attr_email = settings.ldap_attr_email

    resolved_username = (
        str(entry[attr_username]) if attr_username in entry else username
    )
    email: str | None = (
        str(entry[attr_email]) if attr_email in entry else None
    )

    return LDAPUserInfo(username=resolved_username, email=email)
