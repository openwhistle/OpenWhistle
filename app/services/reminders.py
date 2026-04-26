"""SLA reminder service — sends follow-up notifications before HinSchG deadlines.

Runs as an APScheduler job every 30 minutes. Redis keys are used to prevent
duplicate reminders within each warning window.

Privacy: notifications to admins contain only the case number — never report content.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)

# Redis key TTL for dedup locks: slightly longer than the schedule interval
_DEDUP_TTL_SECONDS = 3600  # 1 hour — prevents double-fire even on restarts


def _ack_dedup_key(case_number: str) -> str:
    return f"reminder:ack:{case_number}"


def _feedback_dedup_key(case_number: str) -> str:
    return f"reminder:feedback:{case_number}"


async def send_sla_reminders() -> None:
    """Check all open reports and send deadline reminders where due.

    Designed to be called from the APScheduler job. Opens its own DB session
    and Redis connection so it is fully independent of request-scoped resources.
    """
    from app.config import settings

    if not settings.reminder_enabled:
        return

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.models.report import Report, ReportStatus
    from app.redis_client import get_redis

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            redis = await get_redis()
            now = datetime.now(UTC)

            result = await db.execute(
                select(Report).where(
                    Report.status.notin_([ReportStatus.closed])
                )
            )
            reports = result.scalars().all()

            for report in reports:
                await _check_ack_reminder(report, now, db, redis, settings)
                await _check_feedback_reminder(report, now, db, redis, settings)
    finally:
        await engine.dispose()


async def _check_ack_reminder(
    report: object,
    now: datetime,
    db: object,
    redis: object,
    settings: object,
) -> None:
    from app.models.report import Report
    from app.config import Settings

    r: Report = report  # type: ignore[assignment]
    cfg: Settings = settings  # type: ignore[assignment]

    if r.acknowledged_at is not None:
        return  # already acknowledged

    ack_deadline = r.submitted_at + timedelta(days=7)
    days_left = (ack_deadline - now).days
    if days_left > cfg.reminder_ack_warn_days:
        return

    from redis.asyncio import Redis as RedisType
    red: RedisType = redis  # type: ignore[assignment]

    key = _ack_dedup_key(r.case_number)
    if await red.exists(key):
        return

    await _dispatch_reminder(
        case_number=r.case_number,
        deadline_label="7-day acknowledgement",
        days_left=days_left,
        report=r,
        settings=cfg,
    )
    await red.setex(key, _DEDUP_TTL_SECONDS, "1")
    log.info("ACK reminder sent for %s (%d days left)", r.case_number, days_left)


async def _check_feedback_reminder(
    report: object,
    now: datetime,
    db: object,
    redis: object,
    settings: object,
) -> None:
    from app.models.report import Report
    from app.config import Settings

    r: Report = report  # type: ignore[assignment]
    cfg: Settings = settings  # type: ignore[assignment]

    if r.feedback_due_at is None:
        return

    days_left = (r.feedback_due_at - now).days
    if days_left > cfg.reminder_feedback_warn_days:
        return

    from redis.asyncio import Redis as RedisType
    red: RedisType = redis  # type: ignore[assignment]

    key = _feedback_dedup_key(r.case_number)
    if await red.exists(key):
        return

    await _dispatch_reminder(
        case_number=r.case_number,
        deadline_label="3-month feedback",
        days_left=days_left,
        report=r,
        settings=cfg,
    )
    await red.setex(key, _DEDUP_TTL_SECONDS, "1")
    log.info("Feedback reminder sent for %s (%d days left)", r.case_number, days_left)


async def _dispatch_reminder(
    case_number: str,
    deadline_label: str,
    days_left: int,
    report: object,
    settings: object,
) -> None:
    """Send reminder via all enabled notification channels."""
    import asyncio

    from app.config import Settings
    from app.services.notifications import _send_reminder_email, _send_reminder_webhook

    cfg: Settings = settings  # type: ignore[assignment]

    tasks = []
    if cfg.notify_email_enabled and cfg.notify_email_to.strip():
        tasks.append(
            _send_reminder_email(case_number, deadline_label, days_left, cfg)
        )
    if cfg.notify_webhook_enabled and cfg.notify_webhook_url.strip():
        tasks.append(
            _send_reminder_webhook(case_number, deadline_label, days_left, cfg)
        )

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
