"""Authentication service: passwords, JWT sessions, OIDC."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import AdminUser

_SESSION_PREFIX = "openwhistle:session:"
_TOTP_PENDING_PREFIX = "openwhistle:totp_pending:"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_pin(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
    }
    return str(jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm))


def decode_access_token(token: str) -> str | None:
    """Decode a JWT and return the subject (user_id), or None if invalid."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        sub: str | None = payload.get("sub")
        return sub
    except JWTError:
        return None


async def store_session(redis: Redis, user_id: str, token: str) -> None:
    """Store session token in Redis for quick validation and revocation."""
    key = f"{_SESSION_PREFIX}{token}"
    await redis.setex(key, settings.access_token_expire_minutes * 60, user_id)


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
    user_id: str | None = await redis.getdel(key)
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
