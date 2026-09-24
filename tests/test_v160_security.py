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


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("a-real-setup-token-1234", True),   # >= 16 chars: valid as-is
        ("  a-real-setup-token-1234  ", True),  # padded: stripped before the length check
        ("too-short", False),                # < 16 chars after strip
        ("   ", False),                      # whitespace-only: blank after strip
        ("", True),                          # empty means "unset"
    ],
)
def test_setup_token_validator(value: str, valid: bool) -> None:
    from app.config import Settings

    if valid:
        s = Settings(secret_key="x" * 32, setup_token=value)  # type: ignore[call-arg]
        assert s.setup_token == value.strip()
    else:
        with pytest.raises(ValueError, match="SETUP_TOKEN"):
            Settings(secret_key="x" * 32, setup_token=value)  # type: ignore[call-arg]


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

    # Reload through a fresh session so the value comes from the database, not the identity map.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as fresh:
            loaded = await fresh.get(AdminUser, user.id)
    finally:
        await engine.dispose()
    assert loaded is not None and loaded.totp_secret == secret

    await db_session.execute(text("DELETE FROM admin_users WHERE id = :id"), {"id": user.id})
    await db_session.commit()


def test_migration_004_encrypts_plaintext_secrets_once() -> None:
    import importlib

    from app.services.crypto import encrypt

    mig = importlib.import_module("migrations.versions.004_encrypt_totp_secrets")
    assert not mig._is_token("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
    assert mig._is_token(encrypt("JBSWY3DPEHPK3PXP"))


def _alembic(*args: str) -> None:
    import subprocess

    run = subprocess.run(  # noqa: S603
        ["alembic", *args], capture_output=True, text=True, check=False  # noqa: S607
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.asyncio
async def test_migration_004_round_trip_encrypts_and_stays_idempotent(
    db_session: AsyncSession,
) -> None:
    """Exercise migration 004's data path (not just `_is_token` on literals): a
    real downgrade decrypts and narrows, a legacy plaintext row gets picked up
    by the next upgrade, and a row that already holds a token is left alone."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.services.crypto import decrypt, encrypt
    from app.services.mfa import verify_totp

    secret1, secret2, secret3 = (pyotp.random_base32() for _ in range(3))
    ids = {"user1": uuid.uuid4(), "user2": uuid.uuid4(), "user3": uuid.uuid4()}

    user1 = AdminUser(
        id=ids["user1"], username=f"mig004a_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret1, totp_enabled=True,
    )
    db_session.add(user1)
    await db_session.commit()  # close the session's transaction before the subprocess

    try:
        _alembic("downgrade", "7d4e2b9c1a05")
        raw1 = await db_session.scalar(
            text("SELECT totp_secret FROM admin_users WHERE id = :id"), {"id": ids["user1"]}
        )
        assert raw1 == secret1

        # A legacy row (plaintext, never touched migration 004) and, to prove the
        # upgrade loop's `if not _is_token(...)` guard, a row that already holds a
        # token — widen the column ourselves first (what migration 004's own
        # upgrade() does as its first, idempotent step) so the token fits.
        token3_before = encrypt(secret3)
        await db_session.execute(text("ALTER TABLE admin_users ALTER COLUMN totp_secret TYPE TEXT"))
        await db_session.execute(text(
            "INSERT INTO admin_users (id, username, password_hash, totp_secret, totp_enabled,"
            " role, is_active) VALUES (:i, :u, :p, :t, true, 'admin', true)"
        ), {"i": ids["user2"], "u": f"mig004b_{uuid.uuid4().hex[:8]}",
            "p": hash_password(_PASSWORD), "t": secret2})
        await db_session.execute(text(
            "INSERT INTO admin_users (id, username, password_hash, totp_secret, totp_enabled,"
            " role, is_active) VALUES (:i, :u, :p, :t, true, 'admin', true)"
        ), {"i": ids["user3"], "u": f"mig004c_{uuid.uuid4().hex[:8]}",
            "p": hash_password(_PASSWORD), "t": token3_before})
        await db_session.commit()  # close the session's transaction before the subprocess
    finally:
        _alembic("upgrade", "head")

    rows = dict((await db_session.execute(text(
        "SELECT id, totp_secret FROM admin_users WHERE id IN (:a, :b, :c)"
    ), {"a": ids["user1"], "b": ids["user2"], "c": ids["user3"]})).tuples().all())
    assert rows[ids["user1"]] != secret1
    assert decrypt(rows[ids["user1"]]) == secret1
    assert rows[ids["user2"]] != secret2
    assert decrypt(rows[ids["user2"]]) == secret2
    assert rows[ids["user3"]] == token3_before  # already a token: byte-identical, not re-encrypted

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as fresh:
            loaded = await fresh.get(AdminUser, ids["user1"])
    finally:
        await engine.dispose()
    assert loaded is not None
    assert verify_totp(loaded.totp_secret, pyotp.TOTP(secret1).now())

    await db_session.execute(
        text("DELETE FROM admin_users WHERE id IN (:a, :b, :c)"),
        {"a": ids["user1"], "b": ids["user2"], "c": ids["user3"]},
    )
    await db_session.commit()


# ── Session refresh needs CSRF; absolute session lifetime (A3) ─────────────


def _use_session(client: AsyncClient, token: str) -> None:
    """Replace the session cookie; keep the CSRF cookie the header is checked against.

    The domain is taken from the jar's own ow_csrf cookie (set by the server on an
    earlier response) rather than left unspecified: an unspecified-domain cookie and
    a same-name cookie the server later sets via Set-Cookie are stored as two distinct
    entries by httpx's cookie jar, and client.cookies.get() then raises CookieConflict.
    """
    domain = next((c.domain for c in client.cookies.jar if c.name == "ow_csrf"), "")
    csrf = client.cookies.get("ow_csrf") or ""
    client.cookies.clear()
    client.cookies.set("ow_csrf", csrf, domain=domain)
    client.cookies.set("ow_session", token, domain=domain)


async def _logged_in_admin(client: AsyncClient, db: AsyncSession) -> AdminUser:
    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(), username=f"sess_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret, totp_enabled=True,
        role=AdminRole.admin,
    )
    db.add(user)
    await db.commit()
    csrf = await _csrf(client, "/admin/login")
    r = await client.post("/admin/login", data={
        "username": user.username, "password": _PASSWORD, "csrf_token": csrf})
    temp = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    assert temp
    await client.post("/admin/login/mfa", data={
        "csrf_token": client.cookies.get("ow_csrf"), "temp_token": temp.group(1),
        "totp_code": pyotp.TOTP(secret).now()})
    assert client.cookies.get("ow_session")
    return user


@pytest.mark.asyncio
async def test_session_refresh_without_csrf_header_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_admin(client, db_session)
    resp = await client.post("/admin/session/refresh")
    assert resp.status_code == 403
    ok = await client.post(
        "/admin/session/refresh", headers={"X-CSRF-Token": client.cookies.get("ow_csrf") or ""}
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_session_older_than_the_absolute_limit_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import time

    import jwt

    from app.redis_client import get_redis

    user = await _logged_in_admin(client, db_session)
    now = int(time.time())
    stale = jwt.encode(
        {"sub": str(user.id), "role": "admin", "iat": now, "exp": now + 3600,
         "auth_time": now - (settings.session_max_hours * 3600 + 60), "jti": "x"},
        settings.secret_key, algorithm=settings.algorithm,
    )
    await (await get_redis()).setex(f"openwhistle:session:{stale}", 3600, str(user.id))
    _use_session(client, stale)
    resp = await client.post(
        "/admin/session/refresh", headers={"X-CSRF-Token": client.cookies.get("ow_csrf") or ""},
        follow_redirects=False,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_never_extends_past_the_absolute_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import time

    from app.redis_client import get_redis
    from app.services.auth import create_access_token, decode_access_token_exp

    user = await _logged_in_admin(client, db_session)
    started = int(time.time()) - settings.session_max_hours * 3600 + 120  # 2 min left
    token = create_access_token(str(user.id), "admin", auth_time=started)
    await (await get_redis()).setex(f"openwhistle:session:{token}", 120, str(user.id))
    _use_session(client, token)
    resp = await client.post(
        "/admin/session/refresh", headers={"X-CSRF-Token": client.cookies.get("ow_csrf") or ""}
    )
    assert resp.status_code == 200
    new_exp = decode_access_token_exp(client.cookies.get("ow_session") or "")
    assert new_exp is not None
    assert int(new_exp.timestamp()) <= started + settings.session_max_hours * 3600
