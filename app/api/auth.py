"""Admin authentication: password + TOTP, OIDC, logout."""

import logging
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_signed_in_admin
from app.config import settings
from app.csrf import validate_csrf, validate_csrf_header
from app.database import get_db
from app.middleware import _IP_REVEAL_HEADERS
from app.models.user import AdminRole, AdminUser
from app.onion import cookie_secure
from app.redis_client import get_redis
from app.services import audit as audit_service
from app.services import auth as auth_service
from app.services import oidc as oidc_service
from app.services import rate_limit as rl
from app.services.mfa import consume_totp, generate_qr_code_base64, verify_demo_totp
from app.services.notifications import notify_security_alert
from app.templating import render

log = logging.getLogger(__name__)

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
# default server echoing whatever Host it was given). Together they still do
# not stop a peer that reaches the app port directly and sends "Host:
# localhost" (another pod, a LAN host on a published port), which is why the
# settings also refuse LOCAL_REVIEW_LOGIN unless APP_PUBLIC_URL is loopback and
# SECURE_COOKIES is off, and the review stack binds the port to 127.0.0.1.
_PROXY_HEADERS = _IP_REVEAL_HEADERS | {"x-forwarded-proto", "via"}
_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def _local_review_reachable(request: Request) -> bool:
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    host_header = request.headers.get("host", "")
    try:
        # A malformed bracketed Host (e.g. "[::1].evil.com", "[::1") makes
        # urlsplit raise ValueError instead of returning an unparsed/empty
        # hostname — unparsable is not loopback, so treat it as unreachable
        # rather than let the exception escape as an uncaught 500.
        hostname = urlsplit(f"//{host_header}").hostname or ""
    except ValueError:
        return False
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
    # A password someone else set is replaced before anything else opens.
    landing = "/admin/account" if user.must_change_password else "/admin/dashboard"
    response = RedirectResponse(landing, status_code=302)
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
    # A directory bind that fails falls through to the local check below:
    # the wizard's superadmin (and any account made on /admin/users) has a
    # local password, and switching LDAP on used to lock all of them out.
    if settings.ldap_enabled:
        from sqlalchemy import func, select  # noqa: PLC0415

        from app.services.ldap_auth import LDAPAuthError, authenticate_ldap  # noqa: PLC0415
        from app.services.mfa import generate_totp_secret  # noqa: PLC0415

        try:
            ldap_info = await authenticate_ldap(username, password)
        except LDAPAuthError:
            ldap_info = None

        if ldap_info is not None:
            # Find or provision the local admin user for this LDAP identity
            result = await db.execute(
                select(AdminUser).where(AdminUser.ldap_username == ldap_info.username)
            )
            user: AdminUser | None = result.scalar_one_or_none()

            if user is None:
                taken = await db.scalar(select(AdminUser.id).where(
                    func.lower(AdminUser.username) == ldap_info.username.lower()
                ))
                if taken is not None:
                    # Never merged into the local account of the same name:
                    # the directory would take it over. This used to be an
                    # IntegrityError, a 500.
                    log.warning("LDAP user matches a local account name; not provisioned")
                    await _password_failed(redis, db, username, background_tasks)
                    return render(request, "login.html", _login_ctx(request, {
                        "error": "login.error.invalid",
                        "credentials_invalid": True,
                    }), status_code=401)
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


