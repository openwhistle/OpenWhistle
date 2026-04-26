"""API-level tests for v0.3.0 endpoints.

Covers: categories, users, audit-log, stats, report assignment,
        notes, case linking, 4-eyes deletion, PDF export, status transitions.
"""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password
from app.services.report import create_report

# ── helpers ────────────────────────────────────────────────────────────────────


async def _make_admin(
    db: AsyncSession,
    username: str | None = None,
    role: AdminRole = AdminRole.admin,
    totp_secret: str = "JBSWY3DPEHPK3PXP",
) -> tuple[AdminUser, str]:
    uname = username or f"v3adm_{uuid.uuid4().hex[:8]}"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=uname,
        password_hash=hash_password("AdminTest!Pass1"),
        totp_secret=totp_secret,
        totp_enabled=True,
        role=role,
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login(client: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
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


async def _get_csrf(client: AsyncClient, url: str) -> str:
    r = await client.get(url)
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    return m.group(1) if m else ""


async def _make_report(db: AsyncSession) -> str:
    """Create a report and return its UUID as string."""
    report, _ = await create_report(
        db, category="financial_fraud", description="API test report detail.", lang="en"
    )
    return str(report.id)


# ── categories page ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_categories_page_loads(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/categories")
    assert r.status_code == 200
    assert "Category" in r.text


@pytest.mark.asyncio
async def test_create_category_via_api(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    csrf = await _get_csrf(client, "/admin/categories")
    slug = f"api_cat_{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/admin/categories",
        data={
            "csrf_token": csrf,
            "slug": slug,
            "label_en": "API Category",
            "label_de": "API Kategorie",
            "sort_order": "50",
        },
    )
    assert r.status_code == 200
    assert slug in r.text or "API Category" in r.text


@pytest.mark.asyncio
async def test_categories_requires_admin_role(client: AsyncClient, db_session: AsyncSession):
    cm, secret = await _make_admin(db_session, role=AdminRole.case_manager)
    await _login(client, cm, secret)

    r = await client.get("/admin/categories")
    assert r.status_code == 403


# ── users page ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_page_loads(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/users")
    assert r.status_code == 200
    assert admin.username in r.text


@pytest.mark.asyncio
async def test_create_user_via_api(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    csrf = await _get_csrf(client, "/admin/users")
    new_uname = f"created_{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/admin/users",
        data={
            "csrf_token": csrf,
            "username": new_uname,
            "password": "SecurePass12!",
            "role": "case_manager",
        },
    )
    assert r.status_code == 200
    assert new_uname in r.text


@pytest.mark.asyncio
async def test_users_requires_admin_role(client: AsyncClient, db_session: AsyncSession):
    cm, secret = await _make_admin(db_session, role=AdminRole.case_manager)
    await _login(client, cm, secret)

    r = await client.get("/admin/users")
    assert r.status_code == 403


# ── audit log page ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_page_loads(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/audit-log")
    assert r.status_code == 200
    assert "Audit" in r.text


@pytest.mark.asyncio
async def test_audit_log_csv_export(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/audit-log/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "timestamp" in r.text


# ── stats page ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_page_loads(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/stats")
    assert r.status_code == 200
    assert "Statistics" in r.text or "Statistiken" in r.text or "stat" in r.text.lower()


# ── report detail page ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_detail_404_for_unknown(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get(f"/admin/reports/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_report_detail_shows_new_sections(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    r = await client.get(f"/admin/reports/{rid}")
    assert r.status_code == 200
    # Check for new v0.3.0 sections
    assert "Internal Notes" in r.text or "Interne Notizen" in r.text
    assert "Linked Cases" in r.text or "Verknüpfte Fälle" in r.text


# ── assignment ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_report_via_api(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/assign",
        data={"csrf_token": csrf, "admin_id": str(admin.id)},
    )
    assert r.status_code == 200
    assert str(admin.username) in r.text


@pytest.mark.asyncio
async def test_assign_requires_admin_role(client: AsyncClient, db_session: AsyncSession):
    cm, secret = await _make_admin(db_session, role=AdminRole.case_manager)
    await _login(client, cm, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/assign",
        data={"csrf_token": csrf, "admin_id": ""},
    )
    assert r.status_code == 403


# ── internal notes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_note_via_api(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/notes",
        data={"csrf_token": csrf, "content": "This is an internal note."},
    )
    assert r.status_code == 200
    assert "This is an internal note." in r.text


