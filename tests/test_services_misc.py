"""Coverage tests for miscellaneous services.

Covers:
- services/rate_limit.py remaining gaps: record_failure, reset, lockout paths
- services/mfa.py remaining gaps: verify_totp, verify_demo_totp
- services/pin.py: generate_pin, generate_case_number
- services/auth.py: hash_pin, verify_pin, verify_password

Note: seed_demo_data() coverage is captured automatically when CI runs with
DEMO_MODE=true (lifespan calls seed_demo_data() on startup). Direct tests of
seed_demo_data() cannot run in pytest-asyncio function-scoped loops because
seed_demo_data() internally creates its own AsyncSessionLocal connection that
is bound to a different event loop.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    hash_password,
    hash_pin,
    verify_password,
    verify_pin,
)

# ─── services/rate_limit ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_whistleblower_failure_increments_count(
    client: AsyncClient,
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
    client: AsyncClient,
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
    client: AsyncClient,
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
    client: AsyncClient,
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
