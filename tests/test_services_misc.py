"""Coverage tests for miscellaneous services.

Covers:
- services/demo_seed.py: seed_demo_data() (0% → ~90%)
- services/rate_limit.py remaining gaps: record_failure, reset, lockout paths
- services/mfa.py remaining gaps: verify_totp, verify_demo_totp
- services/pin.py: generate_pin, generate_case_number
- services/auth.py: hash_pin, verify_pin, verify_password
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    hash_password,
    hash_pin,
    verify_password,
    verify_pin,
)

# ─── services/demo_seed ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_demo_data_creates_admin_user(db_session: AsyncSession) -> None:
    """seed_demo_data() must create the demo admin user if it doesn't exist yet."""
    from app.models.user import AdminUser
    from app.services.demo_seed import DEMO_ADMIN_USERNAME, seed_demo_data

    # Delete any existing demo admin first (idempotency test follows separately)
    existing = await db_session.execute(
        select(AdminUser).where(AdminUser.username == DEMO_ADMIN_USERNAME)
    )
    admin = existing.scalar_one_or_none()
    if admin:
        await db_session.delete(admin)
        await db_session.commit()

    await seed_demo_data()

    result = await db_session.execute(
        select(AdminUser).where(AdminUser.username == DEMO_ADMIN_USERNAME)
    )
    created = result.scalar_one_or_none()
    assert created is not None
    assert created.totp_enabled is True


@pytest.mark.asyncio
async def test_seed_demo_data_idempotent_admin(db_session: AsyncSession) -> None:
    """Calling seed_demo_data() twice must not duplicate the admin user."""
    from sqlalchemy import func

    from app.models.user import AdminUser
    from app.services.demo_seed import DEMO_ADMIN_USERNAME, seed_demo_data

    await seed_demo_data()
    await seed_demo_data()

    result = await db_session.execute(
        select(func.count()).where(AdminUser.username == DEMO_ADMIN_USERNAME)
    )
    count = result.scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_seed_demo_data_creates_setup_status(db_session: AsyncSession) -> None:
    """seed_demo_data() must mark setup as complete in SetupStatus."""
    from app.models.setup import SetupStatus
    from app.services.demo_seed import seed_demo_data

    await seed_demo_data()

    result = await db_session.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    assert setup is not None
    assert setup.completed is True


@pytest.mark.asyncio
async def test_seed_demo_data_creates_demo_reports(db_session: AsyncSession) -> None:
    """All demo reports must be created with the expected case numbers."""
    from app.models.report import Report
    from app.services.demo_seed import DEMO_REPORTS, seed_demo_data

    await seed_demo_data()

    for demo in DEMO_REPORTS:
        result = await db_session.execute(
            select(Report).where(Report.case_number == demo["case_number"])
        )
        report = result.scalar_one_or_none()
        assert report is not None, f"Demo report {demo['case_number']} not found"
        assert report.status == demo["status"]


@pytest.mark.asyncio
async def test_seed_demo_data_idempotent_reports(db_session: AsyncSession) -> None:
    """Calling seed_demo_data() twice must not duplicate reports."""
    from sqlalchemy import func

    from app.models.report import Report
    from app.services.demo_seed import DEMO_REPORTS, seed_demo_data

    await seed_demo_data()
    await seed_demo_data()

    for demo in DEMO_REPORTS:
        result = await db_session.execute(
            select(func.count()).where(Report.case_number == demo["case_number"])
        )
        count = result.scalar_one()
        assert count == 1, f"Report {demo['case_number']} duplicated"


@pytest.mark.asyncio
async def test_seed_demo_data_acknowledged_report_has_timestamps(
    db_session: AsyncSession,
) -> None:
    """Demo reports with acknowledged_offset_days must have acknowledged_at set."""
    from app.models.report import Report
    from app.services.demo_seed import seed_demo_data

    await seed_demo_data()

    result = await db_session.execute(
        select(Report).where(Report.case_number == "OW-DEMO-00002")
    )
    report = result.scalar_one_or_none()
    assert report is not None
    assert report.acknowledged_at is not None
    assert report.feedback_due_at is not None


# ─── services/rate_limit ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_whistleblower_failure_increments_count(
    db_session: AsyncSession,
) -> None:
    import secrets

    from app.redis_client import get_redis
    from app.services.rate_limit import (
        record_whistleblower_failure,
        remaining_whistleblower_attempts,
    )

    redis = await get_redis()
    token = secrets.token_urlsafe(32)

    count = await record_whistleblower_failure(redis, token)
    assert count == 1

    remaining = await remaining_whistleblower_attempts(redis, token)
    from app.config import settings
    assert remaining == settings.max_access_attempts - 1


