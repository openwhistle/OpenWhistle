"""Custom report categories service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import ReportCategory
from app.models.organisation import Organisation


async def _default_org_id(db: AsyncSession) -> uuid.UUID | None:
    from app.config import settings

    r = await db.execute(
        select(Organisation.id).where(Organisation.slug == settings.default_org_slug).limit(1)
    )
    return r.scalar_one_or_none()


async def get_active_categories(db: AsyncSession) -> list[ReportCategory]:
    result = await db.execute(
        select(ReportCategory)
        .where(ReportCategory.is_active.is_(True))
        .order_by(ReportCategory.sort_order, ReportCategory.label_en)
    )
    return list(result.scalars().all())


async def get_all_categories(
    db: AsyncSession,
    *,
    scope_org: bool = False,
    org_id: uuid.UUID | None = None,
) -> list[ReportCategory]:
    q = select(ReportCategory).order_by(ReportCategory.sort_order, ReportCategory.label_en)
    if scope_org:
        q = q.where(ReportCategory.org_id == org_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_category_labels(
    db: AsyncSession,
    lang: str,
    *,
    scope_org: bool = False,
    org_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """slug -> label in the caller's UI language, for every category
    (including deactivated ones — an existing report can still reference a
    deactivated category and must still show a real label, not its slug).

    `ReportCategory.slug` is unique per organisation, not globally (two orgs
    can each define their own category under the same slug) — scope this the
    same way as every sibling query in the caller (`_org_scope(current_user)`),
    or a same-slug category in another organisation could silently win the
    dict key and leak that org's label text to an admin who never should have
    seen it.
    """
    categories = await get_all_categories(db, scope_org=scope_org, org_id=org_id)
    return {c.slug: c.label_for(lang) for c in categories}


async def get_category_by_id(db: AsyncSession, cat_id: uuid.UUID) -> ReportCategory | None:
    result = await db.execute(select(ReportCategory).where(ReportCategory.id == cat_id))
    return result.scalar_one_or_none()


async def get_category_by_slug(
    db: AsyncSession, slug: str, org_id: uuid.UUID | None
) -> ReportCategory | None:
    """A slug is unique per organisation only: look it up within one."""
    result = await db.execute(select(ReportCategory).where(
        ReportCategory.slug == slug, ReportCategory.org_id.is_not_distinct_from(org_id)
    ))
    return result.scalar_one_or_none()


class DuplicateSlugError(ValueError):
    """The organisation already has a category with this slug."""


async def create_category(
    db: AsyncSession,
    slug: str,
    label_en: str,
    label_de: str,
    sort_order: int = 50,
    org_id: uuid.UUID | None = None,
) -> ReportCategory:
    if org_id is None:
        org_id = await _default_org_id(db)
    if await get_category_by_slug(db, slug, org_id):
        raise DuplicateSlugError(slug)
    cat = ReportCategory(
        id=uuid.uuid4(),
        slug=slug,
        label_en=label_en,
        label_de=label_de,
        is_default=False,
        is_active=True,
        sort_order=sort_order,
        org_id=org_id,
    )
    db.add(cat)
    await db.flush()  # the caller commits together with its audit row
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
