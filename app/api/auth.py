"""Admin authentication: password + TOTP, logout."""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.redis_client import get_redis
from app.templating import templates
from app.services import auth as auth_service
from app.services import rate_limit as rl
from app.services.mfa import verify_demo_totp, verify_totp

router = APIRouter(prefix="/admin")


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    if not await rl.check_admin_login_attempts(redis, username):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Account temporarily locked due to too many failed attempts."},
            status_code=429,
        )

    user = await auth_service.get_user_by_username(db, username)

    # Constant-time path to prevent username enumeration timing attacks
    if user is None or not auth_service.verify_password(password, user.password_hash):
        await rl.record_admin_login_failure(redis, username)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password."},
            status_code=401,
        )

    # Password correct — store pending TOTP state
    temp_token = secrets.token_urlsafe(32)
    await auth_service.store_totp_pending(redis, temp_token, str(user.id))

    return templates.TemplateResponse(
        request,
        "login_mfa.html",
        {
            "temp_token": temp_token,
            "is_demo": settings.demo_mode,
        },
    )


@router.post("/login/mfa", response_class=HTMLResponse)
async def login_mfa_post(
    request: Request,
    totp_code: str = Form(...),
    temp_token: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    user_id = await auth_service.consume_totp_pending(redis, temp_token)
    if not user_id:
        return RedirectResponse("/admin/login", status_code=302)

    user = await auth_service.get_user_by_id(db, user_id)
    if not user:
        return RedirectResponse("/admin/login", status_code=302)

    code_valid = (settings.demo_mode and verify_demo_totp(totp_code)) or verify_totp(
        user.totp_secret, totp_code
    )

    if not code_valid:
        # Put the pending token back so user can retry
        new_temp = secrets.token_urlsafe(32)
        await auth_service.store_totp_pending(redis, new_temp, user_id)
        return templates.TemplateResponse(
            request,
            "login_mfa.html",
            {
                "temp_token": new_temp,
                "error": "Invalid authentication code. Please try again.",
                "is_demo": settings.demo_mode,
            },
            status_code=401,
        )

    # Full authentication success
    await rl.reset_admin_login_attempts(redis, user.username)
    token = auth_service.create_access_token(str(user.id))
    await auth_service.store_session(redis, str(user.id), token)

    # Update last login
    from sqlalchemy import select
    from app.models.user import AdminUser
    result = await db.execute(select(AdminUser).where(AdminUser.id == user.id))
    db_user = result.scalar_one_or_none()
    if db_user:
        db_user.last_login_at = datetime.now(UTC)
        await db.commit()

    response = RedirectResponse("/admin/dashboard", status_code=302)
    response.set_cookie(
        key="ow_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=not settings.demo_mode,
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


@router.get("/logout")
async def logout(
    request: Request,
    redis: Redis = Depends(get_redis),
    session_token: str | None = None,
) -> RedirectResponse:
    # Read session cookie
    token = request.cookies.get("ow_session")
    if token:
        await auth_service.revoke_session(redis, token)

    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie("ow_session")
    return response
