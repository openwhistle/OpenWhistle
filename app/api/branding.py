"""Operator branding: the public image route and the admin page."""

from __future__ import annotations

import re
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import may_run_the_instance, require_admin
from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.models.branding import Branding
from app.models.organisation import Organisation
from app.models.user import AdminUser
from app.redis_client import get_redis
from app.services import audit as audit_service
from app.services import brand_colour, brand_image, branding
from app.services.audit import AuditAction
from app.templating import render

router = APIRouter()

_SHA = re.compile(r"[0-9a-f]{64}")


@router.get("/branding/{sha}.png", include_in_schema=False)
async def serve_brand_image(sha: str, db: AsyncSession = Depends(get_db)) -> Response:
    png = await branding.image(db, sha) if _SHA.fullmatch(sha) else None
    if png is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # The hash changes with the image, so the URL can be cached for good.
    return Response(
        png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


_RESETTABLE = ("name", "primary_color", "logo_light", "logo_dark")


async def _target(db: AsyncSession, user: AdminUser, org: str) -> uuid.UUID | None:
    """Whose branding this admin edits: an instance admin the default, or with
    multi-tenancy any organisation; an organisation's admin only their own."""
    if may_run_the_instance(user):
        if not org or not settings.multi_tenancy_enabled:
            return None
        try:
            org_id = uuid.UUID(org)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
        if await db.get(Organisation, org_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return org_id
    if settings.multi_tenancy_enabled and user.org_id is not None and org in ("", str(user.org_id)):
        return user.org_id
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


async def _page(
    request: Request,
    db: AsyncSession,
    user: AdminUser,
    org_id: uuid.UUID | None,
    *,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    # Read only: an unsaved Branding() stands in for a row that does not exist yet.
    row = await branding.find_row(db, org_id) or Branding(org_id=org_id)
    snap = getattr(request.state, "branding_snapshot", {})
    effective = branding.resolve(snap, org_id)
    tokens = effective.tokens
    orgs: list[Organisation] = []
    if may_run_the_instance(user) and settings.multi_tenancy_enabled:
        orgs = list((await db.scalars(select(Organisation).order_by(Organisation.name))).all())
    return render(
        request,
        "admin/branding.html",
        {
            "user": user,
            "row": row,
            "org_id": org_id,
            "orgs": orgs,
            "effective": effective,
            "fallback_name": branding.resolve(
                {k: v for k, v in snap.items() if k == "default"}, None
            ).name
            if org_id
            else settings.app_name,
            "ratios": {
                key: f"{brand_colour.contrast(fg, bg):.1f}:1"
                for key, fg, bg in (
                    ("button", tokens["on"], tokens["accent"]),
                    ("light", tokens["accent"], brand_colour.LIGHT_CANVAS),
                    ("dark", tokens["accent-dark"], brand_colour.DARK_CANVAS),
                )
            },
            "error": error,
            "form": form or {},
            "saved": request.query_params.get("saved") == "1",
        },
        status_code=status_code,
    )


def _back(org_id: uuid.UUID | None) -> RedirectResponse:
    suffix = f"&org={org_id}" if org_id else ""
    return RedirectResponse(f"/admin/branding?saved=1{suffix}", status_code=303)


@router.get("/admin/branding", response_class=HTMLResponse)
async def branding_get(
    request: Request,
    org: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    return await _page(request, db, current_user, await _target(db, current_user, org))


async def _logo(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    data = await upload.read(brand_image.MAX_BYTES + 1)
    return brand_image.process_logo(data) if data else None


@router.post("/admin/branding", response_model=None)
async def branding_post(
    request: Request,
    name: str = Form(""),
    primary_color: str = Form(""),
    org: str = Form(""),
    remove_logo_light: str = Form(""),
    remove_logo_dark: str = Form(""),
    logo_light: UploadFile | None = File(None),
    logo_dark: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    org_id = await _target(db, current_user, org)
    form = {"name": name, "primary_color": primary_color}
    name = name.strip()
    try:
        if len(name) > 64:
            raise brand_image.BrandImageError("admin.branding.error.name")
        colour = None
        if primary_color.strip():
            try:
                colour = brand_colour.parse(primary_color)
            except ValueError:
                raise brand_image.BrandImageError("admin.branding.error.colour") from None
        light = await _logo(logo_light)
        dark = await _logo(logo_dark)
    except brand_image.BrandImageError as exc:
        return await _page(
            request, db, current_user, org_id, error=exc.key, form=form, status_code=422
        )

    row = await branding.row_for(db, org_id)
    changed: list[str] = []
    for field_name, value in (("name", name or None), ("primary_color", colour)):
        if getattr(row, field_name) != value:
            setattr(row, field_name, value)
            changed.append(field_name)
    if light is not None:
        row.logo_light = await branding.store_image(db, light)
        row.favicon_32 = await branding.store_image(db, brand_image.favicon(light, 32))
        row.favicon_180 = await branding.store_image(db, brand_image.favicon(light, 180))
        changed.append("logo_light")
    elif remove_logo_light == "1" and row.logo_light:
        row.logo_light = row.favicon_32 = row.favicon_180 = None
        changed.append("logo_light")
    if dark is not None:
        row.logo_dark = await branding.store_image(db, dark)
        changed.append("logo_dark")
    elif remove_logo_dark == "1" and row.logo_dark:
        row.logo_dark = None
        changed.append("logo_dark")
    if changed:
        row.updated_by_id = current_user.id
        await branding.drop_orphan_images(db)
        await audit_service.log(
            db,
            current_user,
            AuditAction.BRANDING_UPDATED,
            detail={"fields": changed},
            target_org=org_id,
        )
    await db.commit()
    await branding.invalidate(redis)
    return _back(org_id)


@router.post("/admin/branding/reset")
async def branding_reset(
    field: str = Form(...),
    org: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    org_id = await _target(db, current_user, org)
    fields = _RESETTABLE if field == "all" else (field,)
    if not set(fields) <= set(_RESETTABLE):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    row = await branding.row_for(db, org_id)
    for name in fields:
        setattr(row, name, None)
        if name == "logo_light":
            row.favicon_32 = row.favicon_180 = None
    row.updated_by_id = current_user.id
    await branding.drop_orphan_images(db)
    await audit_service.log(
        db,
        current_user,
        AuditAction.BRANDING_RESET,
        detail={"fields": list(fields)},
        target_org=org_id,
    )
    await db.commit()
    await branding.invalidate(redis)
    return _back(org_id)
