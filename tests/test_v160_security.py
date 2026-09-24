"""v1.6.0 security: one test per guard (setup token, TOTP at rest, sessions, roles, audit scope)."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.setup import SetupStatus
from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password
from tests.conftest import setup_token

_PASSWORD = "V160-Test-Password"  # noqa: S105


async def _csrf(client: AsyncClient, path: str) -> str:
    await client.get(path)
    return client.cookies.get("ow_csrf") or ""


async def _reset_setup(db: AsyncSession) -> None:
    """Make the instance look freshly installed for one test."""
    await db.execute(
        text(
            "INSERT INTO setup_status (id, completed) VALUES (1, true) "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    await db.execute(text("UPDATE setup_status SET completed = false WHERE id = 1"))
    await db.commit()


async def _restore_setup(db: AsyncSession) -> None:
    await db.execute(text("UPDATE setup_status SET completed = true WHERE id = 1"))
    await db.commit()


def _setup_form(csrf: str, token: str | None) -> dict[str, str]:
    secret = pyotp.random_base32()
    form = {
        "csrf_token": csrf,
        "username": f"setup_{uuid.uuid4().hex[:8]}",
        "password": _PASSWORD,
        "password_confirm": _PASSWORD,
        "totp_secret": secret,
        "totp_code": pyotp.TOTP(secret).now(),
    }
    if token is not None:
        form["setup_token"] = token
    return form


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "wrong-token"])
async def test_setup_without_the_right_token_is_refused(
    client: AsyncClient, db_session: AsyncSession, token: str | None
) -> None:
    await _reset_setup(db_session)
    try:
        csrf = await _csrf(client, "/setup")
        form = _setup_form(csrf, token)
        resp = await client.post("/setup", data=form, follow_redirects=False)
        assert resp.status_code == 403
        created = await db_session.scalar(
            select(AdminUser).where(AdminUser.username == form["username"])
        )
        assert created is None
    finally:
        await _restore_setup(db_session)


@pytest.mark.asyncio
async def test_setup_with_the_token_creates_the_admin_and_deletes_the_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY

    await _reset_setup(db_session)
    try:
        csrf = await _csrf(client, "/setup")
        form = _setup_form(csrf, await setup_token())
        resp = await client.post("/setup", data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert await db_session.scalar(
            select(AdminUser).where(AdminUser.username == form["username"])
        ) is not None
        assert await (await get_redis()).get(SETUP_TOKEN_KEY) is None
    finally:
        await _restore_setup(db_session)


@pytest.mark.asyncio
async def test_get_setup_recreates_a_lost_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY

    await _reset_setup(db_session)
    try:
        redis = await get_redis()
        await redis.delete(SETUP_TOKEN_KEY)
        await client.get("/setup")
        assert await redis.get(SETUP_TOKEN_KEY) is not None
    finally:
        await _restore_setup(db_session)


@pytest.mark.asyncio
async def test_configured_setup_token_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.redis_client import close_redis, get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY, check_setup_token, ensure_setup_token

    monkeypatch.setattr(settings, "setup_token", "operator-chosen-token-123456")
    redis = await get_redis()
    await redis.delete(SETUP_TOKEN_KEY)
    await ensure_setup_token(redis)
    assert await check_setup_token(redis, "operator-chosen-token-123456")
    await redis.delete(SETUP_TOKEN_KEY)
    # This test has no `client`/`db_session` fixture pinning it to the shared
    # loop, so it gets its own event loop. Close the connection before that
    # loop goes away, or the next test's client fixture inherits a dead one.
    await close_redis()
