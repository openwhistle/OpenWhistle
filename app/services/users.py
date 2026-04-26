"""Admin user management service."""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password


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


async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    role: AdminRole = AdminRole.admin,
) -> tuple[AdminUser, str]:
    """Create a new admin user. Returns (user, totp_secret)."""
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
