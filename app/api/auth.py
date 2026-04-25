"""Admin authentication: password + TOTP, OIDC, logout."""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.redis_client import get_redis
from app.services import auth as auth_service
from app.services import oidc as oidc_service
from app.services import rate_limit as rl
from app.services.mfa import verify_demo_totp, verify_totp
from app.templating import render

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_root(request: Request) -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request) -> HTMLResponse:
    return render(
        request,
        "login.html",
        {"oidc_enabled": settings.oidc_enabled},
    )


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    if not await rl.check_admin_login_attempts(redis, username):
        return render(
            request,
            "login.html",
            {
                "error": "Account temporarily locked due to too many failed attempts.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    user = await auth_service.get_user_by_username(db, username)

    if user is None or not auth_service.verify_password(password, user.password_hash):
        await rl.record_admin_login_failure(redis, username)
        return render(
            request,
            "login.html",
            {
                "error": "Invalid username or password.",
                "oidc_enabled": settings.oidc_enabled,
            },
            status_code=401,
        )

    # Block password login for OIDC-only accounts
    if user.oidc_sub and not user.password_hash:
        return render(
            request,
            "login.html",
            {
                "error": "This account uses Single Sign-On. Please use the SSO button.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    temp_token = secrets.token_urlsafe(32)
    await auth_service.store_totp_pending(redis, temp_token, str(user.id))

    return render(
        request,
        "login_mfa.html",
        {
            "temp_token": temp_token,
            "is_demo": settings.demo_mode,
        },
    )


@router.post("/login/mfa", response_class=HTMLResponse, response_model=None)
async def login_mfa_post(
    request: Request,
    totp_code: str = Form(...),
    temp_token: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
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
        new_temp = secrets.token_urlsafe(32)
        await auth_service.store_totp_pending(redis, new_temp, user_id)
        return render(
            request,
            "login_mfa.html",
            {
                "temp_token": new_temp,
                "error": "Invalid authentication code. Please try again.",
                "is_demo": settings.demo_mode,
            },
        )

    await rl.reset_admin_login_attempts(redis, user.username)
    token = auth_service.create_access_token(str(user.id))
    await auth_service.store_session(redis, str(user.id), token)

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
) -> RedirectResponse:
    token = request.cookies.get("ow_session")
    if token:
        await auth_service.revoke_session(redis, token)

    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie(
        "ow_session", httponly=True, samesite="lax", secure=not settings.demo_mode
    )
    return response


# ── OIDC ─────────────────────────────────────────────────────────────────────


@router.get("/oidc/authorize", response_model=None)
async def oidc_authorize(
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    url = await oidc_service.create_authorization_url(redis)
    return RedirectResponse(url, status_code=302)


@router.get("/oidc/callback", response_class=HTMLResponse, response_model=None)
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if error or not code or not state:
        return render(
            request,
            "login.html",
            {
                "error": f"SSO authentication failed: {error or 'missing parameters'}.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    try:
        userinfo = await oidc_service.exchange_code(redis, code, state)
    except Exception:  # noqa: BLE001
        return render(
            request,
            "login.html",
            {
                "error": "SSO authentication failed. Please try again.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    if not userinfo:
        return render(
            request,
            "login.html",
            {
                "error": "SSO session expired or invalid state. Please try again.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    sub: str | None = userinfo.get("sub")
    issuer: str | None = userinfo.get("iss")

    if not sub or not issuer:
        return render(
            request,
            "login.html",
            {
                "error": "SSO provider did not return required identity information.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    user = await auth_service.get_user_by_oidc_sub(db, sub, issuer)
    if not user:
        return render(
            request,
            "login.html",
            {
                "error": "No admin account is linked to this SSO identity. "
                "Contact your system administrator.",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    token = auth_service.create_access_token(str(user.id))
    await auth_service.store_session(redis, str(user.id), token)

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
