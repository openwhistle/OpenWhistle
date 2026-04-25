"""Business logic for whistleblower reports."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.i18n import _DEFAULT, _load
from app.models.attachment import Attachment  # noqa: F401 — ensures mapper is loaded for selectinload
from app.models.report import Report, ReportMessage, ReportSender, ReportStatus
from app.services.auth import hash_pin, verify_pin
from app.services.pin import generate_case_number, generate_pin


async def create_report(
    db: AsyncSession,
    category: str,
    description: str,
    lang: str = "en",
) -> tuple[Report, str]:
    """Create a new whistleblower report. Returns (report, plain_pin)."""
    case_number = await generate_case_number(db)
    plain_pin = generate_pin()
    pin_hash = hash_pin(plain_pin)

    report = Report(
        id=uuid.uuid4(),
        case_number=case_number,
        pin_hash=pin_hash,
        category=category,
        description=description,
        status=ReportStatus.received,
    )
    db.add(report)

    # System message: automatic receipt confirmation (localized)
    strings = _load(lang)
    fallback = _load(_DEFAULT)
    receipt_text = strings.get("system.receipt_message") or fallback.get("system.receipt_message")

    receipt_msg = ReportMessage(
        id=uuid.uuid4(),
        report_id=report.id,
        sender=ReportSender.admin,
        content=receipt_text,
    )
    db.add(receipt_msg)
    await db.commit()
    await db.refresh(report)
    return report, plain_pin


async def get_report_by_credentials(
    db: AsyncSession, case_number: str, plain_pin: str
) -> Report | None:
    """Retrieve a report after verifying both case_number and PIN."""
    result = await db.execute(
        select(Report)
        .options(selectinload(Report.messages), selectinload(Report.attachments))
        .where(Report.case_number == case_number)
    )
    report = result.scalar_one_or_none()
    if report is None:
        return None
    if not verify_pin(plain_pin, report.pin_hash):
        return None
    return report


async def add_whistleblower_message(
    db: AsyncSession, report: Report, content: str
) -> ReportMessage:
    msg = ReportMessage(
        id=uuid.uuid4(),
        report_id=report.id,
        sender=ReportSender.whistleblower,
        content=content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def add_admin_message(
    db: AsyncSession, report: Report, content: str
) -> ReportMessage:
    msg = ReportMessage(
        id=uuid.uuid4(),
        report_id=report.id,
        sender=ReportSender.admin,
        content=content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def acknowledge_report(db: AsyncSession, report: Report) -> Report:
    """Mark report as acknowledged. Sets the 3-month feedback deadline."""
    now = datetime.now(UTC)
    report.acknowledged_at = now
    report.feedback_due_at = now + timedelta(days=90)
    if report.status == ReportStatus.received:
        report.status = ReportStatus.acknowledged
    await db.commit()
    await db.refresh(report)
    return report


async def update_report_status(
    db: AsyncSession, report: Report, new_status: ReportStatus
) -> Report:
    report.status = new_status
    if new_status == ReportStatus.closed and report.closed_at is None:
        report.closed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(report)
    return report


async def get_all_reports(db: AsyncSession) -> list[Report]:
    result = await db.execute(
        select(Report)
        .options(selectinload(Report.messages), selectinload(Report.attachments))
        .order_by(Report.submitted_at.desc())
    )
    return list(result.scalars().all())


async def get_report_by_id(db: AsyncSession, report_id: uuid.UUID) -> Report | None:
    result = await db.execute(
        select(Report)
        .options(selectinload(Report.messages), selectinload(Report.attachments))
        .where(Report.id == report_id)
    )
    return result.scalar_one_or_none()


async def delete_report(db: AsyncSession, report: Report) -> None:
    """Hard delete a report and all its messages (DSGVO Art. 17 compliance)."""
    await db.delete(report)
    await db.commit()
