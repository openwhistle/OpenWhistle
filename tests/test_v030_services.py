"""Tests for v0.3.0 services: audit, categories, users, report enhancements."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import STATUS_TRANSITIONS, ReportStatus
from app.models.user import AdminRole, AdminUser
from app.services import audit as audit_service
from app.services.audit import AuditAction
from app.services.categories import (
    create_category,
    deactivate_category,
    get_active_categories,
    get_category_by_id,
    get_category_by_slug,
    reactivate_category,
)
from app.services.report import (
    acknowledge_report,
    add_note,
    assign_report,
    cancel_deletion_request,
    confirm_deletion,
    create_report,
    get_dashboard_stats,
    get_link,
    get_linked_reports,
    get_report_by_id,
    get_reports_paginated,
    is_valid_transition,
    link_cases,
    request_deletion,
    unlink_cases,
    update_report_status,
)
from app.services.users import (
    count_active_admins,
    create_user,
    deactivate_user,
    get_all_users,
    get_user_by_id,
    reactivate_user,
    update_user_role,
)

# ── helpers ────────────────────────────────────────────────────────────────────


async def _make_report(db: AsyncSession, category: str = "financial_fraud"):
    return await create_report(
        db, category=category, description="Test description with enough detail.", lang="en"
    )


async def _make_admin(
    db: AsyncSession,
    username: str = "testadmin",
    role: AdminRole = AdminRole.admin,
) -> AdminUser:
    user, _ = await create_user(db, username=username, password="TestPassword123!", role=role)
    return user


# ── STATUS_TRANSITIONS ─────────────────────────────────────────────────────────


def test_status_transitions_no_loops():
    for src, targets in STATUS_TRANSITIONS.items():
        assert src not in targets, f"{src} can transition to itself"


def test_is_valid_transition_positive():
    assert is_valid_transition("received", "in_review")
    assert is_valid_transition("in_review", "pending_feedback")
    assert is_valid_transition("pending_feedback", "closed")


def test_is_valid_transition_negative():
    assert not is_valid_transition("received", "pending_feedback")
    assert not is_valid_transition("closed", "received")
    assert not is_valid_transition("received", "received")


# ── audit service ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_records_entry(db_session: AsyncSession):
    actor = await _make_admin(db_session, username=f"auditactor_{uuid.uuid4().hex[:6]}")
    report, _ = await _make_report(db_session)

    entry = await audit_service.log(
        db_session,
        actor,
        AuditAction.REPORT_STATUS_CHANGED,
        report_id=report.id,
        detail={"old": "received", "new": "in_review"},
    )
    await db_session.commit()

    assert entry.id is not None
    assert entry.admin_username == actor.username
    assert entry.action == AuditAction.REPORT_STATUS_CHANGED
    assert entry.report_id == report.id
    assert "in_review" in entry.detail


@pytest.mark.asyncio
async def test_audit_log_get_filters_by_report(db_session: AsyncSession):
    actor = await _make_admin(db_session, username=f"auditget_{uuid.uuid4().hex[:6]}")
    report, _ = await _make_report(db_session)

    await audit_service.log(db_session, actor, AuditAction.REPORT_ACKNOWLEDGED, report_id=report.id)
    await db_session.commit()

    entries, total = await audit_service.get_audit_log(db_session, report_id=report.id)
    assert total >= 1
    assert all(str(e.report_id) == str(report.id) for e in entries)


@pytest.mark.asyncio
async def test_audit_log_no_detail_ok(db_session: AsyncSession):
    actor = await _make_admin(db_session, username=f"auditno_{uuid.uuid4().hex[:6]}")
    entry = await audit_service.log(db_session, actor, AuditAction.REPORT_MESSAGE_SENT)
    await db_session.commit()
    assert entry.detail is None


# ── categories service ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_custom_category(db_session: AsyncSession):
    slug = f"test_cat_{uuid.uuid4().hex[:6]}"
    cat = await create_category(db_session, slug, "Test Category", "Testkategorie", 30)
    assert cat.slug == slug
    assert cat.is_active
    assert not cat.is_default


@pytest.mark.asyncio
async def test_get_active_categories_excludes_inactive(db_session: AsyncSession):
    slug = f"inactive_{uuid.uuid4().hex[:6]}"
    cat = await create_category(db_session, slug, "Inactive Cat", "Inaktive Kat", 99)
    await deactivate_category(db_session, cat)

    active = await get_active_categories(db_session)
    active_slugs = [c.slug for c in active]
    assert slug not in active_slugs


@pytest.mark.asyncio
async def test_deactivate_and_reactivate_category(db_session: AsyncSession):
    slug = f"toggle_{uuid.uuid4().hex[:6]}"
    cat = await create_category(db_session, slug, "Toggle", "Toggle", 50)
    assert cat.is_active

    await deactivate_category(db_session, cat)
    assert not cat.is_active

    await reactivate_category(db_session, cat)
    assert cat.is_active


@pytest.mark.asyncio
async def test_get_category_by_slug(db_session: AsyncSession):
    slug = f"byslug_{uuid.uuid4().hex[:6]}"
    created = await create_category(db_session, slug, "By Slug", "Nach Slug", 50)
    fetched = await get_category_by_slug(db_session, slug)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_get_category_by_id(db_session: AsyncSession):
    slug = f"byid_{uuid.uuid4().hex[:6]}"
    created = await create_category(db_session, slug, "By ID", "Nach ID", 50)
    fetched = await get_category_by_id(db_session, created.id)
    assert fetched is not None
    assert fetched.slug == slug


# ── users service ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user_returns_user_and_totp(db_session: AsyncSession):
    username = f"newuser_{uuid.uuid4().hex[:6]}"
    user, totp = await create_user(db_session, username, "SecurePass12!", AdminRole.admin)
    assert user.id is not None
    assert user.username == username
    assert user.role == AdminRole.admin
    assert user.is_active
    assert len(totp) > 8


@pytest.mark.asyncio
async def test_create_case_manager(db_session: AsyncSession):
    username = f"cm_{uuid.uuid4().hex[:6]}"
    user, _ = await create_user(db_session, username, "SecurePass12!", AdminRole.case_manager)
    assert user.role == AdminRole.case_manager


@pytest.mark.asyncio
async def test_deactivate_and_reactivate_user(db_session: AsyncSession):
    username = f"toggle_u_{uuid.uuid4().hex[:6]}"
    user, _ = await create_user(db_session, username, "SecurePass12!", AdminRole.admin)
    assert user.is_active

    await deactivate_user(db_session, user)
    assert not user.is_active

    await reactivate_user(db_session, user)
    assert user.is_active


@pytest.mark.asyncio
async def test_update_user_role(db_session: AsyncSession):
    username = f"role_u_{uuid.uuid4().hex[:6]}"
    user, _ = await create_user(db_session, username, "SecurePass12!", AdminRole.admin)
    assert user.role == AdminRole.admin

    await update_user_role(db_session, user, AdminRole.case_manager)
    assert user.role == AdminRole.case_manager


@pytest.mark.asyncio
async def test_count_active_admins(db_session: AsyncSession):
    initial = await count_active_admins(db_session)
    username = f"countme_{uuid.uuid4().hex[:6]}"
    user, _ = await create_user(db_session, username, "SecurePass12!", AdminRole.admin)
    after = await count_active_admins(db_session)
    assert after == initial + 1

    await deactivate_user(db_session, user)
    after_deact = await count_active_admins(db_session)
    assert after_deact == initial


@pytest.mark.asyncio
async def test_get_all_users(db_session: AsyncSession):
    before = len(await get_all_users(db_session))
    username = f"list_u_{uuid.uuid4().hex[:6]}"
    await create_user(db_session, username, "SecurePass12!", AdminRole.admin)
    after = await get_all_users(db_session)
    assert len(after) == before + 1


@pytest.mark.asyncio
async def test_get_user_by_id(db_session: AsyncSession):
    username = f"byid_u_{uuid.uuid4().hex[:6]}"
    user, _ = await create_user(db_session, username, "SecurePass12!", AdminRole.admin)
    fetched = await get_user_by_id(db_session, user.id)
    assert fetched is not None
    assert fetched.username == username


# ── report assignment ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_report(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    admin = await _make_admin(db_session, username=f"assignee_{uuid.uuid4().hex[:6]}")

    await assign_report(db_session, report, admin)
    assert report.assigned_to_id == admin.id


@pytest.mark.asyncio
async def test_unassign_report(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    admin = await _make_admin(db_session, username=f"unassign_{uuid.uuid4().hex[:6]}")

    await assign_report(db_session, report, admin)
    await assign_report(db_session, report, None)
    assert report.assigned_to_id is None


# ── internal notes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_note(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    admin = await _make_admin(db_session, username=f"noter_{uuid.uuid4().hex[:6]}")

    note = await add_note(db_session, report, admin, "Test internal note.")
    assert note.id is not None
    assert note.author_username == admin.username
    assert note.content == "Test internal note."
    assert note.report_id == report.id


# ── 4-eyes deletion ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_deletion(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    admin = await _make_admin(db_session, username=f"delreq_{uuid.uuid4().hex[:6]}")

    dr = await request_deletion(db_session, report, admin)
    assert dr.id is not None
    assert dr.requested_by_id == admin.id
    assert dr.report_id == report.id


@pytest.mark.asyncio
async def test_cancel_deletion_request(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    admin = await _make_admin(db_session, username=f"delcancel_{uuid.uuid4().hex[:6]}")

    dr = await request_deletion(db_session, report, admin)
    await cancel_deletion_request(db_session, dr)

    # Verify it's gone
    refreshed = await get_report_by_id(db_session, report.id)
    assert refreshed is not None
    assert refreshed.deletion_request is None


@pytest.mark.asyncio
async def test_confirm_deletion_erases_report(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    rid = report.id
    requester = await _make_admin(db_session, username=f"delconf_r_{uuid.uuid4().hex[:6]}")
    confirmer = await _make_admin(db_session, username=f"delconf_c_{uuid.uuid4().hex[:6]}")

    dr = await request_deletion(db_session, report, requester)
    await confirm_deletion(db_session, report, dr, confirmer)

    gone = await get_report_by_id(db_session, rid)
    assert gone is None


# ── case linking ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_cases(db_session: AsyncSession):
    report_a, _ = await _make_report(db_session)
    report_b, _ = await _make_report(db_session)
    actor = await _make_admin(db_session, username=f"linker_{uuid.uuid4().hex[:6]}")

    link = await link_cases(db_session, report_a, report_b, actor)
    assert link.id is not None

    refreshed_a = await get_report_by_id(db_session, report_a.id)
    linked = get_linked_reports(refreshed_a)  # type: ignore[arg-type]
    linked_ids = [str(t[0]) for t in linked]
    assert str(report_b.id) in linked_ids


@pytest.mark.asyncio
async def test_link_same_pair_normalized(db_session: AsyncSession):
    """Both orderings of the same pair should produce the same normalization."""
    report_a, _ = await _make_report(db_session)
    report_b, _ = await _make_report(db_session)
    actor = await _make_admin(db_session, username=f"normer_{uuid.uuid4().hex[:6]}")

    link = await link_cases(db_session, report_b, report_a, actor)
    smaller = str(report_a.id) if str(report_a.id) < str(report_b.id) else str(report_b.id)
    assert str(link.report_id_a) == smaller


@pytest.mark.asyncio
async def test_unlink_cases(db_session: AsyncSession):
    report_a, _ = await _make_report(db_session)
    report_b, _ = await _make_report(db_session)
    actor = await _make_admin(db_session, username=f"unlinker_{uuid.uuid4().hex[:6]}")

    link = await link_cases(db_session, report_a, report_b, actor)
    fetched_link = await get_link(db_session, link.id)
    assert fetched_link is not None

    await unlink_cases(db_session, link)
    gone = await get_link(db_session, link.id)
    assert gone is None


# ── dashboard stats ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_dashboard_stats_structure(db_session: AsyncSession):
    stats = await get_dashboard_stats(db_session)
    assert "status_counts" in stats
    assert "by_category" in stats
    assert "total_reports" in stats
    assert "sla_7day_rate" in stats
    assert isinstance(stats["total_reports"], int)
    assert 0 <= stats["sla_7day_rate"] <= 100


# ── report pagination with assignee filter ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_reports_paginated_my_cases(db_session: AsyncSession):
    admin = await _make_admin(db_session, username=f"paginassign_{uuid.uuid4().hex[:6]}")
    report, _ = await _make_report(db_session)
    await assign_report(db_session, report, admin)

    my_reports, total = await get_reports_paginated(
        db_session, page=1, per_page=100, assigned_to_id=admin.id
    )
    assert any(str(r.id) == str(report.id) for r in my_reports)


# ── acknowledge moves to in_review ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acknowledge_report_moves_to_in_review(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    assert report.status == ReportStatus.received

    await acknowledge_report(db_session, report)
    assert report.status == ReportStatus.in_review
    assert report.acknowledged_at is not None
    assert report.feedback_due_at is not None


# ── status update ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_status_to_pending_feedback(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    await acknowledge_report(db_session, report)

    await update_report_status(db_session, report, ReportStatus.pending_feedback)
    assert report.status == ReportStatus.pending_feedback


@pytest.mark.asyncio
async def test_update_status_to_closed_sets_closed_at(db_session: AsyncSession):
    report, _ = await _make_report(db_session)
    await acknowledge_report(db_session, report)
    await update_report_status(db_session, report, ReportStatus.pending_feedback)
    await update_report_status(db_session, report, ReportStatus.closed)

    assert report.status == ReportStatus.closed
    assert report.closed_at is not None
