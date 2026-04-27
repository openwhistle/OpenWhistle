"""Business logic for whistleblower reports."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from app.i18n import _DEFAULT, _load
from app.models.attachment import (
    Attachment,  # noqa: F401 — ensures mapper is loaded for selectinload
)
from app.models.report import (
    STATUS_TRANSITIONS,
    AdminNote,
    CaseLink,
    DeletionRequest,
    Report,
    ReportMessage,
    ReportSender,
    ReportStatus,
    SubmissionMode,
)
from app.models.user import AdminUser
from app.services.auth import hash_pin, verify_pin
from app.services.pin import generate_case_number, generate_pin

SortField = Literal["submitted_at", "case_number", "category", "status"]
SortDir = Literal["asc", "desc"]

_VALID_SORT_FIELDS: dict[str, Any] = {
    "submitted_at": Report.submitted_at,
    "case_number": Report.case_number,
    "category": Report.category,
    "status": Report.status,
}

_VALID_STATUSES: frozenset[str] = frozenset(s.value for s in ReportStatus)


def _report_options() -> list[_AbstractLoad]:
    return [
        selectinload(Report.messages),
        selectinload(Report.attachments),
        selectinload(Report.notes),
        selectinload(Report.links_as_a),
        selectinload(Report.links_as_b),
        selectinload(Report.deletion_request),
    ]


async def create_report(
    db: AsyncSession,
    category: str,
    description: str,
    lang: str = "en",
    submission_mode: SubmissionMode = SubmissionMode.anonymous,
    location_id: uuid.UUID | None = None,
    confidential_name_enc: str | None = None,
    confidential_contact_enc: str | None = None,
    secure_email_enc: str | None = None,
) -> tuple[Report, str]:
    """Create a new whistleblower report. Returns (report, plain_pin)."""
    from app.config import settings
    from app.services.encryption import (
        encrypt_dek,
        encrypt_field,
        generate_dek,
        make_report_fernet,
    )

    case_number = await generate_case_number(db)
    plain_pin = generate_pin()
    pin_hash = hash_pin(plain_pin)

    # Envelope-encrypt the description with a fresh per-report DEK
    dek_raw = generate_dek()
    encrypted_dek = encrypt_dek(dek_raw, settings.secret_key)
    report_fernet = make_report_fernet(encrypted_dek, settings.secret_key)
    enc_description = encrypt_field(report_fernet, description)

    report = Report(
        id=uuid.uuid4(),
        case_number=case_number,
        pin_hash=pin_hash,
        category=category,
        description=enc_description,
        encrypted_dek=encrypted_dek,
        status=ReportStatus.received,
        submission_mode=submission_mode,
        location_id=location_id,
        confidential_name=confidential_name_enc,
        confidential_contact=confidential_contact_enc,
        secure_email=secure_email_enc,
    )
    db.add(report)

    strings = _load(lang)
    fallback = _load(_DEFAULT)
    receipt_text = strings.get("system.receipt_message") or fallback.get("system.receipt_message")

    enc_receipt = encrypt_field(report_fernet, receipt_text or "")
    receipt_msg = ReportMessage(
        id=uuid.uuid4(),
        report_id=report.id,
        sender=ReportSender.admin,
        content=enc_receipt,
    )
    db.add(receipt_msg)
    await db.commit()
    await db.refresh(report)
    return report, plain_pin


def decrypt_report_fields(report: Report) -> tuple[str, list[str]]:
    """Return (decrypted_description, [decrypted_message_contents]).

    Falls back to plaintext for rows that pre-date envelope encryption
    (encrypted_dek is None) — backward-compatible with pre-v1.0 data.
    """
    from app.config import settings
    from app.services.encryption import decrypt_field_safe, make_report_fernet

    if report.encrypted_dek:
        fernet = make_report_fernet(report.encrypted_dek, settings.secret_key)
        description = decrypt_field_safe(fernet, report.description) or report.description
        msg_contents = [
            decrypt_field_safe(fernet, m.content) or m.content
            for m in report.messages
        ]
    else:
        description = report.description
        msg_contents = [m.content for m in report.messages]

    return description, msg_contents


async def get_report_by_credentials(
    db: AsyncSession, case_number: str, plain_pin: str
) -> Report | None:
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


def _encrypt_message_content(report: Report, content: str) -> str:
    """Encrypt message content with the report's DEK if available."""
    if not report.encrypted_dek:
        return content
    from app.config import settings
    from app.services.encryption import encrypt_field, make_report_fernet

    fernet = make_report_fernet(report.encrypted_dek, settings.secret_key)
    return encrypt_field(fernet, content)


