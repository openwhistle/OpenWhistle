"""One-time setup token: reaching /setup first is not enough to become admin."""

from __future__ import annotations

import logging
import secrets

from redis.asyncio import Redis

from app.config import settings

log = logging.getLogger(__name__)

SETUP_TOKEN_KEY = "openwhistle:setup-token"  # noqa: S105 — Redis key name, not a secret


def _text(raw: bytes | str | None) -> str | None:
    return raw.decode() if isinstance(raw, bytes) else raw


async def ensure_setup_token(redis: Redis) -> None:
    """Create the token unless one exists, or refresh it to match a configured
    SETUP_TOKEN. Only the caller whose write actually changes the stored value
    logs — so a scaled deployment, or a /setup page loaded repeatedly, prints
    the notice once."""
    if settings.setup_token:
        # A configured token always wins, overwriting whatever is stored — an
        # operator who sets SETUP_TOKEN after Redis already holds a random
        # token (or after another replica's random token) must not be locked
        # out by a stale value. Every replica writes the same value, so the
        # overwrite is idempotent; GET-on-SET reports the previous value so
        # we only log when it actually changed.
        raw_previous = await redis.set(SETUP_TOKEN_KEY, settings.setup_token, get=True)
        previous = _text(raw_previous if isinstance(raw_previous, bytes | str) else None)
        if previous != settings.setup_token:
            log.warning("Setup is open: enter the SETUP_TOKEN from the environment on /setup.")
        return

    token = secrets.token_urlsafe(32)
    if await redis.set(SETUP_TOKEN_KEY, token, nx=True):
        log.warning("Setup is open. Setup token for /setup: %s", token)


async def check_setup_token(redis: Redis, supplied: str) -> bool:
    stored = _text(await redis.get(SETUP_TOKEN_KEY))
    if not stored or not supplied:
        return False
    return secrets.compare_digest(stored.encode(), supplied.encode())


async def delete_setup_token(redis: Redis) -> None:
    await redis.delete(SETUP_TOKEN_KEY)
