"""Audit log service — records every admin action for HinSchG §11 compliance."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.report import Report
from app.models.user import AdminUser


class AuditAction:
    REPORT_STATUS_CHANGED   = "report.status_changed"
    REPORT_ASSIGNED         = "report.assigned"
    REPORT_UNASSIGNED       = "report.unassigned"
    REPORT_NOTE_ADDED       = "report.note_added"
    REPORT_MESSAGE_SENT     = "report.message_sent"
    REPORT_DELETE_REQUESTED = "report.delete_requested"
    REPORT_DELETE_CONFIRMED = "report.delete_confirmed"
    REPORT_DELETE_CANCELLED = "report.delete_cancelled"
    REPORT_ACKNOWLEDGED     = "report.acknowledged"
    REPORT_LINK_ADDED       = "report.link_added"
    REPORT_LINK_REMOVED     = "report.link_removed"
    REPORT_AUTO_DELETED     = "report.auto_deleted"
    REPORT_VIEWED           = "report.viewed"
    IDENTITY_REVEALED       = "report.identity_revealed"
    CATEGORY_CREATED        = "category.created"
    CATEGORY_UPDATED        = "category.updated"
    CATEGORY_DEACTIVATED    = "category.deactivated"
    LOCATION_CREATED        = "location.created"
    ADMIN_CREATED           = "admin.created"
    ADMIN_ROLE_CHANGED      = "admin.role_changed"
    ADMIN_DEACTIVATED       = "admin.deactivated"
    ADMIN_REACTIVATED       = "admin.reactivated"
    AUTH_LOGIN              = "auth.login"
    AUTH_TOTP_SETUP         = "auth.totp_setup"
    AUTH_SPRAYING_SUSPECTED = "auth.password_spraying_suspected"
    ORG_CREATED             = "org.created"
    ORG_DEACTIVATED         = "org.deactivated"


# Every action code, for the audit-log filter and the label-completeness test.
ALL_ACTIONS: tuple[str, ...] = tuple(
    v for k, v in vars(AuditAction).items() if k.isupper()
)


async def log(
    db: AsyncSession,
    actor: AdminUser,
    action: str,
    report_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    org_id = actor.org_id
    if report_id is not None:
        org_id = await db.scalar(select(Report.org_id).where(Report.id == report_id))

    entry = AuditLog(
        id=uuid.uuid4(),
        admin_id=actor.id,
        admin_username=actor.username,
        action=action,
        report_id=report_id,
        detail=json.dumps(detail) if detail else None,
        org_id=org_id,
    )
    db.add(entry)
    # Flush only — caller commits as part of their own transaction
    await db.flush()
    return entry


async def log_system(
    db: AsyncSession, action: str, detail: dict[str, Any] | None = None
) -> AuditLog:
    """Record an event no admin caused (e.g. a detected attack). Flush only."""
    entry = AuditLog(
        id=uuid.uuid4(),
        admin_id=None,
        admin_username="system",
        action=action,
        detail=json.dumps(detail) if detail else None,
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_audit_log(
    db: AsyncSession,
    *,
    report_id: uuid.UUID | None = None,
    action: str | None = None,
    admin_id: uuid.UUID | None = None,
    page: int = 1,
    per_page: int = 50,
    scope_org: bool = False,
    org_id: uuid.UUID | None = None,
    viewer_id: uuid.UUID | None = None,
    exclude_action: str | None = None,
) -> tuple[list[AuditLog], int]:
    """`scope_org`/`org_id` are `_org_scope(user)` — untouched, org-scoped semantics.

    An org-less non-superadmin (`scope_org=True, org_id=None`) is the one case
    `_org_scope` can't distinguish from "no scoping": here it must NOT see every
    org-less row (system alerts, other org-less admins' actions) — only rows they
    authored themselves. `viewer_id` (the caller's own admin id) carries that.
    """
    from sqlalchemy import func

    # created_at ties (same instant, or a day-floored row) need the id for a stable page.
    q = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if report_id is not None:
        q = q.where(AuditLog.report_id == report_id)
    if action:
        q = q.where(AuditLog.action == action)
    if exclude_action:
        q = q.where(AuditLog.action != exclude_action)
    if admin_id is not None:
        q = q.where(AuditLog.admin_id == admin_id)
    if scope_org:
        if org_id is not None:
            q = q.where(AuditLog.org_id == org_id)
        else:
            q = q.where(AuditLog.org_id.is_(None), AuditLog.admin_id == viewer_id)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total: int = count_result.scalar_one()

    rows = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    return list(rows.scalars().all()), total
