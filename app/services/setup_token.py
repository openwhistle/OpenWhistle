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
    """Create the token unless one exists. Only the caller whose SET won logs it,
    so a scaled deployment prints it once."""
    token = settings.setup_token or secrets.token_urlsafe(32)
    if not await redis.set(SETUP_TOKEN_KEY, token, nx=True):
        return
    if settings.setup_token:
        log.warning("Setup is open: enter the SETUP_TOKEN from the environment on /setup.")
    else:
        log.warning("Setup is open. Setup token for /setup: %s", token)


async def check_setup_token(redis: Redis, supplied: str) -> bool:
    stored = _text(await redis.get(SETUP_TOKEN_KEY))
    if not stored or not supplied:
        return False
    return secrets.compare_digest(stored.encode(), supplied.encode())


async def delete_setup_token(redis: Redis) -> None:
    await redis.delete(SETUP_TOKEN_KEY)
