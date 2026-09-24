"""First-run setup wizard: creates the initial admin account."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.csrf import validate_csrf
from app.database import get_db
from app.models.setup import SetupStatus
from app.models.user import AdminUser
from app.services.auth import hash_password, validate_password
from app.services.mfa import generate_qr_code_base64, generate_totp_secret, verify_totp
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
    db: AsyncSession, username: str, password: str, totp_secret: str
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

    # Ensure the default organisation exists (created by migration 012, but guard here)
    from app.models.organisation import Organisation

    org_result = await db.execute(
        select(Organisation).where(Organisation.slug == "default")
    )
    default_org = org_result.scalar_one_or_none()
    if default_org is None:
        default_org = Organisation(
            id=uuid.uuid4(), name="Default Organisation", slug="default"
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

    await db.commit()
    return True


@router.get("/setup", response_class=HTMLResponse, response_model=None)
async def setup_get(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse | RedirectResponse:
    if await _is_setup_complete(db):
        return RedirectResponse("/admin/login", status_code=302)

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
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    if await _is_setup_complete(db):
        return RedirectResponse("/admin/login", status_code=302)

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
            },
        )

    # A concurrent submission that won the race makes this a no-op; either
    # way the only thing left to do is log in.
    await create_initial_admin(db, username, password, totp_secret)
    return RedirectResponse("/admin/login", status_code=302)
