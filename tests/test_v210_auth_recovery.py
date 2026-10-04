"""v2.1.0: self-service OIDC linking and TOTP reset (CLI and UI).

Before this, nothing wrote ``oidc_sub``, so an OIDC login could never succeed,
and a lost authenticator locked its admin out for good.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit import AuditLog
from app.models.user import AdminRole, AdminUser
from app.services import auth as auth_service
from app.services import oidc as oidc_service
from app.services.audit import AuditAction
from app.services.auth import create_access_token, hash_password, store_session
from tests.test_oidc import _FAKE_METADATA, _JWK, _FakeRedis, _id_token

_PASSWORD = "Recovery!Pass-123"
_ISSUER = _FAKE_METADATA["issuer"]


@pytest.fixture(autouse=True)
def _oidc_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_enabled", True)
    monkeypatch.setattr(settings, "oidc_client_id", "openwhistle-client")


async def _user(db: AsyncSession, role: AdminRole = AdminRole.admin, **kw: object) -> AdminUser:
    user = AdminUser(
        id=uuid.uuid4(),
        username=f"rec_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD),
        totp_secret=pyotp.random_base32(),
        totp_enabled=True,
        role=role,
        **kw,
    )
    db.add(user)
    await db.commit()
    return user


async def _sign_in(client: AsyncClient, user: AdminUser) -> str:
    """A live session for ``user`` plus a CSRF cookie; returns the CSRF token."""
    from app.redis_client import get_redis

    token = create_access_token(str(user.id), role=user.role.value)
    await store_session(await get_redis(), str(user.id), token)
    client.cookies.set("ow_session", token)
    await client.get("/admin/login")
    csrf = client.cookies.get("ow_csrf")
    assert csrf
    return csrf


async def _start_link(client: AsyncClient, csrf: str) -> dict[str, str]:
    with patch.object(oidc_service, "_get_metadata", AsyncMock(return_value=_FAKE_METADATA)):
        resp = await client.post(
            "/admin/oidc/link", data={"csrf_token": csrf}, follow_redirects=False
        )
    assert resp.status_code == 303, resp.text
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    return {"state": query["state"][0], "nonce": query["nonce"][0]}


def _idp(id_token: str) -> MagicMock:
    resp = MagicMock(
        raise_for_status=MagicMock(),
        json=MagicMock(return_value={"access_token": "a", "id_token": id_token}),
    )
    http = AsyncMock()
    http.post = AsyncMock(return_value=resp)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)
    return http


async def _callback(client: AsyncClient, state: str, nonce: str, sub: str) -> object:
    token = _id_token(sub=sub, nonce=nonce, aud="openwhistle-client")
    with (
        patch.object(oidc_service, "_get_metadata", AsyncMock(return_value=_FAKE_METADATA)),
        patch.object(oidc_service.httpx, "AsyncClient", return_value=_idp(token)),
        patch.object(jwt.PyJWKClient, "fetch_data", return_value={"keys": [_JWK]}),
    ):
        return await client.get(
            f"/admin/oidc/callback?code=c&state={state}", follow_redirects=False
        )


async def _fresh(db: AsyncSession, user: AdminUser) -> AdminUser:
    got = await db.get(AdminUser, user.id, populate_existing=True)
    assert got is not None
    return got


async def _audit(db: AsyncSession, action: str) -> list[AuditLog]:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return list(rows.scalars())


# ── Linking ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_stores_sub_and_issuer_on_the_signed_in_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    started = await _start_link(client, csrf)
    sub = f"sub-{uuid.uuid4().hex}"

    resp = await _callback(client, started["state"], started["nonce"], sub)

    assert resp.status_code == 303  # type: ignore[attr-defined]
    assert resp.headers["location"] == "/admin/account?sso=linked"  # type: ignore[attr-defined]
    linked = await _fresh(db_session, user)
    assert (linked.oidc_sub, linked.oidc_issuer) == (sub, _ISSUER)
    entries = [
        e for e in await _audit(db_session, AuditAction.AUTH_SSO_LINKED) if e.admin_id == user.id
    ]
    assert len(entries) == 1
    assert json.loads(entries[0].detail or "{}") == {"issuer": _ISSUER}

    page = await client.get("/admin/account?sso=linked")
    assert "Single sign-on is linked" in page.text
    assert 'action="/admin/oidc/unlink"' in page.text


@pytest.mark.asyncio
async def test_link_is_refused_when_the_identity_belongs_to_another_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    sub = f"sub-{uuid.uuid4().hex}"
    owner = await _user(db_session, oidc_sub=sub, oidc_issuer=_ISSUER)
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    started = await _start_link(client, csrf)

    resp = await _callback(client, started["state"], started["nonce"], sub)

    assert resp.headers["location"] == "/admin/account?sso=taken"  # type: ignore[attr-defined]
    assert (await _fresh(db_session, user)).oidc_sub is None
    assert (await _fresh(db_session, owner)).oidc_sub == sub


@pytest.mark.asyncio
async def test_link_callback_without_a_session_links_nothing_and_signs_nobody_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    started = await _start_link(client, csrf)
    client.cookies.delete("ow_session")

    resp = await _callback(client, started["state"], started["nonce"], f"s-{uuid.uuid4().hex}")

    assert resp.status_code == 401  # type: ignore[attr-defined]
    assert "Nothing was linked: your session had ended." in resp.text  # type: ignore[attr-defined]
    assert 'name="temp_token"' not in resp.text  # type: ignore[attr-defined]
    assert (await _fresh(db_session, user)).oidc_sub is None


@pytest.mark.asyncio
async def test_a_link_started_by_one_session_cannot_land_on_another(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    attacker = await _user(db_session)
    victim = await _user(db_session)
    started = await _start_link(client, await _sign_in(client, attacker))
    await _sign_in(client, victim)  # the victim's browser completes the attacker's flow

    resp = await _callback(client, started["state"], started["nonce"], f"s-{uuid.uuid4().hex}")

    assert resp.headers["location"] == "/admin/account?sso=failed"  # type: ignore[attr-defined]
    assert (await _fresh(db_session, victim)).oidc_sub is None
    assert (await _fresh(db_session, attacker)).oidc_sub is None


async def _exchange(redis: _FakeRedis, state: str, purpose: str, binding: str = "") -> object:
    token = _id_token(aud="openwhistle-client")
    with (
        patch.object(oidc_service, "_get_metadata", AsyncMock(return_value=_FAKE_METADATA)),
        patch.object(oidc_service.httpx, "AsyncClient", return_value=_idp(token)),
        patch.object(jwt.PyJWKClient, "fetch_data", return_value={"keys": [_JWK]}),
    ):
        return await oidc_service.exchange_code(
            redis,
            "c",
            state,
            purpose=purpose,
            binding=binding,  # type: ignore[arg-type]
        )


def _store(redis: _FakeRedis, state: str, purpose: str, binding: str = "") -> None:
    redis.data[f"openwhistle:oidc_state:{state}"] = json.dumps(
        {
            "nonce": "the-nonce",
            "code_verifier": "v",
            "purpose": purpose,
            "binding": binding,
        }
    )


@pytest.mark.asyncio
async def test_a_login_state_cannot_link_and_a_link_state_cannot_log_in() -> None:
    redis = _FakeRedis()
    _store(redis, "login-state", oidc_service.PURPOSE_LOGIN)
    _store(redis, "link.state", oidc_service.PURPOSE_LINK, binding="b")

    assert await _exchange(redis, "login-state", oidc_service.PURPOSE_LINK, "") is None
    assert await _exchange(redis, "link.state", oidc_service.PURPOSE_LOGIN, "b") is None
    assert redis.data == {}  # both consumed: a refused state is not retried

    _store(redis, "link.ok", oidc_service.PURPOSE_LINK, binding="b")
    assert await _exchange(redis, "link.ok", oidc_service.PURPOSE_LINK, "b") is not None


@pytest.mark.asyncio
async def test_a_link_state_needs_its_own_session_binding() -> None:
    redis = _FakeRedis()
    _store(redis, "link.x", oidc_service.PURPOSE_LINK, binding="the-session")
    assert await _exchange(redis, "link.x", oidc_service.PURPOSE_LINK, "another") is None


@pytest.mark.asyncio
async def test_link_state_is_stored_with_purpose_and_binding() -> None:
    redis = _FakeRedis()
    with patch.object(oidc_service, "_get_metadata", AsyncMock(return_value=_FAKE_METADATA)):
        url = await oidc_service.create_authorization_url(
            redis,
            purpose=oidc_service.PURPOSE_LINK,
            binding="b",  # type: ignore[arg-type]
        )
    state = parse_qs(urlsplit(url).query)["state"][0]
    assert state.startswith(oidc_service.LINK_STATE_PREFIX)
    stored = json.loads(redis.data[f"openwhistle:oidc_state:{state}"])
    assert (stored["purpose"], stored["binding"]) == ("link", "b")


@pytest.mark.asyncio
async def test_link_needs_csrf(client: AsyncClient, db_session: AsyncSession) -> None:
    await _sign_in(client, await _user(db_session))
    resp = await client.post("/admin/oidc/link", data={"csrf_token": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_link_and_unlink_are_gone_when_oidc_is_off(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = await _sign_in(client, await _user(db_session))
    monkeypatch.setattr(settings, "oidc_enabled", False)
    for path in ("/admin/oidc/link", "/admin/oidc/unlink"):
        assert (await client.post(path, data={"csrf_token": csrf})).status_code == 404
    assert "/admin/oidc/link" not in (await client.get("/admin/account")).text


@pytest.mark.asyncio
async def test_link_callback_errors_go_back_to_the_menu(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _sign_in(client, await _user(db_session))
    resp = await client.get(
        "/admin/oidc/callback?error=access_denied&state=link.x", follow_redirects=False
    )
    assert resp.headers["location"] == "/admin/account?sso=failed"
    with patch.object(oidc_service, "exchange_code", AsyncMock(side_effect=RuntimeError)):
        resp = await client.get("/admin/oidc/callback?code=c&state=link.x", follow_redirects=False)
    assert resp.headers["location"] == "/admin/account?sso=failed"


@pytest.mark.asyncio
async def test_unlink_clears_the_identity_and_is_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, oidc_sub=f"s-{uuid.uuid4().hex}", oidc_issuer=_ISSUER)
    csrf = await _sign_in(client, user)

    assert (await client.post("/admin/oidc/unlink", data={"csrf_token": "x"})).status_code == 403
    resp = await client.post(
        "/admin/oidc/unlink", data={"csrf_token": csrf}, follow_redirects=False
    )

    assert resp.headers["location"] == "/admin/account?sso=unlinked"
    fresh = await _fresh(db_session, user)
    assert (fresh.oidc_sub, fresh.oidc_issuer) == (None, None)
    unlinked = await _audit(db_session, AuditAction.AUTH_SSO_UNLINKED)
    assert any(e.admin_id == user.id for e in unlinked)
    again = await client.post(
        "/admin/oidc/unlink", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert again.headers["location"] == "/admin/account?sso=unlinked"


@pytest.mark.asyncio
async def test_unlink_is_refused_when_sso_is_the_only_way_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    sub = f"s-{uuid.uuid4().hex}"
    user = await _user(db_session, oidc_sub=sub, oidc_issuer=_ISSUER)
    user.password_hash = None
    await db_session.commit()
    csrf = await _sign_in(client, user)

    resp = await client.post(
        "/admin/oidc/unlink", data={"csrf_token": csrf}, follow_redirects=False
    )

    assert resp.headers["location"] == "/admin/account?sso=only_way_in"
    assert (await _fresh(db_session, user)).oidc_sub == sub


@pytest.mark.asyncio
async def test_a_directory_name_is_no_way_in_while_ldap_is_off(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An account LDAP provisioned before LDAP was switched off: the link is
    its only way in, and unlinking used to be allowed."""
    from app.config import settings

    monkeypatch.setattr(settings, "ldap_enabled", False)
    sub = f"s-{uuid.uuid4().hex}"
    user = await _user(db_session, oidc_sub=sub, oidc_issuer=_ISSUER)
    user.password_hash = None
    user.ldap_username = user.username
    await db_session.commit()
    csrf = await _sign_in(client, user)

    resp = await client.post(
        "/admin/oidc/unlink", data={"csrf_token": csrf}, follow_redirects=False
    )

    assert resp.headers["location"] == "/admin/account?sso=only_way_in"