@pytest.mark.asyncio
async def test_add_note_empty_content_422(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/notes",
        data={"csrf_token": csrf, "content": "   "},
    )
    assert r.status_code == 422


# ── case linking ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_cases_via_api(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid_a = await _make_report(db_session)

    # Create second report and get its case number
    from app.services.report import create_report
    report_b, _ = await create_report(
        db_session, category="corruption", description="Second report for linking test.", lang="en"
    )

    csrf = await _get_csrf(client, f"/admin/reports/{rid_a}")
    r = await client.post(
        f"/admin/reports/{rid_a}/links",
        data={"csrf_token": csrf, "case_number": report_b.case_number},
    )
    assert r.status_code == 200
    assert report_b.case_number in r.text


@pytest.mark.asyncio
async def test_link_self_returns_400(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    from app.services.report import get_report_by_id
    report = await get_report_by_id(db_session, uuid.UUID(rid))

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/links",
        data={"csrf_token": csrf, "case_number": report.case_number},  # type: ignore[union-attr]
    )
    assert r.status_code == 400


# ── status transitions ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_valid_transition(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    # Acknowledge first (moves to in_review)
    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    await client.post(f"/admin/reports/{rid}/acknowledge", data={"csrf_token": csrf})

    # Then move to pending_feedback
    csrf2 = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/status",
        data={"csrf_token": csrf2, "new_status": "pending_feedback"},
    )
    assert r.status_code == 200
    assert "pending_feedback" in r.text or "Pending Feedback" in r.text or "Rückmeldung" in r.text


@pytest.mark.asyncio
async def test_status_invalid_transition_returns_400(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(
        f"/admin/reports/{rid}/status",
        data={"csrf_token": csrf, "new_status": "pending_feedback"},
    )
    assert r.status_code == 400


# ── 4-eyes deletion ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_delete_creates_pending_state(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(f"/admin/reports/{rid}/request-delete", data={"csrf_token": csrf})
    assert r.status_code == 200
    # Should show pending deletion UI
    assert "Deletion Requested" in r.text or "Löschung beantragt" in r.text


@pytest.mark.asyncio
async def test_same_admin_cannot_confirm_own_deletion(
    client: AsyncClient, db_session: AsyncSession
):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    await client.post(f"/admin/reports/{rid}/request-delete", data={"csrf_token": csrf})

    csrf2 = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(f"/admin/reports/{rid}/confirm-delete", data={"csrf_token": csrf2})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cancel_deletion_request(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    csrf = await _get_csrf(client, f"/admin/reports/{rid}")
    await client.post(f"/admin/reports/{rid}/request-delete", data={"csrf_token": csrf})

    csrf2 = await _get_csrf(client, f"/admin/reports/{rid}")
    r = await client.post(f"/admin/reports/{rid}/cancel-delete", data={"csrf_token": csrf2})
    assert r.status_code == 200
    # Pending state should be gone
    assert "Deletion Requested" not in r.text


# ── PDF export ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_export(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    rid = await _make_report(db_session)

    r = await client.get(f"/admin/reports/{rid}/export.pdf")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 1000  # Non-trivial PDF


# ── dashboard new features ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_my_cases_filter(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/dashboard?my_cases=1")
    assert r.status_code == 200
    assert "My Cases" in r.text or "Meine Fälle" in r.text


@pytest.mark.asyncio
async def test_dashboard_new_status_filter_pills(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/dashboard")
    assert r.status_code == 200
    assert "in_review" in r.text
    assert "pending_feedback" in r.text


@pytest.mark.asyncio
async def test_dashboard_filter_in_review(client: AsyncClient, db_session: AsyncSession):
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)

    r = await client.get("/admin/dashboard?status=in_review")
    assert r.status_code == 200
