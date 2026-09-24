"""Authentication service: passwords, JWT sessions, OIDC."""

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import AdminUser

_SESSION_PREFIX = "openwhistle:session:"
_TOTP_PENDING_PREFIX = "openwhistle:totp_pending:"
_TOTP_SETUP_PREFIX = "openwhistle:totp_setup:"


# bcrypt only looks at the first 72 bytes, and bcrypt>=5 raises ValueError
# beyond that instead of truncating silently.
_BCRYPT_MAX_BYTES = 72
MIN_PASSWORD_LENGTH = 12


def validate_password(password: str) -> str:
    """The one password policy for every account password a person sets.

    Used by the setup wizard, admin-created users and the reset script.
    Raises ValueError with a user-facing message.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode()) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {_BCRYPT_MAX_BYTES} bytes long.")
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def _bcrypt_check(plain: str, hashed: str) -> bool:
    encoded = plain.encode()
    if len(encoded) > _BCRYPT_MAX_BYTES:
        # Never a valid secret (the policy and the PIN format forbid it); without
        # this, bcrypt raises and an over-long login attempt becomes a 500.
        bcrypt.checkpw(b"", hashed.encode())  # same work, same timing
        return False
    return bcrypt.checkpw(encoded, hashed.encode())


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt_check(plain, hashed)


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_pin(plain: str, hashed: str) -> bool:
    return _bcrypt_check(plain, hashed)


# Precomputed bcrypt hash used only to equalize timing when no real hash is
# available (unknown username or case number, SSO-only account). Never matches.
TIMING_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-secret")


def create_access_token(user_id: str, role: str = "admin", auth_time: int | None = None) -> str:
    """A session JWT. ``auth_time`` (login time, epoch seconds) survives refreshes,
    so ``exp`` never passes auth_time + SESSION_MAX_HOURS."""
    now = datetime.now(UTC)
    started = auth_time if auth_time is not None else int(now.timestamp())
    expire = min(
        now + timedelta(minutes=settings.access_token_expire_minutes),
        datetime.fromtimestamp(started, tz=UTC) + timedelta(hours=settings.session_max_hours),
    )
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "iat": now,
        "auth_time": started,
        "jti": str(uuid.uuid4()),
    }
    return str(jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm))


def decode_access_token_claims(token: str) -> dict[str, Any] | None:
    try:
        claims: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    return claims


def session_started_at(claims: dict[str, Any]) -> int:
    """Login time; tokens issued before v1.6.0 carry only ``iat``."""
    return int(claims.get("auth_time", claims.get("iat", 0)))


def session_too_old(claims: dict[str, Any]) -> bool:
    return time.time() - session_started_at(claims) > settings.session_max_hours * 3600


def decode_access_token_exp(token: str) -> datetime | None:
    """Decode a JWT and return the expiry as a UTC datetime, or None if invalid."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        exp = payload.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=UTC)
    except jwt.PyJWTError:
        return None


def seconds_left(token: str) -> int:
    """Seconds remaining until the token's ``exp``; 0 if invalid or already expired."""
    exp = decode_access_token_exp(token)
    if exp is None:
        return 0
    return max(0, int((exp - datetime.now(UTC)).total_seconds()))


async def get_session_ttl(redis: Redis, token: str) -> int:
    """Return remaining TTL in seconds for a session token (0 if not found)."""
    key = f"{_SESSION_PREFIX}{token}"
    ttl = await redis.ttl(key)
    return max(0, int(ttl))


async def store_session(redis: Redis, user_id: str, token: str) -> None:
    """Store session token in Redis; it lives exactly as long as the JWT."""
    await redis.setex(f"{_SESSION_PREFIX}{token}", max(1, seconds_left(token)), user_id)


async def validate_session(redis: Redis, token: str) -> bool:
    """Return True if the session token is still active in Redis."""
    key = f"{_SESSION_PREFIX}{token}"
    return bool(await redis.exists(key) == 1)


async def revoke_session(redis: Redis, token: str) -> None:
    """Invalidate a session (logout)."""
    key = f"{_SESSION_PREFIX}{token}"
    await redis.delete(key)


async def store_totp_pending(redis: Redis, temp_token: str, user_id: str) -> None:
    """Store a temporary token awaiting TOTP verification (5 min expiry)."""
    key = f"{_TOTP_PENDING_PREFIX}{temp_token}"
    await redis.setex(key, 300, user_id)


async def consume_totp_pending(redis: Redis, temp_token: str) -> str | None:
    """Consume a TOTP-pending token and return the user_id, or None if expired."""
    key = f"{_TOTP_PENDING_PREFIX}{temp_token}"
    raw = await redis.getdel(key)
    user_id: str | None = raw.decode() if isinstance(raw, bytes) else raw
    return user_id


async def store_totp_setup_pending(redis: Redis, temp_token: str, user_id: str) -> None:
    """Store a temporary token for first-time TOTP setup (10 min expiry)."""
    key = f"{_TOTP_SETUP_PREFIX}{temp_token}"
    await redis.setex(key, 600, user_id)


async def peek_totp_setup_pending(redis: Redis, temp_token: str) -> str | None:
    """Peek at a TOTP-setup token without consuming it."""
    key = f"{_TOTP_SETUP_PREFIX}{temp_token}"
    raw = await redis.get(key)
    user_id: str | None = raw.decode() if isinstance(raw, bytes) else raw
    return user_id


async def consume_totp_setup_pending(redis: Redis, temp_token: str) -> str | None:
    """Consume a TOTP-setup token and return the user_id, or None if expired."""
    key = f"{_TOTP_SETUP_PREFIX}{temp_token}"
    raw = await redis.getdel(key)
    user_id: str | None = raw.decode() if isinstance(raw, bytes) else raw
    return user_id


async def get_user_by_username(db: AsyncSession, username: str) -> AdminUser | None:
    result = await db.execute(select(AdminUser).where(AdminUser.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> AdminUser | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    result = await db.execute(select(AdminUser).where(AdminUser.id == uid))
    return result.scalar_one_or_none()


async def get_user_by_oidc_sub(db: AsyncSession, sub: str, issuer: str) -> AdminUser | None:
    result = await db.execute(
        select(AdminUser).where(
            AdminUser.oidc_sub == sub,
            AdminUser.oidc_issuer == issuer,
        )
    )
    return result.scalar_one_or_none()
