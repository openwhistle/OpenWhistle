"""v1.6.0 security: one test per guard (setup token, TOTP at rest, sessions, roles, audit scope)."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from fastapi import HTTPException
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
        ("a-real-setup-token-1234-abcdefghij", True),   # >= 32 chars: valid as-is
        ("  a-real-setup-token-1234-abcdefghij  ", True),  # padded: stripped first
        ("a-real-setup-token-1234", False),  # < 32 chars after strip
        ("too-short", False),
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


async def _refresh(
    client: AsyncClient, *, csrf: bool = True, follow_redirects: bool = True
) -> Response:
    headers = {"X-CSRF-Token": client.cookies.get("ow_csrf") or ""} if csrf else {}
    return await client.post(
        "/admin/session/refresh", headers=headers, follow_redirects=follow_redirects
    )


@pytest.mark.asyncio
async def test_session_refresh_without_csrf_header_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_admin(client, db_session)
    resp = await client.post("/admin/session/refresh")
    assert resp.status_code == 403
    ok = await _refresh(client)
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
    await (await get_redis()).set(f"openwhistle:session:{stale}", str(user.id), ex=3600)
    _use_session(client, stale)
    resp = await _refresh(client, follow_redirects=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_session_older_than_the_absolute_limit_is_401_even_without_csrf_header(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A stale session is rejected by get_current_admin (401), which runs before
    the CSRF dependency — so a missing header on a stale session must still read
    as 401, not be masked by a 403 that would suggest the session was otherwise fine."""
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
    await (await get_redis()).set(f"openwhistle:session:{stale}", str(user.id), ex=3600)
    _use_session(client, stale)
    resp = await _refresh(client, csrf=False, follow_redirects=False)
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
    redis = await get_redis()
    await redis.set(f"openwhistle:session:{token}", str(user.id), ex=120)
    _use_session(client, token)
    resp = await _refresh(client)
    assert resp.status_code == 200
    new_token = client.cookies.get("ow_session") or ""
    new_exp = decode_access_token_exp(new_token)
    assert new_exp is not None
    assert int(new_exp.timestamp()) <= started + settings.session_max_hours * 3600

    # The refresh must not hand out more than the ~2 minutes actually left on the
    # absolute limit: neither the new Redis session key nor the Set-Cookie the
    # browser will honour may outlive it.
    new_ttl = await redis.ttl(f"openwhistle:session:{new_token}")
    assert 0 < new_ttl <= 120
    set_cookie_headers = resp.headers.get_list("set-cookie")
    session_cookie_header = next(h for h in set_cookie_headers if h.startswith("ow_session="))
    max_age_m = re.search(r"Max-Age=(\d+)", session_cookie_header, re.IGNORECASE)
    assert max_age_m
    assert int(max_age_m.group(1)) <= 120


