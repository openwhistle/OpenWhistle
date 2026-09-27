"""An installation gets a superadmin: the account the setup wizard creates,
and on an upgrade the earliest account where none exists yet. Before 2.0.1 the
wizard made a plain admin and only a superadmin may grant superadmin, so no
installation had one and /admin/organisations was unreachable."""

import os
import subprocess
import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import AdminRole, AdminUser
from app.services.mfa import generate_totp_secret, get_totp
from tests.conftest import setup_token


def _alembic(*args: str) -> None:
    run = subprocess.run(  # noqa: S603
        ["alembic", *args], capture_output=True, text=True, check=False,  # noqa: S607
        env={**os.environ, "DATABASE_URL": settings.database_url},
    )
    assert run.returncode == 0, run.stderr


async def _add(
    db: AsyncSession, name: str, role: str, created: str, active: bool = True
) -> uuid.UUID:
    stamp = datetime.fromisoformat(created)
    uid = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO admin_users (id, username, password_hash, totp_secret, totp_enabled, role,"
        " created_at, is_active) VALUES (:i, :u, 'x', 'x', true, :r, :c, :a)"
    ), {"i": uid, "u": name, "r": role, "c": stamp, "a": active})
    return uid


async def _roles(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(text("SELECT username, role::text FROM admin_users"))).all()
    await db.commit()
    return {str(name): str(role) for name, role in rows}


@pytest.mark.asyncio
async def test_migration_008_promotes_the_first_account_where_no_superadmin_exists(
    throwaway_db: AsyncSession,
) -> None:
    _alembic("downgrade", "d4f9b3c7e504")
    await _add(throwaway_db, "later", "admin", "2026-02-01T00:00:00Z")
    await _add(throwaway_db, "wizard", "admin", "2026-01-01T00:00:00Z")
    await _add(throwaway_db, "handler", "case_manager", "2025-12-01T00:00:00Z")
    await _add(throwaway_db, "gone", "admin", "2025-11-01T00:00:00Z", active=False)
    await throwaway_db.commit()

    _alembic("upgrade", "head")

    assert await _roles(throwaway_db) == {
        "wizard": "superadmin", "later": "admin", "handler": "case_manager", "gone": "admin",
    }


@pytest.mark.asyncio
async def test_migration_008_leaves_an_existing_superadmin_alone(
    throwaway_db: AsyncSession,
) -> None:
    _alembic("downgrade", "d4f9b3c7e504")
    await _add(throwaway_db, "first", "admin", "2026-01-01T00:00:00Z")
    await _add(throwaway_db, "owner", "superadmin", "2026-02-01T00:00:00Z")
    await throwaway_db.commit()

    _alembic("upgrade", "head")
    _alembic("downgrade", "d4f9b3c7e504")  # keeps the role: the account needs it
    _alembic("upgrade", "head")

    assert await _roles(throwaway_db) == {"first": "admin", "owner": "superadmin"}


@pytest.mark.asyncio
async def test_the_wizard_creates_a_superadmin(
    throwaway_db: AsyncSession, client: AsyncClient,
) -> None:
    get_resp = await client.get("/setup", follow_redirects=False)
    assert get_resp.status_code == 200
    secret = generate_totp_secret()
    resp = await client.post("/setup", data={
        "username": "owner201", "password": "SecureTestPassword123!",
        "password_confirm": "SecureTestPassword123!", "totp_secret": secret,
        "totp_code": get_totp(secret).now(), "csrf_token": get_resp.cookies.get("ow_csrf"),
        "setup_token": await setup_token(),
    }, follow_redirects=False)
    assert resp.status_code == 302, resp.text
    user = await throwaway_db.scalar(
        select(AdminUser).where(AdminUser.username == "owner201")
        .execution_options(populate_existing=True)
    )
    assert user is not None and user.role == AdminRole.superadmin
