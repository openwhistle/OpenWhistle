"""Direct service-layer tests for app/services/report.py.

Covers all business-logic functions at the service boundary without going through
the HTTP stack, giving precise per-function coverage.

Missing coverage before these tests: 28% (lines 39-214).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report, ReportSender, ReportStatus
from app.services.report import (
    acknowledge_report,
    add_admin_message,
    add_whistleblower_message,
    create_report,
    delete_report,
    get_all_reports,
    get_report_by_credentials,
    get_report_by_id,
    get_report_stats,
    get_reports_paginated,
    update_report_status,
)

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _make_report(db: AsyncSession, **kwargs: str) -> tuple[Report, str]:
    """Create a report with default values, returning (report, plain_pin)."""
    return await create_report(
        db,
        category=kwargs.get("category", "financial_fraud"),
        description=kwargs.get("description", "A test report with enough detail."),
        lang=kwargs.get("lang", "en"),
    )


# ─── create_report ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_report_returns_report_and_pin(db_session: AsyncSession) -> None:
    report, pin = await _make_report(db_session)
    assert report.id is not None
    assert report.case_number.startswith("OW-")
    assert report.status == ReportStatus.received
    assert len(pin) > 10


@pytest.mark.asyncio
async def test_create_report_receipt_message_added(db_session: AsyncSession) -> None:
    report, _ = await _make_report(db_session)
    await db_session.refresh(report, ["messages"])
    assert len(report.messages) == 1
    assert report.messages[0].sender == ReportSender.admin


@pytest.mark.asyncio
async def test_create_report_german_lang_adds_receipt_message(db_session: AsyncSession) -> None:
    """lang='de' exercises the i18n path in create_report."""
    report, _ = await create_report(
        db_session,
        category="workplace_safety",
        description="Ein Testbericht mit ausreichend Detail.",
        lang="de",
    )
    await db_session.refresh(report, ["messages"])
    assert len(report.messages) >= 1


@pytest.mark.asyncio
async def test_create_report_unknown_lang_falls_back_to_default(
    db_session: AsyncSession,
) -> None:
    """An unknown lang code must fall back to the default language without crashing."""
    report, _ = await create_report(
        db_session,
        category="corruption",
        description="Fallback language test report.",
        lang="xx",
    )
    await db_session.refresh(report, ["messages"])
    assert len(report.messages) >= 1


# ─── get_report_by_credentials ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_report_by_credentials_correct_returns_report(
    db_session: AsyncSession,
) -> None:
    report, plain_pin = await _make_report(db_session)
    found = await get_report_by_credentials(db_session, report.case_number, plain_pin)
    assert found is not None
    assert found.id == report.id


@pytest.mark.asyncio
async def test_get_report_by_credentials_wrong_pin_returns_none(
    db_session: AsyncSession,
) -> None:
    report, _ = await _make_report(db_session)
    result = await get_report_by_credentials(db_session, report.case_number, "wrong-pin-xyz")
    assert result is None


@pytest.mark.asyncio
async def test_get_report_by_credentials_wrong_case_number_returns_none(
    db_session: AsyncSession,
) -> None:
    result = await get_report_by_credentials(db_session, "OW-9999-99999", "any-pin")
    assert result is None


# ─── add_whistleblower_message ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_whistleblower_message_persisted(db_session: AsyncSession) -> None:
    from app.config import settings as cfg
    from app.services.encryption import decrypt_field_safe, make_report_fernet

    report, _ = await _make_report(db_session)
    msg = await add_whistleblower_message(db_session, report, "Follow-up from whistleblower.")
    fernet = make_report_fernet(report.encrypted_dek, cfg.secret_key)
    assert msg.id is not None
    assert msg.sender == ReportSender.whistleblower
    assert decrypt_field_safe(fernet, msg.content) == "Follow-up from whistleblower."
    assert msg.report_id == report.id


# ─── add_admin_message ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_admin_message_persisted(db_session: AsyncSession) -> None:
    from app.config import settings as cfg
    from app.services.encryption import decrypt_field_safe, make_report_fernet

    report, _ = await _make_report(db_session)
    msg = await add_admin_message(db_session, report, "Admin reply content.")
    fernet = make_report_fernet(report.encrypted_dek, cfg.secret_key)
    assert msg.id is not None
    assert msg.sender == ReportSender.admin
    assert decrypt_field_safe(fernet, msg.content) == "Admin reply content."


# ─── acknowledge_report ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acknowledge_report_sets_timestamps(db_session: AsyncSession) -> None:
    report, _ = await _make_report(db_session)
    assert report.acknowledged_at is None
    assert report.feedback_due_at is None

    updated = await acknowledge_report(db_session, report)
    assert updated.acknowledged_at is not None
    assert updated.feedback_due_at is not None


@pytest.mark.asyncio
async def test_acknowledge_report_feedback_due_is_90_days_after_ack(
    db_session: AsyncSession,
) -> None:

    report, _ = await _make_report(db_session)
    updated = await acknowledge_report(db_session, report)
    delta = updated.feedback_due_at - updated.acknowledged_at  # type: ignore[operator]
    assert abs(delta.total_seconds() - 90 * 86400) < 5


@pytest.mark.asyncio
async def test_acknowledge_report_received_becomes_in_review(
    db_session: AsyncSession,
) -> None:
    report, _ = await _make_report(db_session)
    assert report.status == ReportStatus.received
    updated = await acknowledge_report(db_session, report)
    assert updated.status == ReportStatus.in_review


@pytest.mark.asyncio
async def test_acknowledge_report_non_received_status_unchanged(
    db_session: AsyncSession,
) -> None:
    """If status is already beyond 'received', acknowledge must not reset it."""
    report, _ = await _make_report(db_session)
    report.status = ReportStatus.pending_feedback
    await db_session.commit()

    updated = await acknowledge_report(db_session, report)
    assert updated.status == ReportStatus.pending_feedback


# ─── update_report_status ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_report_status_pending_feedback(db_session: AsyncSession) -> None:
    report, _ = await _make_report(db_session)
    updated = await update_report_status(db_session, report, ReportStatus.pending_feedback)
    assert updated.status == ReportStatus.pending_feedback
    assert updated.closed_at is None


@pytest.mark.asyncio
async def test_update_report_status_closed_sets_closed_at(db_session: AsyncSession) -> None:
    report, _ = await _make_report(db_session)
    updated = await update_report_status(db_session, report, ReportStatus.closed)
    assert updated.status == ReportStatus.closed
    assert updated.closed_at is not None


@pytest.mark.asyncio
async def test_update_report_status_closed_at_not_reset_on_second_close(
    db_session: AsyncSession,
) -> None:
    """closed_at is set only once — a second close call must not overwrite it."""
    report, _ = await _make_report(db_session)
    first = await update_report_status(db_session, report, ReportStatus.closed)
    first_closed_at = first.closed_at

    second = await update_report_status(db_session, report, ReportStatus.closed)
    assert second.closed_at == first_closed_at


# ─── get_all_reports ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_reports_returns_list(db_session: AsyncSession) -> None:
    await _make_report(db_session)
    reports = await get_all_reports(db_session)
    assert isinstance(reports, list)
    assert len(reports) >= 1


@pytest.mark.asyncio
async def test_get_all_reports_includes_messages_and_attachments(
    db_session: AsyncSession,
) -> None:
    """selectinload must be applied — accessing .messages must not trigger lazy load errors."""
    report, _ = await _make_report(db_session)
    all_reports = await get_all_reports(db_session)
    target = next(r for r in all_reports if r.id == report.id)
    # Should be accessible without an active session (selectinload already fetched them)
    assert isinstance(target.messages, list)
    assert isinstance(target.attachments, list)


# ─── get_reports_paginated ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_reports_paginated_returns_tuple(db_session: AsyncSession) -> None:
    reports, total = await get_reports_paginated(db_session)
    assert isinstance(reports, list)
    assert isinstance(total, int)
    assert total >= 0


@pytest.mark.asyncio
async def test_get_reports_paginated_with_received_status_filter(
    db_session: AsyncSession,
) -> None:
    await _make_report(db_session)
    reports, total = await get_reports_paginated(db_session, status_filter="received")
    assert all(r.status == ReportStatus.received for r in reports)
    assert total >= 1


@pytest.mark.asyncio
async def test_get_reports_paginated_invalid_status_filter_returns_all(
    db_session: AsyncSession,
) -> None:
    """An unknown status_filter value must be ignored (not crash)."""
    await _make_report(db_session)
    reports_all, total_all = await get_reports_paginated(db_session)
    reports_bad, total_bad = await get_reports_paginated(
        db_session, status_filter="not_a_real_status"
    )
    assert total_bad == total_all


@pytest.mark.asyncio
async def test_get_reports_paginated_sort_by_case_number_asc(
    db_session: AsyncSession,
) -> None:
    await _make_report(db_session)
    await _make_report(db_session)
    reports, _ = await get_reports_paginated(
        db_session, sort_by="case_number", sort_dir="asc"
    )
    case_numbers = [r.case_number for r in reports]
    assert case_numbers == sorted(case_numbers)


@pytest.mark.asyncio
async def test_get_reports_paginated_sort_by_category_desc(
    db_session: AsyncSession,
) -> None:
    reports, _ = await get_reports_paginated(
        db_session, sort_by="category", sort_dir="desc"
    )
    assert isinstance(reports, list)


@pytest.mark.asyncio
async def test_get_reports_paginated_per_page_1(db_session: AsyncSession) -> None:
    await _make_report(db_session)
    await _make_report(db_session)
    reports, total = await get_reports_paginated(db_session, per_page=1, page=1)
    assert len(reports) == 1
    assert total >= 2


@pytest.mark.asyncio
async def test_get_reports_paginated_page_beyond_end_returns_empty(
    db_session: AsyncSession,
) -> None:
    _, total = await get_reports_paginated(db_session, per_page=1000)
    reports, _ = await get_reports_paginated(
        db_session, page=total + 100, per_page=25
    )
    assert reports == []


@pytest.mark.asyncio
async def test_get_reports_paginated_invalid_sort_field_falls_back(
    db_session: AsyncSession,
) -> None:
    """An invalid sort_by value falls back to 'submitted_at'."""
    reports, _ = await get_reports_paginated(
        db_session,
        sort_by="invalid_field",  # type: ignore[arg-type]
        sort_dir="desc",
    )
    assert isinstance(reports, list)


# ─── get_report_stats ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_report_stats_contains_all_statuses(db_session: AsyncSession) -> None:
    stats = await get_report_stats(db_session)
    for s in ReportStatus:
        assert s.value in stats, f"Missing status key: {s.value}"


@pytest.mark.asyncio
async def test_get_report_stats_counts_received(db_session: AsyncSession) -> None:
    before_stats = await get_report_stats(db_session)
    before_count = before_stats.get("received", 0)

    await _make_report(db_session)
    after_stats = await get_report_stats(db_session)
    assert after_stats["received"] == before_count + 1


# ─── get_report_by_id ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_report_by_id_found(db_session: AsyncSession) -> None:
    report, _ = await _make_report(db_session)
    found = await get_report_by_id(db_session, report.id)
    assert found is not None
    assert found.id == report.id


@pytest.mark.asyncio
async def test_get_report_by_id_not_found_returns_none(db_session: AsyncSession) -> None:
    result = await get_report_by_id(db_session, uuid.uuid4())
    assert result is None


# ─── delete_report ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_report_removes_from_db(db_session: AsyncSession) -> None:
    report, _ = await _make_report(db_session)
    report_id = report.id

    await delete_report(db_session, report)

    gone = await get_report_by_id(db_session, report_id)
    assert gone is None
