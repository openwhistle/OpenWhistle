"""Admin authentication: password + TOTP, OIDC, logout."""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.models.user import AdminUser
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


def _login_ctx(extra: dict | None = None) -> dict:
    base: dict = {"oidc_enabled": settings.oidc_enabled, "ldap_enabled": settings.ldap_enabled}
    if extra:
        base.update(extra)
    return base


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request) -> HTMLResponse:
    return render(request, "login.html", _login_ctx())


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
        return render(request, "login.html", _login_ctx({
            "error": "Account temporarily locked due to too many failed attempts.",
        }))

    # ── LDAP authentication path ────────────────────────────────────
    if settings.ldap_enabled:
        from sqlalchemy import select  # noqa: PLC0415

        from app.services.ldap_auth import LDAPAuthError, authenticate_ldap  # noqa: PLC0415
        from app.services.mfa import generate_totp_secret  # noqa: PLC0415

        try:
            ldap_info = await authenticate_ldap(username, password)
        except LDAPAuthError:
            await rl.record_admin_login_failure(redis, username)
            return render(request, "login.html", _login_ctx({
                "error": "Invalid username or password.",
            }), status_code=401)

        # Find or provision the local admin user for this LDAP identity
        result = await db.execute(
            select(AdminUser).where(AdminUser.ldap_username == ldap_info.username)
        )
        user: AdminUser | None = result.scalar_one_or_none()

        if user is None:
            # First LDAP login — auto-provision with a temporary TOTP secret.
            # The user must set up TOTP on their first login via /admin/mfa/setup.
            user = AdminUser(
                id=__import__("uuid").uuid4(),
                username=ldap_info.username,
                password_hash=None,
                ldap_username=ldap_info.username,
                totp_secret=generate_totp_secret(),
                totp_enabled=False,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        if not user.is_active:
            return render(request, "login.html", _login_ctx({
                "error": "This account has been deactivated.",
            }), status_code=401)

        temp_token = secrets.token_urlsafe(32)
        await auth_service.store_totp_pending(redis, temp_token, str(user.id))
        return render(request, "login_mfa.html", {
            "temp_token": temp_token,
            "is_demo": settings.demo_mode,
        })

    # ── Local password authentication path ─────────────────────────
    user = await auth_service.get_user_by_username(db, username)

    pw_ok = user is not None and user.password_hash and auth_service.verify_password(
        password, user.password_hash
    )
    if not pw_ok:
        await rl.record_admin_login_failure(redis, username)
        return render(request, "login.html", _login_ctx({
            "error": "Invalid username or password.",
        }), status_code=401)

    # Block password login for OIDC-only accounts
    if user.oidc_sub and not user.password_hash:
        return render(request, "login.html", _login_ctx({
            "error": "This account uses Single Sign-On. Please use the SSO button.",
        }))

    temp_token = secrets.token_urlsafe(32)
    await auth_service.store_totp_pending(redis, temp_token, str(user.id))

    return render(request, "login_mfa.html", {
        "temp_token": temp_token,
        "is_demo": settings.demo_mode,
    })


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
    token = auth_service.create_access_token(str(user.id), role=user.role.value)
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


# ── Session management ───────────────────────────────────────────────────────


@router.get("/session/ttl")
async def session_ttl(
    request: Request,
    _user: AdminUser = Depends(get_current_admin),
) -> JSONResponse:
    """Return remaining TTL for the current admin session."""
    expires_at: int = getattr(request.state, "session_expires_at", 0)
    ttl = max(0, expires_at - int(datetime.now(UTC).timestamp())) if expires_at else 0
    return JSONResponse({"ttl_seconds": ttl, "expires_at": expires_at})


@router.post("/session/refresh")
async def session_refresh(
    request: Request,
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(get_current_admin),
    session_token: str | None = Cookie(default=None, alias="ow_session"),
) -> JSONResponse:
    """Issue a new JWT + Redis session, extending the admin session by the full TTL."""
    if session_token:
        await auth_service.revoke_session(redis, session_token)

    new_token = auth_service.create_access_token(str(current_user.id), role=current_user.role.value)
    await auth_service.store_session(redis, str(current_user.id), new_token)

    new_exp = auth_service.decode_access_token_exp(new_token)
    expires_at = int(new_exp.timestamp()) if new_exp else 0
    ttl = max(0, expires_at - int(datetime.now(UTC).timestamp()))

    response = JSONResponse({"ttl_seconds": ttl, "expires_at": expires_at})
    response.set_cookie(
        key="ow_session",
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=not settings.demo_mode,
        max_age=settings.access_token_expire_minutes * 60,
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

    token = auth_service.create_access_token(str(user.id), role=user.role.value)
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
