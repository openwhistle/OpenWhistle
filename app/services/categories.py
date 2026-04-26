"""Custom report categories service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import ReportCategory


async def get_active_categories(db: AsyncSession) -> list[ReportCategory]:
    result = await db.execute(
        select(ReportCategory)
        .where(ReportCategory.is_active.is_(True))
        .order_by(ReportCategory.sort_order, ReportCategory.label_en)
    )
    return list(result.scalars().all())


async def get_all_categories(db: AsyncSession) -> list[ReportCategory]:
    result = await db.execute(
        select(ReportCategory).order_by(ReportCategory.sort_order, ReportCategory.label_en)
    )
    return list(result.scalars().all())


async def get_category_by_id(db: AsyncSession, cat_id: uuid.UUID) -> ReportCategory | None:
    result = await db.execute(select(ReportCategory).where(ReportCategory.id == cat_id))
    return result.scalar_one_or_none()


async def get_category_by_slug(db: AsyncSession, slug: str) -> ReportCategory | None:
    result = await db.execute(select(ReportCategory).where(ReportCategory.slug == slug))
    return result.scalar_one_or_none()


async def create_category(
    db: AsyncSession,
    slug: str,
    label_en: str,
    label_de: str,
    sort_order: int = 50,
) -> ReportCategory:
    cat = ReportCategory(
        id=uuid.uuid4(),
        slug=slug,
        label_en=label_en,
        label_de=label_de,
        is_default=False,
        is_active=True,
        sort_order=sort_order,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


async def update_category(
    db: AsyncSession,
    cat: ReportCategory,
    label_en: str | None = None,
    label_de: str | None = None,
    sort_order: int | None = None,
) -> ReportCategory:
    if label_en is not None:
        cat.label_en = label_en
    if label_de is not None:
        cat.label_de = label_de
    if sort_order is not None:
        cat.sort_order = sort_order
    await db.commit()
    await db.refresh(cat)
    return cat


async def deactivate_category(db: AsyncSession, cat: ReportCategory) -> ReportCategory:
    cat.is_active = False
    await db.commit()
    await db.refresh(cat)
    return cat


async def reactivate_category(db: AsyncSession, cat: ReportCategory) -> ReportCategory:
    cat.is_active = True
    await db.commit()
    await db.refresh(cat)
    return cat
