"""Integration tests for admin session expiry warning endpoints."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminUser
from app.services.auth import (
    create_access_token,
    decode_access_token_exp,
    hash_password,
)

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _create_admin(db: AsyncSession, suffix: str = "") -> tuple[AdminUser, str]:
    """Create a test admin user, return (user, totp_secret)."""
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"exp_admin_{suffix or uuid.uuid4().hex[:6]}",
        password_hash=hash_password("Expiry!Test123"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login_admin(ac: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    """Full two-step admin login."""
    get_resp = await ac.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")

    login_resp = await ac.post(
        "/admin/login",
        data={
            "username": admin.username,
            "password": "Expiry!Test123",
            "csrf_token": csrf_token,
        },
    )
    temp_m = re.search(r'name="temp_token" value="([^"]+)"', login_resp.text)
    temp_token = temp_m.group(1) if temp_m else ""
    csrf_m = re.search(r'name="csrf_token" value="([^"]+)"', login_resp.text)
    mfa_csrf = csrf_m.group(1) if csrf_m else ""

    totp_code = pyotp.TOTP(totp_secret).now()
    await ac.post(
        "/admin/login/mfa",
        data={"csrf_token": mfa_csrf, "temp_token": temp_token, "totp_code": totp_code},
    )


# ─── Unit tests for auth service functions ────────────────────────────────────


def test_decode_access_token_exp_returns_datetime() -> None:
    """decode_access_token_exp returns a UTC datetime for a valid token."""
    from datetime import UTC, datetime

    token = create_access_token("test-user-id")
    exp = decode_access_token_exp(token)

    assert exp is not None
    assert exp.tzinfo is not None
    assert exp > datetime.now(UTC)


def test_decode_access_token_exp_returns_none_for_invalid() -> None:
    """decode_access_token_exp returns None for a garbage token."""
    exp = decode_access_token_exp("not.a.real.jwt")
    assert exp is None


def test_create_access_token_exp_is_in_future() -> None:
    """Newly created tokens expire in the future."""
    from datetime import UTC, datetime

    token = create_access_token("abc123")
    exp = decode_access_token_exp(token)
    assert exp is not None
    assert exp > datetime.now(UTC)


# ─── TTL endpoint ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_ttl_returns_401_without_session(client: AsyncClient) -> None:
    """GET /admin/session/ttl requires authentication."""
    resp = await client.get("/admin/session/ttl")
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_ttl_returns_positive_seconds_when_authenticated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /admin/session/ttl returns ttl_seconds > 0 for an active session."""
    admin, totp_secret = await _create_admin(db_session, "ttl1")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/session/ttl")
    assert resp.status_code == 200

    data = resp.json()
    assert "ttl_seconds" in data
    assert "expires_at" in data
    assert data["ttl_seconds"] > 0
    assert data["expires_at"] > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_ttl_expires_at_is_in_future(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """expires_at in /admin/session/ttl response is a future Unix timestamp."""
    import time

    admin, totp_secret = await _create_admin(db_session, "ttl2")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/session/ttl")
    data = resp.json()
    assert data["expires_at"] > int(time.time())


# ─── Refresh endpoint ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_refresh_returns_401_without_session(client: AsyncClient) -> None:
    """POST /admin/session/refresh requires authentication."""
    resp = await client.post("/admin/session/refresh")
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_refresh_returns_new_ttl(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /admin/session/refresh returns new ttl_seconds and expires_at."""
    admin, totp_secret = await _create_admin(db_session, "ref1")
    await _login_admin(client, admin, totp_secret)

    resp = await client.post("/admin/session/refresh")
    assert resp.status_code == 200

    data = resp.json()
    assert "ttl_seconds" in data
    assert "expires_at" in data
    assert data["ttl_seconds"] > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_refresh_sets_new_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /admin/session/refresh sets a new ow_session cookie."""
    admin, totp_secret = await _create_admin(db_session, "ref2")
    await _login_admin(client, admin, totp_secret)

    old_cookie = client.cookies.get("ow_session")
    resp = await client.post("/admin/session/refresh")
    assert resp.status_code == 200

    new_cookie = client.cookies.get("ow_session")
    assert new_cookie is not None
    # New token must differ from the old one
    assert new_cookie != old_cookie


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_refresh_new_session_is_still_valid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After /admin/session/refresh the new session allows access to admin pages."""
    admin, totp_secret = await _create_admin(db_session, "ref3")
    await _login_admin(client, admin, totp_secret)

    await client.post("/admin/session/refresh")

    # The refreshed session must still grant dashboard access
    resp = await client.get("/admin/dashboard")
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_refresh_extends_ttl_to_full_duration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After refresh, ttl_seconds is approximately equal to the configured max TTL."""
    from app.config import settings

    admin, totp_secret = await _create_admin(db_session, "ref4")
    await _login_admin(client, admin, totp_secret)

    resp = await client.post("/admin/session/refresh")
    data = resp.json()

    max_ttl = settings.access_token_expire_minutes * 60
    # Allow a 10-second window for test execution time
    assert data["ttl_seconds"] >= max_ttl - 10
    assert data["ttl_seconds"] <= max_ttl


# ─── Template injection ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_contains_session_expiry_banner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Admin dashboard HTML contains the session expiry banner with data-expires."""
    admin, totp_secret = await _create_admin(db_session, "tpl1")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert 'id="session-expiry-banner"' in resp.text
    assert "data-expires=" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_report_detail_contains_session_expiry_banner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Admin report detail page HTML contains the session expiry banner."""
    from app.services.report import create_report

    admin, totp_secret = await _create_admin(db_session, "tpl2")
    await _login_admin(client, admin, totp_secret)

    report, _ = await create_report(db_session, "corruption", "Test report for session expiry.")

    resp = await client.get(f"/admin/reports/{report.id}")
    assert resp.status_code == 200
    assert 'id="session-expiry-banner"' in resp.text
    assert "data-expires=" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_public_pages_do_not_contain_session_expiry_banner(
    client: AsyncClient,
) -> None:
    """Public pages (submit, status) must NOT contain the session expiry banner."""
    for path in ("/submit", "/status"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert 'id="session-expiry-banner"' not in resp.text, (
            f"Session expiry banner should not appear on {path}"
        )
