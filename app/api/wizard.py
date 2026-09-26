"""First-run setup wizard: creates the initial admin account."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.models.setup import SetupStatus
from app.models.telemetry import TelemetryState
from app.models.user import AdminUser
from app.redis_client import get_redis
from app.services import rate_limit as rl
from app.services.auth import hash_password, validate_password
from app.services.mfa import generate_qr_code_base64, generate_totp_secret, verify_totp
from app.services.setup_token import check_setup_token, delete_setup_token, ensure_setup_token
from app.services.telemetry import new_installation_id
from app.services.users import validate_username
from app.templating import render

router = APIRouter()

# pg_advisory_xact_lock key serialising setup completion across requests and
# replicas. Arbitrary, but must not collide with other advisory lock users.
SETUP_LOCK_KEY = 0x4F57_0001


async def _is_setup_complete(db: AsyncSession) -> bool:
    # populate_existing: a re-check inside the same session must see the row
    # as it is now, not the copy the identity map loaded before the lock.
    result = await db.execute(
        select(SetupStatus)
        .where(SetupStatus.id == 1)
        .execution_options(populate_existing=True)
    )
    setup = result.scalar_one_or_none()
    return setup is not None and setup.completed


async def create_initial_admin(
    db: AsyncSession, username: str, password: str, totp_secret: str, telemetry: bool = False
) -> bool:
    """Create the first admin and mark setup complete, atomically.

    Returns False, creating nothing, when setup is already complete. The
    "already complete?" check and the insert run under a transaction-scoped
    advisory lock (released by the commit or rollback), so two concurrent
    submissions cannot both create an admin.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK_KEY})
    if await _is_setup_complete(db):
        await db.rollback()
        return False

    # The migration seeds "default"; DEFAULT_ORG_SLUG may name another one.
    from app.models.organisation import Organisation

    org_result = await db.execute(
        select(Organisation).where(Organisation.slug == settings.default_org_slug)
    )
    default_org = org_result.scalar_one_or_none()
    if default_org is None:
        default_org = Organisation(
            id=uuid.uuid4(), name="Default Organisation", slug=settings.default_org_slug
        )
        db.add(default_org)
        await db.flush()

    admin = AdminUser(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(password),
        totp_secret=totp_secret,
        totp_enabled=True,
        org_id=default_org.id,
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

    # The installation-count answer; unchecked by default in the form.
    state = await db.get(TelemetryState, 1)
    if state is None:
        db.add(TelemetryState(id=1, enabled=telemetry, installation_id=new_installation_id()))
    else:
        state.enabled = telemetry

    await db.commit()
    return True


@router.get("/setup", response_class=HTMLResponse, response_model=None)
async def setup_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> HTMLResponse | RedirectResponse:
    if await _is_setup_complete(db):
        return RedirectResponse("/admin/login", status_code=302)

    await ensure_setup_token(redis)

    totp_secret = generate_totp_secret()
    qr_code = generate_qr_code_base64(totp_secret, "admin")

    return render(
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
    username: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    totp_secret: str = Form(...),
    totp_code: str = Form(""),
    setup_token: str = Form(""),
    telemetry: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    if await _is_setup_complete(db):
        return RedirectResponse("/admin/login", status_code=302)

    locked = await rl.setup_token_locked(redis)
    if locked or not await check_setup_token(redis, setup_token.strip()):
        if not locked:
            await rl.record_setup_token_failure(redis)
        error = "wizard.error.setup_token_locked" if locked else "wizard.error.setup_token"
        return render(
            request,
            "wizard/setup.html",
            {
                "totp_secret": totp_secret,
                "qr_code": generate_qr_code_base64(totp_secret, username or "admin"),
                "field_errors": {"setup_token": error},
                "username": username,
                "telemetry": telemetry == "1",
            },
            status_code=429 if locked else 403,
        )
    await rl.reset_setup_token_failures(redis)

    # field -> locale key; each shows next to its field and in the summary banner.
    errors: dict[str, str] = {}

    try:
        username = validate_username(username)
    except ValueError:
        errors["username"] = "wizard.error.username"

    try:
        validate_password(password)
    except ValueError:
        errors["password"] = "wizard.error.password"  # noqa: S105 — locale key

    if password != password_confirm:
        errors["password_confirm"] = "wizard.error.password_confirm"  # noqa: S105

    if not verify_totp(totp_secret, totp_code):
        errors["totp_code"] = "wizard.error.totp_code"

    if errors:
        qr_code = generate_qr_code_base64(totp_secret, username)
        return render(
            request,
            "wizard/setup.html",
            {
                "totp_secret": totp_secret,
                "qr_code": qr_code,
                "field_errors": errors,
                "username": username,
                "telemetry": telemetry == "1",
            },
        )

    # A concurrent submission that won the race makes this a no-op; either
    # way the only thing left to do is log in.
    if await create_initial_admin(
        db, username, password, totp_secret, telemetry=telemetry == "1"
    ):
        await delete_setup_token(redis)
    return RedirectResponse("/admin/login", status_code=302)
