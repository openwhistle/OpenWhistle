"""Regression tests: every login path requires MFA, LDAP least privilege and
filter escaping, and deleting a report removes its externally stored files."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import AdminRole, AdminUser


@pytest.mark.asyncio
async def test_oidc_login_requires_totp(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = f"sub-{uuid.uuid4().hex}"
    db_session.add(
        AdminUser(
            id=uuid.uuid4(),
            username=f"oidc_{uuid.uuid4().hex[:8]}",
            oidc_sub=sub,
            oidc_issuer="https://idp.example.com",
            totp_secret="JBSWY3DPEHPK3PXP",
            totp_enabled=True,
        )
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "oidc_enabled", True)
    userinfo = {"sub": sub, "iss": "https://idp.example.com"}
    with patch("app.services.oidc.exchange_code", AsyncMock(return_value=userinfo)):
        resp = await client.get("/admin/oidc/callback?code=c&state=s", follow_redirects=False)

    assert resp.status_code == 200
    assert 'name="temp_token"' in resp.text
    assert "ow_session" not in resp.cookies


@pytest.mark.asyncio
async def test_ldap_first_login_provisions_case_manager(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ldap_auth import LDAPUserInfo

    username = f"ldap_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "ldap_enabled", True)
    info = LDAPUserInfo(username=username, email=None)
    csrf = (await client.get("/admin/login")).cookies.get("ow_csrf")
    with patch("app.services.ldap_auth.authenticate_ldap", AsyncMock(return_value=info)):
        resp = await client.post(
            "/admin/login",
            data={"username": username, "password": "x", "csrf_token": csrf},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/admin/mfa/setup")
    user = (
        await db_session.execute(select(AdminUser).where(AdminUser.ldap_username == username))
    ).scalar_one()
    assert user.role == AdminRole.case_manager


def test_ldap_filter_escapes_username() -> None:
    from app.services.ldap_auth import LDAPAuthError, _authenticate_ldap_sync

    cfg = MagicMock(ldap_enabled=True, ldap_user_filter="(uid={username})")
    conn = MagicMock(entries=[])
    with (
        patch("app.config.settings", cfg),
        patch("app.services.ldap_auth._make_server"),
        patch("ldap3.Connection", return_value=conn),
        pytest.raises(LDAPAuthError),
    ):
        _authenticate_ldap_sync("*)(uid=*", "pw")

    assert conn.search.call_args.kwargs["search_filter"] == r"(uid=\2a\29\28uid=\2a)"


@pytest.mark.asyncio
async def test_delete_report_removes_stored_objects(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.attachment import Attachment
    from app.services import storage
    from app.services.report import create_report, delete_report

    report, _ = await create_report(db_session, "financial_fraud", "Stored object cleanup.")
    db_session.add(
        Attachment(
            id=uuid.uuid4(),
            report_id=report.id,
            filename="e.pdf",
            content_type="application/pdf",
            size=3,
            data=None,
            storage_key="k/e.pdf",
        )
    )
    await db_session.commit()

    backend = MagicMock(delete=AsyncMock())
    monkeypatch.setattr(storage, "get_storage_backend", lambda: backend)
    await delete_report(db_session, report)

    backend.delete.assert_awaited_once_with("k/e.pdf")


@pytest.mark.asyncio
async def test_oidc_login_rejects_deactivated_account(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = f"sub-{uuid.uuid4().hex}"
    db_session.add(
        AdminUser(
            id=uuid.uuid4(),
            username=f"oidc_{uuid.uuid4().hex[:8]}",
            oidc_sub=sub,
            oidc_issuer="https://idp.example.com",
            totp_secret="JBSWY3DPEHPK3PXP",
            totp_enabled=True,
            is_active=False,
        )
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "oidc_enabled", True)
    userinfo = {"sub": sub, "iss": "https://idp.example.com"}
    with patch("app.services.oidc.exchange_code", AsyncMock(return_value=userinfo)):
        resp = await client.get("/admin/oidc/callback?code=c&state=s", follow_redirects=False)

    assert resp.status_code == 401
    assert 'name="temp_token"' not in resp.text


def test_ldaps_verifies_server_certificate() -> None:
    import ssl

    from app.services.ldap_auth import _make_server

    cfg = MagicMock(ldap_server="ldap.example.com", ldap_port=636, ldap_use_ssl=True)
    server = _make_server(cfg)
    assert server.tls.validate == ssl.CERT_REQUIRED  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_delete_stored_objects_continues_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import storage
    from app.services.attachment import delete_stored_objects

    backend = MagicMock(delete=AsyncMock(side_effect=[RuntimeError("boom"), None]))
    monkeypatch.setattr(storage, "get_storage_backend", lambda: backend)
    await delete_stored_objects(["a", "b"])

    assert backend.delete.await_count == 2


@pytest.mark.asyncio
async def test_demo_totp_code_only_works_for_demo_accounts(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEMO_MODE on a real database must not turn 000000 into a master code."""
    from app.services.auth import store_totp_pending

    user = AdminUser(
        id=uuid.uuid4(),
        username=f"real_{uuid.uuid4().hex[:8]}",
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()
    monkeypatch.setattr(settings, "demo_mode", True)

    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url)
    temp = uuid.uuid4().hex
    await store_totp_pending(redis, temp, str(user.id))
    await redis.aclose()

    csrf = (await client.get("/admin/login")).cookies.get("ow_csrf")
    resp = await client.post(
        "/admin/login/mfa",
        data={"totp_code": "000000", "temp_token": temp, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert "ow_session" not in resp.cookies


@pytest.mark.asyncio
async def test_admin_notes_are_stored_encrypted(db_session: AsyncSession) -> None:
    from app.services.report import add_note, create_report, decrypt_note_contents, get_report_by_id

    report, _ = await create_report(db_session, "financial_fraud", "Note encryption test.")
    author = AdminUser(
        id=uuid.uuid4(),
        username=f"n_{uuid.uuid4().hex[:8]}",
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_enabled=True,
    )
    db_session.add(author)
    await db_session.commit()
    note = await add_note(db_session, report, author, "Witness: J. Doe, 2nd floor")

    assert "J. Doe" not in note.content
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None
    assert decrypt_note_contents(loaded) == ["Witness: J. Doe, 2nd floor"]
