"""SLA reminder service — sends follow-up notifications before HinSchG deadlines.

Runs as an APScheduler job every 30 minutes. Redis keys are used to prevent
duplicate reminders within each warning window.

Privacy: the reminder email to the org's own admins carries the case number;
the reminder webhook (Slack, Teams, generic — third parties) carries only the
aggregate count of cases due, sent once per run — never a case number or a
deadline date.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)


def _dedup_ttl_seconds(days_left: int) -> int:
    """TTL for a reminder dedup key.

    A fixed 1-hour TTL was far shorter than the multi-day warn window, so the
    key expired every couple of scheduler ticks and the same reminder re-fired
    for days. Instead suppress re-reminders until the deadline itself has passed
    (plus a one-day buffer), giving one reminder per warn-window entry.
    """
    return max(days_left, 0) * 86400 + 86400


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
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.report import Report, ReportStatus
    from app.redis_client import get_redis

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            redis = await get_redis()
            # Distributed lock: the app runs stateless/scaled, so every replica
            # starts its own scheduler. Only one may run each cycle, else audit
            # entries and outbound notifications are duplicated per replica.
            # Acquire → run → release; the TTL is only a crash safety-net.
            lock_key = "openwhistle:job_lock:sla_reminders"
            if not await redis.set(lock_key, "1", nx=True, ex=300):
                return
            try:
                now = datetime.now(UTC)

                result = await db.execute(
                    select(Report).where(
                        Report.status.notin_([ReportStatus.closed])
                    )
                )
                reports = result.scalars().all()

                ack_due = feedback_due = 0
                for report in reports:
                    # Isolate per-report failures: one bad row must not abort SLA
                    # checks for every other pending report in this run.
                    try:
                        ack_due += await _check_ack_reminder(report, now, db, redis, settings)
                        feedback_due += await _check_feedback_reminder(
                            report, now, db, redis, settings
                        )
                    except Exception:  # noqa: BLE001
                        log.exception("SLA reminder check failed for a report; continuing")
                if (ack_due or feedback_due) and settings.notify_webhook_enabled \
                        and settings.notify_webhook_url.strip():
                    from app.services import notifications  # noqa: PLC0415

                    await notifications._send_reminder_webhook(ack_due, feedback_due, settings)
            finally:
                try:
                    await redis.delete(lock_key)
                except Exception:  # noqa: BLE001, S110
                    pass
    finally:
        await engine.dispose()


async def _check_ack_reminder(
    report: object,
    now: datetime,
    db: object,
    redis: object,
    settings: object,
) -> bool:
    """Check and, if due, send the ack reminder for one report.

    Returns True when a reminder was dispatched (used by the caller to build
    the aggregate count for the once-per-run webhook), False otherwise.
    """
    from app.config import Settings
    from app.models.report import Report

    r: Report = report  # type: ignore[assignment]
    cfg: Settings = settings  # type: ignore[assignment]

    if r.acknowledged_at is not None:
        return False  # already acknowledged

    ack_deadline = r.submitted_at + timedelta(days=7)
    days_left = (ack_deadline - now).days
    if days_left > cfg.reminder_ack_warn_days:
        return False

    from redis.asyncio import Redis as RedisType
    red: RedisType = redis  # type: ignore[assignment]

    key = _ack_dedup_key(r.case_number)
    if await red.exists(key):
        return False

    await _dispatch_reminder(
        case_number=r.case_number,
        deadline_label="7-day acknowledgement",
        days_left=days_left,
        settings=cfg,
    )
    await red.set(key, "1", ex=_dedup_ttl_seconds(days_left))
    log.info("ACK reminder sent for %s (%d days left)", r.case_number, days_left)
    return True


async def _check_feedback_reminder(
    report: object,
    now: datetime,
    db: object,
    redis: object,
    settings: object,
) -> bool:
    """Check and, if due, send the feedback reminder for one report.

    Returns True when a reminder was dispatched, False otherwise (see
    ``_check_ack_reminder``).
    """
    from app.config import Settings
    from app.models.report import Report

    r: Report = report  # type: ignore[assignment]
    cfg: Settings = settings  # type: ignore[assignment]

    if r.feedback_due_at is None:
        return False

    days_left = (r.feedback_due_at - now).days
    if days_left > cfg.reminder_feedback_warn_days:
        return False

    from redis.asyncio import Redis as RedisType
    red: RedisType = redis  # type: ignore[assignment]

    key = _feedback_dedup_key(r.case_number)
    if await red.exists(key):
        return False

    await _dispatch_reminder(
        case_number=r.case_number,
        deadline_label="3-month feedback",
        days_left=days_left,
        settings=cfg,
    )
    await red.set(key, "1", ex=_dedup_ttl_seconds(days_left))
    log.info("Feedback reminder sent for %s (%d days left)", r.case_number, days_left)
    return True


async def _dispatch_reminder(
    case_number: str,
    deadline_label: str,
    days_left: int,
    settings: object,
) -> None:
    """Send the per-report reminder email to admins.

    The webhook is not sent here: it carries counts only, aggregated and sent
    once per ``send_sla_reminders`` run, never per report.
    """
    from app.config import Settings
    from app.services.notifications import _send_reminder_email

    cfg: Settings = settings  # type: ignore[assignment]

    if cfg.notify_email_enabled and cfg.notify_email_to.strip():
        await _send_reminder_email(case_number, deadline_label, days_left, cfg)