@pytest.mark.asyncio
async def test_after_linking_sso_login_works_and_still_asks_for_totp(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    started = await _start_link(client, await _sign_in(client, user))
    sub = f"sub-{uuid.uuid4().hex}"
    await _callback(client, started["state"], started["nonce"], sub)
    client.cookies.delete("ow_session")

    with patch.object(oidc_service, "_get_metadata", AsyncMock(return_value=_FAKE_METADATA)):
        auth = await client.get("/admin/oidc/authorize", follow_redirects=False)
    query = parse_qs(urlsplit(auth.headers["location"]).query)
    assert not query["state"][0].startswith(oidc_service.LINK_STATE_PREFIX)
    resp = await _callback(client, query["state"][0], query["nonce"][0], sub)

    assert resp.status_code == 200  # type: ignore[attr-defined]
    assert 'name="temp_token"' in resp.text  # type: ignore[attr-defined]
    assert "ow_session" not in resp.cookies  # type: ignore[attr-defined]


# ── TOTP reset: UI ───────────────────────────────────────────────────────────


async def _reset(client: AsyncClient, csrf: str, target: AdminUser) -> object:
    return await client.post(
        f"/admin/users/{target.id}/reset-totp", data={"csrf_token": csrf}, follow_redirects=False
    )


@pytest.mark.asyncio
async def test_superadmin_resets_an_authenticator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.auth import validate_session

    target = await _user(db_session)
    old_secret = target.totp_secret
    target_token = create_access_token(str(target.id), role=target.role.value)
    redis = await get_redis()
    await store_session(redis, str(target.id), target_token)
    bystander = await _user(db_session)
    bystander_token = create_access_token(str(bystander.id), role=bystander.role.value)
    await store_session(redis, str(bystander.id), bystander_token)
    boss = await _user(db_session, role=AdminRole.superadmin)
    csrf = await _sign_in(client, boss)
    page = await client.get("/admin/users")
    assert f'action="/admin/users/{target.id}/reset-totp"' in page.text
    assert f'action="/admin/users/{boss.id}/reset-totp"' not in page.text

    resp = await _reset(client, csrf, target)

    assert resp.status_code == 200  # type: ignore[attr-defined]
    temporary = _temporary_password(resp.text)  # type: ignore[attr-defined]
    fresh = await _fresh(db_session, target)
    assert fresh.totp_enabled is False
    assert fresh.totp_secret != old_secret
    assert not await validate_session(redis, target_token)
    assert await validate_session(redis, bystander_token)
    entry = [
        e for e in await _audit(db_session, AuditAction.ADMIN_TOTP_RESET) if e.admin_id == boss.id
    ]
    assert json.loads(entry[0].detail or "{}") == {
        "username": target.username,
        "password_reset": True,
    }
    # Shown once: the next page load does not carry it.
    assert temporary not in (await client.get("/admin/users")).text

    # The target's old session is dead, and so is the old password.
    client.cookies.set("ow_session", target_token)
    assert (await client.get("/admin/dashboard")).status_code == 401
    client.cookies.delete("ow_session")
    old = await _password_login(client, csrf, target.username, _PASSWORD)
    assert old.status_code == 401

    # The temporary password takes the path of a new account: set up TOTP, then in.
    login = await _password_login(client, csrf, target.username, temporary)
    assert login.status_code == 302
    assert login.headers["location"].startswith("/admin/mfa/setup")
    setup_token = parse_qs(urlsplit(login.headers["location"]).query)["token"][0]
    new_secret = (await _fresh(db_session, target)).totp_secret
    done = await client.post(
        "/admin/mfa/setup",
        data={
            "csrf_token": csrf,
            "temp_token": setup_token,
            "totp_code": pyotp.TOTP(new_secret).now(),
        },
        follow_redirects=False,
    )
    # The superadmin saw the temporary password: its change comes next.
    assert done.headers["location"] == "/admin/account"
    assert "ow_session" in done.cookies
    fresh = await _fresh(db_session, target)
    assert (fresh.totp_enabled, fresh.must_change_password) == (True, True)


async def _password_login(client: AsyncClient, csrf: str, username: str, password: str) -> Any:
    return await client.post(
        "/admin/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )


def _temporary_password(page: str) -> str:
    found = re.search(r'<code class="usr-temp-password">([^<]+)</code>', page)
    assert found, "no temporary password on the result page"
    return found.group(1)


@pytest.mark.asyncio
async def test_the_temporary_password_leaks_nowhere(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    target = await _user(db_session)
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))

    with caplog.at_level(logging.DEBUG):
        resp = await _reset(client, csrf, target)
    temporary = _temporary_password(resp.text)  # type: ignore[attr-defined]

    assert auth_service.validate_password(temporary) == temporary
    assert temporary not in caplog.text
    assert all(temporary not in v for v in resp.headers.values())  # type: ignore[attr-defined]
    assert resp.headers["cache-control"] == "no-store"  # type: ignore[attr-defined]
    rows = (await db_session.execute(select(AuditLog.detail))).scalars()
    assert all(temporary not in (d or "") for d in rows)
    assert temporary not in (await _fresh(db_session, target)).password_hash  # type: ignore[operator]


@pytest.mark.asyncio
async def test_an_account_without_a_password_keeps_its_directory_login(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    target = await _user(db_session, ldap_username=f"ldap_{uuid.uuid4().hex[:8]}")
    target.password_hash = None
    await db_session.commit()
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))

    resp = await _reset(client, csrf, target)

    assert '<code class="usr-temp-password">' not in resp.text  # type: ignore[attr-defined]
    assert "signs in through the directory" in resp.text  # type: ignore[attr-defined]
    fresh = await _fresh(db_session, target)
    assert (fresh.password_hash, fresh.totp_enabled) == (None, False)
    entry = [
        e
        for e in await _audit(db_session, AuditAction.ADMIN_TOTP_RESET)
        if target.username in (e.detail or "")
    ]
    assert json.loads(entry[0].detail or "{}")["password_reset"] is False


