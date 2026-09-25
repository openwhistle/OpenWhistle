"""v1.5.0 authentication hardening: one test per guard.

Whistleblower login that cannot be used to lock the owner out, password-spraying
alarm, POST+CSRF logouts, Secure CSRF cookie, atomic setup wizard, serialised
migrations, one password policy, LDAP StartTLS, over-long bcrypt input.
"""

from __future__ import annotations

import asyncio
import re
import ssl
import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pyotp
import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.audit import AuditLog
from app.models.setup import SetupStatus
from app.models.user import AdminUser
from app.services.audit import AuditAction
from app.services.auth import hash_password, validate_session
from app.services.report import create_report

_ADMIN_PASSWORD = "V150-Test-Password"  # noqa: S105


# ─── helpers ─────────────────────────────────────────────────────────────────


async def _csrf(client: AsyncClient, path: str = "/status") -> str:
    await client.get(path)
    return client.cookies.get("ow_csrf") or ""


async def _status_login(client: AsyncClient, case_number: str, pin: str) -> Response:
    return await client.post(
        "/status",
        data={"case_number": case_number, "pin": pin, "csrf_token": await _csrf(client)},
        follow_redirects=False,
    )


_WRONG_PIN = "00000000-0000-4000-8000-000000000000"


async def _create_admin(db: AsyncSession) -> tuple[AdminUser, str]:
    secret = pyotp.random_base32()
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"v150_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_ADMIN_PASSWORD),
        totp_secret=secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, secret


async def _admin_login(client: AsyncClient, admin: AdminUser, secret: str) -> str:
    csrf = await _csrf(client, "/admin/login")
    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": _ADMIN_PASSWORD, "csrf_token": csrf},
    )
    temp = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    assert temp
    await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": client.cookies.get("ow_csrf"),
            "temp_token": temp.group(1),
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    token = client.cookies.get("ow_session")
    assert token
    return token


