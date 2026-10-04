"""v2.1.0: every admin changes their own password, and must when someone else set it.

Before this there was no such page: whoever set a password for someone else
(an admin creating the account, a superadmin reset) knew it for good.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.organisation import Organisation
from app.models.user import AdminRole, AdminUser
from app.services import auth as auth_service
from app.services import rate_limit as rl
from app.services.audit import AuditAction
from app.services.auth import create_access_token, store_session, validate_session
from tests.test_v210_auth_recovery import (
    _PASSWORD,
    _audit,
    _fresh,
    _password_login,
    _reset,
    _script,
    _sign_in,
    _temporary_password,
    _user,
)

_NEW = "An-Own-Password-456"


@pytest.fixture(autouse=True)
def _oidc_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_enabled", True)
    monkeypatch.setattr(settings, "oidc_client_id", "openwhistle-client")


async def _redis() -> Any:
    from app.redis_client import get_redis

    return await get_redis()


def _code(user: AdminUser) -> str:
    return pyotp.TOTP(user.totp_secret).now()


async def _change(client: AsyncClient, csrf: str, user: AdminUser, **overrides: str) -> Any:
    form = {
        "csrf_token": csrf,
        "current_password": _PASSWORD,
        "new_password": _NEW,
        "confirm_password": _NEW,
        "totp_code": _code(user),
        **overrides,
    }
    return await client.post("/admin/account/password", data=form, follow_redirects=False)


def _unchanged(user: AdminUser) -> bool:
    assert user.password_hash
    return auth_service.verify_password(_PASSWORD, user.password_hash)


async def _failures(user: AdminUser) -> int:
    return int(await (await _redis()).get(f"openwhistle:admin_ratelimit:{user.username}") or 0)


# ── The change ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_with_the_current_password_and_a_totp_code(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)

    resp = await _change(client, csrf, user)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/account?password=changed"
    fresh = await _fresh(db_session, user)
    assert fresh.password_hash and auth_service.verify_password(_NEW, fresh.password_hash)
    entries = [
        e
        for e in await _audit(db_session, AuditAction.AUTH_PASSWORD_CHANGED)
        if e.admin_id == user.id
    ]
    assert len(entries) == 1
    assert json.loads(entries[0].detail or "{}") == {"required": False}
    assert _NEW not in (entries[0].detail or "")
    page = await client.get(resp.headers["location"])
    assert "Every other session of your account has ended." in page.text


@pytest.mark.asyncio
async def test_a_wrong_current_password_changes_nothing_and_counts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)

    resp = await _change(client, csrf, user, current_password="not-the-password-1")

    assert resp.status_code == 401
    assert "The current password is not correct." in resp.text
    assert 'aria-invalid="true" aria-describedby="current_password-error"' in resp.text
    assert _unchanged(await _fresh(db_session, user))
    assert await _failures(user) == 1


@pytest.mark.parametrize("code", ["", "12345x", "wrong"])
@pytest.mark.asyncio
async def test_a_session_alone_cannot_change_the_password(
    client: AsyncClient, db_session: AsyncSession, code: str
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    if code == "wrong":
        right = _code(user)
        code = f"{(int(right) + 1) % 1_000_000:06d}"

    resp = await _change(client, csrf, user, totp_code=code)

    assert resp.status_code == 401
    assert 'aria-describedby="totp_code-error' in resp.text
    assert _unchanged(await _fresh(db_session, user))
    assert await _failures(user) == 1


@pytest.mark.asyncio
async def test_a_totp_code_already_used_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    code = _code(user)
    await (await _redis()).set(f"openwhistle:totp_used:{user.id}:{code}", "1", ex=90)

    resp = await _change(client, csrf, user, totp_code=code)

    assert resp.status_code == 401
    assert _unchanged(await _fresh(db_session, user))


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"new_password": "short", "confirm_password": "short"}, "new_password"),
        ({"new_password": "x" * 73, "confirm_password": "x" * 73}, "new_password"),
        ({"confirm_password": "Something-Else-789"}, "confirm_password"),
        ({"new_password": _PASSWORD, "confirm_password": _PASSWORD}, "new_password"),
        ({"current_password": ""}, "current_password"),
    ],
)
@pytest.mark.asyncio
async def test_a_form_error_is_answered_before_any_credential_check(
    client: AsyncClient, db_session: AsyncSession, overrides: dict[str, str], field: str
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    code = _code(user)

    resp = await _change(client, csrf, user, totp_code=code, **overrides)

    assert resp.status_code == 400
    assert f'aria-describedby="{field}-error' in resp.text
    assert _unchanged(await _fresh(db_session, user))
    # Neither a guess counted nor the code burnt.
    assert await _failures(user) == 0
    assert not await (await _redis()).exists(f"openwhistle:totp_used:{user.id}:{code}")


@pytest.mark.asyncio
async def test_the_change_needs_csrf(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _user(db_session)
    await _sign_in(client, user)
    assert (await _change(client, "wrong", user)).status_code == 403
    assert _unchanged(await _fresh(db_session, user))


@pytest.mark.asyncio
async def test_a_locked_account_cannot_change_even_with_the_right_credentials(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    for _ in range(settings.max_login_attempts - 1):
        await _change(client, csrf, user, current_password="not-the-password-1")
    assert await _failures(user) == settings.max_login_attempts - 1
    await _change(client, csrf, user, current_password="not-the-password-1")

    resp = await _change(client, csrf, user)

    assert resp.status_code == 429
    assert _unchanged(await _fresh(db_session, user))
    # The same counter locks the sign-in form.
    assert not await rl.check_admin_login_attempts(await _redis(), user.username)


@pytest.mark.asyncio
async def test_every_other_session_ends_and_the_current_one_stays(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    redis = await _redis()
    user = await _user(db_session)
    other = create_access_token(str(user.id), role=user.role.value)
    await store_session(redis, str(user.id), other)
    await auth_service.store_totp_pending(redis, f"pending-{user.id}", str(user.id))
    bystander = await _user(db_session)
    bystander_token = create_access_token(str(bystander.id), role=bystander.role.value)
    await store_session(redis, str(bystander.id), bystander_token)
    csrf = await _sign_in(client, user)
    current = client.cookies.get("ow_session")
    assert current

    assert (await _change(client, csrf, user)).status_code == 303

    assert await validate_session(redis, current)
    assert not await validate_session(redis, other)
    assert await auth_service.consume_totp_pending(redis, f"pending-{user.id}") is None
    assert await validate_session(redis, bystander_token)
    assert (await client.get("/admin/dashboard")).status_code == 200


@pytest.mark.asyncio
async def test_revoking_keeps_only_the_named_session() -> None:
    from redis.asyncio import from_url

    redis = await from_url(settings.redis_url, decode_responses=True)
    uid = str(uuid.uuid4())
    kept, gone = f"kept-{uid}", f"gone-{uid}"
    for token in (kept, gone):
        await redis.set(f"openwhistle:session:{token}", uid, ex=60)
    try:
        assert await auth_service.revoke_user_sessions(redis, uid, keep=kept) == 1
        assert await validate_session(redis, kept)
        assert not await validate_session(redis, gone)
    finally:
        await redis.aclose()


# ── The account page ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", list(AdminRole))
@pytest.mark.asyncio
async def test_every_role_reaches_its_account_from_the_sidebar(
    client: AsyncClient, db_session: AsyncSession, role: AdminRole
) -> None:
    user = await _user(db_session, role=role)
    await _sign_in(client, user)

    dashboard = await client.get("/admin/dashboard")
    assert 'href="/admin/account"' in dashboard.text
    # Link/unlink moved from the sidebar onto the account page.
    assert 'action="/admin/oidc/link"' not in dashboard.text

    page = await client.get("/admin/account")
    assert page.status_code == 200
    assert user.username in page.text
    assert 'action="/admin/account/password"' in page.text
    assert 'action="/admin/oidc/link"' in page.text
    assert 'aria-current="page">My account' in page.text


@pytest.mark.asyncio
async def test_the_account_page_names_the_organisation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = Organisation(id=uuid.uuid4(), name="Org Acct", slug=f"acct-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.commit()
    await _sign_in(client, await _user(db_session, org_id=org.id))
    assert "Org Acct" in (await client.get("/admin/account")).text


@pytest.mark.parametrize("kind", ["ldap", "sso"])
@pytest.mark.asyncio
async def test_an_account_without_a_password_gets_no_form_and_cannot_post_one(
    client: AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    extra: dict[str, object] = (
        {"ldap_username": f"ldap_{uuid.uuid4().hex[:8]}"}
        if kind == "ldap"
        else {"oidc_sub": f"s-{uuid.uuid4().hex}", "oidc_issuer": "https://idp.example"}
    )
    user = await _user(db_session, **extra)
    user.password_hash = None
    await db_session.commit()
    csrf = await _sign_in(client, user)

    page = await client.get("/admin/account")
    assert 'action="/admin/account/password"' not in page.text
    hint = "through the directory (LDAP)" if kind == "ldap" else "at your identity provider"
    assert hint in page.text

    assert (await _change(client, csrf, user)).status_code == 404
    assert (await _fresh(db_session, user)).password_hash is None


@pytest.mark.asyncio
async def test_the_demo_accounts_keep_their_password(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import demo_seed

    demo = await _user(db_session)
    monkeypatch.setattr(demo_seed, "DEMO_USERNAMES", frozenset({demo.username}))
    csrf = await _sign_in(client, demo)

    monkeypatch.setattr(settings, "demo_mode", True)
    page = await client.get("/admin/account")
    assert "the password of the demo accounts cannot be changed" in page.text
    assert 'action="/admin/account/password"' not in page.text
    assert (await _change(client, csrf, demo)).status_code == 403
    assert _unchanged(await _fresh(db_session, demo))

    monkeypatch.setattr(settings, "demo_mode", False)
    assert (await _change(client, csrf, demo)).status_code == 303


# ── Forced change ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", [AdminRole.admin, AdminRole.case_manager])
@pytest.mark.asyncio
async def test_forced_change_redirects_every_admin_route(
    client: AsyncClient, db_session: AsyncSession, role: AdminRole
) -> None:
    user = await _user(db_session, role=role, must_change_password=True)
    csrf = await _sign_in(client, user)

    for path in (
        "/admin/dashboard",
        f"/admin/reports/{uuid.uuid4()}",
        "/admin/users",
        "/admin/stats",
        "/admin/audit-log",
        "/admin/system",
    ):
        resp = await client.get(path, follow_redirects=False)
        assert (resp.status_code, resp.headers.get("location")) == (303, "/admin/account"), path
    posted = await client.post(
        "/admin/users",
        data={
            "csrf_token": csrf,
            "username": f"x_{uuid.uuid4().hex[:6]}",
            "password": _NEW,
        },
        follow_redirects=False,
    )
    assert (posted.status_code, posted.headers.get("location")) == (303, "/admin/account")
    linked = await client.post(
        "/admin/oidc/link", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert linked.headers.get("location") == "/admin/account"

    # Exempt: the account page, the session timer, sign-out.
    page = await client.get("/admin/account", follow_redirects=False)
    assert page.status_code == 200
    assert "Choose your own password" in page.text
    assert 'href="/admin/dashboard"' not in page.text  # the rest of the menu is hidden
    assert 'action="/admin/oidc/link"' not in page.text
    assert (await client.get("/admin/session/ttl")).json()["ttl_seconds"] > 0
    out = await client.post("/admin/logout", data={"csrf_token": csrf}, follow_redirects=False)
    assert out.headers["location"] == "/admin/login"


@pytest.mark.asyncio
async def test_the_session_timer_renews_during_a_forced_change(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, must_change_password=True)
    csrf = await _sign_in(client, user)
    resp = await client.post(
        "/admin/session/refresh", headers={"X-CSRF-Token": csrf}, follow_redirects=False
    )
    assert resp.status_code == 200
    assert resp.json()["ttl_seconds"] > 0


@pytest.mark.asyncio
async def test_the_forced_change_clears_the_flag_and_opens_the_admin_area(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, must_change_password=True)
    csrf = await _sign_in(client, user)

    assert (await _change(client, csrf, user)).status_code == 303

    fresh = await _fresh(db_session, user)
    assert fresh.must_change_password is False
    entry = [
        e
        for e in await _audit(db_session, AuditAction.AUTH_PASSWORD_CHANGED)
        if e.admin_id == user.id
    ]
    assert json.loads(entry[0].detail or "{}") == {"required": True}
    assert (await client.get("/admin/dashboard", follow_redirects=False)).status_code == 200


async def _enrol_and_change(
    client: AsyncClient, db_session: AsyncSession, csrf: str, user: AdminUser, password: str
) -> None:
    """Password → authenticator enrolment → forced change → admin area."""
    login = await _password_login(client, csrf, user.username, password)
    assert login.headers["location"].startswith("/admin/mfa/setup")
    token = parse_qs(urlsplit(login.headers["location"]).query)["token"][0]
    secret = (await _fresh(db_session, user)).totp_secret
    done = await client.post(
        "/admin/mfa/setup",
        data={
            "csrf_token": csrf,
            "temp_token": token,
            "totp_code": pyotp.TOTP(secret).now(),
        },
        follow_redirects=False,
    )
    assert done.headers["location"] == "/admin/account"
    # Enrolling the authenticator does not release the flag; only the change does.
    assert (await _fresh(db_session, user)).must_change_password is True
    assert (await client.get("/admin/dashboard", follow_redirects=False)).status_code == 303

    changed = await client.post(
        "/admin/account/password",
        data={
            "csrf_token": csrf,
            "current_password": password,
            "new_password": _NEW,
            # The next step's code: the enrolment code is used up (one code, one action).
            "confirm_password": _NEW,
            "totp_code": pyotp.TOTP(secret).at(time.time() + 30),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303, changed.text
    assert (await _fresh(db_session, user)).must_change_password is False
    assert (await client.get("/admin/dashboard", follow_redirects=False)).status_code == 200


@pytest.mark.asyncio
async def test_a_new_account_enrols_then_must_change_its_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await _sign_in(client, await _user(db_session))
    name = f"new_{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/admin/users",
        data={
            "csrf_token": csrf,
            "username": name,
            "password": "Chosen-By-The-Admin-1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302
    new = await auth_service.get_user_by_username(db_session, name)
    assert new is not None and new.must_change_password is True
    client.cookies.delete("ow_session")

    await _enrol_and_change(client, db_session, csrf, new, "Chosen-By-The-Admin-1")


@pytest.mark.asyncio
async def test_a_reset_account_enrols_then_must_change_its_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    target = await _user(db_session)
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))
    temporary = _temporary_password((await _reset(client, csrf, target)).text)
    assert (await _fresh(db_session, target)).must_change_password is True
    client.cookies.delete("ow_session")

    await _enrol_and_change(client, db_session, csrf, target, temporary)


@pytest.mark.asyncio
async def test_a_role_change_does_not_release_the_flag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    target = await _user(db_session, role=AdminRole.case_manager, must_change_password=True)
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))
    await client.post(
        f"/admin/users/{target.id}/role",
        data={
            "csrf_token": csrf,
            "role": "admin",
        },
    )
    assert (await _fresh(db_session, target)).must_change_password is True


@pytest.mark.asyncio
async def test_cli_password_reset_forces_a_change_ends_sessions_and_is_audited(
    db_session: AsyncSession,
) -> None:
    from redis.asyncio import from_url

    user = await _user(db_session)
    token = create_access_token(str(user.id), role=user.role.value)
    redis = await from_url(settings.redis_url, decode_responses=True)
    await store_session(redis, str(user.id), token)

    assert await _script()._reset_password(user.username, _NEW)  # noqa: SLF001
    session_left = await validate_session(redis, token)
    await redis.aclose()

    fresh = await _fresh(db_session, user)
    assert fresh.password_hash and auth_service.verify_password(_NEW, fresh.password_hash)
    assert fresh.must_change_password is True
    assert not session_left
    entry = [
        e
        for e in await _audit(db_session, AuditAction.ADMIN_PASSWORD_RESET)
        if user.username in (e.detail or "")
    ]
    assert json.loads(entry[0].detail or "{}") == {
        "username": user.username,
        "via": "command line",
    }
    assert not await _script()._reset_password(f"nobody_{uuid.uuid4().hex}", _NEW)  # noqa: SLF001


# ── Migration 009 ────────────────────────────────────────────────────────────


def _alembic(*args: str) -> None:
    run = subprocess.run(  # noqa: S603
        ["alembic", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,  # noqa: S607
        env={**os.environ, "DATABASE_URL": settings.database_url},
    )
    assert run.returncode == 0, run.stderr


async def _columns(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'admin_users'")
    )
    await db.commit()
    return {str(r[0]) for r in rows}


@pytest.mark.asyncio
async def test_migration_009_leaves_existing_accounts_unforced_and_round_trips(
    throwaway_db: AsyncSession,
) -> None:
    _alembic("downgrade", "e5a0c4d8f605")
    assert "must_change_password" not in await _columns(throwaway_db)
    await throwaway_db.execute(
        text(
            "INSERT INTO admin_users (id, username, password_hash, totp_secret, totp_enabled, role,"
            " is_active) VALUES (:i, 'existing', 'x', 'x', true, 'admin', true)"
        ),
        {"i": uuid.uuid4()},
    )
    await throwaway_db.commit()

    _alembic("upgrade", "head")
    flag = await throwaway_db.scalar(
        text("SELECT must_change_password FROM admin_users WHERE username = 'existing'")
    )
    await throwaway_db.commit()
    assert flag is False

    _alembic("downgrade", "e5a0c4d8f605")
    assert "must_change_password" not in await _columns(throwaway_db)
    _alembic("upgrade", "head")
    assert "must_change_password" in await _columns(throwaway_db)
