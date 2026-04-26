"""Tests for UX fixes: browser validation (UX #1) and Redis session cleanup (UX #10)."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminUser
from app.services.auth import hash_password
from app.services.report import create_report

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _create_admin(db: AsyncSession, suffix: str = "") -> tuple[AdminUser, str]:
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"ux_admin_{suffix or uuid.uuid4().hex[:6]}",
        password_hash=hash_password("UXFix!Test123"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login_admin(ac: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    get_resp = await ac.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")

    login_resp = await ac.post(
        "/admin/login",
        data={
            "username": admin.username,
            "password": "UXFix!Test123",
            "csrf_token": csrf_token,
        },
    )
    temp_m = re.search(r'name="temp_token" value="([^"]+)"', login_resp.text)
    temp_token = temp_m.group(1) if temp_m else ""
    csrf_m = re.search(r'name="csrf_token" value="([^"]+)"', login_resp.text)
    mfa_csrf = csrf_m.group(1) if csrf_m else ""

    totp_code = pyotp.TOTP(totp_secret).now()
    await ac.post(
        "/admin/login/mfa",
        data={"csrf_token": mfa_csrf, "temp_token": temp_token, "totp_code": totp_code},
    )


# ─── UX #1: Browser validation (no novalidate) ────────────────────────────────


@pytest.mark.asyncio
async def test_submit_form_has_no_novalidate(client: AsyncClient) -> None:
    """Submit form must not carry novalidate — browser enforces required fields."""
    resp = await client.get("/submit")
    assert resp.status_code == 200
    # The opening form tag must not contain 'novalidate'
    form_match = re.search(r"<form[^>]+action=\"/submit\"[^>]*>", resp.text)
    assert form_match is not None, "Could not find /submit form tag"
    assert "novalidate" not in form_match.group(0)


@pytest.mark.asyncio
async def test_status_form_has_no_novalidate(client: AsyncClient) -> None:
    """Status check form must not carry novalidate — browser enforces required fields."""
    resp = await client.get("/status")
    assert resp.status_code == 200
    form_match = re.search(r"<form[^>]+action=\"/status\"[^>]*>", resp.text)
    assert form_match is not None, "Could not find /status form tag"
    assert "novalidate" not in form_match.group(0)


@pytest.mark.asyncio
async def test_submit_form_fields_carry_required(client: AsyncClient) -> None:
    """Category select and description textarea have the required attribute."""
    resp = await client.get("/submit")
    assert resp.status_code == 200
    # select#category
    assert re.search(r'<select[^>]+id="category"[^>]*required', resp.text)
    # textarea#description
    assert re.search(r'<textarea[^>]+id="description"[^>]*required', resp.text)


@pytest.mark.asyncio
async def test_status_form_fields_carry_required(client: AsyncClient) -> None:
    """Case number and PIN inputs have the required attribute."""
    resp = await client.get("/status")
    assert resp.status_code == 200
    assert re.search(r'<input[^>]+id="case_number"[^>]*required', resp.text)
    assert re.search(r'<input[^>]+id="pin"[^>]*required', resp.text)


# ─── UX #10: Redis session cleanup on report deletion ─────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_report_removes_redis_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting a report also removes any active whistleblower status-session keys in Redis."""
    from app.redis_client import get_redis

    # Create a report and a matching Redis status-session
    report, pin = await create_report(db_session, "corruption", "Report for deletion cleanup test.")

    redis = await get_redis()
    session_key = f"status-session:test-session-{uuid.uuid4().hex}"
    await redis.setex(session_key, 7200, str(report.id))

    # Verify the session exists before deletion
    assert await redis.exists(session_key)

    # Login as admin and delete the report
    admin, totp_secret = await _create_admin(db_session, "del1")
    await _login_admin(client, admin, totp_secret)

    get_resp = await client.get("/admin/dashboard")
    csrf_token = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        f"/admin/reports/{report.id}/delete",
        data={"csrf_token": csrf_token},
    )
    assert resp.status_code == 200  # after redirect to dashboard

    # The Redis session key must be gone
    assert not await redis.exists(session_key)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_report_only_removes_matching_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting report A must not remove sessions for report B."""
    from app.redis_client import get_redis

    report_a, _ = await create_report(db_session, "financial_fraud", "Report A for isolation test.")
    report_b, _ = await create_report(db_session, "corruption", "Report B for isolation test.")

    redis = await get_redis()
    key_a = f"status-session:iso-a-{uuid.uuid4().hex}"
    key_b = f"status-session:iso-b-{uuid.uuid4().hex}"
    await redis.setex(key_a, 7200, str(report_a.id))
    await redis.setex(key_b, 7200, str(report_b.id))

    admin, totp_secret = await _create_admin(db_session, "del2")
    await _login_admin(client, admin, totp_secret)

    get_resp = await client.get("/admin/dashboard")
    csrf_token = get_resp.cookies.get("ow_csrf")

    # Delete only report A
    await client.post(
        f"/admin/reports/{report_a.id}/delete",
        data={"csrf_token": csrf_token},
    )

    # Session for A is gone, session for B is intact
    assert not await redis.exists(key_a)
    assert await redis.exists(key_b)

    # Cleanup Redis and report_b so later tests don't inherit a skewed case number counter
    await redis.delete(key_b)
    csrf_token2 = (await client.get("/admin/dashboard")).cookies.get("ow_csrf")
    await client.post(f"/admin/reports/{report_b.id}/delete", data={"csrf_token": csrf_token2})


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_report_with_no_sessions_succeeds(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting a report with no associated Redis sessions completes without error."""
    report, _ = await create_report(db_session, "other", "Report with no active sessions.")

    admin, totp_secret = await _create_admin(db_session, "del3")
    await _login_admin(client, admin, totp_secret)

    get_resp = await client.get("/admin/dashboard")
    csrf_token = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        f"/admin/reports/{report.id}/delete",
        data={"csrf_token": csrf_token},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleted_report_session_falls_back_to_login(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After a report is deleted, an existing status session shows the login form, not a crash."""
    from app.redis_client import get_redis

    report, pin = await create_report(
        db_session, "workplace_safety", "Report session fallback test."
    )

    # Simulate an active whistleblower session for this report
    redis = await get_redis()
    session_key = uuid.uuid4().hex
    await redis.setex(f"status-session:{session_key}", 7200, str(report.id))

    admin, totp_secret = await _create_admin(db_session, "del4")
    await _login_admin(client, admin, totp_secret)

    get_resp = await client.get("/admin/dashboard")
    csrf_token = get_resp.cookies.get("ow_csrf")

    await client.post(
        f"/admin/reports/{report.id}/delete",
        data={"csrf_token": csrf_token},
    )

    # The whistleblower now visits /status with the stale session cookie
    # (use a separate client to avoid admin cookie interference)
    from httpx import ASGITransport

    from app.main import app as ow_app

    async with AsyncClient(
        transport=ASGITransport(app=ow_app),
        base_url="http://test",
        follow_redirects=True,
        cookies={"ow-status-session": session_key},
    ) as wb_client:
        resp = await wb_client.get("/status")
        assert resp.status_code == 200
        # Should show the login form, not an error page
        assert "Case Number" in resp.text or "Vorgangsnummer" in resp.text
