"""Redis-based rate limiting with no IP tracking.

For whistleblower access: each browser session gets an anonymous challenge token.
Rate limits are tracked against that token — no IP is ever read or stored.

For admin login: rate limits are tracked per username.
"""

from redis.asyncio import Redis

from app.config import settings

_WB_PREFIX = "openwhistle:wb_ratelimit:"
_ADMIN_PREFIX = "openwhistle:admin_ratelimit:"


async def check_whistleblower_attempts(redis: Redis, session_token: str) -> bool:
    """Returns True if the session token is allowed to attempt access."""
    key = f"{_WB_PREFIX}{session_token}"
    count = await redis.get(key)
    if count is None:
        return True
    return int(count) < settings.max_access_attempts


async def record_whistleblower_failure(redis: Redis, session_token: str) -> int:
    """Record a failed access attempt. Returns total failure count."""
    key = f"{_WB_PREFIX}{session_token}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.access_lockout_minutes * 60)
    return int(count)


async def reset_whistleblower_attempts(redis: Redis, session_token: str) -> None:
    """Clear the failure counter after a successful access."""
    key = f"{_WB_PREFIX}{session_token}"
    await redis.delete(key)


async def get_whistleblower_lockout_ttl(redis: Redis, session_token: str) -> int:
    """Returns seconds remaining in the lockout window, or 0 if not locked."""
    key = f"{_WB_PREFIX}{session_token}"
    ttl = await redis.ttl(key)
    return max(0, int(ttl))


async def remaining_whistleblower_attempts(redis: Redis, session_token: str) -> int:
    """Returns how many attempts remain before lockout."""
    key = f"{_WB_PREFIX}{session_token}"
    count = await redis.get(key)
    used = int(count) if count else 0
    return max(0, settings.max_access_attempts - used)


async def check_admin_login_attempts(redis: Redis, username: str) -> bool:
    """Returns True if the username is allowed to attempt login."""
    key = f"{_ADMIN_PREFIX}{username}"
    count = await redis.get(key)
    if count is None:
        return True
    return int(count) < settings.max_login_attempts


async def record_admin_login_failure(redis: Redis, username: str) -> int:
    """Record a failed admin login attempt."""
    key = f"{_ADMIN_PREFIX}{username}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.login_lockout_minutes * 60)
    return int(count)


async def reset_admin_login_attempts(redis: Redis, username: str) -> None:
    """Clear admin login failures after successful authentication."""
    key = f"{_ADMIN_PREFIX}{username}"
    await redis.delete(key)
