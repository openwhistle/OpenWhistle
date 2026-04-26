"""Coverage tests for app/api/auth.py gaps.

Covers:
- admin_root redirect (lines 28-29)
- login_mfa_post with invalid/expired temp_token (lines 107-113)
- last_login_at update on successful MFA (lines 140-144)
- logout session revocation in Redis (lines 162-165)
- decode_access_token_exp missing exp claim (services/auth.py lines 56-65)
- get_session_ttl for non-existent key (services/auth.py lines 68-72)
"""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import AdminUser
from app.services.auth import (
    create_access_token,
    decode_access_token_exp,
    get_session_ttl,
    hash_password,
    store_session,
    store_totp_pending,
    validate_session,
)

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _create_admin(db: AsyncSession, username: str = "") -> tuple[AdminUser, str]:
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=username or f"cov_auth_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("AuthTest!Pass1"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login(client: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    """Full login flow: password → MFA → session cookie set."""
    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")

    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "AuthTest!Pass1", "csrf_token": csrf},
    )
    temp_m = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    csrf_m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    totp_code = pyotp.TOTP(totp_secret).now()
    await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": csrf_m.group(1) if csrf_m else "",
            "temp_token": temp_m.group(1) if temp_m else "",
            "totp_code": totp_code,
        },
    )


# ─── admin_root redirect ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_root_redirects_to_login(client: AsyncClient) -> None:
    """/admin (no trailing slash) must redirect to /admin/login."""
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/admin/login")


@pytest.mark.asyncio
async def test_admin_root_slash_redirects_to_login(client: AsyncClient) -> None:
    """/admin/ (trailing slash) must also redirect to /admin/login."""
    resp = await client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/admin/login")


# ─── MFA — invalid / expired temp_token ───────────────────────────────────────


@pytest.mark.asyncio
async def test_mfa_with_invalid_temp_token_redirects_to_login(
    client: AsyncClient,
) -> None:
    """Submitting MFA with a completely unknown temp_token redirects to /admin/login."""
    get_resp = await client.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": csrf_token,
            "temp_token": "this-token-does-not-exist-in-redis",
            "totp_code": "000000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/admin/login")


@pytest.mark.asyncio
async def test_mfa_with_expired_temp_token_redirects_to_login(
    client: AsyncClient,
) -> None:
    """A temp_token that was stored but then deleted (simulating expiry) redirects to login."""
    from app.redis_client import get_redis

    redis = await get_redis()

    # Store and immediately delete a pending token so it's gone by the time MFA is submitted
    temp_token = "already-expired-token-xyz"
    await store_totp_pending(redis, temp_token, str(uuid.uuid4()))
    from app.services.auth import _TOTP_PENDING_PREFIX  # noqa: PLC2701
    await redis.delete(f"{_TOTP_PENDING_PREFIX}{temp_token}")

    get_resp = await client.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        "/admin/login/mfa",
        data={"csrf_token": csrf_token, "temp_token": temp_token, "totp_code": "000000"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/admin/login")


# ─── last_login_at updated on successful MFA ─────────────────────────────────


@pytest.mark.asyncio
async def test_last_login_at_is_set_after_successful_mfa(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A successful MFA login sets last_login_at on the AdminUser record."""
    from datetime import UTC, datetime, timedelta

    admin, totp_secret = await _create_admin(db_session)
    assert admin.last_login_at is None

    await _login(client, admin, totp_secret)

    # Reload the user from DB to see the updated value
    result = await db_session.execute(select(AdminUser).where(AdminUser.id == admin.id))
    updated = result.scalar_one()
    assert updated.last_login_at is not None
    # Timestamp should be within the last minute
    assert updated.last_login_at >= datetime.now(UTC) - timedelta(minutes=1)


# ─── logout session revocation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_revokes_redis_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After logout, the session token must no longer be valid in Redis."""
    from app.redis_client import get_redis

    admin, totp_secret = await _create_admin(db_session)
    await _login(client, admin, totp_secret)

    # Capture the session token before logout
    session_token = client.cookies.get("ow_session")
    assert session_token is not None

    redis = await get_redis()
    assert await validate_session(redis, session_token) is True

    await client.get("/admin/logout", follow_redirects=True)

    assert await validate_session(redis, session_token) is False


@pytest.mark.asyncio
async def test_logout_without_session_cookie_does_not_crash(
    client: AsyncClient,
) -> None:
    """GET /admin/logout with no session cookie must complete without error."""
    resp = await client.get("/admin/logout", follow_redirects=True)
    assert resp.status_code == 200


# ─── services/auth.py: decode_access_token_exp ───────────────────────────────


def test_decode_access_token_exp_returns_none_when_exp_missing() -> None:
    """decode_access_token_exp returns None if the JWT has no 'exp' claim."""
    payload = {"sub": str(uuid.uuid4()), "iat": 1000000}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    result = decode_access_token_exp(token)
    assert result is None


def test_decode_access_token_exp_returns_none_for_invalid_token() -> None:
    """decode_access_token_exp returns None for a garbage token."""
    result = decode_access_token_exp("not.a.valid.jwt")
    assert result is None


def test_decode_access_token_exp_returns_datetime_for_valid_token() -> None:
    """decode_access_token_exp returns a datetime for a normal access token."""
    from datetime import datetime

    token = create_access_token(str(uuid.uuid4()))
    result = decode_access_token_exp(token)
    assert result is not None
    assert isinstance(result, datetime)


# ─── services/auth.py: get_session_ttl ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_ttl_returns_zero_for_nonexistent_key(
    client: AsyncClient,
) -> None:
    """get_session_ttl returns 0 when the session key does not exist in Redis."""
    from app.redis_client import get_redis

    redis = await get_redis()
    ttl = await get_session_ttl(redis, "nonexistent-token-xyz-abc")
    assert ttl == 0


@pytest.mark.asyncio
async def test_get_session_ttl_returns_positive_for_active_session(
    client: AsyncClient,
) -> None:
    """get_session_ttl returns a positive number for an active session."""
    from app.redis_client import get_redis

    redis = await get_redis()
    token = create_access_token(str(uuid.uuid4()))
    await store_session(redis, str(uuid.uuid4()), token)

    ttl = await get_session_ttl(redis, token)
    assert ttl > 0
