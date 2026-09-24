"""With multi-tenancy on, an org admin sees and manages only their own org:
users, assignment targets, audit log and statistics."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.config import settings
from app.main import app
from app.models.organisation import Organisation
from app.models.user import AdminRole, AdminUser


def _user(org: uuid.UUID, role: AdminRole = AdminRole.admin) -> AdminUser:
    return AdminUser(
        id=uuid.uuid4(), username=f"mt_{uuid.uuid4().hex[:8]}", role=role, org_id=org,
        is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True,
    )


@pytest_asyncio.fixture(loop_scope="function")
async def two_orgs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dict[str, AdminUser]]:
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    orgs = [Organisation(id=uuid.uuid4(), name=n, slug=f"{n}-{uuid.uuid4().hex[:6]}") for n in "ab"]
    db_session.add_all(orgs)
    await db_session.flush()
    users = {
        "admin_a": _user(orgs[0].id),
        "peer_a": _user(orgs[0].id, AdminRole.case_manager),
        "user_b": _user(orgs[1].id, AdminRole.case_manager),
    }
    db_session.add_all(users.values())
    await db_session.commit()
    yield users


@pytest_asyncio.fixture(loop_scope="function")
async def as_admin_a(
    client: AsyncClient, two_orgs: dict[str, AdminUser]
) -> AsyncGenerator[AsyncClient]:
    app.dependency_overrides[get_current_admin] = lambda: two_orgs["admin_a"]
    yield client
    app.dependency_overrides.pop(get_current_admin, None)


async def _csrf(client: AsyncClient) -> str:
    return (await client.get("/admin/login")).cookies.get("ow_csrf") or ""


@pytest.mark.asyncio
async def test_users_page_lists_only_own_org(
    as_admin_a: AsyncClient, two_orgs: dict[str, AdminUser]
) -> None:
    resp = await as_admin_a.get("/admin/users")
    assert two_orgs["peer_a"].username in resp.text
    assert two_orgs["user_b"].username not in resp.text


@pytest.mark.asyncio
async def test_cannot_change_role_of_other_org_user(
    as_admin_a: AsyncClient, two_orgs: dict[str, AdminUser]
) -> None:
    csrf = await _csrf(as_admin_a)
    resp = await as_admin_a.post(
        f"/admin/users/{two_orgs['user_b'].id}/role",
        data={"role": "admin", "csrf_token": csrf}, follow_redirects=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_assign_report_to_other_org_user(
    as_admin_a: AsyncClient, two_orgs: dict[str, AdminUser], db_session: AsyncSession
) -> None:
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Cross-org assignment test.")
    report.org_id = two_orgs["admin_a"].org_id
    await db_session.commit()

    csrf = await _csrf(as_admin_a)
    resp = await as_admin_a.post(
        f"/admin/reports/{report.id}/assign",
        data={"admin_id": str(two_orgs["user_b"].id), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_audit_log_and_stats_are_scoped(
    db_session: AsyncSession, two_orgs: dict[str, AdminUser]
) -> None:
    from app.models.audit import AuditLog
    from app.services.audit import get_audit_log
    from app.services.report import create_report, get_report_stats

    org_a, org_b = two_orgs["admin_a"].org_id, two_orgs["user_b"].org_id
    report, _ = await create_report(db_session, "financial_fraud", "Scoped stats test.")
    report.org_id = org_b
    db_session.add(AuditLog(id=uuid.uuid4(), admin_username="x", action="t", org_id=org_b))
    await db_session.commit()

    entries, _ = await get_audit_log(db_session, scope_org=True, org_id=org_a)
    assert all(e.org_id == org_a for e in entries)
    stats_a = await get_report_stats(db_session, scope_org=True, org_id=org_a)
    stats_b = await get_report_stats(db_session, scope_org=True, org_id=org_b)
    assert sum(stats_a.values()) == 0
    assert sum(stats_b.values()) >= 1


@pytest.mark.asyncio
async def test_new_user_joins_the_creators_org(
    as_admin_a: AsyncClient, two_orgs: dict[str, AdminUser], db_session: AsyncSession
) -> None:
    from sqlalchemy import select

    name = f"new_{uuid.uuid4().hex[:8]}"
    csrf = await _csrf(as_admin_a)
    resp = await as_admin_a.post(
        "/admin/users",
        data={"username": name, "password": "a-long-password-123", "role": "case_manager",
              "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    query = select(AdminUser).where(AdminUser.username == name)
    created = (await db_session.execute(query)).scalar_one()
    assert created.org_id == two_orgs["admin_a"].org_id


@pytest.mark.asyncio
async def test_assignment_picker_offers_only_the_reports_org(
    as_admin_a: AsyncClient, two_orgs: dict[str, AdminUser], db_session: AsyncSession
) -> None:
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Picker scoping test.")
    report.org_id = two_orgs["admin_a"].org_id
    await db_session.commit()

    page = (await as_admin_a.get(f"/admin/reports/{report.id}")).text
    assert two_orgs["peer_a"].username in page
    assert two_orgs["user_b"].username not in page


@pytest.mark.asyncio
async def test_dashboard_statistics_are_scoped(
    db_session: AsyncSession, two_orgs: dict[str, AdminUser]
) -> None:
    from app.services.report import create_report, get_dashboard_stats

    report, _ = await create_report(db_session, "financial_fraud", "Scoped dashboard stats.")
    report.org_id = two_orgs["user_b"].org_id
    await db_session.commit()

    org_a = two_orgs["admin_a"].org_id
    stats_a = await get_dashboard_stats(db_session, scope_org=True, org_id=org_a)
    assert stats_a["total_reports"] == 0
    assert stats_a["by_category"] == {}
