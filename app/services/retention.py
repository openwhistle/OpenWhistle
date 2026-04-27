"""Data-retention service — hard-deletes closed reports past the retention window.

Runs as a daily APScheduler job (03:00 UTC). Each deleted report produces an
immutable audit log entry (REPORT_AUTO_DELETED) written by the "system" actor.

Compliance basis:
  GDPR Art. 5(1)(e) — storage limitation (data not kept longer than necessary)
  HinSchG §12 Abs. 3 — documentation obligation (3-year minimum retention)

The default RETENTION_DAYS=1095 (3 years) ensures the HinSchG §12 Abs. 3
minimum is met before auto-deletion begins. Operators may increase this value
for their own legal requirements; setting it below 1095 is at the operator's
own legal risk.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)


async def run_retention_cleanup() -> None:
    """Hard-delete closed reports that have exceeded the configured retention window.

    Called by the APScheduler daily cron job. Opens its own DB session so it is
    fully independent of any request-scoped resources.
    """
    from app.config import settings

    if not settings.retention_enabled:
        return

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.audit import AuditLog
    from app.models.report import Report, ReportStatus

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)
    deleted_count = 0

    try:
        async with session_factory() as db:
            result = await db.execute(
                select(Report).where(
                    Report.status == ReportStatus.closed,
                    Report.closed_at.isnot(None),
                    Report.closed_at < cutoff,
                )
            )
            reports = result.scalars().all()

            for report in reports:
                audit_entry = AuditLog(
                    id=uuid.uuid4(),
                    admin_id=None,
                    admin_username="system",
                    action="report.auto_deleted",
                    report_id=None,  # report is about to be deleted; store case_number in detail
                    org_id=report.org_id,  # preserve org context for multi-tenant audit trails
                    detail=json.dumps({
                        "case_number": report.case_number,
                        "closed_at": report.closed_at.isoformat() if report.closed_at else None,
                        "retention_days": settings.retention_days,
                        "reason": "GDPR Art. 5(1)(e) / HinSchG §12 — retention period exceeded",
                    }),
                )
                db.add(audit_entry)
                await db.execute(delete(Report).where(Report.id == report.id))
                deleted_count += 1
                log.info(
                    "Auto-deleted report %s (closed_at=%s, retention=%d days)",
                    report.case_number,
                    report.closed_at,
                    settings.retention_days,
                )

            await db.commit()

    except Exception:
        log.exception("Retention cleanup failed")
    finally:
        await engine.dispose()

    if deleted_count:
        log.info("Retention cleanup complete: %d report(s) deleted.", deleted_count)
    else:
        log.debug("Retention cleanup: no reports eligible for deletion.")
