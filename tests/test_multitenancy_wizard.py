"""Multi-tenancy: DEFAULT_ORG_SLUG names the default organisation everywhere."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.config import settings
from app.main import app
from app.models.category import ReportCategory
from app.models.location import Location
from app.models.organisation import Organisation
from app.models.user import AdminRole, AdminUser

_CASE_RE = re.compile(r"OW-\d{4}-\d+")
_PIN_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}")
_HTML = {"accept": "text/html"}


@dataclass
class _Org:
    org: Organisation
    category: ReportCategory
    location: Location
    admin: AdminUser

    @property
    def path(self) -> str:
        return f"/submit/{self.org.slug}"


def _csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


def _step(text: str) -> int:
    m = re.search(r'name="step" value="(\d+)"', text)
    return int(m.group(1)) if m else 1


def _org(tag: str) -> _Org:
    hex6 = uuid.uuid4().hex[:6]
    org = Organisation(id=uuid.uuid4(), name=f"Org {tag} {hex6}", slug=f"org-{tag}-{hex6}")
    return _Org(
        org=org,
        category=ReportCategory(
            id=uuid.uuid4(), slug=f"cat_{tag}_{hex6}", label_en=f"Category {tag} {hex6}",
            label_de=f"Kategorie {tag} {hex6}", is_default=False, is_active=True,
            sort_order=1, org_id=org.id,
        ),
        location=Location(
            id=uuid.uuid4(), name=f"Site {tag} {hex6}", code=f"S{tag.upper()}{hex6}",
            is_active=True, sort_order=0, org_id=org.id,
        ),
        admin=AdminUser(
            id=uuid.uuid4(), username=f"mtw_{tag}_{hex6}", role=AdminRole.admin, org_id=org.id,
            is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True,
        ),
    )


@pytest_asyncio.fixture(loop_scope="function")
async def orgs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dict[str, _Org]]:
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    made = {"a": _org("a"), "b": _org("b"), "c": _org("c")}
    made["c"].org.is_active = False
    db_session.add_all(o.org for o in made.values())
    await db_session.flush()
    for o in made.values():
        db_session.add_all([o.category, o.location, o.admin])
    await db_session.commit()
    yield made
    # Other tests run the wizard unscoped: leave nothing of ours in it.
    for o in made.values():
        o.category.is_active = False
        o.location.is_active = False
    await db_session.commit()


# ── DEFAULT_ORG_SLUG names the default organisation everywhere ──────


@pytest.mark.asyncio
async def test_the_configured_default_org_cannot_be_deactivated(
    client: AsyncClient, orgs: dict[str, _Org], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "default_org_slug", orgs["a"].org.slug)
    root = AdminUser(
        id=uuid.uuid4(), username=f"root_{uuid.uuid4().hex[:6]}", role=AdminRole.superadmin,
        is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True,
    )
    csrf = _csrf((await client.get("/submit")).text)
    app.dependency_overrides[get_current_admin] = lambda: root
    try:
        resp = await client.post(
            f"/admin/organisations/{orgs['a'].org.id}/deactivate",
            data={"csrf_token": csrf}, follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_setup_creates_the_configured_default_org(
    throwaway_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.wizard import create_initial_admin

    monkeypatch.setattr(settings, "default_org_slug", "acme")
    assert await create_initial_admin(throwaway_db, "first", "pw-" + "x" * 20, "JBSWY3DPEHPK3PXP")
    admin = (
        await throwaway_db.execute(select(AdminUser).where(AdminUser.username == "first"))
    ).scalar_one()
    org = await throwaway_db.get(Organisation, admin.org_id)
    assert org is not None and org.slug == "acme"
