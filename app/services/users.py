"""Admin user management service."""

from __future__ import annotations

import re
import uuid

import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password

# Locally-created usernames are restricted to an unambiguous allowlist. This
# prevents storing quotes / JS metacharacters that could break out of an
# HTML/JS context in the admin UI (defense in depth alongside contextual output
# encoding). Directory-provisioned identities (OIDC/LDAP) do not pass through
# this validator.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@ -]{3,64}$")


def validate_username(username: str) -> str:
    """Return the trimmed username or raise ValueError if it is not allowed."""
    candidate = username.strip()
    if not _USERNAME_RE.fullmatch(candidate):
        raise ValueError(
            "Username must be 3–64 characters and may only contain letters, "
            "digits, spaces and the characters . _ @ -"
        )
    return candidate


async def get_all_users(db: AsyncSession) -> list[AdminUser]:
    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at))
    return list(result.scalars().all())


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> AdminUser | None:
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    return result.scalar_one_or_none()


async def count_active_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(AdminUser.id)).where(
            AdminUser.role == AdminRole.admin,
            AdminUser.is_active.is_(True),
        )
    )
    return result.scalar_one()


async def count_active_privileged_admins(db: AsyncSession) -> int:
    """Active accounts that can administer the instance (admin OR superadmin)."""
    result = await db.execute(
        select(func.count(AdminUser.id)).where(
            AdminUser.role.in_([AdminRole.admin, AdminRole.superadmin]),
            AdminUser.is_active.is_(True),
        )
    )
    return result.scalar_one()


async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    role: AdminRole = AdminRole.admin,
) -> tuple[AdminUser, str]:
    """Create a new admin user. Returns (user, totp_secret).

    Raises ValueError if the username contains disallowed characters.
    """
    username = validate_username(username)
    totp_secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(password),
        totp_secret=totp_secret,
        totp_enabled=False,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, totp_secret


async def update_user_role(
    db: AsyncSession,
    user: AdminUser,
    new_role: AdminRole,
) -> AdminUser:
    user.role = new_role
    await db.commit()
    await db.refresh(user)
    return user


async def deactivate_user(db: AsyncSession, user: AdminUser) -> AdminUser:
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user


async def reactivate_user(db: AsyncSession, user: AdminUser) -> AdminUser:
    user.is_active = True
    await db.commit()
    await db.refresh(user)
    return user
