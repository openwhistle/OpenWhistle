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

    from redis.asyncio import Redis
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.audit import AuditLog
    from app.models.report import Report, ReportStatus

    # Distributed lock: with multiple stateless replicas each running a
    # scheduler, only one may perform the daily cleanup, otherwise the same
    # deletions are audited twice. Acquire → run → release; the TTL is only a
    # crash safety-net. Use a dedicated short-lived connection (not the shared
    # request-scoped client) so the job never binds/poisons that client's loop.
    lock_key = "openwhistle:job_lock:retention"
    lock_redis = None
    acquired = False
    engine = None
    deleted_count = 0
    try:
        # Best-effort: if the lock backend is unreachable, still run the job
        # (retention is a compliance obligation) — only skip when we positively
        # observe another replica holding the lock.
        try:
            lock_redis = Redis.from_url(settings.redis_url)
            if not await lock_redis.set(lock_key, "1", nx=True, ex=600):
                return
            acquired = True
        except Exception:  # noqa: BLE001
            log.warning("Retention job lock unavailable; proceeding without it")

        engine = create_async_engine(settings.database_url, echo=False)
        cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
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
        if engine is not None:
            await engine.dispose()
        # Release the lock (only if we hold it) so the next run — or the next
        # test — can acquire cleanly; then drop the dedicated connection.
        if lock_redis is not None:
            if acquired:
                try:
                    await lock_redis.delete(lock_key)
                except Exception:  # noqa: BLE001, S110
                    pass
            await lock_redis.aclose()

    if deleted_count:
        log.info("Retention cleanup complete: %d report(s) deleted.", deleted_count)
    else:
        log.debug("Retention cleanup: no reports eligible for deletion.")
