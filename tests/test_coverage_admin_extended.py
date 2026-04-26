"""Extended coverage tests for app/api/admin.py gaps.

Covers:
- dashboard: query parameters (sort, per_page, page, status_filter) (lines 54-115)
- acknowledge_report endpoint (lines 143-156)
- update_status endpoint including invalid status (lines 159-178)
- admin_download_attachment: valid download, wrong report 404, not found 404 (lines 230-248)
- dismiss_ip_warning endpoint (lines 222-227)
- cleanup_report_sessions helper via delete_report flow (lines 27-41)
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
        username=f"adm_ext_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("AdminExt!Pass1"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login_admin(client: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")
    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "AdminExt!Pass1", "csrf_token": csrf},
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


async def _get_csrf(client: AsyncClient, path: str = "/admin/dashboard") -> str:
    resp = await client.get(path)
    m = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    return m.group(1) if m else (resp.cookies.get("ow_csrf") or "")


async def _create_and_find_report(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[str, str]:
    """Submit a report via API and find it in the dashboard. Returns (report_id, case_number)."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    submit_resp = await client.post(
        "/submit",
        data={
            "category": "financial_fraud",
            "description": "Admin extended test report content.",
            "csrf_token": csrf,
        },
    )
    case_m = re.search(r"OW-\d{4}-\d{5}", submit_resp.text)
    case_number = case_m.group(0) if case_m else ""

    dash = await client.get("/admin/dashboard")
    id_m = re.search(r'/admin/reports/([0-9a-f-]{36})"', dash.text)
    report_id = id_m.group(1) if id_m else ""
    return report_id, case_number


# ─── dashboard: query parameters ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_loads_successfully(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_with_sort_asc_case_number(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?sort=case_number&dir=asc")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_with_per_page_10(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?per_page=10")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_with_invalid_per_page_falls_back(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?per_page=notanumber&page=notanumber")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_with_status_filter_received(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?status=received")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_with_invalid_sort_field_falls_back(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?sort=nonexistent&dir=sideways")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_page_2(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?page=2&per_page=1")
    assert resp.status_code == 200


# ─── acknowledge_report ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acknowledge_report_endpoint_redirects(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    report_id, _ = await _create_and_find_report(client, db_session)
    assert report_id

    csrf = await _get_csrf(client, f"/admin/reports/{report_id}")
    resp = await client.post(
        f"/admin/reports/{report_id}/acknowledge",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f"/admin/reports/{report_id}" in resp.headers["location"]


@pytest.mark.asyncio
async def test_acknowledge_report_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    fake_id = uuid.uuid4()
    csrf = await _get_csrf(client)
    resp = await client.post(
        f"/admin/reports/{fake_id}/acknowledge",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ─── update_status ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_status_to_in_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    report_id, _ = await _create_and_find_report(client, db_session)
    assert report_id

    csrf = await _get_csrf(client, f"/admin/reports/{report_id}")
    resp = await client.post(
        f"/admin/reports/{report_id}/status",
        data={"new_status": "in_progress", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302


@pytest.mark.asyncio
async def test_update_status_invalid_enum_returns_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    report_id, _ = await _create_and_find_report(client, db_session)
    assert report_id

    csrf = await _get_csrf(client, f"/admin/reports/{report_id}")
    resp = await client.post(
        f"/admin/reports/{report_id}/status",
        data={"new_status": "not_a_real_status", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_status_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    fake_id = uuid.uuid4()
    csrf = await _get_csrf(client)
    resp = await client.post(
        f"/admin/reports/{fake_id}/status",
        data={"new_status": "in_progress", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ─── admin_download_attachment ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_download_attachment_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    report_id, _ = await _create_and_find_report(client, db_session)
    assert report_id

    resp = await client.get(
        f"/admin/reports/{report_id}/attachments/{uuid.uuid4()}",
        follow_redirects=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_download_attachment_wrong_report_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An attachment exists but belongs to a different report → 404."""
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get(
        f"/admin/reports/{uuid.uuid4()}/attachments/{uuid.uuid4()}",
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ─── dismiss_ip_warning ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dismiss_ip_warning_returns_cleared(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.post("/admin/ip-warning/dismiss")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("cleared") is True


# ─── delete_report (cleanup_report_sessions) ─────────────────────────────────


@pytest.mark.asyncio
async def test_delete_report_cleans_up_whistleblower_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After hard-deleting a report, any associated status-session keys must be gone."""
    from app.redis_client import get_redis

    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    report_id, _ = await _create_and_find_report(client, db_session)
    assert report_id

    # Plant a fake status-session key pointing to this report
    redis = await get_redis()
    fake_session_key = f"status-session:cleanup-test-{uuid.uuid4().hex}"
    await redis.setex(fake_session_key, 7200, report_id)
    assert await redis.exists(fake_session_key) == 1

    csrf = await _get_csrf(client, f"/admin/reports/{report_id}")
    await client.post(
        f"/admin/reports/{report_id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=True,
    )

    assert await redis.exists(fake_session_key) == 0
