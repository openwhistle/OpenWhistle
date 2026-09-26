"""Tests for app/services/demo_seed.py.

Calls _seed(db) directly with the pytest db_session so the function runs on
the correct event loop (avoids the AsyncSessionLocal loop-isolation problem).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminUser
from app.services.demo_seed import (
    DEMO_ADMIN_USERNAME,
    DEMO_REPORTS,
    DEMO_TOTP_SECRET,
    _seed,
    seed_demo_data,
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
async def test_demo_accounts_belong_to_the_default_org(db_session: AsyncSession) -> None:
    """Like setup's first admin: with multi-tenancy on, an org-less admin sees
    none of the default org's demo reports and has no reporting link."""
    from app.config import settings
    from app.models.organisation import Organisation
    from app.services.demo_seed import DEMO_CM_USERNAME

    await _seed(db_session)
    default_id = (
        await db_session.execute(
            select(Organisation.id).where(Organisation.slug == settings.default_org_slug)
        )
    ).scalar_one()
    orgs = (
        await db_session.execute(
            select(AdminUser.org_id).where(
                AdminUser.username.in_([DEMO_ADMIN_USERNAME, DEMO_CM_USERNAME])
            )
        )
    ).scalars().all()
    assert list(orgs) == [default_id, default_id]


@pytest.mark.asyncio
async def test_seed_gives_existing_org_less_demo_accounts_the_default_org(
    db_session: AsyncSession,
) -> None:
    from sqlalchemy import update

    from app.services.demo_seed import DEMO_CM_USERNAME

    names = [DEMO_ADMIN_USERNAME, DEMO_CM_USERNAME]
    await _seed(db_session)
    await db_session.execute(
        update(AdminUser).where(AdminUser.username.in_(names)).values(org_id=None)
    )
    await db_session.commit()

    await _seed(db_session)
    orgs = (
        await db_session.execute(
            select(AdminUser.org_id)
            .where(AdminUser.username.in_(names))
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(orgs) == 2 and None not in orgs


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


# ─── seed_demo_data wrapper ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_demo_data_wrapper_calls_seed() -> None:
    """seed_demo_data() must call _seed via AsyncSessionLocal (covers lines 364-365)."""
    from unittest.mock import AsyncMock, patch

    with patch("app.services.demo_seed._seed", new_callable=AsyncMock) as mock_seed:
        await seed_demo_data()

    mock_seed.assert_called_once()


@pytest.mark.asyncio
async def test_seed_refuses_a_real_installation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEMO_MODE on a real database must not add demo/demo logins to it."""
    from app.services import demo_seed

    monkeypatch.setattr(demo_seed, "_is_foreign_database", AsyncMock(return_value=True))
    before = await db_session.scalar(
        select(func.count()).select_from(AdminUser).where(AdminUser.username == "case_manager")
    )
    await demo_seed._seed(db_session)
    after = await db_session.scalar(
        select(func.count()).select_from(AdminUser).where(AdminUser.username == "case_manager")
    )
    assert after == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup_done", "demo_admin_id", "foreign"),
    [
        (True, None, True),     # real installation, DEMO_MODE on by mistake
        (True, "id", False),    # seeded demo database
        (None, None, False),    # fresh database, setup not run yet
    ],
)
async def test_foreign_database_detection(
    setup_done: bool | None, demo_admin_id: str | None, foreign: bool
) -> None:
    from app.services.demo_seed import _is_foreign_database

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[setup_done, demo_admin_id])
    assert await _is_foreign_database(db) is foreign
