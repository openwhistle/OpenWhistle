"""Redis-based rate limiting with no IP tracking.

For whistleblower access: failed attempts are counted per case number, for an
informational message only — a correct case number and PIN always succeed (see
``report.authenticate_whistleblower``). No IP is ever read or stored.

For admin login: rate limits are tracked per username.
"""

import hashlib
import hmac
import time

from redis.asyncio import Redis

from app.config import settings

_WB_PREFIX = "openwhistle:wb_ratelimit:"
_ADMIN_PREFIX = "openwhistle:admin_ratelimit:"
_SPRAY_PREFIX = "openwhistle:admin_failed_logins:"  # + minute number
_SPRAY_ALERTED = "openwhistle:admin_spray_alerted"
_SETUP_TOKEN_FAILURES = "openwhistle:setup_token_failures"  # noqa: S105 — Redis key name


def _wb_key(case_key: str) -> str:
    """The Redis key for a case's failure counter: an HMAC, never the case number,
    so a Redis dump does not list which cases someone tried to open."""
    digest = hmac.new(settings.secret_key.encode(), case_key.encode(), hashlib.sha256)
    return f"{_WB_PREFIX}{digest.hexdigest()}"


async def record_whistleblower_failure(redis: Redis, case_key: str) -> int:
    """Record a failed access attempt. Returns total failure count."""
    key = _wb_key(case_key)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.access_lockout_minutes * 60)
    return int(count)


async def reset_whistleblower_attempts(redis: Redis, case_key: str) -> None:
    """Clear the failure counter after a successful access."""
    key = _wb_key(case_key)
    await redis.delete(key)


async def get_whistleblower_lockout_ttl(redis: Redis, case_key: str) -> int:
    """Returns seconds remaining in the lockout window, or 0 if not locked."""
    key = _wb_key(case_key)
    ttl = await redis.ttl(key)
    return max(0, int(ttl))


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


async def record_instance_login_failure(redis: Redis) -> bool:
    """Count one failed admin password attempt across the whole instance.

    Per-username lockout does not see password spraying (one guess against each
    of many accounts). This counts every failure in one-minute buckets - no
    username, no IP - and sums the buckets of the sliding window. Returns True
    exactly once per window, when the count reaches the alert threshold;
    a threshold of 0 disables the check.
    """
    threshold = settings.admin_failed_login_alert_threshold
    if threshold <= 0:
        return False
    minutes = settings.admin_failed_login_alert_window_minutes
    now_minute = int(time.time() // 60)
    key = f"{_SPRAY_PREFIX}{now_minute}"
    await redis.incr(key)
    await redis.expire(key, (minutes + 1) * 60)
    counts = await redis.mget(
        [f"{_SPRAY_PREFIX}{m}" for m in range(now_minute - minutes + 1, now_minute + 1)]
    )
    if sum(int(c) for c in counts if c) < threshold:
        return False
    return bool(await redis.set(_SPRAY_ALERTED, "1", nx=True, ex=minutes * 60))


async def setup_token_locked(redis: Redis) -> bool:
    """True once MAX_LOGIN_ATTEMPTS wrong setup tokens were tried in the lockout window.

    Counted for the whole instance (there is no account yet, and no IP is read).
    """
    count = await redis.get(_SETUP_TOKEN_FAILURES)
    return count is not None and int(count) >= settings.max_login_attempts


async def record_setup_token_failure(redis: Redis) -> None:
    count = await redis.incr(_SETUP_TOKEN_FAILURES)
    if count == 1:
        await redis.expire(_SETUP_TOKEN_FAILURES, settings.login_lockout_minutes * 60)


async def reset_setup_token_failures(redis: Redis) -> None:
    """Clear the count after a right token (only reachable while not locked)."""
    await redis.delete(_SETUP_TOKEN_FAILURES)
