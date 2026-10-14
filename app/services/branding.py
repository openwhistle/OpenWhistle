"""Operator branding: the cached snapshot, resolution order, and the image store.

Resolution, per field: the organisation's row, the default row, the
environment (APP_NAME, BRAND_PRIMARY_COLOR, BRAND_LOGO_URL), the built-in.
The light logo, the dark logo and the favicons always come from one row.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import delete, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.branding import BrandImage, Branding
from app.services import brand_colour

CACHE_KEY = "branding:snapshot"
CACHE_SECONDS = 3600
_FIELDS = ("name", "primary_color", *Branding.IMAGE_FIELDS)

Snapshot = dict[str, dict[str, str | None]]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Brand:
    name: str
    primary_color: str
    logo_url: str
    logo_dark_url: str = ""
    favicon_32_url: str = ""
    favicon_180_url: str = ""
    tokens: dict[str, str] = field(default_factory=dict)


def _url(sha: str | None) -> str:
    return f"/branding/{sha}.png" if sha else ""


def resolve(snap: Snapshot, org_id: uuid.UUID | None) -> Brand:
    own = snap.get(str(org_id), {}) if org_id else {}
    base = snap.get("default", {})
    images = own if own.get("logo_light") else base
    try:
        colour = brand_colour.parse(
            own.get("primary_color") or base.get("primary_color") or settings.brand_primary_color
        )
    except ValueError:
        colour = brand_colour.DEFAULT
    return Brand(
        name=own.get("name") or base.get("name") or settings.app_name,
        primary_color=colour,
        logo_url=_url(images.get("logo_light")) or settings.brand_logo_url,
        logo_dark_url=_url(images.get("logo_dark")),
        favicon_32_url=_url(images.get("favicon_32")),
        favicon_180_url=_url(images.get("favicon_180")),
        tokens=brand_colour.tokens(colour),
    )


async def _load() -> Snapshot:
    from app.database import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(Branding))).all()
    return {
        (str(row.org_id) if row.org_id else "default"): {f: getattr(row, f) for f in _FIELDS}
        for row in rows
    }


async def snapshot(redis: Redis) -> Snapshot:
    cached = await redis.get(CACHE_KEY)
    if cached:
        data: Any
        try:
            data = json.loads(cached)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
    snap = await _load()
    await redis.set(CACHE_KEY, json.dumps(snap), ex=CACHE_SECONDS)
    return snap


async def invalidate(redis: Redis) -> None:
    await redis.delete(CACHE_KEY)


async def find_row(db: AsyncSession, org_id: uuid.UUID | None) -> Branding | None:
    where = Branding.org_id.is_(None) if org_id is None else Branding.org_id == org_id
    return await db.scalar(select(Branding).where(where))


async def row_for(db: AsyncSession, org_id: uuid.UUID | None) -> Branding:
    row = await find_row(db, org_id)
    if row is None:
        row = Branding(id=uuid.uuid4(), org_id=org_id)
        db.add(row)
    return row


async def store_image(db: AsyncSession, png: bytes) -> str:
    sha = hashlib.sha256(png).hexdigest()
    if await db.get(BrandImage, sha) is None:
        db.add(BrandImage(sha256=sha, png=png))
        await db.flush()
    return sha


async def drop_orphan_images(db: AsyncSession) -> None:
    await db.flush()
    columns = [getattr(Branding, name) for name in Branding.IMAGE_FIELDS]
    used = union(*(select(c).where(c.is_not(None)) for c in columns)).subquery()
    await db.execute(delete(BrandImage).where(BrandImage.sha256.not_in(select(used.c[0]))))


async def image(db: AsyncSession, sha: str) -> bytes | None:
    found = await db.get(BrandImage, sha)
    return found.png if found else None


async def load_branding(request: Request) -> None:
    """Every route's dependency: one Redis read, never a failed page. A broken cache or
    an unreachable Redis leaves the environment's branding (APP_NAME and BRAND_*)."""
    from app.redis_client import get_redis  # noqa: PLC0415

    try:
        request.state.branding_snapshot = await snapshot(await get_redis())
    except Exception:  # noqa: BLE001 — branding must never take a page down
        log.warning("branding snapshot unavailable; using the environment's", exc_info=True)
        request.state.branding_snapshot = {}