@pytest.mark.asyncio
async def test_session_refresh_never_restarts_the_clock_when_claims_are_missing() -> None:
    """`session_refresh` must reuse the claims `get_current_admin` already verified
    (via `request.state.session_claims`) rather than fall back to `now()` when they
    are absent — that fallback would silently hand out a fresh SESSION_MAX_HOURS
    window instead of respecting the login time. This can't happen through the
    HTTP dependency chain (get_current_admin always sets session_claims before
    returning), so the guard is exercised directly."""
    from types import SimpleNamespace

    from app.api.auth import session_refresh

    request = SimpleNamespace(state=SimpleNamespace())  # no session_claims attribute
    user = AdminUser(id=uuid.uuid4(), username="direct-call-user", role=AdminRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        await session_refresh(
            request=request,  # type: ignore[arg-type]
            redis=None,  # type: ignore[arg-type]
            current_user=user,
            session_token="irrelevant",
            _csrf=None,
        )
    assert exc_info.value.status_code == 401


def test_session_too_old_with_no_claims_is_true() -> None:
    from app.services.auth import session_too_old

    assert session_too_old({}) is True


def test_session_too_old_past_the_absolute_limit_is_true() -> None:
    import time

    from app.services.auth import session_too_old

    assert session_too_old({"iat": time.time() - 13 * 3600}) is True


def test_session_started_at_prefers_auth_time_over_iat() -> None:
    from app.services.auth import session_started_at

    assert session_started_at({"iat": 5, "auth_time": 7}) == 7


def test_seconds_left_is_zero_for_an_invalid_token() -> None:
    from app.services.auth import seconds_left

    assert seconds_left("not.a.valid.jwt") == 0


# ── Deactivated accounts never reach the second factor (A5) ────────────────


@pytest.mark.asyncio
async def test_deactivated_user_never_reaches_the_totp_step(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = AdminUser(
        id=uuid.uuid4(), username=f"inactive_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=pyotp.random_base32(),
        totp_enabled=True, is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    csrf = await _csrf(client, "/admin/login")
    resp = await client.post("/admin/login", data={
        "username": user.username, "password": _PASSWORD, "csrf_token": csrf})
    assert resp.status_code == 401
    assert 'name="temp_token"' not in resp.text


@pytest.mark.asyncio
async def test_user_deactivated_between_password_and_totp_gets_no_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(), username=f"late_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret, totp_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()
    csrf = await _csrf(client, "/admin/login")
    r = await client.post("/admin/login", data={
        "username": user.username, "password": _PASSWORD, "csrf_token": csrf})
    temp = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    assert temp
    user.is_active = False
    await db_session.commit()
    await client.post("/admin/login/mfa", data={
        "csrf_token": client.cookies.get("ow_csrf"), "temp_token": temp.group(1),
        "totp_code": pyotp.TOTP(secret).now()})
    assert not client.cookies.get("ow_session")


@pytest.mark.asyncio
async def test_unknown_role_creates_no_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_admin(client, db_session)
    name = f"role_{uuid.uuid4().hex[:8]}"
    resp = await client.post("/admin/users", data={
        "username": name, "password": _PASSWORD, "role": "root",
        "csrf_token": client.cookies.get("ow_csrf")}, follow_redirects=False)
    assert resp.status_code == 422
    assert await db_session.scalar(select(AdminUser).where(AdminUser.username == name)) is None


@pytest.mark.asyncio
async def test_case_manager_cannot_dismiss_the_ip_warning(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_admin(client, db_session)
    user.role = AdminRole.case_manager
    await db_session.commit()
    resp = await client.post(
        "/admin/ip-warning/dismiss", headers={"X-CSRF-Token": client.cookies.get("ow_csrf") or ""}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_deactivated_user_mfa_setup_makes_no_state_change(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A deactivated user holding a valid setup-pending token must not flip
    totp_enabled or write an AUTH_TOTP_SETUP audit row before rejection."""
    from app.models.audit import AuditLog
    from app.redis_client import get_redis
    from app.services import auth as auth_service

    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(), username=f"deact_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret,
        totp_enabled=False, is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    redis = await get_redis()
    temp_token = uuid.uuid4().hex
    await auth_service.store_totp_setup_pending(redis, temp_token, str(user.id))

    csrf = await _csrf(client, "/admin/login")
    resp = await client.post("/admin/mfa/setup", data={
        "csrf_token": csrf, "temp_token": temp_token,
        "totp_code": pyotp.TOTP(secret).now(),
    }, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/login"
    await db_session.refresh(user)
    assert user.totp_enabled is False
    rows = (await db_session.scalars(
        select(AuditLog).where(AuditLog.admin_id == user.id)
    )).all()
    assert rows == []


@pytest.mark.asyncio
async def test_migration_005_backfills_audit_org_from_report_or_actor(
    db_session: AsyncSession,
) -> None:
    """A pre-v1.6.0 audit row has org_id NULL. Migration 005 must fill it from the
    row's report when there is one, else from the acting admin — exercised via a
    real downgrade/upgrade round trip, not just the SQL string."""
    from app.models.organisation import Organisation
    from app.services.report import create_report

    org = Organisation(id=uuid.uuid4(), name="Mig005 Org", slug=f"m5-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    admin = AdminUser(
        id=uuid.uuid4(), username=f"mig005_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=pyotp.random_base32(),
        totp_enabled=True, org_id=org.id,
    )
    db_session.add(admin)
    report, _ = await create_report(db_session, "corruption", "Migration 005 backfill test.")
    report.org_id = org.id
    await db_session.commit()  # close the session's transaction before the subprocess

    row_with_report = uuid.uuid4()
    row_without_report = uuid.uuid4()
    try:
        _alembic("downgrade", "a1c6e0f4b201")
        await db_session.execute(text(
            "INSERT INTO audit_log (id, admin_id, admin_username, action, report_id, org_id)"
            " VALUES (:id, :admin_id, 'mig005', 'report.viewed', :report_id, NULL)"
        ), {"id": row_with_report, "admin_id": admin.id, "report_id": report.id})
        await db_session.execute(text(
            "INSERT INTO audit_log (id, admin_id, admin_username, action, report_id, org_id)"
            " VALUES (:id, :admin_id, 'mig005', 'admin.created', NULL, NULL)"
        ), {"id": row_without_report, "admin_id": admin.id})
        await db_session.commit()  # close the session's transaction before the subprocess
    finally:
        _alembic("upgrade", "head")

    rows = dict((await db_session.execute(text(
        "SELECT id, org_id FROM audit_log WHERE id IN (:a, :b)"
    ), {"a": row_with_report, "b": row_without_report})).tuples().all())
    assert rows[row_with_report] == org.id
    assert rows[row_without_report] == org.id


# ── Guards the v1.6.0 mutation audit found unpinned ───────────────────────


@pytest.mark.asyncio
async def test_get_setup_keeps_the_token_it_already_created(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Reloading /setup must not replace the token the log already showed."""
    from app.redis_client import get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY

    await _reset_setup(db_session)
    try:
        redis = await get_redis()
        await redis.delete(SETUP_TOKEN_KEY)
        await client.get("/setup")
        first = await redis.get(SETUP_TOKEN_KEY)
        await client.get("/setup")
        assert first is not None
        assert await redis.get(SETUP_TOKEN_KEY) == first
    finally:
        await _restore_setup(db_session)


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_startup_creates_the_setup_token_only_while_setup_is_open(complete: bool) -> None:
    """The token is logged at start, so an operator has it before opening /setup."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import FastAPI

    redis = object()
    cfg = MagicMock(
        demo_mode=False, reminder_enabled=False, retention_enabled=False,
        update_check_enabled=False, storage_backend="db", encryption_key="k" * 32,
    )
    with (
        patch("app.main._run_alembic_upgrade"),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("app.main.settings", cfg),
        patch("app.api.wizard._is_setup_complete", new_callable=AsyncMock, return_value=complete),
        patch("app.redis_client.get_redis", new_callable=AsyncMock, return_value=redis),
        patch("app.services.setup_token.ensure_setup_token", new_callable=AsyncMock) as ensure,
        patch("app.services.notifications.batching_enabled", return_value=False),
    ):
        from app.main import lifespan

        async with lifespan(FastAPI()):
            pass
    if complete:
        ensure.assert_not_awaited()
    else:
        ensure.assert_awaited_once_with(redis)


@pytest.mark.asyncio
async def test_migration_004_downgrade_names_an_unreadable_secret(
    db_session: AsyncSession,
) -> None:
    """A secret that decrypts under no configured key is named by id, and the
    downgrade changes nothing (one transaction)."""
    import subprocess

    uid = uuid.uuid4()
    await db_session.execute(text(
        "INSERT INTO admin_users (id, username, password_hash, totp_secret, totp_enabled,"
        " role, is_active) VALUES (:i, :u, :p, :t, true, 'admin', true)"
    ), {"i": uid, "u": f"mig004d_{uuid.uuid4().hex[:8]}", "p": hash_password(_PASSWORD),
        "t": "gAAAAA" + "x" * 80})
    await db_session.commit()
    try:
        run = subprocess.run(  # noqa: S603
            ["alembic", "downgrade", "7d4e2b9c1a05"],  # noqa: S607
            capture_output=True, text=True, check=False,
        )
        assert run.returncode != 0
        assert str(uid) in run.stderr
    finally:
        _alembic("upgrade", "head")
        await db_session.execute(text("DELETE FROM admin_users WHERE id = :i"), {"i": uid})
        await db_session.commit()


def test_a_session_token_without_exp_or_sub_is_refused() -> None:
    import jwt

    from app.services.auth import decode_access_token_claims

    for claims in ({"sub": "someone", "auth_time": 1}, {"exp": 4102444800}):
        token = jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)
        assert decode_access_token_claims(token) is None, claims


@pytest.mark.asyncio
async def test_deactivated_user_gets_no_mfa_setup_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services import auth as auth_service

    user = AdminUser(
        id=uuid.uuid4(), username=f"deact_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=pyotp.random_base32(),
        totp_enabled=False, is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    temp_token = uuid.uuid4().hex
    await auth_service.store_totp_setup_pending(await get_redis(), temp_token, str(user.id))

    resp = await client.get(f"/admin/mfa/setup?token={temp_token}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/login"


@pytest.mark.asyncio
async def test_unknown_role_change_is_422_and_changes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_admin(client, db_session)
    target = AdminUser(
        id=uuid.uuid4(), username=f"target_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=pyotp.random_base32(),
        totp_enabled=True, role=AdminRole.case_manager,
    )
    db_session.add(target)
    await db_session.commit()
    resp = await client.post(f"/admin/users/{target.id}/role", data={
        "role": "root", "csrf_token": client.cookies.get("ow_csrf")}, follow_redirects=False)
    assert resp.status_code == 422
    await db_session.refresh(target)
    assert target.role == AdminRole.case_manager


@pytest.mark.asyncio
async def test_a_new_user_without_a_role_is_a_case_manager(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_admin(client, db_session)
    name = f"role_{uuid.uuid4().hex[:8]}"
    await client.post("/admin/users", data={
        "username": name, "password": _PASSWORD,
        "csrf_token": client.cookies.get("ow_csrf")}, follow_redirects=False)
    created = await db_session.scalar(select(AdminUser).where(AdminUser.username == name))
    assert created is not None
    assert created.role == AdminRole.case_manager
