"""Admin authentication: password + TOTP, OIDC, logout."""

import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.config import settings
from app.csrf import validate_csrf, validate_csrf_header
from app.database import get_db
from app.models.user import AdminRole, AdminUser
from app.onion import cookie_secure
from app.redis_client import get_redis
from app.services import audit as audit_service
from app.services import auth as auth_service
from app.services import oidc as oidc_service
from app.services import rate_limit as rl
from app.services.mfa import generate_qr_code_base64, verify_demo_totp, verify_totp
from app.services.notifications import notify_security_alert
from app.templating import render

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_root(request: Request) -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=302)


# Second barrier for LOCAL_REVIEW_LOGIN, beyond the config flag: the button
# and the route both disappear unless the request looks like it came straight
# from a browser on the local machine. A client-*address* check does not work
# here — uvicorn runs without --proxy-headers (see Dockerfile), so a browser
# on the operator's own machine, reaching the container through podman/
# docker's NAT, shows up as the container's gateway IP, never as 127.0.0.1.
# Instead, reject the request if either:
#   - it carries a header only a reverse proxy adds (nginx and every ingress
#     controller always set X-Forwarded-Proto in front of this app; a client
#     cannot strip a header the proxy adds after it); or
#   - the Host it addressed is not a loopback name.
# Either check alone can be spoofed (a stray client-sent header; nginx's
# default server echoing whatever Host it was given); together they hold.
_PROXY_HEADERS = ("x-forwarded-proto", "x-forwarded-for", "x-real-ip", "forwarded", "via")
_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def _local_review_reachable(request: Request) -> bool:
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    hostname = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
    return hostname.lower() in _LOOPBACK_HOSTNAMES


def _login_ctx(request: Request, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "oidc_enabled": settings.oidc_enabled,
        "ldap_enabled": settings.ldap_enabled,
        "local_review_login": settings.local_review_login and _local_review_reachable(request),
    }
    if extra:
        base.update(extra)
    return base


async def _second_factor(
    request: Request, redis: Redis, user: AdminUser
) -> HTMLResponse | RedirectResponse:
    """Hand a first-factor-verified user to TOTP setup or verification.

    Every login path (local, LDAP, OIDC) ends here: MFA is mandatory for all
    accounts, so no path may issue a session directly.
    """
    if not user.is_active:
        return render(request, "login.html", _login_ctx(request, {
            "error": "login.error.deactivated",
        }), status_code=401)

    if not user.totp_enabled:
        setup_token = secrets.token_urlsafe(32)
        await auth_service.store_totp_setup_pending(redis, setup_token, str(user.id))
        return RedirectResponse(f"/admin/mfa/setup?token={setup_token}", status_code=302)

    temp_token = secrets.token_urlsafe(32)
    await auth_service.store_totp_pending(redis, temp_token, str(user.id))
    return render(request, "login_mfa.html", {
        "temp_token": temp_token,
        "is_demo": settings.demo_mode,
    })


async def _password_failed(
    redis: Redis, db: AsyncSession, username: str, background_tasks: BackgroundTasks
) -> None:
    """Count a failed password: per username (lockout) and instance-wide.

    The instance-wide count makes password spraying visible - one guess
    against each of many accounts never trips a per-username lockout.
    """
    await rl.record_admin_login_failure(redis, username)
    if not await rl.record_instance_login_failure(redis):
        return
    threshold = settings.admin_failed_login_alert_threshold
    minutes = settings.admin_failed_login_alert_window_minutes
    await audit_service.log_system(
        db,
        audit_service.AuditAction.AUTH_SPRAYING_SUSPECTED,
        detail={"failed_attempts_at_least": threshold, "window_minutes": minutes},
    )
    await db.commit()
    background_tasks.add_task(
        notify_security_alert,
        "Possible password spraying",
        f"At least {threshold} failed admin password attempts in the last {minutes} "
        "minutes, across all accounts. MFA still protects every account, but check "
        "the audit log and consider whether the login page should be reachable from "
        "where these attempts come from. No further alert is sent for this window.",
    )


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    max_age = max(1, auth_service.seconds_left(token))
    response.set_cookie(
        key="ow_session", value=token, httponly=True, samesite="lax",
        secure=cookie_secure(request), max_age=max_age,
    )


