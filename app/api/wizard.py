"""First-run setup wizard: creates the initial admin account."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setup import SetupStatus
from app.models.user import AdminUser
from app.services.auth import hash_password
from app.services.mfa import generate_qr_code_base64, generate_totp_secret, verify_totp
from app.templating import templates

router = APIRouter()


async def _is_setup_complete(db: AsyncSession) -> bool:
    result = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    return setup is not None and setup.completed


@router.get("/setup", response_class=HTMLResponse, response_model=None)
async def setup_get(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse | RedirectResponse:
    if await _is_setup_complete(db):
        return RedirectResponse("/admin/login", status_code=302)

    totp_secret = generate_totp_secret()
    qr_code = generate_qr_code_base64(totp_secret, "admin")

    return templates.TemplateResponse(
        request,
        "wizard/setup.html",
        {
            "totp_secret": totp_secret,
            "qr_code": qr_code,
        },
    )


@router.post("/setup", response_class=HTMLResponse, response_model=None)
async def setup_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    totp_secret: str = Form(...),
    totp_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    if await _is_setup_complete(db):
        return RedirectResponse("/admin/login", status_code=302)

    errors: list[str] = []

    if len(username) < 3 or len(username) > 64:
        errors.append("Username must be between 3 and 64 characters.")

    if len(password) < 12:
        errors.append("Password must be at least 12 characters.")

    if password != password_confirm:
        errors.append("Passwords do not match.")

    if not verify_totp(totp_secret, totp_code):
        errors.append("Invalid TOTP code. Please scan the QR code and enter the current code.")

    if errors:
        qr_code = generate_qr_code_base64(totp_secret, username)
        return templates.TemplateResponse(
            request,
            "wizard/setup.html",
            {
                "totp_secret": totp_secret,
                "qr_code": qr_code,
                "errors": errors,
                "username": username,
            },
            status_code=422,
        )

    admin = AdminUser(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(password),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)

    result = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    if setup is None:
        setup = SetupStatus(id=1, completed=True, completed_at=datetime.now(UTC))
        db.add(setup)
    else:
        setup.completed = True
        setup.completed_at = datetime.now(UTC)

    await db.commit()

    return RedirectResponse("/admin/login", status_code=302)
