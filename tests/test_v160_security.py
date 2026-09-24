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
        assert "setup token is missing or wrong" in resp.text.lower()
        created = await db_session.scalar(
            select(AdminUser).where(AdminUser.username == form["username"])
        )
        assert created is None
    finally:
        await _restore_setup(db_session)


@pytest.mark.asyncio
async def test_setup_post_refused_when_the_redis_key_is_absent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Nobody has opened /setup yet in this Redis, so nothing is stored — any
    supplied token, however plausible, must be refused."""
    from app.redis_client import get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY

    await _reset_setup(db_session)
    try:
        redis = await get_redis()
        await redis.delete(SETUP_TOKEN_KEY)
        csrf = await _csrf(client, "/status")  # sets the CSRF cookie without touching /setup
        form = _setup_form(csrf, "a-token-nobody-configured-or-was-shown")
        resp = await client.post("/setup", data=form, follow_redirects=False)
        assert resp.status_code == 403
        assert await redis.get(SETUP_TOKEN_KEY) is None
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
async def test_get_setup_creates_no_token_once_setup_is_complete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY

    await _reset_setup(db_session)
    await _restore_setup(db_session)  # row exists and is marked complete
    redis = await get_redis()
    await redis.delete(SETUP_TOKEN_KEY)
    resp = await client.get("/setup", follow_redirects=False)
    assert resp.status_code == 302
    assert await redis.get(SETUP_TOKEN_KEY) is None


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


@pytest.mark.asyncio
async def test_configured_setup_token_overrides_a_stale_stored_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A random token already sat in Redis (created before SETUP_TOKEN was set,
    or by another replica) — the configured value must win immediately, not
    just after that stale key expires or is deleted by hand."""
    from app.redis_client import close_redis, get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY, check_setup_token, ensure_setup_token

    monkeypatch.setattr(settings, "setup_token", "operator-chosen-token-654321")
    redis = await get_redis()
    await redis.set(SETUP_TOKEN_KEY, "stale-random-token-from-before")
    try:
        await ensure_setup_token(redis)
        assert await check_setup_token(redis, "operator-chosen-token-654321")
        assert not await check_setup_token(redis, "stale-random-token-from-before")
    finally:
        await redis.delete(SETUP_TOKEN_KEY)
        await close_redis()


# ── TOTP secrets are encrypted at rest (A2) ────────────────────────────────


@pytest.mark.asyncio
async def test_totp_secret_is_stored_encrypted(db_session: AsyncSession) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.services.crypto import decrypt

    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(), username=f"totp_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret, totp_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()

    raw = await db_session.scalar(
        text("SELECT totp_secret FROM admin_users WHERE id = :id"), {"id": user.id}
    )
    assert raw != secret
    assert decrypt(raw) == secret

    # Reload through a fresh session/connection rather than `db_session.expire_all()` +
    # `db_session.get()` on the same session: on this stack (Python 3.14, SQLAlchemy 2.0,
    # greenlet 3.5, asyncpg, NullPool) reusing one AsyncSession for a second checkout
    # right after an ORM flush against admin_users raises MissingGreenlet — reproduced
    # even with a plain String column and no encryption involved, so it is a pre-existing
    # environment issue, not something this feature causes. `setup_incomplete` in
    # tests/test_v150_auth.py uses the same own-engine pattern for the same reason.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as fresh:
            loaded = await fresh.get(AdminUser, user.id)
    finally:
        await engine.dispose()
    assert loaded is not None and loaded.totp_secret == secret


def test_migration_004_encrypts_plaintext_secrets_once() -> None:
    import importlib

    from app.services.crypto import encrypt

    mig = importlib.import_module("migrations.versions.004_encrypt_totp_secrets")
    assert not mig._is_token("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
    assert mig._is_token(encrypt("JBSWY3DPEHPK3PXP"))
