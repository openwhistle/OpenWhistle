"""Coverage tests for remaining app/api/admin.py gaps.

Covers:
- dashboard: invalid location_id query param is ignored (not a 500)
- link_report: linking two already-linked cases returns 409
- unlink_report: success, and link/report mismatch returns 404
- admin_reply: success path (message sent + audit log)
- category create/deactivate/reactivate: success paths
- user deactivate/reactivate: success paths
- audit_log_page: invalid page number falls back to page 1
- location create: required code / duplicate code errors
- location deactivate/reactivate: success paths
- demo_reset: success path when DEMO_MODE is true
- telephone_channel_page: renders
- organisations_page / create_organisation / deactivate_organisation (superadmin)
"""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.organisation import Organisation
from app.models.report import Report
from app.models.user import AdminRole, AdminUser
from app.services.report import create_report, link_cases
from tests.test_coverage_admin_extended import _create_admin, _login_admin

# ─── dashboard: invalid location_id ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_invalid_location_id_is_ignored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/dashboard?location_id=not-a-uuid")
    assert resp.status_code == 200


# ─── link_report: already linked ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_report_already_linked_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    report_a, _ = await create_report(db_session, "financial_fraud", "Case A for link test.")
    report_b, _ = await create_report(db_session, "financial_fraud", "Case B for link test.")
    await link_cases(db_session, report_a, report_b, admin)
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/reports/{report_a.id}/links",
        data={"case_number": report_b.case_number, "csrf_token": csrf},
    )
    assert resp.status_code == 409

    await db_session.execute(delete(Report).where(Report.id.in_([report_a.id, report_b.id])))
    await db_session.commit()


# ─── unlink_report: success + mismatch ────────────────────────────────────────