async def _start_session(
    redis: Redis, db: AsyncSession, user: AdminUser, request: Request
) -> RedirectResponse:
    """The only place a login becomes a session (TOTP verify and TOTP setup)."""
    if not user.is_active:
        return RedirectResponse("/admin/login", status_code=302)

    token = auth_service.create_access_token(str(user.id), role=user.role.value)
    await auth_service.store_session(redis, str(user.id), token)
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    response = RedirectResponse("/admin/dashboard", status_code=302)
    _set_session_cookie(response, token, request)
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request) -> HTMLResponse:
    return render(request, "login.html", _login_ctx(request))


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login_post(
    request: Request,
    background_tasks: BackgroundTasks,
    username: str = Form(""),
    password: str = Form(""),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    # An empty field is answered on the form, next to the field — not with a
    # bare 422 JSON body (the form is novalidate, and must work without JS).
    missing: dict[str, str] = {}
    if not username.strip():
        missing["username"] = "login.error.username_required"
    if not password:
        missing["password"] = "login.error.password_required"  # noqa: S105 — locale key
    if missing:
        return render(request, "login.html", _login_ctx(request, {
            "error": "login.error.required",
            "field_errors": missing,
        }), status_code=400)

    if not await rl.check_admin_login_attempts(redis, username):
        return render(request, "login.html", _login_ctx(request, {
            "error": "login.error.locked",
        }))

    # ── LDAP authentication path ────────────────────────────────────
    if settings.ldap_enabled:
        from sqlalchemy import select  # noqa: PLC0415

        from app.services.ldap_auth import LDAPAuthError, authenticate_ldap  # noqa: PLC0415
        from app.services.mfa import generate_totp_secret  # noqa: PLC0415

        try:
            ldap_info = await authenticate_ldap(username, password)
        except LDAPAuthError:
            await _password_failed(redis, db, username, background_tasks)
            return render(request, "login.html", _login_ctx(request, {
                "error": "login.error.invalid",
                "credentials_invalid": True,
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
                # Least privilege: every directory user can reach this point,
                # so never inherit the model's admin default. An admin promotes.
                role=AdminRole.case_manager,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        return await _second_factor(request, redis, user)

    # ── Local password authentication path ─────────────────────────
    user = await auth_service.get_user_by_username(db, username)

    if user is not None and user.password_hash:
        pw_ok = auth_service.verify_password(password, user.password_hash)
    else:
        # Constant-time-ish: run a dummy bcrypt check so a nonexistent username
        # or an SSO/LDAP-only account (no local hash) is not distinguishable by
        # response latency (username enumeration side-channel).
        auth_service.verify_password(password, auth_service.TIMING_DUMMY_HASH)
        pw_ok = False
    if not pw_ok:
        await _password_failed(redis, db, username, background_tasks)
        return render(request, "login.html", _login_ctx(request, {
            "error": "login.error.invalid",
            "credentials_invalid": True,
        }), status_code=401)

    assert user is not None  # narrowed: pw_ok True implies user is not None
    # Note: SSO-only accounts (oidc_sub set, no password_hash) never reach here —
    # pw_ok is False for them, so they already received the generic 401 above.
    # We intentionally do NOT reveal "this account uses SSO", which would leak
    # account existence / auth method (kept generic for privacy).

    return await _second_factor(request, redis, user)


@router.get("/local-review-login", include_in_schema=False)
@router.head("/local-review-login", include_in_schema=False)
async def local_review_login_get_or_head() -> None:
    """No GET/HEAD ever existed for this path. Explicit here so a bare method
    probe gets the same 404 the POST gives when disabled, instead of the
    405 FastAPI would otherwise answer for a path that has *some* handler —
    which would itself reveal that the path exists."""
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post(
    "/local-review-login", response_class=HTMLResponse, response_model=None, include_in_schema=False
)
async def local_review_login_post(
    request: Request,
    csrf_token: str = Form(""),
    ow_csrf: str | None = Cookie(None),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """One-click sign-in as the seeded demo admin, full session, no password or
    MFA check — LOCAL_REVIEW_LOGIN only, so an agent can review every admin
    page without a human typing credentials. Every check below runs before
    any state changes, in this order, so a disabled/unreachable/deactivated
    outcome never writes an audit row for a login that did not really happen:
      1. the setting, and the request-shape barrier (`_local_review_reachable`)
         — both 404 (it does not exist), never 403, when either fails;
      2. CSRF, called directly rather than via Depends(validate_csrf), which
         would run before step 1 and turn a disabled route into a 403;
      3. the seeded demo admin exists and is active.
    Not rate-limited: `_local_review_reachable` already confines it to a
    loopback request with no proxy header in front of it.
    """
    if not settings.local_review_login or not _local_review_reachable(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await validate_csrf(csrf_token, ow_csrf)

    from app.services.demo_seed import DEMO_ADMIN_USERNAME  # noqa: PLC0415

    user = await auth_service.get_user_by_username(db, DEMO_ADMIN_USERNAME)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not user.is_active:
        # Same outcome _start_session gives an inactive user — checked here,
        # before the audit write, so a deactivated demo admin never gets a
        # "signed in via local review" row for a login that did not happen.
        return RedirectResponse("/admin/login", status_code=302)

    await audit_service.log(db, user, audit_service.AuditAction.AUTH_LOCAL_REVIEW_LOGIN)
    await db.commit()
    return await _start_session(redis, db, user, request)


@router.post("/login/mfa", response_class=HTMLResponse, response_model=None)
async def login_mfa_post(
    request: Request,
    totp_code: str = Form(""),
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

    # Second-factor guessing must be throttled just like the password factor,
    # otherwise an attacker who already holds the password can brute-force the
    # 6-digit TOTP unhindered.
    if not await rl.check_admin_login_attempts(redis, user.username):
        return render(
            request,
            "login_mfa.html",
            {
                "error": "login.error.locked",
                "is_demo": settings.demo_mode,
            },
            status_code=429,
        )

    demo_code = settings.demo_mode and verify_demo_totp(totp_code, user.username)
    code_valid = demo_code or verify_totp(
        user.totp_secret, totp_code
    )

    # One-time use: a valid code may authenticate exactly one session within its
    # ~90s validity window. Prevents an intercepted/relayed code from logging in
    # a second, attacker-controlled session (AiTM replay). Skipped for the demo
    # accounts, whose static code is intentionally reusable.
    if code_valid and not demo_code:
        used_key = f"openwhistle:totp_used:{user.id}:{totp_code}"
        if not await redis.set(used_key, "1", nx=True, ex=90):
            code_valid = False

    if not code_valid:
        await rl.record_admin_login_failure(redis, user.username)
        new_temp = secrets.token_urlsafe(32)
        await auth_service.store_totp_pending(redis, new_temp, user_id)
        return render(
            request,
            "login_mfa.html",
            {
                "temp_token": new_temp,
                "error": "mfa.error.invalid",
                "field_errors": {"totp_code": "mfa.error.invalid"},
                "is_demo": settings.demo_mode,
            },
        )

    await rl.reset_admin_login_attempts(redis, user.username)
    return await _start_session(redis, db, user, request)


@router.get("/mfa/setup", response_class=HTMLResponse, response_model=None)
async def mfa_setup_get(
    request: Request,
    token: str | None = None,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    if not token:
        return RedirectResponse("/admin/login", status_code=302)

    user_id = await auth_service.peek_totp_setup_pending(redis, token)
    if not user_id:
        return RedirectResponse("/admin/login", status_code=302)

    user = await auth_service.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        return RedirectResponse("/admin/login", status_code=302)

    qr_b64 = generate_qr_code_base64(user.totp_secret, user.username)
    return render(request, "login_mfa_setup.html", {
        "temp_token": token,
        "qr_b64": qr_b64,
        "totp_secret": user.totp_secret,
        "username": user.username,
    })


@router.post("/mfa/setup", response_class=HTMLResponse, response_model=None)
async def mfa_setup_post(
    request: Request,
    totp_code: str = Form(""),
    temp_token: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    user_id = await auth_service.consume_totp_setup_pending(redis, temp_token)
    if not user_id:
        return RedirectResponse("/admin/login", status_code=302)

    user = await auth_service.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        return RedirectResponse("/admin/login", status_code=302)

    if not verify_totp(user.totp_secret, totp_code):
        new_setup_token = secrets.token_urlsafe(32)
        await auth_service.store_totp_setup_pending(redis, new_setup_token, user_id)
        qr_b64 = generate_qr_code_base64(user.totp_secret, user.username)
        return render(request, "login_mfa_setup.html", {
            "temp_token": new_setup_token,
            "qr_b64": qr_b64,
            "totp_secret": user.totp_secret,
            "username": user.username,
            "error": "mfa.setup.error.invalid",
            "field_errors": {"totp_code": "mfa.setup.error.invalid"},
        })

    user.totp_enabled = True
    await audit_service.log(db, user, audit_service.AuditAction.AUTH_TOTP_SETUP)
    await db.commit()

    return await _start_session(redis, db, user, request)


@router.post("/logout")
async def logout(
    request: Request,
    redis: Redis = Depends(get_redis),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    # POST + CSRF: a GET logout can be triggered by any page (an <img> tag),
    # which is a nuisance at best and a session-fixation helper at worst.
    token = request.cookies.get("ow_session")
    if token:
        await auth_service.revoke_session(redis, token)

    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(
        "ow_session", httponly=True, samesite="lax", secure=cookie_secure(request)
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
    _csrf: None = Depends(validate_csrf_header),
) -> JSONResponse:
    """New JWT + Redis session up to the full TTL, never past the absolute limit.

    Reuses the claims `get_current_admin` already verified for this same request
    (via `request.state.session_claims`) instead of decoding the cookie a second
    time: a second decode could observe the token expiring between the two calls,
    or a crafted/blank `auth_time`, and silently restart the 12 h clock from now.
    """
    claims: dict[str, Any] | None = getattr(request.state, "session_claims", None)
    started_at = auth_service.session_started_at(claims) if claims else 0
    if not started_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if session_token:
        await auth_service.revoke_session(redis, session_token)
    new_token = auth_service.create_access_token(
        str(current_user.id), role=current_user.role.value, auth_time=started_at,
    )
    await auth_service.store_session(redis, str(current_user.id), new_token)
    new_exp = auth_service.decode_access_token_exp(new_token)
    expires_at = int(new_exp.timestamp()) if new_exp else 0
    ttl = auth_service.seconds_left(new_token)
    response = JSONResponse({"ttl_seconds": ttl, "expires_at": expires_at})
    _set_session_cookie(response, new_token, request)
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
                "error": "login.error.sso_failed",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    try:
        claims = await oidc_service.exchange_code(redis, code, state)
    except Exception:  # noqa: BLE001
        return render(
            request,
            "login.html",
            {
                "error": "login.error.sso_failed",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    if not claims:
        return render(
            request,
            "login.html",
            {
                "error": "login.error.sso_expired",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    # Both from the verified ID token (see oidc_service.exchange_code).
    sub: str | None = claims.get("sub")
    issuer: str | None = claims.get("iss")

    if not sub or not issuer:
        return render(
            request,
            "login.html",
            {
                "error": "login.error.sso_identity",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    user = await auth_service.get_user_by_oidc_sub(db, sub, issuer)
    if not user:
        return render(
            request,
            "login.html",
            {
                "error": "login.error.sso_unlinked",
                "oidc_enabled": settings.oidc_enabled,
            },
        )

    return await _second_factor(request, redis, user)
