"""Location / branch management service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location import Location


async def get_active_locations(db: AsyncSession) -> list[Location]:
    result = await db.execute(
        select(Location)
        .where(Location.is_active.is_(True))
        .order_by(Location.sort_order, Location.name)
    )
    return list(result.scalars().all())


async def get_all_locations(db: AsyncSession) -> list[Location]:
    result = await db.execute(
        select(Location).order_by(Location.sort_order, Location.name)
    )
    return list(result.scalars().all())


async def get_location_by_id(db: AsyncSession, loc_id: uuid.UUID) -> Location | None:
    result = await db.execute(select(Location).where(Location.id == loc_id))
    return result.scalar_one_or_none()


async def get_location_by_code(db: AsyncSession, code: str) -> Location | None:
    result = await db.execute(select(Location).where(Location.code == code))
    return result.scalar_one_or_none()


async def create_location(
    db: AsyncSession,
    name: str,
    code: str,
    description: str | None = None,
    sort_order: int = 0,
) -> Location:
    loc = Location(
        id=uuid.uuid4(),
        name=name,
        code=code.strip().upper(),
        description=description or None,
        is_active=True,
        sort_order=sort_order,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


async def deactivate_location(db: AsyncSession, loc: Location) -> Location:
    loc.is_active = False
    await db.commit()
    await db.refresh(loc)
    return loc


async def reactivate_location(db: AsyncSession, loc: Location) -> Location:
    loc.is_active = True
    await db.commit()
    await db.refresh(loc)
    return loc
