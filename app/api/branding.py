"""Operator branding: the public image route and the admin page."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import branding

router = APIRouter()

_SHA = re.compile(r"[0-9a-f]{64}")


@router.get("/branding/{sha}.png", include_in_schema=False)
async def brand_image(sha: str, db: AsyncSession = Depends(get_db)) -> Response:
    png = await branding.image(db, sha) if _SHA.fullmatch(sha) else None
    if png is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # The hash changes with the image, so the URL can be cached for good.
    return Response(
        png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
