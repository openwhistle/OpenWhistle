"""Demo data seeding — only runs when DEMO_MODE=true.

Seeds:
  - Admin account: demo / demo (with static TOTP)
  - Case manager account: case_manager / demo
  - 4 sample reports with known case numbers and PINs
  - Internal notes, case links, and status progression examples
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.report import (
    AdminNote,
    CaseLink,
    Report,
    ReportMessage,
    ReportSender,
    ReportStatus,
)
from app.models.setup import SetupStatus
from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password, hash_pin

# Stable demo credentials — published intentionally for the demo instance
DEMO_ADMIN_USERNAME = "demo"
DEMO_ADMIN_PASSWORD = "demo"  # noqa: S105
DEMO_TOTP_SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105  # encodes to static codes for demo

DEMO_CM_USERNAME = "case_manager"
DEMO_CM_PASSWORD = "demo"  # noqa: S105

# Known demo report access credentials (published in docs/demo)
DEMO_REPORTS: list[dict[str, Any]] = [
    {
        "case_number": "OW-DEMO-00001",
        "pin": "demo-pin-received-00001",
        "category": "financial_fraud",
        "description": (
            "I have noticed irregularities in the quarterly expense reports. "
            "Several managers appear to be submitting duplicate reimbursement claims "
            "for the same business trips."
        ),
        "status": ReportStatus.received,
    },
    {
        "case_number": "OW-DEMO-00002",
        "pin": "demo-pin-inreview-00002",
        "category": "workplace_safety",
        "description": (
            "The fire exits on the third floor of the main building have been blocked "
            "by storage equipment for over two months. Multiple complaints to facility "
            "management have been ignored."
        ),
        "status": ReportStatus.in_review,
        "acknowledged_offset_days": -5,
    },
    {
        "case_number": "OW-DEMO-00003",
        "pin": "demo-pin-pending-00003",
        "category": "corruption",
        "description": (
            "A senior procurement officer appears to be awarding contracts exclusively "
            "to a company owned by a family member, bypassing the standard bidding process."
        ),
        "status": ReportStatus.pending_feedback,
        "acknowledged_offset_days": -14,
    },
    {
        "case_number": "OW-DEMO-00004",
        "pin": "demo-pin-closed-00004",
        "category": "data_protection",
        "description": (
            "Customer data including email addresses and purchase histories is being exported "
            "to an external marketing service without explicit consent. This was discovered "
            "while reviewing server access logs last week."
        ),
        "status": ReportStatus.closed,
        "acknowledged_offset_days": -60,
        "closed": True,
    },
]


async def _seed(db: AsyncSession) -> None:
    """Core seeding logic — runs against the given session."""
    # Create admin user if not exists
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == DEMO_ADMIN_USERNAME)
    )
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = AdminUser(
            id=uuid.uuid4(),
            username=DEMO_ADMIN_USERNAME,
            password_hash=hash_password(DEMO_ADMIN_PASSWORD),
            totp_secret=DEMO_TOTP_SECRET,
            totp_enabled=True,
            role=AdminRole.admin,
            is_active=True,
        )
        db.add(admin)
        await db.flush()

    # Create case manager user if not exists
    result_cm = await db.execute(
        select(AdminUser).where(AdminUser.username == DEMO_CM_USERNAME)
    )
    case_mgr = result_cm.scalar_one_or_none()
    if case_mgr is None:
        case_mgr = AdminUser(
            id=uuid.uuid4(),
            username=DEMO_CM_USERNAME,
            password_hash=hash_password(DEMO_CM_PASSWORD),
            totp_secret=DEMO_TOTP_SECRET,
            totp_enabled=True,
            role=AdminRole.case_manager,
            is_active=True,
        )
        db.add(case_mgr)
        await db.flush()

    # Mark setup as complete for demo
    result_setup = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result_setup.scalar_one_or_none()
    if setup is None:
        setup = SetupStatus(id=1, completed=True, completed_at=datetime.now(UTC))
        db.add(setup)
    elif not setup.completed:
        setup.completed = True
        setup.completed_at = datetime.now(UTC)

    # Track newly seeded reports for linking
    seeded: list[Report] = []

    for demo in DEMO_REPORTS:
        result_rep = await db.execute(
            select(Report).where(Report.case_number == demo["case_number"])
        )
        if result_rep.scalar_one_or_none() is not None:
            continue

        now = datetime.now(UTC)
        acknowledged_at = None
        feedback_due_at = None
        closed_at = None
        if "acknowledged_offset_days" in demo:
            acknowledged_at = now + timedelta(days=demo["acknowledged_offset_days"])
            feedback_due_at = acknowledged_at + timedelta(days=90)
        if demo.get("closed"):
            closed_at = now - timedelta(days=3)

        report = Report(
            id=uuid.uuid4(),
            case_number=demo["case_number"],
            pin_hash=hash_pin(demo["pin"]),
            category=demo["category"],
            description=demo["description"],
            status=demo["status"],
            acknowledged_at=acknowledged_at,
            feedback_due_at=feedback_due_at,
            closed_at=closed_at,
        )
        db.add(report)
        await db.flush()
        seeded.append(report)

        # Initial receipt message
        db.add(
            ReportMessage(
                id=uuid.uuid4(),
                report_id=report.id,
                sender=ReportSender.admin,
                content=(
                    "Your report has been received. You will receive an acknowledgement "
                    "within 7 days as required by §17 HinSchG."
                ),
            )
        )

        if demo["status"] in (
            ReportStatus.in_review,
            ReportStatus.pending_feedback,
            ReportStatus.closed,
        ):
            db.add(
                ReportMessage(
                    id=uuid.uuid4(),
                    report_id=report.id,
                    sender=ReportSender.admin,
                    content=(
                        "We have acknowledged your report and have begun our internal review. "
                        "We will provide a full update within 3 months."
                    ),
                )
            )

        if demo["status"] in (ReportStatus.pending_feedback, ReportStatus.closed):
            db.add(
                ReportMessage(
                    id=uuid.uuid4(),
                    report_id=report.id,
                    sender=ReportSender.whistleblower,
                    content=(
                        "Thank you. I have additional documentation I can provide if needed."
                    ),
                )
            )
            db.add(
                ReportMessage(
                    id=uuid.uuid4(),
                    report_id=report.id,
                    sender=ReportSender.admin,
                    content=(
                        "Our investigation is progressing. We will reach out with further "
                        "questions if needed. An interim update will follow shortly."
                    ),
                )
            )

        if demo["status"] == ReportStatus.closed:
            db.add(
                ReportMessage(
                    id=uuid.uuid4(),
                    report_id=report.id,
                    sender=ReportSender.admin,
                    content=(
                        "This case has been fully investigated. The issues raised were confirmed "
                        "and appropriate corrective measures have been implemented. Thank you for "
                        "your report — your identity remains fully protected."
                    ),
                )
            )

        # Add internal notes for in_review and beyond
        if demo["status"] in (
            ReportStatus.in_review,
            ReportStatus.pending_feedback,
            ReportStatus.closed,
        ):
            db.add(
                AdminNote(
                    id=uuid.uuid4(),
                    report_id=report.id,
                    author_id=admin.id,
                    author_username=admin.username,
                    content=(
                        "Initial review completed. Case assigned to compliance team. "
                        "Supporting documents requested from HR."
                    ),
                )
            )

        # Add audit log entry
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                admin_id=admin.id,
                admin_username=admin.username,
                action="report.acknowledged" if acknowledged_at else "report.viewed",
                report_id=report.id,
                detail='{"source": "demo_seed"}',
            )
        )

    # Link OW-DEMO-00001 and OW-DEMO-00002 if both freshly seeded
    if len(seeded) >= 2:
        report_a, report_b = seeded[0], seeded[1]
        norm_a, norm_b = (
            (report_a.id, report_b.id)
            if str(report_a.id) < str(report_b.id)
            else (report_b.id, report_a.id)
        )
        result_link = await db.execute(
            select(CaseLink).where(
                CaseLink.report_id_a == norm_a,
                CaseLink.report_id_b == norm_b,
            )
        )
        if result_link.scalar_one_or_none() is None:
            db.add(
                CaseLink(
                    id=uuid.uuid4(),
                    report_id_a=norm_a,
                    report_id_b=norm_b,
                    linked_by_id=admin.id,
                    linked_by_username=admin.username,
                )
            )

    await db.commit()


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as db:
        await _seed(db)