# Every method FastAPI/Starlette route matching supports, registered on ONE
# api_route: a per-method decorator for only
# GET/HEAD/POST still left PUT/DELETE/PATCH/OPTIONS answering Starlette's
# default 405 — which, like the 405 this whole route exists to avoid for
# GET/HEAD, still confirms to a probe that *some* handler lives at this path.
# A single handler for every method, 404 for anything but an allowed POST,
# closes that regardless of which method is tried.
_LOCAL_REVIEW_LOGIN_METHODS = ["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]


@router.api_route(
    "/local-review-login",
    methods=_LOCAL_REVIEW_LOGIN_METHODS,
    response_model=None,
    include_in_schema=False,
)
async def local_review_login(
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
      1. the method (only POST is ever allowed), the setting, and the
         request-shape barrier (`_local_review_reachable`) — all 404 (it does
         not exist), never 403 or 405, when any of them fails;
      2. CSRF, called directly rather than via Depends(validate_csrf), which
         would run before step 1 and turn a disabled route into a 403;
      3. the seeded demo admin exists and is active.
    Not rate-limited: `_local_review_reachable` already confines it to a
    loopback request with no proxy header in front of it.
    """
    if (
        request.method != "POST"
        or not settings.local_review_login
        or not _local_review_reachable(request)
    ):
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

    # One-time use (consume_totp), except for the demo accounts, whose static
    # code is intentionally reusable.
    demo_code = settings.demo_mode and verify_demo_totp(totp_code, user.username)
    code_valid = demo_code or await consume_totp(
        redis, user.id, user.totp_secret, totp_code
    )

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

    # Consumed, so the enrolment code cannot sign in a second session.
    if not await consume_totp(redis, user.id, user.totp_secret, totp_code):
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
    _user: AdminUser = Depends(get_signed_in_admin),
) -> JSONResponse:
    """Return remaining TTL for the current admin session."""
    expires_at: int = getattr(request.state, "session_expires_at", 0)
    ttl = max(0, expires_at - int(datetime.now(UTC).timestamp())) if expires_at else 0
    return JSONResponse({"ttl_seconds": ttl, "expires_at": expires_at})


@router.post("/session/refresh")
async def session_refresh(
    request: Request,
    redis: Redis = Depends(get_redis),
    # The timer of the account page keeps a forced password change alive.
    current_user: AdminUser = Depends(get_signed_in_admin),
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

    if state and state.startswith(oidc_service.LINK_STATE_PREFIX):
        return await _oidc_link_callback(request, code, state, error, redis, db)

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


# ── OIDC account linking (self-service) ──────────────────────────────────────
#
# An admin already signed in with password (or LDAP) and TOTP links their own
# account to their identity at the provider. The state is bound to that
# session and to the "link" purpose (oidc_service.exchange_code checks both),
# so a link can only ever land on the account whose session started it.
# Linking adds a way to pass the first factor; TOTP stays mandatory
# (_second_factor), and the password keeps working.

def _sso_result(result: str) -> RedirectResponse:
    """Back to the account page, which shows the result (oidc.SSO_RESULTS)."""
    return RedirectResponse(f"/admin/account?sso={result}", status_code=303)


@router.post("/oidc/link", response_model=None)
async def oidc_link(
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(get_current_admin),
    session_token: str = Cookie(alias="ow_session"),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    binding = oidc_service.session_binding(str(current_user.id), session_token)
    url = await oidc_service.create_authorization_url(
        redis, purpose=oidc_service.PURPOSE_LINK, binding=binding
    )
    return RedirectResponse(url, status_code=303)


async def _oidc_link_callback(
    request: Request,
    code: str | None,
    state: str,
    error: str | None,
    redis: Redis,
    db: AsyncSession,
) -> HTMLResponse | RedirectResponse:
    session_token = request.cookies.get("ow_session")
    try:
        user = await get_current_admin(request, db, redis, session_token)
    except HTTPException:
        # No live session: this is never a login, and never links anything.
        return render(request, "login.html", _login_ctx(request, {
            "error": "login.error.sso_link_session",
        }), status_code=401)
    assert session_token is not None  # get_current_admin refuses a missing cookie

    if error or not code:
        return _sso_result("failed")
    try:
        claims = await oidc_service.exchange_code(
            redis, code, state,
            purpose=oidc_service.PURPOSE_LINK,
            binding=oidc_service.session_binding(str(user.id), session_token),
        )
    except Exception:  # noqa: BLE001
        return _sso_result("failed")
    sub = claims.get("sub") if claims else None
    issuer = claims.get("iss") if claims else None
    if not sub or not issuer:
        return _sso_result("failed")

    # oidc_sub is unique on its own (not per issuer): an identity already on
    # another account fails the constraint, and is never moved across.
    user.oidc_sub = sub
    user.oidc_issuer = issuer
    try:
        await audit_service.log(
            db, user, audit_service.AuditAction.AUTH_SSO_LINKED, detail={"issuer": issuer}
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _sso_result("taken")
    return _sso_result("linked")


@router.post("/oidc/unlink", response_model=None)
async def oidc_unlink(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not current_user.oidc_sub:
        return _sso_result("unlinked")
    # Without a password or a directory login, the link is the only way in.
    if not current_user.password_hash and not current_user.ldap_username:
        return _sso_result("only_way_in")

    issuer = current_user.oidc_issuer
    current_user.oidc_sub = None
    current_user.oidc_issuer = None
    await audit_service.log(
        db, current_user, audit_service.AuditAction.AUTH_SSO_UNLINKED,
        detail={"issuer": issuer},
    )
    await db.commit()
    return _sso_result("unlinked")


# ── Own account: overview and password change ────────────────────────────────
#
# Whoever set a password for someone else (a new account, a superadmin reset,
# the host's reset script) knows it; `must_change_password` sends the holder
# here before anything else opens (deps.get_current_admin). The change needs
# the current password and a fresh TOTP code: a session alone, left open on a
# desk, must not be enough to take the account over.

_PASSWORD_CHANGED = "changed"  # noqa: S105 — a query value, not a secret


def _demo_account(user: AdminUser) -> bool:
    from app.services.demo_seed import DEMO_USERNAMES  # noqa: PLC0415

    return settings.demo_mode and user.username in DEMO_USERNAMES


async def _account_page(
    request: Request,
    db: AsyncSession,
    user: AdminUser,
    extra: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    from app.models.organisation import Organisation  # noqa: PLC0415

    org = await db.get(Organisation, user.org_id) if user.org_id else None
    return render(request, "admin/account.html", {
        "user": user,
        "org_name": org.name if org else None,
        "ldap_enabled": settings.ldap_enabled,
        "demo_locked": _demo_account(user),
        "password_changed": request.query_params.get("password") == _PASSWORD_CHANGED,
        **(extra or {}),
    }, status_code=status_code)


@router.get("/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_signed_in_admin),
) -> HTMLResponse:
    return await _account_page(request, db, current_user)


def _new_password_error(current: str, new: str, confirm: str) -> dict[str, str]:
    """Form errors that need no credential check, so a typo never burns a code."""
    if not current:
        return {"current_password": "account.password.error.current_required"}
    if new != confirm:
        return {"confirm_password": "account.password.error.mismatch"}
    try:
        auth_service.validate_password(new)
    except ValueError:
        return {"new_password": "account.password.error.policy"}
    if new == current:
        return {"new_password": "account.password.error.unchanged"}
    return {}


@router.post("/account/password", response_class=HTMLResponse, response_model=None)
async def account_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    totp_code: str = Form(""),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_signed_in_admin),
    session_token: str = Cookie(alias="ow_session"),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    # LDAP and SSO-only accounts have no password here to change.
    if not current_user.password_hash:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if _demo_account(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The demo accounts keep their password.",
        )

    async def refuse(errors: dict[str, str], code: int) -> HTMLResponse:
        return await _account_page(request, db, current_user, {
            "error": next(iter(errors.values())), "field_errors": errors,
        }, status_code=code)

    # The same per-account counter as the sign-in form: guesses here and there add up.
    if not await rl.check_admin_login_attempts(redis, current_user.username):
        return await refuse({"current_password": "login.error.locked"}, 429)

    form_errors = _new_password_error(current_password, new_password, confirm_password)
    if form_errors:
        return await refuse(form_errors, 400)

    if not auth_service.verify_password(current_password, current_user.password_hash):
        await rl.record_admin_login_failure(redis, current_user.username)
        return await refuse({"current_password": "account.password.error.current"}, 401)

    # Single use, like the sign-in code: a code seen over a shoulder opens nothing twice.
    code_ok = await consume_totp(redis, current_user.id, current_user.totp_secret, totp_code)
    if not code_ok:
        await rl.record_admin_login_failure(redis, current_user.username)
        return await refuse({"totp_code": "mfa.error.invalid"}, 401)

    required = current_user.must_change_password
    current_user.password_hash = auth_service.hash_password(new_password)
    current_user.must_change_password = False
    await audit_service.log(
        db, current_user, audit_service.AuditAction.AUTH_PASSWORD_CHANGED,
        detail={"required": required},
    )
    await db.commit()
    await rl.reset_admin_login_attempts(redis, current_user.username)
    # Every other session ends: whoever knew the old password may hold one.
    await auth_service.revoke_user_sessions(redis, str(current_user.id), keep=session_token)
    return RedirectResponse(f"/admin/account?password={_PASSWORD_CHANGED}", status_code=303)
