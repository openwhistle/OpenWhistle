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


def _wiz_csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


def _wiz_step(text: str) -> int:
    m = re.search(r'name="step" value="(\d+)"', text)
    return int(m.group(1)) if m else 1


# ─── UX #1: Browser validation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_step1_server_validates_mode_required(client: AsyncClient) -> None:
    """Server-side validation: step 1 must re-render with an error when no mode is selected.

    The wizard uses novalidate intentionally (server validates each step).
    This test confirms the server enforces mode selection at step 1.
    """
    resp = await client.get("/submit")
    assert resp.status_code == 200
    csrf = _wiz_csrf(resp.text)

    # POST step 1 with no submission_mode — server must reject it
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": "",
    })
    assert resp.status_code == 200
    # Must stay on mode-selection (submission_mode radios still present)
    assert "submission_mode" in resp.text


@pytest.mark.asyncio
async def test_status_form_has_no_novalidate(client: AsyncClient) -> None:
    """Status check form must not carry novalidate — browser enforces required fields."""
    resp = await client.get("/status")
    assert resp.status_code == 200
    form_match = re.search(r"<form[^>]+action=\"/status\"[^>]*>", resp.text)
    assert form_match is not None, "Could not find /status form tag"
    assert "novalidate" not in form_match.group(0)


@pytest.mark.asyncio
async def test_submit_step3_category_field_carries_required(client: AsyncClient) -> None:
    """Category select (step 3) must have the required attribute."""
    # Walk through step 1 to reach step 3 (category), skipping step 2 if locations are active
    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": "anonymous",
    })
    assert resp.status_code == 200

    # Step 2 (location — conditional): skip if present by posting with empty location_id
    if _wiz_step(resp.text) == 2:
        csrf = _wiz_csrf(resp.text)
        resp = await client.post("/submit", data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": "",
        })
        assert resp.status_code == 200

    # Now on step 3: select#category should have required
    assert re.search(r'<select[^>]+id="category"[^>]*required', resp.text)


@pytest.mark.asyncio
async def test_submit_step4_description_field_carries_required(client: AsyncClient) -> None:
    """Description textarea (step 4) must have the required attribute."""
    # Walk steps 1 (mode), optional step 2 (location), step 3 (category) to reach step 4
    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)

    # Step 1
    resp = await client.post("/submit", data={
        "csrf_token": csrf, "step": "1", "action": "next", "submission_mode": "anonymous",
    })

    # Step 2 (location — conditional): skip if present by posting with empty location_id
    if _wiz_step(resp.text) == 2:
        csrf = _wiz_csrf(resp.text)
        resp = await client.post("/submit", data={
            "csrf_token": csrf, "step": "2", "action": "next", "location_id": "",
        })

    # Step 3 (category)
    csrf = _wiz_csrf(resp.text)
    step3_num = _wiz_step(resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf, "step": str(step3_num), "action": "next",
        "category": "financial_fraud",
    })

    assert resp.status_code == 200
    # Step 4: textarea#description should have required
    assert re.search(r'<textarea[^>]+id="description"[^>]*required', resp.text)


@pytest.mark.asyncio
async def test_status_form_fields_carry_required(client: AsyncClient) -> None:
    """Case number and PIN inputs have the required attribute."""
    resp = await client.get("/status")
    assert resp.status_code == 200
    assert re.search(r'<input[^>]+id="case_number"[^>]*required', resp.text)
    assert re.search(r'<input[^>]+id="pin"[^>]*required', resp.text)


# ─── UX #10: Redis session cleanup on report deletion ─────────────────────────


async def _delete_report_4eyes(
    client: AsyncClient,
    db: AsyncSession,
    report_id: str,
    requester_suffix: str,
    confirmer_suffix: str,
) -> None:
    """Full 4-eyes deletion: requester requests, confirmer confirms."""
    requester, req_secret = await _create_admin(db, requester_suffix)
    confirmer, con_secret = await _create_admin(db, confirmer_suffix)

    # Requester logs in and requests deletion
    await _login_admin(client, requester, req_secret)
    csrf = (await client.get(f"/admin/reports/{report_id}")).cookies.get("ow_csrf")
    await client.post(f"/admin/reports/{report_id}/request-delete", data={"csrf_token": csrf})

    # Confirmer logs in and confirms
    await client.get("/admin/logout")
    await _login_admin(client, confirmer, con_secret)
    csrf2 = (await client.get(f"/admin/reports/{report_id}")).cookies.get("ow_csrf")
    await client.post(f"/admin/reports/{report_id}/confirm-delete", data={"csrf_token": csrf2})


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_report_removes_redis_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Confirming 4-eyes deletion removes active whistleblower status-session keys in Redis."""
    from app.redis_client import get_redis

    report, _ = await create_report(db_session, "corruption", "Report for deletion cleanup test.")

    redis = await get_redis()
    session_key = f"status-session:test-session-{uuid.uuid4().hex}"
    await redis.setex(session_key, 7200, str(report.id))
    assert await redis.exists(session_key)

    await _delete_report_4eyes(client, db_session, str(report.id), "dr1a", "dr1b")

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

    await _delete_report_4eyes(client, db_session, str(report_a.id), "dr2a", "dr2b")

    assert not await redis.exists(key_a)
    assert await redis.exists(key_b)

    # Cleanup
    await redis.delete(key_b)
    await _delete_report_4eyes(client, db_session, str(report_b.id), "dr2c", "dr2d")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_report_with_no_sessions_succeeds(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting a report with no associated Redis sessions completes without error."""
    report, _ = await create_report(db_session, "other", "Report with no active sessions.")
    await _delete_report_4eyes(client, db_session, str(report.id), "dr3a", "dr3b")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleted_report_session_falls_back_to_login(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After a report is deleted, an existing status session shows the login form, not a crash."""
    from app.redis_client import get_redis

    report, _ = await create_report(
        db_session, "workplace_safety", "Report session fallback test."
    )

    redis = await get_redis()
    session_key = uuid.uuid4().hex
    await redis.setex(f"status-session:{session_key}", 7200, str(report.id))

    await _delete_report_4eyes(client, db_session, str(report.id), "dr4a", "dr4b")

    from httpx import ASGITransport

    from app.main import app as ow_app

    async with AsyncClient(
        transport=ASGITransport(app=ow_app),
        base_url="https://test",
        follow_redirects=True,
        cookies={"ow-status-session": session_key},
    ) as wb_client:
        resp = await wb_client.get("/status")
        assert resp.status_code == 200
        assert "Case Number" in resp.text or "Vorgangsnummer" in resp.text