async def _failed_admin_login(client: AsyncClient, username: str) -> None:
    # Unique per run: the per-username lockout outlives the test in Redis.
    username = f"{username}-{uuid.uuid4().hex[:8]}"
    csrf = await _csrf(client, "/admin/login")
    r = await client.post(
        "/admin/login",
        data={"username": username, "password": "wrong-password-xyz", "csrf_token": csrf},
    )
    assert r.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# 1. Whistleblower login: a correct PIN is never refused
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_correct_pin_opens_case_after_many_wrong_attempts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    report, pin = await create_report(db_session, "corruption", "Lockout test report text.")
    for _ in range(settings.max_access_attempts + 3):
        await _status_login(client, report.case_number, _WRONG_PIN)

    resp = await _status_login(client, report.case_number, pin)

    assert resp.status_code == 303
    assert "ow-status-session" in resp.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_wrong_pin_past_the_limit_shows_wait_notice_and_keeps_the_form(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    report, _pin = await create_report(db_session, "corruption", "Notice test report text.")
    for _ in range(settings.max_access_attempts):
        resp = await _status_login(client, report.case_number, _WRONG_PIN)
        assert "Many wrong attempts" not in resp.text

    resp = await _status_login(client, report.case_number, _WRONG_PIN)

    assert resp.status_code == 401
    assert "Many wrong attempts" in resp.text
    assert 'name="pin"' in resp.text  # the owner can still log in


@pytest.mark.asyncio
async def test_successful_login_resets_the_failure_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    report, pin = await create_report(db_session, "corruption", "Reset test report text.")
    for _ in range(settings.max_access_attempts):
        await _status_login(client, report.case_number, _WRONG_PIN)
    assert (await _status_login(client, report.case_number, pin)).status_code == 303

    resp = await _status_login(client, report.case_number, _WRONG_PIN)

    assert "No report matches this case number and PIN." in resp.text
    assert "Many wrong attempts" not in resp.text


@pytest.mark.asyncio
async def test_reply_fallback_shares_the_case_number_count_and_accepts_correct_pin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The /reply fallback no longer keys anything on a client-supplied token."""
    report, pin = await create_report(db_session, "corruption", "Reply fallback report.")
    for i in range(settings.max_access_attempts + 1):
        resp = await client.post(
            "/reply",
            data={
                "case_number": report.case_number,
                "pin": _WRONG_PIN,
                "session_token": f"rotating-{i}",
                "content": "hello",
                "csrf_token": await _csrf(client),
            },
            follow_redirects=False,
        )
    assert resp.status_code == 429

    # The count is per case number, shared with /status.
    status_resp = await _status_login(client, report.case_number, _WRONG_PIN)
    assert "Many wrong attempts" in status_resp.text

    resp = await client.post(
        "/reply",
        data={
            "case_number": report.case_number,
            "pin": pin,
            "content": "Follow-up from the rightful owner.",
            "csrf_token": await _csrf(client),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_unknown_case_number_costs_a_bcrypt_check(db_session: AsyncSession) -> None:
    """No early return: existing and unknown case numbers take the same time."""
    from app.services import report as report_service
    from app.services.auth import TIMING_DUMMY_HASH

    with patch.object(report_service, "verify_pin", wraps=report_service.verify_pin) as spy:
        found = await report_service.get_report_by_credentials(
            db_session, "OW-1999-00000", _WRONG_PIN
        )

    assert found is None
    spy.assert_called_once_with(_WRONG_PIN, TIMING_DUMMY_HASH)


# ═════════════════════════════════════════════════════════════════════════════
# bcrypt input over 72 bytes: a failed login, not a 500
# ═════════════════════════════════════════════════════════════════════════════


def test_over_long_secret_is_rejected_not_raised() -> None:
    from app.services.auth import verify_password, verify_pin

    hashed = hash_password("a-normal-password")
    assert verify_password("x" * 100, hashed) is False
    assert verify_pin("x" * 100, hashed) is False


@pytest.mark.asyncio
async def test_over_long_admin_password_is_a_401(client: AsyncClient) -> None:
    csrf = await _csrf(client, "/admin/login")
    r = await client.post(
        "/admin/login",
        data={
            "username": f"nobody-{uuid.uuid4().hex[:8]}",
            "password": "p" * 200,
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# 2. Password-spraying alarm
# ═════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture(loop_scope="function")
async def spray_env(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncMock]:
    from app.redis_client import get_redis
    from app.services import rate_limit as rl

    monkeypatch.setattr(settings, "admin_failed_login_alert_threshold", 3)
    monkeypatch.setattr(settings, "admin_failed_login_alert_window_minutes", 15)
    redis = await get_redis()
    for key in await redis.keys(f"{rl._SPRAY_PREFIX}*"):  # noqa: SLF001
        await redis.delete(key)
    await redis.delete(rl._SPRAY_ALERTED)  # noqa: SLF001
    with patch("app.api.auth.notify_security_alert", new=AsyncMock()) as notify:
        yield notify
    await redis.delete(rl._SPRAY_ALERTED)  # noqa: SLF001


async def _spray_audit_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == AuditAction.AUTH_SPRAYING_SUSPECTED
        )
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_spraying_sends_one_alert_and_one_audit_entry_per_window(
    client: AsyncClient, db_session: AsyncSession, spray_env: AsyncMock
) -> None:
    before = await _spray_audit_count(db_session)

    await _failed_admin_login(client, "spray-a")
    await _failed_admin_login(client, "spray-b")
    spray_env.assert_not_called()

    await _failed_admin_login(client, "spray-c")
    spray_env.assert_called_once()
    assert "password spraying" in spray_env.call_args.args[0].lower()

    await _failed_admin_login(client, "spray-d")
    await _failed_admin_login(client, "spray-e")
    spray_env.assert_called_once()  # one alert per window
    assert await _spray_audit_count(db_session) == before + 1


@pytest.mark.asyncio
async def test_spraying_window_sums_the_minute_buckets(
    client: AsyncClient, spray_env: AsyncMock
) -> None:
    import time

    from app.redis_client import get_redis
    from app.services import rate_limit as rl

    redis = await get_redis()
    earlier = int(time.time() // 60) - 5
    await redis.set(f"{rl._SPRAY_PREFIX}{earlier}", 2, ex=600)  # noqa: SLF001

    await _failed_admin_login(client, "spray-window")

    spray_env.assert_called_once()


@pytest.mark.asyncio
async def test_spraying_counts_ldap_failures_too(
    client: AsyncClient, spray_env: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ldap_auth import LDAPAuthError

    monkeypatch.setattr(settings, "admin_failed_login_alert_threshold", 1)
    monkeypatch.setattr(settings, "ldap_enabled", True)
    with patch(
        "app.services.ldap_auth.authenticate_ldap", AsyncMock(side_effect=LDAPAuthError("no"))
    ):
        await _failed_admin_login(client, "ldap-spray")

    spray_env.assert_called_once()


@pytest.mark.asyncio
async def test_spraying_threshold_zero_disables_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.rate_limit import record_instance_login_failure

    monkeypatch.setattr(settings, "admin_failed_login_alert_threshold", 0)
    redis = AsyncMock()
    assert await record_instance_login_failure(redis) is False
    redis.incr.assert_not_called()


@pytest.mark.asyncio
async def test_security_alert_goes_to_email_and_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import notifications

    monkeypatch.setattr(settings, "notify_email_enabled", True)
    monkeypatch.setattr(settings, "notify_email_to", "sec@example.com")
    monkeypatch.setattr(settings, "notify_smtp_user", "u")
    monkeypatch.setattr(settings, "notify_smtp_password", "p")
    monkeypatch.setattr(settings, "notify_webhook_enabled", True)
    monkeypatch.setattr(settings, "notify_webhook_url", "https://hooks.example.com/x")
    monkeypatch.setattr(settings, "notify_webhook_secret", "s3cret")

    http = AsyncMock()
    http.post = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("aiosmtplib.send", new=AsyncMock()) as smtp,
        patch("httpx.AsyncClient", return_value=http),
    ):
        await notifications.notify_security_alert("Subject", "Body")

    smtp.assert_awaited_once()
    assert smtp.call_args.kwargs["recipients"] == ["sec@example.com"]
    headers = http.post.call_args.kwargs["headers"]
    assert headers["X-OpenWhistle-Signature"].startswith("sha256=")

    # A failing channel is logged, never raised.
    with (
        patch("aiosmtplib.send", new=AsyncMock(side_effect=OSError)),
        patch("httpx.AsyncClient", side_effect=OSError),
    ):
        await notifications.notify_security_alert("Subject", "Body")


def test_security_alert_payload_shapes() -> None:
    from app.services.notifications import _build_security_alert_payload

    assert "Subject" in _build_security_alert_payload("Subject", "Body", "slack")["text"]
    assert _build_security_alert_payload("S", "B", "teams")["type"] == "message"
    assert _build_security_alert_payload("S", "B", "generic")["event"] == "security_alert"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Logout is POST + CSRF; the CSRF cookie is Secure
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_admin_logout_does_not_log_out(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis

    admin, secret = await _create_admin(db_session)
    token = await _admin_login(client, admin, secret)

    resp = await client.get("/admin/logout", follow_redirects=False)

    assert resp.status_code == 405
    assert await validate_session(await get_redis(), token) is True


@pytest.mark.asyncio
async def test_admin_logout_without_csrf_token_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis

    admin, secret = await _create_admin(db_session)
    token = await _admin_login(client, admin, secret)

    resp = await client.post("/admin/logout", data={"csrf_token": "forged"})

    assert resp.status_code == 403
    assert await validate_session(await get_redis(), token) is True


@pytest.mark.asyncio
async def test_admin_nav_logs_out_through_a_csrf_form(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, secret = await _create_admin(db_session)
    await _admin_login(client, admin, secret)

    page = await client.get("/admin/dashboard")

    assert 'action="/admin/logout"' in page.text
    assert 'href="/admin/logout"' not in page.text


async def _status_session(client: AsyncClient, db: AsyncSession) -> str:
    report, pin = await create_report(db, "corruption", "Logout test report text.")
    await _status_login(client, report.case_number, pin)
    key = client.cookies.get("ow-status-session")
    assert key
    return key


@pytest.mark.asyncio
async def test_get_status_logout_does_not_log_out(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis

    key = await _status_session(client, db_session)

    resp = await client.get("/status/logout", follow_redirects=False)

    assert resp.status_code == 405
    assert await (await get_redis()).exists(f"status-session:{key}") == 1


@pytest.mark.asyncio
async def test_status_logout_without_csrf_token_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis

    key = await _status_session(client, db_session)

    resp = await client.post("/status/logout", data={"csrf_token": "forged"})

    assert resp.status_code == 403
    assert await (await get_redis()).exists(f"status-session:{key}") == 1


@pytest.mark.asyncio
async def test_csrf_cookie_is_secure_when_secure_cookies(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "secure_cookies", True)
    cookie = (await client.get("/status")).headers["set-cookie"]
    assert "ow_csrf=" in cookie
    assert "Secure" in cookie

    monkeypatch.setattr(settings, "secure_cookies", False)
    cookie = (await client.get("/status")).headers["set-cookie"]
    assert "Secure" not in cookie


# ═════════════════════════════════════════════════════════════════════════════
# 5. Setup wizard: check-and-insert is atomic
# ═════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture(loop_scope="function")
async def setup_incomplete(db_engine: object) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """Pretend setup has not happened; restore the row and drop created admins."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = (await s.execute(select(SetupStatus).where(SetupStatus.id == 1))).scalar_one_or_none()
        was = None if row is None else row.completed
        if row is None:
            s.add(SetupStatus(id=1, completed=False))
        else:
            row.completed = False
        await s.commit()
    yield factory
    async with factory() as s:
        await s.execute(delete(AdminUser).where(AdminUser.username.like("v150-setup-%")))
        row = (await s.execute(select(SetupStatus).where(SetupStatus.id == 1))).scalar_one()
        if was is None:
            await s.delete(row)
        else:
            row.completed = was
        await s.commit()
    await engine.dispose()


async def _admins_named(factory: async_sessionmaker[AsyncSession], name: str) -> int:
    async with factory() as s:
        result = await s.execute(select(func.count(AdminUser.id)).where(AdminUser.username == name))
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_setup_waits_for_a_concurrent_completion_and_creates_nothing(
    setup_incomplete: async_sessionmaker[AsyncSession],
) -> None:
    from app.api.wizard import SETUP_LOCK_KEY, create_initial_admin

    factory = setup_incomplete
    async with factory() as holder, factory() as racer:
        # Another request is inside its critical section ...
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SETUP_LOCK_KEY})
        task = asyncio.create_task(
            create_initial_admin(racer, "v150-setup-racer", _ADMIN_PASSWORD, "JBSWY3DPEHPK3PXP")
        )
        await asyncio.sleep(0.5)
        assert not task.done(), "the second request must wait for the lock"

        # ... and completes setup.
        await holder.execute(text("UPDATE setup_status SET completed = true WHERE id = 1"))
        await holder.commit()

        assert await asyncio.wait_for(task, 10) is False
    assert await _admins_named(factory, "v150-setup-racer") == 0


