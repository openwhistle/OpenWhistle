"""Coverage tests for app/api/admin.py gaps.

Covers:
- report_detail: 404 for non-existent report (line 127)
- admin_reply: 422 for empty content (line 195)
- demo_reset: 403 when DEMO_MODE is false (line 257)
"""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminUser
from app.services.auth import hash_password

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _create_admin(db: AsyncSession) -> tuple[AdminUser, str]:
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"cov_adm_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("AdminTest!Pass1"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login_admin(client: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    """Full admin login: password → MFA → session cookie set."""
    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")

    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "AdminTest!Pass1", "csrf_token": csrf},
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


# ─── report_detail 404 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_detail_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /admin/reports/<non-existent-uuid> must return 404."""
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get(
        f"/admin/reports/{uuid.uuid4()}",
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ─── admin_reply: empty content ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_reply_empty_content_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /admin/reports/<id>/reply with blank content must return 422."""
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    # First create a report to reply to
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    submit_resp = await client.post(
        "/submit",
        data={
            "category": "financial_fraud",
            "description": "Report for admin reply test.",
            "csrf_token": csrf,
        },
    )
    case_m = re.search(r"OW-\d{4}-\d{5}", submit_resp.text)
    assert case_m is not None, "Could not find case number in submit response"

    # Get the report from the dashboard
    dash_resp = await client.get("/admin/dashboard")
    assert dash_resp.status_code == 200
    report_id_m = re.search(
        r'/admin/reports/([0-9a-f-]{36})"', dash_resp.text
    )
    assert report_id_m is not None, "Could not find report link in dashboard"
    report_id = report_id_m.group(1)

    # Get a CSRF token from the report detail page
    detail_resp = await client.get(f"/admin/reports/{report_id}")
    csrf_detail = detail_resp.cookies.get("ow_csrf")
    csrf_form_m = re.search(r'name="csrf_token" value="([^"]+)"', detail_resp.text)
    csrf_token = csrf_form_m.group(1) if csrf_form_m else csrf_detail

    resp = await client.post(
        f"/admin/reports/{report_id}/reply",
        data={"content": "   ", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert resp.status_code == 422


# ─── demo_reset: forbidden outside demo mode ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    __import__("app.config", fromlist=["settings"]).settings.demo_mode,
    reason="Only testable with DEMO_MODE=false",
)
async def test_demo_reset_forbidden_in_non_demo_mode(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /admin/demo/reset must return 403 when DEMO_MODE is false."""
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.post("/admin/demo/reset", follow_redirects=False)
    assert resp.status_code == 403
