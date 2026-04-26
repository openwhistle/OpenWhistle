"""Extended coverage tests for app/api/auth.py gaps.

Covers:
- login_post: admin rate-limit lockout path (lines 50-58)
- login_mfa_post: wrong TOTP code → re-rendered MFA form with new temp token (lines 119-130)
- session/ttl GET: returns JSON with ttl_seconds (lines 177-185)
- session/refresh POST: revokes old session, issues new token, sets cookie (lines 188-215)
- services/auth: decode_access_token invalid JWT (returns None), validate_session paths,
  revoke_session, consume_totp_pending, get_user_by_id with bad UUID
"""

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
    decode_access_token,
    hash_password,
    revoke_session,
    store_session,
    store_totp_pending,
    validate_session,
)

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _create_admin(db: AsyncSession, username: str = "") -> tuple[AdminUser, str]:
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=username or f"auth_ext_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("ExtTest!Pass1"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _full_login(client: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")
    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "ExtTest!Pass1", "csrf_token": csrf},
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


# ─── login_post: rate-limit lockout ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_post_shows_locked_message_when_rate_limited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After exceeding max_login_attempts the login page must show a lockout message."""
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.rate_limit import record_admin_login_failure

    admin, _ = await _create_admin(db_session)

    redis = await get_redis()
    for _ in range(settings.max_login_attempts):
        await record_admin_login_failure(redis, admin.username)

    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "ExtTest!Pass1", "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "locked" in resp.text.lower() or "too many" in resp.text.lower()


# ─── login_mfa_post: wrong TOTP ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    __import__("app.config", fromlist=["settings"]).settings.demo_mode,
    reason="000000 is always valid in demo mode — wrong-TOTP path not reachable",
)
async def test_login_mfa_wrong_totp_returns_error_form(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Wrong TOTP code must re-render the MFA form with an error and a new temp_token."""
    admin, _ = await _create_admin(db_session)

    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")
    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "ExtTest!Pass1", "csrf_token": csrf},
    )
    temp_m = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    csrf_m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert temp_m is not None

    old_temp = temp_m.group(1)
    mfa_resp = await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": csrf_m.group(1) if csrf_m else "",
            "temp_token": old_temp,
            "totp_code": "000000",  # deliberately wrong
        },
    )
    assert mfa_resp.status_code == 200
    assert "Invalid" in mfa_resp.text or "invalid" in mfa_resp.text.lower()

    # New temp_token must be different (rotated)
    new_temp_m = re.search(r'name="temp_token" value="([^"]+)"', mfa_resp.text)
    assert new_temp_m is not None
    assert new_temp_m.group(1) != old_temp


# ─── session/ttl ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_ttl_returns_json_with_ttl_seconds(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /admin/session/ttl must return JSON with ttl_seconds > 0."""
    admin, totp_secret = await _create_admin(db_session)
    await _full_login(client, admin, totp_secret)

    resp = await client.get("/admin/session/ttl")
    assert resp.status_code == 200
    data = resp.json()
    assert "ttl_seconds" in data
    assert data["ttl_seconds"] > 0


# ─── session/refresh ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_refresh_extends_session_and_rotates_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /admin/session/refresh must return a new ow_session cookie and positive TTL."""
    admin, totp_secret = await _create_admin(db_session)
    await _full_login(client, admin, totp_secret)

    old_session = client.cookies.get("ow_session")
    assert old_session is not None

    resp = await client.post("/admin/session/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ttl_seconds"] > 0
    assert "expires_at" in data

    new_session = client.cookies.get("ow_session")
    assert new_session is not None
    assert new_session != old_session


@pytest.mark.asyncio
async def test_session_refresh_old_session_is_revoked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After refresh, the old session token must no longer validate in Redis."""
    from app.redis_client import get_redis

    admin, totp_secret = await _create_admin(db_session)
    await _full_login(client, admin, totp_secret)

    old_session = client.cookies.get("ow_session")
    assert old_session is not None

    await client.post("/admin/session/refresh")

    redis = await get_redis()
    assert await validate_session(redis, old_session) is False


# ─── services/auth: decode_access_token (invalid JWT) ────────────────────────


def test_decode_access_token_invalid_jwt_returns_none() -> None:
    """decode_access_token must return None for a garbage token string."""
    result = decode_access_token("not.a.valid.jwt")
    assert result is None


def test_decode_access_token_valid_returns_user_id() -> None:
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id)
    result = decode_access_token(token)
    assert result == user_id


# ─── services/auth: validate_session ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_session_true_for_active_session(client: AsyncClient) -> None:
    from app.redis_client import get_redis

    redis = await get_redis()
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id)
    await store_session(redis, user_id, token)

    assert await validate_session(redis, token) is True


@pytest.mark.asyncio
async def test_validate_session_false_for_unknown_token(client: AsyncClient) -> None:
    from app.redis_client import get_redis

    redis = await get_redis()
    assert await validate_session(redis, "nonexistent-token-xyz") is False


# ─── services/auth: revoke_session ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_session_invalidates_token(client: AsyncClient) -> None:
    from app.redis_client import get_redis

    redis = await get_redis()
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id)
    await store_session(redis, user_id, token)
    assert await validate_session(redis, token) is True

    await revoke_session(redis, token)
    assert await validate_session(redis, token) is False


# ─── services/auth: consume_totp_pending ─────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_totp_pending_returns_user_id_once(client: AsyncClient) -> None:
    from app.redis_client import get_redis
    from app.services.auth import consume_totp_pending

    redis = await get_redis()
    import secrets

    temp_token = secrets.token_urlsafe(32)
    user_id = str(uuid.uuid4())
    await store_totp_pending(redis, temp_token, user_id)

    result = await consume_totp_pending(redis, temp_token)
    assert result == user_id

    second = await consume_totp_pending(redis, temp_token)
    assert second is None


# ─── services/auth: get_user_by_id with invalid UUID ─────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_id_invalid_uuid_returns_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.auth import get_user_by_id

    result = await get_user_by_id(db_session, "not-a-valid-uuid")
    assert result is None


# ─── services/auth: get_user_by_oidc_sub ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_oidc_sub_not_found_returns_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.auth import get_user_by_oidc_sub

    result = await get_user_by_oidc_sub(db_session, "unknown-sub", "https://issuer.example.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_by_username_not_found_returns_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.auth import get_user_by_username

    result = await get_user_by_username(db_session, "this_user_does_not_exist_xyz")
    assert result is None