@pytest.mark.asyncio
async def test_no_session_is_accepted_while_the_authenticator_awaits_enrolment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The reset commits before the Redis sweep; a session minted in between
    # must still be refused.
    user = await _user(db_session)
    await _sign_in(client, user)
    user.totp_enabled = False
    await db_session.commit()
    assert (await client.get("/admin/dashboard")).status_code == 401


@pytest.mark.asyncio
async def test_after_a_reset_the_old_code_opens_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.auth import store_totp_pending

    target = await _user(db_session)
    old_code = pyotp.TOTP(target.totp_secret).now()
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))
    await _reset(client, csrf, target)
    client.cookies.delete("ow_session")

    await store_totp_pending(await get_redis(), "pending-after-reset", str(target.id))
    resp = await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": csrf,
            "temp_token": "pending-after-reset",
            "totp_code": old_code,
        },
        follow_redirects=False,
    )

    assert "ow_session" not in resp.cookies
    assert resp.status_code == 200 and "totp_code" in resp.text


@pytest.mark.asyncio
async def test_reset_revokes_a_login_waiting_at_the_totp_step(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.auth import consume_totp_pending, store_totp_pending

    target = await _user(db_session)
    redis = await get_redis()
    await store_totp_pending(redis, "pending-before-reset", str(target.id))
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))
    await _reset(client, csrf, target)
    assert await consume_totp_pending(redis, "pending-before-reset") is None


