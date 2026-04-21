"""Demo data seeding — only runs when DEMO_MODE=true.

Seeds:
  - Admin account: demo / demo (with static TOTP)
  - 3 sample reports with known case numbers and PINs

The known demo PINs are intentionally published here since this is
demo-mode only and the data has no real confidentiality.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.report import Report, ReportMessage, ReportSender, ReportStatus
from app.models.setup import SetupStatus
from app.models.user import AdminUser
from app.services.auth import hash_password, hash_pin

# Stable demo credentials — published intentionally for the demo instance
DEMO_ADMIN_USERNAME = "demo"
DEMO_ADMIN_PASSWORD = "demo"  # noqa: S105
DEMO_TOTP_SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105  # encodes to static codes for demo

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
        "pin": "demo-pin-acknowledged-00002",
        "category": "workplace_safety",
        "description": (
            "The fire exits on the third floor of the main building have been blocked "
            "by storage equipment for over two months. Multiple complaints to facility "
            "management have been ignored."
        ),
        "status": ReportStatus.acknowledged,
        "acknowledged_offset_days": -5,
    },
    {
        "case_number": "OW-DEMO-00003",
        "pin": "demo-pin-inprogress-00003",
        "category": "corruption",
        "description": (
            "A senior procurement officer appears to be awarding contracts exclusively "
            "to a company owned by a family member, bypassing the standard bidding process."
        ),
        "status": ReportStatus.in_progress,
        "acknowledged_offset_days": -14,
    },
]


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as db:
        # Create admin user if not exists
        result = await db.execute(
            select(AdminUser).where(AdminUser.username == DEMO_ADMIN_USERNAME)
        )
        if result.scalar_one_or_none() is None:
            admin = AdminUser(
                id=uuid.uuid4(),
                username=DEMO_ADMIN_USERNAME,
                password_hash=hash_password(DEMO_ADMIN_PASSWORD),
                totp_secret=DEMO_TOTP_SECRET,
                totp_enabled=True,
            )
            db.add(admin)

        # Mark setup as complete for demo
        result_setup = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
        setup = result_setup.scalar_one_or_none()
        if setup is None:
            setup = SetupStatus(id=1, completed=True, completed_at=datetime.now(UTC))
            db.add(setup)
        elif not setup.completed:
            setup.completed = True
            setup.completed_at = datetime.now(UTC)

        # Create demo reports
        for demo in DEMO_REPORTS:
            result_rep = await db.execute(
                select(Report).where(Report.case_number == demo["case_number"])
            )
            if result_rep.scalar_one_or_none() is not None:
                continue

            now = datetime.now(UTC)
            acknowledged_at = None
            feedback_due_at = None
            if "acknowledged_offset_days" in demo:
                acknowledged_at = now + timedelta(days=demo["acknowledged_offset_days"])
                feedback_due_at = acknowledged_at + timedelta(days=90)

            report = Report(
                id=uuid.uuid4(),
                case_number=demo["case_number"],
                pin_hash=hash_pin(demo["pin"]),
                category=demo["category"],
                description=demo["description"],
                status=demo["status"],
                acknowledged_at=acknowledged_at,
                feedback_due_at=feedback_due_at,
            )
            db.add(report)
            await db.flush()

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

            if demo["status"] in (ReportStatus.acknowledged, ReportStatus.in_progress):
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

            if demo["status"] == ReportStatus.in_progress:
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

        await db.commit()
