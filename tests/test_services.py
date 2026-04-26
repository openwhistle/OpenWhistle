"""Tests for service-layer functions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import ReportStatus
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_pin,
    verify_password,
    verify_pin,
)
from app.services.mfa import generate_totp_secret, get_totp, verify_totp
from app.services.pin import generate_pin
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


def test_password_hash_and_verify() -> None:
    password = "correct-horse-battery-staple-99"  # noqa: S105
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_pin_hash_and_verify() -> None:
    pin = generate_pin()
    assert len(pin) == 36  # UUID4 length
    hashed = hash_pin(pin)
    assert verify_pin(pin, hashed)
    assert not verify_pin("wrong-pin", hashed)


def test_generate_pin_is_unique() -> None:
    pins = {generate_pin() for _ in range(100)}
    assert len(pins) == 100


def test_totp_secret_generation() -> None:
    secret = generate_totp_secret()
    assert len(secret) == 32


def test_totp_verify_valid_code() -> None:
    secret = generate_totp_secret()
    totp = get_totp(secret)
    current_code = totp.now()
    assert verify_totp(secret, current_code)


def test_totp_verify_invalid_code() -> None:
    secret = generate_totp_secret()
    assert not verify_totp(secret, "000000")


def test_create_access_token_and_decode() -> None:
    token = create_access_token("test-user-id-123")
    assert isinstance(token, str)
    user_id = decode_access_token(token)
    assert user_id == "test-user-id-123"


def test_decode_invalid_access_token() -> None:
    result = decode_access_token("not-a-valid-jwt-token")
    assert result is None


def test_decode_malformed_token() -> None:
    result = decode_access_token("")
    assert result is None


def test_schemas_instantiation() -> None:
    from app.schemas.auth import LoginRequest, SetupRequest, TOTPVerifyRequest
    from app.schemas.report import (
        AdminReplyRequest,
        AdminStatusUpdate,
        ReportAccessRequest,
        ReportCreate,
        ReportReplyRequest,
        ReportSubmitResult,
    )

    lr = LoginRequest(username="admin", password="secure-password-123")
    assert lr.username == "admin"

    rc = ReportCreate(category="financial_fraud", description="A valid description long enough!")
    assert rc.description == "A valid description long enough!"

    rsr = ReportSubmitResult(case_number="OW-2026-00001", pin="some-pin-value")
    assert rsr.case_number == "OW-2026-00001"

    rr = ReportReplyRequest(
        case_number="OW-2026-00001",
        pin="some-pin-for-test",
        session_token="a" * 32,
        content="Reply content here.",
    )
    assert rr.content == "Reply content here."

    asu = AdminStatusUpdate(status=ReportStatus.pending_feedback)
    assert asu.status == ReportStatus.pending_feedback

    arr = AdminReplyRequest(content="Admin reply here.")
    assert arr.content == "Admin reply here."

    rra = ReportAccessRequest(
        case_number="OW-2026-00001",
        pin="some-pin-value-ok",
        session_token="b" * 32,
    )
    assert rra.case_number == "OW-2026-00001"

    tvr = TOTPVerifyRequest(totp_code="123456", temp_token="c" * 32)
    assert tvr.totp_code == "123456"

    sr = SetupRequest(
        username="admin_user",
        password="SecurePassword123!",
        totp_code="123456",
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    assert sr.username == "admin_user"


async def test_create_report_service(db_session: AsyncSession) -> None:
    report, pin = await create_report(db_session, "financial_fraud", "Test fraud description here.")
    assert report.case_number.startswith("OW-")
    assert len(pin) == 36


async def test_get_report_correct_credentials(db_session: AsyncSession) -> None:
    report, pin = await create_report(db_session, "corruption", "Testing corruption report here.")
    found = await get_report_by_credentials(db_session, report.case_number, pin)
    assert found is not None
    assert found.id == report.id


async def test_get_report_wrong_pin(db_session: AsyncSession) -> None:
    report, _ = await create_report(
        db_session, "workplace_safety", "Safety issue description here!"
    )
    found = await get_report_by_credentials(db_session, report.case_number, "wrong-pin-completely")
    assert found is None


async def test_get_report_wrong_case_number(db_session: AsyncSession) -> None:
    found = await get_report_by_credentials(db_session, "OW-9999-99999", "any-pin-value")
    assert found is None


async def test_add_whistleblower_message(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "financial_fraud", "Description long enough here!")
    msg = await add_whistleblower_message(db_session, report, "Additional info from whistleblower.")
    assert msg.content == "Additional info from whistleblower."


async def test_add_admin_message(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "corruption", "Corruption description here pls!")
    msg = await add_admin_message(db_session, report, "Admin response to this report.")
    assert msg.content == "Admin response to this report."


async def test_acknowledge_report(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "financial_fraud", "Acknowledge test description!")
    result = await acknowledge_report(db_session, report)
    assert result.status == ReportStatus.in_review
    assert result.feedback_due_at is not None
    assert result.acknowledged_at is not None


async def test_update_report_status_pending_feedback(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "corruption", "Update status test description!")
    result = await update_report_status(db_session, report, ReportStatus.pending_feedback)
    assert result.status == ReportStatus.pending_feedback


async def test_update_report_status_closed(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "corruption", "Close status test description ok!")
    result = await update_report_status(db_session, report, ReportStatus.closed)
    assert result.status == ReportStatus.closed
    assert result.closed_at is not None


async def test_get_all_reports(db_session: AsyncSession) -> None:
    await create_report(db_session, "financial_fraud", "Get all reports test description!")
    reports = await get_all_reports(db_session)
    assert len(reports) >= 1


async def test_get_report_by_id_found(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "corruption", "Get by id test description here!")
    found = await get_report_by_id(db_session, report.id)
    assert found is not None
    assert found.id == report.id


async def test_delete_report(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "workplace_safety", "Delete report test here!")
    report_id = report.id
    await delete_report(db_session, report)
    found = await get_report_by_id(db_session, report_id)
    assert found is None


# ─── get_reports_paginated ────────────────────────────────────────────────────


async def test_paginated_returns_all_on_first_page(db_session: AsyncSession) -> None:
    for i in range(3):
        await create_report(db_session, "corruption", f"Pagination test report number {i} ok!")
    reports, total = await get_reports_paginated(db_session, page=1, per_page=100)
    assert total >= 3
    assert len(reports) == total


async def test_paginated_page_size_is_respected(db_session: AsyncSession) -> None:
    for i in range(5):
        await create_report(db_session, "financial_fraud", f"Page size test report {i} long ok!")
    reports, total = await get_reports_paginated(db_session, page=1, per_page=2)
    assert len(reports) == 2
    assert total >= 5


async def test_paginated_second_page(db_session: AsyncSession) -> None:
    for i in range(4):
        await create_report(db_session, "other", f"Second page test report number {i} here!")
    _, total = await get_reports_paginated(db_session, page=1, per_page=2)
    page2, total2 = await get_reports_paginated(db_session, page=2, per_page=2)
    assert total2 == total
    assert len(page2) <= 2


async def test_paginated_status_filter(db_session: AsyncSession) -> None:
    r1, _ = await create_report(db_session, "corruption", "Status filter test report one here!")
    await update_report_status(db_session, r1, ReportStatus.closed)
    await create_report(db_session, "corruption", "Status filter test report two is open!")

    closed_reports, total_closed = await get_reports_paginated(
        db_session, page=1, per_page=100, status_filter="closed"
    )
    assert total_closed >= 1
    assert all(r.status == ReportStatus.closed for r in closed_reports)


async def test_paginated_invalid_status_filter_returns_all(db_session: AsyncSession) -> None:
    await create_report(db_session, "other", "Invalid filter fallback test report here ok!")
    _, total_all = await get_reports_paginated(db_session, page=1, per_page=100)
    _, total_invalid = await get_reports_paginated(
        db_session, page=1, per_page=100, status_filter="not_a_real_status"
    )
    assert total_invalid == total_all


async def test_paginated_sort_asc(db_session: AsyncSession) -> None:
    reports, _ = await get_reports_paginated(
        db_session, page=1, per_page=100, sort_by="submitted_at", sort_dir="asc"
    )
    dates = [r.submitted_at for r in reports]
    assert dates == sorted(dates)


async def test_paginated_sort_desc(db_session: AsyncSession) -> None:
    reports, _ = await get_reports_paginated(
        db_session, page=1, per_page=100, sort_by="submitted_at", sort_dir="desc"
    )
    dates = [r.submitted_at for r in reports]
    assert dates == sorted(dates, reverse=True)


async def test_paginated_clamps_per_page(db_session: AsyncSession) -> None:
    reports, _ = await get_reports_paginated(db_session, page=1, per_page=999)
    assert len(reports) <= 100


async def test_paginated_page_beyond_end_returns_empty(db_session: AsyncSession) -> None:
    _, total = await get_reports_paginated(db_session, page=1, per_page=100)
    huge_page = total + 100
    reports, count = await get_reports_paginated(db_session, page=huge_page, per_page=25)
    assert reports == []
    assert count == total


# ─── get_report_stats ─────────────────────────────────────────────────────────


async def test_get_report_stats_returns_all_statuses(db_session: AsyncSession) -> None:
    stats = await get_report_stats(db_session)
    for key in ("received", "in_review", "pending_feedback", "closed"):
        assert key in stats
        assert isinstance(stats[key], int)


async def test_get_report_stats_counts_correctly(db_session: AsyncSession) -> None:
    r1, _ = await create_report(db_session, "other", "Stats count test report one long ok!")
    await update_report_status(db_session, r1, ReportStatus.closed)
    stats = await get_report_stats(db_session)
    assert stats["closed"] >= 1
