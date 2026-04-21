"""Tests for rate limiting logic."""

import pytest
from unittest.mock import AsyncMock

from app.services.rate_limit import (
    check_whistleblower_attempts,
    record_whistleblower_failure,
    remaining_whistleblower_attempts,
    reset_whistleblower_attempts,
    check_admin_login_attempts,
    record_admin_login_failure,
)


def make_redis_mock(stored: dict[str, str | None]) -> AsyncMock:
    """Create a Redis mock that uses a local dict as storage."""
    redis = AsyncMock()

    async def get(key: str) -> str | None:
        return stored.get(key)

    async def incr(key: str) -> int:
        current = int(stored.get(key) or 0)
        stored[key] = str(current + 1)
        return current + 1

    async def expire(key: str, seconds: int) -> None:
        pass

    async def delete(key: str) -> None:
        stored.pop(key, None)

    async def exists(key: str) -> int:
        return 1 if key in stored else 0

    redis.get = get
    redis.incr = incr
    redis.expire = expire
    redis.delete = delete
    redis.exists = exists
    return redis


@pytest.mark.asyncio
async def test_fresh_token_is_allowed() -> None:
    redis = make_redis_mock({})
    allowed = await check_whistleblower_attempts(redis, "fresh-token-abc")
    assert allowed is True


@pytest.mark.asyncio
async def test_token_blocked_after_max_attempts() -> None:
    stored: dict[str, str | None] = {}
    redis = make_redis_mock(stored)

    token = "test-token-xyz"
    for _ in range(5):
        await record_whistleblower_failure(redis, token)

    allowed = await check_whistleblower_attempts(redis, token)
    assert allowed is False


@pytest.mark.asyncio
async def test_token_reset_after_success() -> None:
    stored: dict[str, str | None] = {}
    redis = make_redis_mock(stored)

    token = "test-reset-token"
    await record_whistleblower_failure(redis, token)
    await record_whistleblower_failure(redis, token)
    await reset_whistleblower_attempts(redis, token)

    allowed = await check_whistleblower_attempts(redis, token)
    assert allowed is True


@pytest.mark.asyncio
async def test_remaining_attempts_decrements() -> None:
    stored: dict[str, str | None] = {}
    redis = make_redis_mock(stored)

    token = "token-remaining"
    await record_whistleblower_failure(redis, token)
    await record_whistleblower_failure(redis, token)

    remaining = await remaining_whistleblower_attempts(redis, token)
    assert remaining == 3  # 5 max - 2 used


@pytest.mark.asyncio
async def test_admin_login_rate_limit() -> None:
    stored: dict[str, str | None] = {}
    redis = make_redis_mock(stored)

    username = "admin"
    for _ in range(10):
        await record_admin_login_failure(redis, username)

    allowed = await check_admin_login_attempts(redis, username)
    assert allowed is False