@pytest.mark.parametrize("role", [AdminRole.admin, AdminRole.case_manager])
@pytest.mark.asyncio
async def test_only_a_superadmin_resets_an_authenticator(
    client: AsyncClient, db_session: AsyncSession, role: AdminRole
) -> None:
    target = await _user(db_session)
    csrf = await _sign_in(client, await _user(db_session, role=role))
    assert (await _reset(client, csrf, target)).status_code == 403  # type: ignore[attr-defined]
    assert (await _fresh(db_session, target)).totp_enabled is True
    if role == AdminRole.admin:
        assert "/reset-totp" not in (await client.get("/admin/users")).text


@pytest.mark.asyncio
async def test_a_superadmin_cannot_reset_their_own_authenticator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    boss = await _user(db_session, role=AdminRole.superadmin)
    csrf = await _sign_in(client, boss)
    assert (await _reset(client, csrf, boss)).status_code == 400  # type: ignore[attr-defined]
    assert (await _fresh(db_session, boss)).totp_enabled is True


@pytest.mark.asyncio
async def test_reset_needs_csrf(client: AsyncClient, db_session: AsyncSession) -> None:
    target = await _user(db_session)
    await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))
    assert (await _reset(client, "wrong", target)).status_code == 403  # type: ignore[attr-defined]
    assert (await _fresh(db_session, target)).totp_enabled is True