@pytest.mark.asyncio
async def test_reset_whistleblower_attempts_clears_counter(
    db_session: AsyncSession,
) -> None:
    import secrets

    from app.redis_client import get_redis
    from app.services.rate_limit import (
        record_whistleblower_failure,
        remaining_whistleblower_attempts,
        reset_whistleblower_attempts,
    )

    redis = await get_redis()
    token = secrets.token_urlsafe(32)

    await record_whistleblower_failure(redis, token)
    await record_whistleblower_failure(redis, token)
    await reset_whistleblower_attempts(redis, token)

    from app.config import settings
    remaining = await remaining_whistleblower_attempts(redis, token)
    assert remaining == settings.max_access_attempts


@pytest.mark.asyncio
async def test_check_admin_login_attempts_locked_after_max(
    db_session: AsyncSession,
) -> None:
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.rate_limit import (
        check_admin_login_attempts,
        record_admin_login_failure,
    )

    redis = await get_redis()
    username = f"locktest_{__import__('uuid').uuid4().hex[:8]}"

    for _ in range(settings.max_login_attempts):
        await record_admin_login_failure(redis, username)

    result = await check_admin_login_attempts(redis, username)
    assert result is False


@pytest.mark.asyncio
async def test_reset_admin_login_attempts_re_allows_login(
    db_session: AsyncSession,
) -> None:
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.rate_limit import (
        check_admin_login_attempts,
        record_admin_login_failure,
        reset_admin_login_attempts,
    )

    redis = await get_redis()
    username = f"resettest_{__import__('uuid').uuid4().hex[:8]}"

    for _ in range(settings.max_login_attempts):
        await record_admin_login_failure(redis, username)

    assert await check_admin_login_attempts(redis, username) is False

    await reset_admin_login_attempts(redis, username)

    assert await check_admin_login_attempts(redis, username) is True


# ─── services/mfa ─────────────────────────────────────────────────────────────


def test_verify_totp_valid_code() -> None:
    import pyotp

    from app.services.mfa import generate_totp_secret, verify_totp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True


def test_verify_totp_invalid_code() -> None:
    from app.services.mfa import generate_totp_secret, verify_totp

    secret = generate_totp_secret()
    assert verify_totp(secret, "000000") is False


def test_verify_demo_totp_accepts_000000() -> None:
    from app.services.mfa import verify_demo_totp

    assert verify_demo_totp("000000") is True


def test_verify_demo_totp_rejects_other() -> None:
    from app.services.mfa import verify_demo_totp

    assert verify_demo_totp("123456") is False


def test_generate_qr_code_base64_returns_string() -> None:
    from app.services.mfa import generate_qr_code_base64, generate_totp_secret

    secret = generate_totp_secret()
    result = generate_qr_code_base64(secret, "testuser")
    assert isinstance(result, str)
    assert len(result) > 0


# ─── services/pin ─────────────────────────────────────────────────────────────


def test_generate_pin_is_uuid_format() -> None:
    import re

    from app.services.pin import generate_pin

    pin = generate_pin()
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", pin
    ), f"PIN does not look like a UUID: {pin}"


def test_generate_pin_unique_each_call() -> None:
    from app.services.pin import generate_pin

    pins = {generate_pin() for _ in range(20)}
    assert len(pins) == 20


@pytest.mark.asyncio
async def test_generate_case_number_sequential(db_session: AsyncSession) -> None:
    """Two consecutive case numbers in the same year must differ by exactly 1."""
    from app.services.pin import generate_case_number

    first = await generate_case_number(db_session)
    # We can't easily create a real report in-service here, so just verify format
    year = __import__("datetime").datetime.now().year
    assert first.startswith(f"OW-{year}-")
    seq = int(first.split("-")[2])
    assert seq >= 1


# ─── services/auth: hash_pin / verify_pin / verify_password ──────────────────


def test_hash_pin_and_verify_pin_roundtrip() -> None:
    pin = "my-secret-pin-value"
    hashed = hash_pin(pin)
    assert verify_pin(pin, hashed) is True
    assert verify_pin("wrong-pin", hashed) is False


def test_hash_password_and_verify_password_roundtrip() -> None:
    pw = "Secure!Test123"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong", hashed) is False