@pytest.mark.asyncio
async def test_unlink_report_success(client: AsyncClient, db_session: AsyncSession) -> None:
    admin, totp_secret = await _create_admin(db_session)
    report_a, _ = await create_report(db_session, "financial_fraud", "Case A for unlink test.")
    report_b, _ = await create_report(db_session, "financial_fraud", "Case B for unlink test.")
    link = await link_cases(db_session, report_a, report_b, admin)
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/reports/{report_a.id}/links/{link.id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f"/admin/reports/{report_a.id}" in resp.headers["location"]

    await db_session.execute(delete(Report).where(Report.id.in_([report_a.id, report_b.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_unlink_report_mismatched_link_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    report_a, _ = await create_report(db_session, "financial_fraud", "Case A for mismatch test.")
    report_b, _ = await create_report(db_session, "financial_fraud", "Case B for mismatch test.")
    report_c, _ = await create_report(db_session, "financial_fraud", "Case C for mismatch test.")
    link = await link_cases(db_session, report_a, report_b, admin)
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/reports/{report_c.id}/links/{link.id}/delete",
        data={"csrf_token": csrf},
    )
    assert resp.status_code == 404

    ids = [report_a.id, report_b.id, report_c.id]
    await db_session.execute(delete(Report).where(Report.id.in_(ids)))
    await db_session.commit()


# ─── admin_reply: success ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_reply_success(client: AsyncClient, db_session: AsyncSession) -> None:
    admin, totp_secret = await _create_admin(db_session)
    report, _ = await create_report(db_session, "financial_fraud", "Case for admin reply test.")
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/reports/{report.id}/reply",
        data={"content": "Thank you for the report, we are looking into it.", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f"/admin/reports/{report.id}" in resp.headers["location"]

    await db_session.execute(delete(Report).where(Report.id == report.id))
    await db_session.commit()


# ─── categories: create / deactivate / reactivate ─────────────────────────────


@pytest.mark.asyncio
async def test_category_deactivate_and_reactivate_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.category import ReportCategory

    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)
    slug = f"cov_cat_{uuid.uuid4().hex[:8]}"

    csrf = client.cookies.get("ow_csrf")
    create_resp = await client.post(
        "/admin/categories",
        data={
            "slug": slug,
            "label_en": "Coverage Category",
            "label_de": "Testkategorie",
            "sort_order": "50",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 302

    cat = (
        await db_session.execute(select(ReportCategory).where(ReportCategory.slug == slug))
    ).scalar_one()

    deact_resp = await client.post(
        f"/admin/categories/{cat.id}/deactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deact_resp.status_code == 302

    react_resp = await client.post(
        f"/admin/categories/{cat.id}/reactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert react_resp.status_code == 302

    await db_session.refresh(cat)
    assert cat.is_active is True

    await db_session.execute(delete(ReportCategory).where(ReportCategory.id == cat.id))
    await db_session.commit()


# ─── users: deactivate / reactivate ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_deactivate_and_reactivate_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    target, _ = await _create_admin(db_session)  # a second privileged admin
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    deact_resp = await client.post(
        f"/admin/users/{target.id}/deactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deact_resp.status_code == 302

    react_resp = await client.post(
        f"/admin/users/{target.id}/reactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert react_resp.status_code == 302

    await db_session.refresh(target)
    assert target.is_active is True


# ─── audit_log_page: invalid page number ──────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_invalid_page_falls_back_to_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/audit-log?page=not-a-number")
    assert resp.status_code == 200


# ─── locations: create errors + deactivate/reactivate success ────────────────


@pytest.mark.asyncio
async def test_create_location_requires_code(client: AsyncClient, db_session: AsyncSession) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        "/admin/locations",
        data={"name": "Coverage Office", "code": "   ", "csrf_token": csrf},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_location_duplicate_code_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)
    code = f"COV{uuid.uuid4().hex[:6].upper()}"

    csrf = client.cookies.get("ow_csrf")
    first = await client.post(
        "/admin/locations",
        data={"name": "Coverage Office", "code": code, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert first.status_code == 302

    second = await client.post(
        "/admin/locations",
        data={"name": "Coverage Office Two", "code": code, "csrf_token": csrf},
    )
    assert second.status_code == 409

    from app.models.location import Location

    await db_session.execute(delete(Location).where(Location.code == code))
    await db_session.commit()


@pytest.mark.asyncio
async def test_location_deactivate_and_reactivate_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.location import Location

    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)
    code = f"COV{uuid.uuid4().hex[:6].upper()}"

    csrf = client.cookies.get("ow_csrf")
    await client.post(
        "/admin/locations",
        data={"name": "Coverage Office Three", "code": code, "csrf_token": csrf},
        follow_redirects=False,
    )
    loc = (await db_session.execute(select(Location).where(Location.code == code))).scalar_one()

    deact_resp = await client.post(
        f"/admin/locations/{loc.id}/deactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deact_resp.status_code == 302

    react_resp = await client.post(
        f"/admin/locations/{loc.id}/reactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert react_resp.status_code == 302

    await db_session.refresh(loc)
    assert loc.is_active is True

    await db_session.execute(delete(Location).where(Location.id == loc.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_deactivate_location_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/locations/{uuid.uuid4()}/deactivate",
        data={"csrf_token": csrf},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_location_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/locations/{uuid.uuid4()}/reactivate",
        data={"csrf_token": csrf},
    )
    assert resp.status_code == 404


# ─── demo_reset: success ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_demo_reset_success_when_demo_mode(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock, patch

    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)
    monkeypatch.setattr(settings, "demo_mode", True)

    csrf = client.cookies.get("ow_csrf")
    with patch("app.services.demo_seed.seed_demo_data", AsyncMock()) as mock_seed:
        resp = await client.post("/admin/demo/reset", headers={"X-CSRF-Token": csrf or ""})

    assert resp.status_code == 200
    assert resp.json() == {"reset": True}
    mock_seed.assert_awaited_once()


@pytest.mark.asyncio
async def test_demo_reset_forbidden_when_not_demo_mode(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)
    monkeypatch.setattr(settings, "demo_mode", False)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post("/admin/demo/reset", headers={"X-CSRF-Token": csrf or ""})
    assert resp.status_code == 403


# ─── telephone_channel_page ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telephone_channel_page_renders(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_admin(db_session)
    await _login_admin(client, admin, totp_secret)

    resp = await client.get("/admin/telephone-channel")
    assert resp.status_code == 200


# ─── organisations: page / create / deactivate (superadmin) ──────────────────


async def _create_superadmin(db: AsyncSession) -> tuple[AdminUser, str]:
    from app.services.auth import hash_password

    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"cov_super_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("SuperCoverage!Pass1"),
        totp_secret=totp_secret,
        totp_enabled=True,
        role=AdminRole.superadmin,
    )
    db.add(admin)
    await db.commit()
    return admin, totp_secret


async def _login_superadmin(client: AsyncClient, admin: AdminUser, totp_secret: str) -> None:
    import pyotp

    get_resp = await client.get("/admin/login")
    csrf = get_resp.cookies.get("ow_csrf")
    r = await client.post(
        "/admin/login",
        data={"username": admin.username, "password": "SuperCoverage!Pass1", "csrf_token": csrf},
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


@pytest.mark.asyncio
async def test_organisations_page_and_create_and_deactivate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_superadmin(db_session)
    await _login_superadmin(client, admin, totp_secret)

    list_resp = await client.get("/admin/organisations")
    assert list_resp.status_code == 200

    slug = f"cov-org-{uuid.uuid4().hex[:8]}"
    csrf = client.cookies.get("ow_csrf")
    create_resp = await client.post(
        "/admin/organisations",
        data={"name": "Coverage Org", "slug": slug, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert create_resp.status_code == 302

    org = (
        await db_session.execute(select(Organisation).where(Organisation.slug == slug))
    ).scalar_one()

    deact_resp = await client.post(
        f"/admin/organisations/{org.id}/deactivate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert deact_resp.status_code == 302

    await db_session.refresh(org)
    assert org.is_active is False

    await db_session.execute(delete(Organisation).where(Organisation.id == org.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_organisation_invalid_slug_returns_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_superadmin(db_session)
    await _login_superadmin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        "/admin/organisations",
        data={"name": "No Slug Org", "slug": "   ", "csrf_token": csrf},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_organisation_duplicate_slug_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_superadmin(db_session)
    await _login_superadmin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        "/admin/organisations",
        data={"name": "Duplicate Org", "slug": "default", "csrf_token": csrf},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_organisation_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_superadmin(db_session)
    await _login_superadmin(client, admin, totp_secret)

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/organisations/{uuid.uuid4()}/deactivate",
        data={"csrf_token": csrf},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_default_organisation_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, totp_secret = await _create_superadmin(db_session)
    await _login_superadmin(client, admin, totp_secret)

    default_org = (
        await db_session.execute(select(Organisation).where(Organisation.slug == "default"))
    ).scalar_one()

    csrf = client.cookies.get("ow_csrf")
    resp = await client.post(
        f"/admin/organisations/{default_org.id}/deactivate",
        data={"csrf_token": csrf},
    )
    assert resp.status_code == 400