@pytest.mark.asyncio
async def test_reset_of_an_unknown_user_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))
    resp = await client.post(f"/admin/users/{uuid.uuid4()}/reset-totp", data={"csrf_token": csrf})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_demo_accounts_keep_their_authenticator(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import demo_seed

    demo = await _user(db_session, role=AdminRole.case_manager)
    monkeypatch.setattr(demo_seed, "DEMO_USERNAMES", frozenset({demo.username}))
    csrf = await _sign_in(client, await _user(db_session, role=AdminRole.superadmin))

    monkeypatch.setattr(settings, "demo_mode", True)
    assert (await _reset(client, csrf, demo)).status_code == 403  # type: ignore[attr-defined]
    assert (await _fresh(db_session, demo)).totp_enabled is True
    monkeypatch.setattr(settings, "demo_mode", False)
    assert (await _reset(client, csrf, demo)).status_code == 200  # type: ignore[attr-defined]


# ── TOTP reset: CLI ──────────────────────────────────────────────────────────


def _script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "reset_admin_password.py"
    spec = importlib.util.spec_from_file_location("reset_admin_password_v210", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_cli_reset_gives_the_only_superadmin_a_working_new_secret(
    db_session: AsyncSession,
) -> None:
    from redis.asyncio import from_url

    from app.services.auth import validate_session

    boss = await _user(db_session, role=AdminRole.superadmin)
    old_secret = boss.totp_secret
    token = create_access_token(str(boss.id), role=boss.role.value)
    redis = await from_url(settings.redis_url, decode_responses=True)
    await store_session(redis, str(boss.id), token)

    result = await _script()._reset_totp(boss.username)  # noqa: SLF001
    session_left = await validate_session(redis, token)
    await redis.aclose()

    assert result is not None
    secret, uri = result
    assert secret != old_secret
    assert uri == pyotp.TOTP(secret).provisioning_uri(
        name=boss.username, issuer_name=settings.app_name
    )
    fresh = await _fresh(db_session, boss)
    assert (fresh.totp_secret, fresh.totp_enabled) == (secret, True)
    assert not session_left
    entry = [
        e
        for e in await _audit(db_session, AuditAction.ADMIN_TOTP_RESET)
        if e.admin_username == "system" and boss.username in (e.detail or "")
    ]
    assert json.loads(entry[0].detail or "{}") == {
        "username": boss.username,
        "via": "command line",
    }


@pytest.mark.asyncio
async def test_cli_reset_of_an_unknown_user_changes_nothing() -> None:
    assert await _script()._reset_totp(f"nobody_{uuid.uuid4().hex}") is None  # noqa: SLF001


def test_cli_prints_the_secret_and_uri_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _script()
    monkeypatch.setattr(module, "_reset_totp", AsyncMock(return_value=("SECRET32", "otpauth://x")))
    monkeypatch.setattr(sys, "argv", ["x", "--reset-totp", "someone"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.count("SECRET32") == 1 and "otpauth://x" in out

    monkeypatch.setattr(module, "_reset_totp", AsyncMock(return_value=None))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1


def test_sso_result_shows_only_known_outcomes() -> None:
    from starlette.requests import Request

    from app.templating import sso_result

    def req(q: str) -> Request:
        return Request({"type": "http", "query_string": q.encode(), "headers": []})

    assert sso_result(req("sso=linked")) == "linked"
    assert sso_result(req("sso=<script>")) is None