async def add_whistleblower_message(
    db: AsyncSession, report: Report, content: str
) -> ReportMessage:
    msg = ReportMessage(
        id=uuid.uuid4(),
        report_id=report.id,
        sender=ReportSender.whistleblower,
        content=_encrypt_message_content(report, content),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def add_admin_message(
    db: AsyncSession,
    report: Report,
    content: str,
    notify_whistleblower: bool = False,
) -> ReportMessage:
    msg = ReportMessage(
        id=uuid.uuid4(),
        report_id=report.id,
        sender=ReportSender.admin,
        content=_encrypt_message_content(report, content),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    if notify_whistleblower and report.secure_email:
        from app.config import settings
        from app.services.crypto import decrypt_or_none
        from app.services.notifications import notify_reply_to_whistleblower

        plain_email = decrypt_or_none(report.secure_email)
        if plain_email:
            import asyncio
            asyncio.create_task(
                notify_reply_to_whistleblower(plain_email, settings.app_public_url)
            )

    return msg


async def acknowledge_report(db: AsyncSession, report: Report) -> Report:
    now = datetime.now(UTC)
    report.acknowledged_at = now
    report.feedback_due_at = now + timedelta(days=90)
    if report.status == ReportStatus.received:
        report.status = ReportStatus.in_review
    await db.commit()
    await db.refresh(report)
    return report


def is_valid_transition(current: str, new: str) -> bool:
    return new in STATUS_TRANSITIONS.get(current, set())


async def update_report_status(
    db: AsyncSession, report: Report, new_status: ReportStatus
) -> Report:
    report.status = new_status
    if new_status == ReportStatus.closed and report.closed_at is None:
        report.closed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(report)
    return report


async def assign_report(
    db: AsyncSession, report: Report, admin: AdminUser | None
) -> Report:
    report.assigned_to_id = admin.id if admin else None
    await db.commit()
    await db.refresh(report)
    return report


async def add_note(
    db: AsyncSession, report: Report, author: AdminUser, content: str
) -> AdminNote:
    note = AdminNote(
        id=uuid.uuid4(),
        report_id=report.id,
        author_id=author.id,
        author_username=author.username,
        content=content,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def get_all_reports(db: AsyncSession) -> list[Report]:
    result = await db.execute(
        select(Report)
        .options(*_report_options())
        .order_by(Report.submitted_at.desc())
    )
    return list(result.scalars().all())


async def get_reports_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 25,
    status_filter: str | None = None,
    sort_by: SortField = "submitted_at",
    sort_dir: SortDir = "desc",
    assigned_to_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> tuple[list[Report], int]:
    page = max(1, page)
    per_page = max(1, min(100, per_page))

    safe_sort = sort_by if sort_by in _VALID_SORT_FIELDS else "submitted_at"
    col = _VALID_SORT_FIELDS[safe_sort]
    order_expr = col.asc() if sort_dir == "asc" else col.desc()

    base_q = select(Report)
    if status_filter and status_filter in _VALID_STATUSES:
        base_q = base_q.where(Report.status == ReportStatus(status_filter))
    if assigned_to_id is not None:
        base_q = base_q.where(Report.assigned_to_id == assigned_to_id)
    if location_id is not None:
        base_q = base_q.where(Report.location_id == location_id)

    count_result = await db.execute(select(func.count()).select_from(base_q.subquery()))
    total: int = count_result.scalar_one()

    rows_result = await db.execute(
        base_q
        .options(*_report_options())
        .order_by(order_expr)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(rows_result.scalars().all()), total


async def get_report_stats(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(Report.status, func.count(Report.id)).group_by(Report.status)
    )
    counts: dict[str, int] = {s.value: 0 for s in ReportStatus}
    for status_val, cnt in result.all():
        if isinstance(status_val, ReportStatus):
            counts[status_val.value] = cnt
        else:
            counts[str(status_val)] = cnt
    return counts


async def get_report_by_id(db: AsyncSession, report_id: uuid.UUID) -> Report | None:
    result = await db.execute(
        select(Report)
        .options(*_report_options())
        .where(Report.id == report_id)
    )
    return result.scalar_one_or_none()


async def get_report_by_case_number(db: AsyncSession, case_number: str) -> Report | None:
    result = await db.execute(
        select(Report).where(Report.case_number == case_number)
    )
    return result.scalar_one_or_none()


async def delete_report(db: AsyncSession, report: Report) -> None:
    await db.delete(report)
    await db.commit()


# ── 4-eyes deletion ────────────────────────────────────────────────

async def request_deletion(
    db: AsyncSession, report: Report, requester: AdminUser
) -> DeletionRequest:
    dr = DeletionRequest(
        id=uuid.uuid4(),
        report_id=report.id,
        requested_by_id=requester.id,
        requested_by_username=requester.username,
    )
    db.add(dr)
    await db.commit()
    await db.refresh(dr)
    return dr


async def cancel_deletion_request(
    db: AsyncSession, deletion_request: DeletionRequest
) -> None:
    await db.delete(deletion_request)
    await db.commit()


async def confirm_deletion(
    db: AsyncSession,
    report: Report,
    deletion_request: DeletionRequest,
    confirmer: AdminUser,
) -> None:
    """Confirm and immediately execute the deletion."""
    from datetime import UTC, datetime
    deletion_request.confirmed_by_id = confirmer.id
    deletion_request.confirmed_by_username = confirmer.username
    deletion_request.confirmed_at = datetime.now(UTC)
    await db.flush()
    await db.delete(report)
    await db.commit()


# ── Case linking ───────────────────────────────────────────────────

def _normalize_ids(
    id_a: uuid.UUID, id_b: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    return (id_a, id_b) if str(id_a) < str(id_b) else (id_b, id_a)


async def get_link(
    db: AsyncSession, link_id: uuid.UUID
) -> CaseLink | None:
    result = await db.execute(select(CaseLink).where(CaseLink.id == link_id))
    return result.scalar_one_or_none()


async def link_cases(
    db: AsyncSession,
    report_a: Report,
    report_b: Report,
    actor: AdminUser,
) -> CaseLink:
    norm_a, norm_b = _normalize_ids(report_a.id, report_b.id)
    link = CaseLink(
        id=uuid.uuid4(),
        report_id_a=norm_a,
        report_id_b=norm_b,
        linked_by_id=actor.id,
        linked_by_username=actor.username,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def unlink_cases(db: AsyncSession, link: CaseLink) -> None:
    await db.delete(link)
    await db.commit()


def get_linked_reports(report: Report) -> list[tuple[uuid.UUID, str]]:
    """Return list of (linked_report_id, link_id) for a report."""
    result: list[tuple[uuid.UUID, str]] = []
    for lnk in report.links_as_a:
        result.append((lnk.report_id_b, str(lnk.id)))
    for lnk in report.links_as_b:
        result.append((lnk.report_id_a, str(lnk.id)))
    return result


# ── Dashboard statistics ────────────────────────────────────────────

async def get_dashboard_stats(db: AsyncSession) -> dict[str, Any]:
    """Aggregate statistics for the dashboard stats view."""
    from sqlalchemy import case as sa_case

    status_counts = await get_report_stats(db)

    cat_result = await db.execute(
        select(Report.category, func.count(Report.id)).group_by(Report.category)
    )
    by_category = {row[0]: row[1] for row in cat_result.all()}

    # SLA compliance: % of reports acknowledged within 7 days
    ack_result = await db.execute(
        select(
            func.count(Report.id).label("total"),
            func.sum(
                sa_case(
                    (
                        Report.acknowledged_at.isnot(None) &
                        (
                            func.extract("epoch", Report.acknowledged_at - Report.submitted_at)
                            <= 7 * 86400
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("on_time"),
        )
    )
    ack_row = ack_result.one()
    total_reports = ack_row.total or 0
    on_time = int(ack_row.on_time or 0)
    sla_rate = round(on_time / total_reports * 100) if total_reports else 0

    return {
        "status_counts": status_counts,
        "by_category": by_category,
        "total_reports": total_reports,
        "sla_7day_rate": sla_rate,
    }
