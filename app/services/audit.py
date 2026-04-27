"""Audit log service — records every admin action for HinSchG §12 compliance."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
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
    CATEGORY_CREATED        = "category.created"
    CATEGORY_UPDATED        = "category.updated"
    CATEGORY_DEACTIVATED    = "category.deactivated"
    ADMIN_CREATED           = "admin.created"
    ADMIN_ROLE_CHANGED      = "admin.role_changed"
    ADMIN_DEACTIVATED       = "admin.deactivated"
    ADMIN_REACTIVATED       = "admin.reactivated"
    AUTH_LOGIN              = "auth.login"
    ORG_CREATED             = "org.created"
    ORG_DEACTIVATED         = "org.deactivated"


async def log(
    db: AsyncSession,
    actor: AdminUser,
    action: str,
    report_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        id=uuid.uuid4(),
        admin_id=actor.id,
        admin_username=actor.username,
        action=action,
        report_id=report_id,
        detail=json.dumps(detail) if detail else None,
    )
    db.add(entry)
    # Flush only — caller commits as part of their own transaction
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
) -> tuple[list[AuditLog], int]:
    from sqlalchemy import func

    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if report_id is not None:
        q = q.where(AuditLog.report_id == report_id)
    if action:
        q = q.where(AuditLog.action == action)
    if admin_id is not None:
        q = q.where(AuditLog.admin_id == admin_id)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total: int = count_result.scalar_one()

    rows = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    return list(rows.scalars().all()), total
