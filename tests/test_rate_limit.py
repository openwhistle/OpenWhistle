"""Tests for rate limiting logic."""

from unittest.mock import AsyncMock

import pytest

from app.services.rate_limit import (
    check_admin_login_attempts,
    record_admin_login_failure,
    record_whistleblower_failure,
    reset_whistleblower_attempts,
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
async def test_whistleblower_failures_are_counted() -> None:
    redis = make_redis_mock({})
    assert await record_whistleblower_failure(redis, "OW-2026-00001") == 1
    assert await record_whistleblower_failure(redis, "OW-2026-00001") == 2


@pytest.mark.asyncio
async def test_whistleblower_counter_reset_after_success() -> None:
    redis = make_redis_mock({})
    await record_whistleblower_failure(redis, "OW-2026-00002")
    await record_whistleblower_failure(redis, "OW-2026-00002")
    await reset_whistleblower_attempts(redis, "OW-2026-00002")
    assert await record_whistleblower_failure(redis, "OW-2026-00002") == 1


@pytest.mark.asyncio
async def test_admin_login_rate_limit() -> None:
    stored: dict[str, str | None] = {}
    redis = make_redis_mock(stored)

    username = "admin"
    for _ in range(10):
        await record_admin_login_failure(redis, username)

    allowed = await check_admin_login_attempts(redis, username)
    assert allowed is False
