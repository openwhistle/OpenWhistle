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
async def test_audit_rows_carry_the_report_org_and_else_the_actor_org(
    db_session: AsyncSession,
) -> None:
    from app.models.organisation import Organisation
    from app.services import audit as audit_service
    from app.services.report import create_report

    org = Organisation(id=uuid.uuid4(), name="Org A", slug=f"a-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    actor = AdminUser(
        id=uuid.uuid4(), username=f"aud_{uuid.uuid4().hex[:8]}", password_hash=None,
        totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True, org_id=org.id,
    )
    db_session.add(actor)
    report, _ = await create_report(db_session, "corruption", "Audit org test report text.")
    report.org_id = org.id
    await db_session.commit()

    with_report = await audit_service.log(db_session, actor, "report.viewed", report_id=report.id)
    without = await audit_service.log(db_session, actor, "admin.created")
    await db_session.commit()
    assert with_report.org_id == org.id
    assert without.org_id == org.id


@pytest.mark.asyncio
async def test_audit_log_page_is_scoped_per_org(
    client: AsyncClient,
    as_admin_a: AsyncClient,
    two_orgs: dict[str, AdminUser],
    db_session: AsyncSession,
) -> None:
    """The cross-tenant leak Task 6 fixes: org A's audit row must not leak into org B's page."""
    from app.services.audit import log as audit_log

    await audit_log(db_session, two_orgs["admin_a"], "admin.created", detail={"username": "probe"})
    await db_session.commit()

    page_a = (await as_admin_a.get("/admin/audit-log")).text
    assert two_orgs["admin_a"].username in page_a

    admin_b = _user(two_orgs["user_b"].org_id)
    app.dependency_overrides[get_current_admin] = lambda: admin_b
    try:
        page_b = (await client.get("/admin/audit-log")).text
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert two_orgs["admin_a"].username not in page_b


def _org_less_admin() -> AdminUser:
    return AdminUser(
        id=uuid.uuid4(), username=f"ol_{uuid.uuid4().hex[:8]}", role=AdminRole.admin,
        is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True, org_id=None,
    )


@pytest.mark.asyncio
async def test_org_less_admin_sees_only_their_own_org_less_audit_rows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Residual NULL-org exposure fix: an org-less admin must not see the system's
    own alerts (admin_id NULL) nor another org-less admin's rows — only their own."""
    from app.services import audit as audit_service

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    viewer, other = _org_less_admin(), _org_less_admin()
    db_session.add_all([viewer, other])
    await db_session.flush()

    own = await audit_service.log(db_session, viewer, "admin.created")
    others_row = await audit_service.log(db_session, other, "admin.created")
    system_row = await audit_service.log_system(db_session, "auth.password_spraying_suspected")
    await db_session.commit()

    entries, total = await audit_service.get_audit_log(
        db_session, scope_org=True, org_id=None, viewer_id=viewer.id,
    )
    ids = {e.id for e in entries}
    assert own.id in ids
    assert others_row.id not in ids
    assert system_row.id not in ids
    assert total == 1


@pytest.mark.asyncio
async def test_superadmin_sees_system_audit_rows(db_session: AsyncSession) -> None:
    """A superadmin (`_org_scope` gives `scope_org=False`) is unrestricted — the only
    role that can see instance-wide system rows and every org's rows."""
    from app.services import audit as audit_service

    system_row = await audit_service.log_system(db_session, "auth.password_spraying_suspected")
    await db_session.commit()

    entries, _ = await audit_service.get_audit_log(db_session, scope_org=False, org_id=None)
    assert system_row.id in {e.id for e in entries}


@pytest.mark.asyncio
async def test_audit_log_csv_export_follows_org_less_scoping(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The export route shares `get_audit_log`, so it must follow the same rule as the page."""
    from app.services import audit as audit_service

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    viewer, other = _org_less_admin(), _org_less_admin()
    db_session.add_all([viewer, other])
    await db_session.flush()
    await audit_service.log(db_session, viewer, "admin.created")
    await audit_service.log(db_session, other, "admin.created")
    await audit_service.log_system(db_session, "auth.password_spraying_suspected")
    await db_session.commit()

    app.dependency_overrides[get_current_admin] = lambda: viewer
    try:
        resp = await client.get("/admin/audit-log/export.csv")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert viewer.username in resp.text
    assert other.username not in resp.text
    assert ",system," not in resp.text


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
