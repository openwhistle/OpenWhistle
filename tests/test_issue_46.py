"""Issue #46 — SSO-only accounts get a generic login error (no account-type leak)."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminUser


@pytest.mark.asyncio
async def test_sso_only_account_password_login_returns_generic_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # An OIDC-only account: oidc_sub set, no local password hash.
    user = AdminUser(
        id=uuid.uuid4(),
        username="ssouser",
        password_hash=None,
        oidc_sub="sub-123",
        oidc_issuer="https://idp.example",
        totp_secret="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        totp_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()

    get_resp = await client.get("/admin/login")
    m = re.search(r'name="csrf_token" value="([^"]+)"', get_resp.text)
    csrf = m.group(1) if m else (get_resp.cookies.get("ow_csrf") or "")

    resp = await client.post(
        "/admin/login",
        data={"username": "ssouser", "password": "anything", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    # Must not reveal the account exists / uses SSO — keep the error generic.
    assert "Single Sign-On" not in resp.text
    assert "Invalid username or password" in resp.text
