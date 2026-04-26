"""Tests for app/services/demo_seed.py.

Calls _seed(db) directly with the pytest db_session so the function runs on
the correct event loop (avoids the AsyncSessionLocal loop-isolation problem).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.demo_seed import (
    DEMO_ADMIN_USERNAME,
    DEMO_REPORTS,
    DEMO_TOTP_SECRET,
    _seed,
)

# ─── admin user ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_creates_demo_admin(db_session: AsyncSession) -> None:
    from app.models.user import AdminUser

    await _seed(db_session)

    result = await db_session.execute(
        select(AdminUser).where(AdminUser.username == DEMO_ADMIN_USERNAME)
    )
    admin = result.scalar_one_or_none()
    assert admin is not None
    assert admin.totp_enabled is True
    assert admin.totp_secret == DEMO_TOTP_SECRET


@pytest.mark.asyncio
async def test_seed_admin_idempotent(db_session: AsyncSession) -> None:
    """Calling _seed twice must not duplicate the admin user."""
    from app.models.user import AdminUser

    await _seed(db_session)
    await _seed(db_session)

    result = await db_session.execute(
        select(func.count()).select_from(AdminUser).where(
            AdminUser.username == DEMO_ADMIN_USERNAME
        )
    )
    assert result.scalar_one() == 1


# ─── setup status ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_marks_setup_complete(db_session: AsyncSession) -> None:
    from app.models.setup import SetupStatus

    await _seed(db_session)

    result = await db_session.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    assert setup is not None
    assert setup.completed is True
    assert setup.completed_at is not None


@pytest.mark.asyncio
async def test_seed_marks_existing_incomplete_setup_complete(
    db_session: AsyncSession,
) -> None:
    """If SetupStatus row exists but completed=False, _seed must flip it to True."""
    from datetime import UTC, datetime

    from app.models.setup import SetupStatus

    # The row with id=1 may already exist (DEMO_MODE lifespan commits it before tests run).
    # In that case update the existing row to completed=False instead of inserting.
    result = await db_session.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    if setup is None:
        setup = SetupStatus(id=1, completed=False, completed_at=None)
        db_session.add(setup)
    else:
        setup.completed = False
        setup.completed_at = None
    await db_session.commit()

    await _seed(db_session)

    await db_session.refresh(setup)
    assert setup.completed is True
    assert setup.completed_at is not None
    assert setup.completed_at <= datetime.now(UTC)


# ─── demo reports ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_creates_all_demo_reports(db_session: AsyncSession) -> None:
    from app.models.report import Report

    await _seed(db_session)

    for demo in DEMO_REPORTS:
        result = await db_session.execute(
            select(Report).where(Report.case_number == demo["case_number"])
        )
        report = result.scalar_one_or_none()
        assert report is not None, f"Missing demo report: {demo['case_number']}"
        assert report.status == demo["status"]
        assert report.category == demo["category"]


@pytest.mark.asyncio
async def test_seed_reports_idempotent(db_session: AsyncSession) -> None:
    """Calling _seed twice must not duplicate any report."""
    from app.models.report import Report

    await _seed(db_session)
    await _seed(db_session)

    for demo in DEMO_REPORTS:
        result = await db_session.execute(
            select(func.count()).select_from(Report).where(
                Report.case_number == demo["case_number"]
            )
        )
        assert result.scalar_one() == 1, f"Duplicate report: {demo['case_number']}"


@pytest.mark.asyncio
async def test_seed_in_review_report_has_timestamps(db_session: AsyncSession) -> None:
    from app.models.report import Report

    await _seed(db_session)

    result = await db_session.execute(
        select(Report).where(Report.case_number == "OW-DEMO-00002")
    )
    report = result.scalar_one_or_none()
    assert report is not None
    assert report.acknowledged_at is not None
    assert report.feedback_due_at is not None
    delta = report.feedback_due_at - report.acknowledged_at
    assert abs(delta.total_seconds() - 90 * 86400) < 5


@pytest.mark.asyncio
async def test_seed_received_report_has_no_timestamps(db_session: AsyncSession) -> None:
    from app.models.report import Report

    await _seed(db_session)

    result = await db_session.execute(
        select(Report).where(Report.case_number == "OW-DEMO-00001")
    )
    report = result.scalar_one_or_none()
    assert report is not None
    assert report.acknowledged_at is None
    assert report.feedback_due_at is None


# ─── messages ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_received_report_has_one_message(db_session: AsyncSession) -> None:
    from app.models.report import Report

    await _seed(db_session)

    result = await db_session.execute(
        select(Report).where(Report.case_number == "OW-DEMO-00001")
    )
    report = result.scalar_one()
    await db_session.refresh(report, ["messages"])
    assert len(report.messages) == 1


@pytest.mark.asyncio
async def test_seed_in_review_report_has_two_messages(db_session: AsyncSession) -> None:
    from app.models.report import Report

    await _seed(db_session)

    result = await db_session.execute(
        select(Report).where(Report.case_number == "OW-DEMO-00002")
    )
    report = result.scalar_one()
    await db_session.refresh(report, ["messages"])
    assert len(report.messages) == 2


@pytest.mark.asyncio
async def test_seed_pending_feedback_report_has_four_messages(db_session: AsyncSession) -> None:
    """pending_feedback reports get receipt + ack + whistleblower reply + admin update."""
    from app.models.report import Report, ReportSender

    await _seed(db_session)

    result = await db_session.execute(
        select(Report).where(Report.case_number == "OW-DEMO-00003")
    )
    report = result.scalar_one()
    await db_session.refresh(report, ["messages"])
    assert len(report.messages) == 4
    senders = {m.sender for m in report.messages}
    assert ReportSender.whistleblower in senders