@pytest.mark.asyncio
async def test_setup_recheck_is_not_fooled_by_the_session_cache(
    setup_incomplete: async_sessionmaker[AsyncSession],
) -> None:
    """setup_post checks first, then locks: the re-check must read the row again,
    also when the session still holds the row it loaded before the lock."""
    from app.api.wizard import create_initial_admin

    factory = setup_incomplete
    async with factory() as late:
        held = (await late.execute(select(SetupStatus).where(SetupStatus.id == 1))).scalar_one()
        assert held.completed is False  # the fast-path check, row kept in the session
        async with factory() as winner:
            assert (
                await create_initial_admin(
                    winner, "v150-setup-winner", _ADMIN_PASSWORD, "JBSWY3DPEHPK3PXP"
                )
                is True
            )
        assert (
            await create_initial_admin(late, "v150-setup-late", _ADMIN_PASSWORD, "JBSWY3DPEHPK3PXP")
            is False
        )
    assert await _admins_named(factory, "v150-setup-late") == 0


@pytest.mark.asyncio
async def test_setup_wizard_applies_the_password_policy(
    client: AsyncClient, setup_incomplete: async_sessionmaker[AsyncSession]
) -> None:
    secret = pyotp.random_base32()
    csrf = await _csrf(client, "/setup")
    too_long = "p" * 80  # passes a bare length >= 12 check, bcrypt cannot take it
    resp = await client.post(
        "/setup",
        data={
            "username": "v150-setup-policy",
            "password": too_long,
            "password_confirm": too_long,
            "totp_secret": secret,
            "totp_code": pyotp.TOTP(secret).now(),
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert "at most 72 bytes" in resp.text
    assert await _admins_named(setup_incomplete, "v150-setup-policy") == 0


@pytest.mark.asyncio
async def test_setup_wizard_validates_the_username_like_admin_created_users(
    client: AsyncClient, setup_incomplete: async_sessionmaker[AsyncSession]
) -> None:
    secret = pyotp.random_base32()
    csrf = await _csrf(client, "/setup")
    resp = await client.post(
        "/setup",
        data={
            "username": "v150-setup-<script>",
            "password": _ADMIN_PASSWORD,
            "password_confirm": _ADMIN_PASSWORD,
            "totp_secret": secret,
            "totp_code": pyotp.TOTP(secret).now(),
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert "letters, digits, spaces" in resp.text


# ═════════════════════════════════════════════════════════════════════════════
# 6. Migrations take a cluster-wide advisory lock
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_alembic_upgrade_waits_for_the_migration_lock(db_engine: object) -> None:
    env_py = (Path(__file__).resolve().parents[1] / "migrations" / "env.py").read_text()
    m = re.search(r"^MIGRATION_LOCK_KEY = (\S+)", env_py, re.MULTILINE)
    assert m, "migrations/env.py must define MIGRATION_LOCK_KEY"
    key = int(m.group(1), 0)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
        await conn.commit()
        proc = await asyncio.create_subprocess_exec(
            "alembic",
            "upgrade",
            "head",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        with pytest.raises(TimeoutError):
            # Another replica is migrating: this one must wait, not race.
            await asyncio.wait_for(asyncio.shield(proc.wait()), 3)
        await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        await conn.commit()
    await engine.dispose()
    assert await asyncio.wait_for(proc.wait(), 120) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 7. One password policy
# ═════════════════════════════════════════════════════════════════════════════


def test_password_policy() -> None:
    from app.services.auth import validate_password

    assert validate_password("x" * 12) == "x" * 12
    with pytest.raises(ValueError, match="at least 12"):
        validate_password("x" * 11)
    with pytest.raises(ValueError, match="at most 72 bytes"):
        validate_password("ä" * 40)  # 40 characters, 80 bytes


@pytest.mark.asyncio
async def test_admin_created_user_gets_the_password_policy(db_session: AsyncSession) -> None:
    from app.services.users import create_user

    with pytest.raises(ValueError, match="at least 12"):
        await create_user(db_session, f"v150_short_{uuid.uuid4().hex[:6]}", "short")


def test_reset_script_applies_the_password_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "reset_admin_password.py"
    spec = importlib.util.spec_from_file_location("reset_admin_password", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    reset = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "_reset_password", reset)
    # Composition rules are gone (upper/lower/digit): length is the policy.
    monkeypatch.setattr(sys, "argv", ["x", "--username", "a", "--password", "p" * 80])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1
    reset.assert_not_called()

    monkeypatch.setattr(sys, "argv", ["x", "--username", "a", "--password", "alllowercase-ok"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 0


# ═════════════════════════════════════════════════════════════════════════════
# 8. LDAP StartTLS
# ═════════════════════════════════════════════════════════════════════════════


def test_ldap_start_tls_verifies_the_certificate() -> None:
    from app.services.ldap_auth import _make_server

    cfg = MagicMock(
        ldap_server="ldap.example.com", ldap_port=389, ldap_use_ssl=False, ldap_start_tls=True
    )
    server = _make_server(cfg)
    assert server.tls is not None
    assert server.tls.validate == ssl.CERT_REQUIRED


def test_ldap_start_tls_happens_before_any_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    from ldap3 import AUTO_BIND_TLS_BEFORE_BIND

    from app.services import ldap_auth

    monkeypatch.setattr(settings, "ldap_enabled", True)
    monkeypatch.setattr(settings, "ldap_start_tls", True)
    monkeypatch.setattr(settings, "ldap_use_ssl", False)
    entry = MagicMock(entry_dn="uid=alice,dc=example,dc=com")
    entry.__contains__ = lambda self, key: False
    conn = MagicMock(entries=[entry])
    with patch("ldap3.Connection", return_value=conn) as connection:
        ldap_auth._authenticate_ldap_sync("alice", "pw")

    assert connection.call_count == 2  # service bind, user bind
    for call in connection.call_args_list:
        assert call.kwargs["auto_bind"] == AUTO_BIND_TLS_BEFORE_BIND


def test_ldap_without_start_tls_binds_plainly() -> None:
    from app.services.ldap_auth import _auto_bind

    assert _auto_bind(MagicMock(ldap_start_tls=False, ldap_use_ssl=False)) is True
    assert _auto_bind(MagicMock(ldap_start_tls=True, ldap_use_ssl=True)) is True
