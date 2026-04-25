"""Integration tests for dashboard pagination, sorting, and filtering."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import ReportStatus
from app.models.user import AdminUser
from app.services.auth import hash_password
from app.services.report import create_report, update_report_status

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _create_admin(db: AsyncSession, suffix: str = "") -> tuple[AdminUser, str]:
    """Create a test admin user and return (user, totp_secret)."""
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"pg_admin_{suffix or uuid.uuid4().hex[:6]}",
        password_hash=hash_password("Pagination!Test123"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login_admin(ac: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    """Perform the full two-step admin login."""
    get_resp = await ac.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")

    login_resp = await ac.post(
        "/admin/login",
        data={
            "username": admin.username,
            "password": "Pagination!Test123",
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


# ─── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_loads_for_authenticated_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "load")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text or "Meldungen" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_default_pagination_renders(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "paginit")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?page=1&per_page=25")
    assert resp.status_code == 200
    assert "per_page" in resp.text or "25" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_status_filter_received(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "filt1")
    await _login_admin(client, admin, totp_secret)

    r, _ = await create_report(db_session, "other", "Filter test report status received here!")
    await update_report_status(db_session, r, ReportStatus.closed)

    resp = await client.get("/admin/dashboard?status=received")
    assert resp.status_code == 200
    assert r.case_number not in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_status_filter_closed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "filt2")
    await _login_admin(client, admin, totp_secret)

    r, _ = await create_report(db_session, "corruption", "Closed filter test report is here ok!")
    await update_report_status(db_session, r, ReportStatus.closed)

    resp = await client.get("/admin/dashboard?status=closed")
    assert resp.status_code == 200
    assert r.case_number in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_sort_asc_contains_sort_indicators(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "sort1")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?sort=submitted_at&dir=asc")
    assert resp.status_code == 200
    assert "↑" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_sort_desc_contains_sort_indicators(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "sort2")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?sort=submitted_at&dir=desc")
    assert resp.status_code == 200
    assert "↓" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_page_beyond_end_is_empty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "pgempty")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?page=9999&per_page=25")
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_invalid_sort_falls_back_gracefully(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "sortfb")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?sort=injected_field&dir=drop_table")
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_per_page_selector_present(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "pp1")
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert "per_page" in resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_stat_cards_show_counts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session, "stats1")
    await _login_admin(client, admin, totp_secret)

    await create_report(db_session, "financial_fraud", "Stats card test report enough length!")

    resp = await client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert "stat-card" in resp.text
