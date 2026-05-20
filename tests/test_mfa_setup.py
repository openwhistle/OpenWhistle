"""Tests for the first-login TOTP setup flow (/admin/mfa/setup)."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminUser
from app.services.auth import hash_password, store_totp_setup_pending

# ─── helpers ──────────────────────────────────────────────────────────────────


def _get_csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


async def _create_user_totp_disabled(
    db: AsyncSession,
    username: str | None = None,
    totp_secret: str = "JBSWY3DPEHPK3PXP",
) -> AdminUser:
    user = AdminUser(
        id=uuid.uuid4(),
        username=username or f"setup_user_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("SetupPass!123"),
        totp_secret=totp_secret,
        totp_enabled=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ─── login redirect for totp_enabled=False users ──────────────────────────────


@pytest.mark.asyncio
async def test_login_with_totp_disabled_redirects_to_setup(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A user with totp_enabled=False is redirected to /admin/mfa/setup after login."""
    user = await _create_user_totp_disabled(db_session)

    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        "/admin/login",
        data={"username": user.username, "password": "SetupPass!123", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin/mfa/setup" in resp.headers["location"]


# ─── GET /admin/mfa/setup ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mfa_setup_get_with_valid_token_shows_qr(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /admin/mfa/setup?token=<valid> renders the QR code image."""
    from app.redis_client import get_redis

    user = await _create_user_totp_disabled(db_session)
    redis = await get_redis()
    setup_token = "test-setup-token-valid-001"
    await store_totp_setup_pending(redis, setup_token, str(user.id))

    resp = await client.get(f"/admin/mfa/setup?token={setup_token}")
    assert resp.status_code == 200
    assert "data:image/png;base64," in resp.text


@pytest.mark.asyncio
async def test_mfa_setup_get_without_token_redirects_to_login(
    client: AsyncClient,
) -> None:
    """GET /admin/mfa/setup without token redirects to login."""
    resp = await client.get("/admin/mfa/setup", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["location"]


@pytest.mark.asyncio
async def test_mfa_setup_get_with_invalid_token_redirects_to_login(
    client: AsyncClient,
) -> None:
    """GET /admin/mfa/setup with unknown token redirects to login."""
    resp = await client.get(
        "/admin/mfa/setup?token=totally-fake-token-xyz", follow_redirects=False
    )
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["location"]


@pytest.mark.asyncio
async def test_mfa_setup_get_does_not_consume_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Visiting the setup page (GET) twice should still work — token is not consumed."""
    from app.redis_client import get_redis

    user = await _create_user_totp_disabled(db_session)
    redis = await get_redis()
    setup_token = "test-setup-token-not-consumed"
    await store_totp_setup_pending(redis, setup_token, str(user.id))

    resp1 = await client.get(f"/admin/mfa/setup?token={setup_token}")
    assert resp1.status_code == 200

    resp2 = await client.get(f"/admin/mfa/setup?token={setup_token}")
    assert resp2.status_code == 200


# ─── POST /admin/mfa/setup ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mfa_setup_post_with_invalid_code_shows_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST with a wrong TOTP code re-renders the setup page with an error."""
    from app.redis_client import get_redis

    user = await _create_user_totp_disabled(db_session)
    redis = await get_redis()
    setup_token = "test-setup-token-bad-code"
    await store_totp_setup_pending(redis, setup_token, str(user.id))

    get_resp = await client.get(f"/admin/mfa/setup?token={setup_token}")
    csrf = _get_csrf(get_resp.text)

    resp = await client.post(
        "/admin/mfa/setup",
        data={"csrf_token": csrf, "temp_token": setup_token, "totp_code": "000000"},
    )
    assert resp.status_code == 200
    assert "data:image/png;base64," in resp.text  # QR still shown


@pytest.mark.asyncio
async def test_mfa_setup_post_with_invalid_token_redirects_to_login(
    client: AsyncClient,
) -> None:
    """POST with an unknown/expired setup token redirects to login."""
    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        "/admin/mfa/setup",
        data={
            "csrf_token": csrf,
            "temp_token": "expired-setup-token-xyz",
            "totp_code": "123456",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["location"]


@pytest.mark.asyncio
async def test_mfa_setup_post_with_valid_code_enables_totp_and_logs_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST with a valid TOTP code sets totp_enabled=True and redirects to dashboard."""
    from sqlalchemy import select

    from app.redis_client import get_redis

    totp_secret = pyotp.random_base32()
    user = await _create_user_totp_disabled(
        db_session, totp_secret=totp_secret
    )
    redis = await get_redis()
    setup_token = "test-setup-token-success-001"
    await store_totp_setup_pending(redis, setup_token, str(user.id))

    get_resp = await client.get(f"/admin/mfa/setup?token={setup_token}")
    csrf = _get_csrf(get_resp.text)

    valid_code = pyotp.TOTP(totp_secret).now()
    resp = await client.post(
        "/admin/mfa/setup",
        data={"csrf_token": csrf, "temp_token": setup_token, "totp_code": valid_code},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin/dashboard" in resp.headers["location"]

    # Verify totp_enabled was persisted in the DB (populate_existing forces re-fetch)
    result = await db_session.execute(
        select(AdminUser)
        .where(AdminUser.id == user.id)
        .execution_options(populate_existing=True)
    )
    updated = result.scalar_one_or_none()
    assert updated is not None
    assert updated.totp_enabled is True


@pytest.mark.asyncio
async def test_full_first_login_setup_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """End-to-end: create user → login → redirected to setup → scan → verify → dashboard."""
    totp_secret = pyotp.random_base32()
    user = await _create_user_totp_disabled(
        db_session, totp_secret=totp_secret
    )

    # Step 1: POST /admin/login — should redirect to /admin/mfa/setup
    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")

    login_resp = await client.post(
        "/admin/login",
        data={"username": user.username, "password": "SetupPass!123", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert login_resp.status_code == 302
    setup_url = login_resp.headers["location"]
    assert "/admin/mfa/setup" in setup_url

    # Step 2: GET setup page — shows QR code
    setup_resp = await client.get(setup_url)
    assert setup_resp.status_code == 200
    assert "data:image/png;base64," in setup_resp.text
    csrf2 = _get_csrf(setup_resp.text)

    # Extract temp_token from form
    token_m = re.search(r'name="temp_token" value="([^"]+)"', setup_resp.text)
    assert token_m, "temp_token not found in setup page"
    temp_token = token_m.group(1)

    # Step 3: POST setup with valid code — redirects to dashboard
    valid_code = pyotp.TOTP(totp_secret).now()
    submit_resp = await client.post(
        "/admin/mfa/setup",
        data={"csrf_token": csrf2, "temp_token": temp_token, "totp_code": valid_code},
        follow_redirects=False,
    )
    assert submit_resp.status_code == 302
    assert "/admin/dashboard" in submit_resp.headers["location"]
