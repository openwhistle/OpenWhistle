"""/admin/branding: who may brand what, and what a save does (spec: Permissions and audit)."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.branding import Branding
from app.models.organisation import Organisation
from app.models.user import AdminRole
from app.services import branding
from tests.test_v210_bug_bounty import _totp_user

pytestmark = pytest.mark.usefixtures("clean_branding")


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 150), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


async def _post(client: Any, data: dict[str, str], files: dict[str, Any] | None = None) -> Any:
    return await client.post(
        "/admin/branding",
        data={"csrf_token": "x", **data},
        files=files or {},
        follow_redirects=False,
    )


async def test_a_case_manager_may_not_open_it(acting_as: Any, db_session: AsyncSession) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.case_manager))
    assert (await client.get("/admin/branding")).status_code == 403


async def test_an_admin_saves_name_colour_and_logo(
    acting_as: Any, db_session: AsyncSession
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    response = await _post(
        client,
        {"name": "Acme", "primary_color": "#AA3300"},
        {"logo_light": ("logo.png", _png(), "image/png")},
    )
    assert response.status_code == 303
    row = await branding.row_for(db_session, None)
    await db_session.refresh(row)
    assert (row.name, row.primary_color) == ("Acme", "#aa3300")
    assert row.logo_light and row.favicon_32 and row.favicon_180
    entry = await db_session.scalar(select(AuditLog).where(AuditLog.action == "branding.updated"))
    assert entry and "name" in (entry.detail or "") and "logo_light" in (entry.detail or "")


@pytest.mark.parametrize(
    ("data", "files"),
    [
        ({"primary_color": "red"}, None),
        ({"name": "x" * 65}, None),
        ({}, {"logo_light": ("logo.svg", b"<svg/>", "image/svg+xml")}),
    ],
)
async def test_invalid_input_saves_nothing(
    acting_as: Any, db_session: AsyncSession, data: dict[str, str], files: Any
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    response = await _post(client, data, files)
    assert response.status_code == 422
    row = await db_session.scalar(select(Branding).where(Branding.org_id.is_(None)))
    assert row is None


async def test_reset_clears_one_field_and_the_cache_follows(
    acting_as: Any, db_session: AsyncSession
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    await _post(client, {"name": "Zzyzx"})
    assert "Zzyzx" in (await client.get("/submit")).text
    response = await client.post(
        "/admin/branding/reset", data={"csrf_token": "x", "field": "name"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "Zzyzx" not in (await client.get("/submit")).text


async def test_an_org_admin_cannot_brand_another_org(
    acting_as: Any, db_session: AsyncSession, tenants: None
) -> None:
    mine = Organisation(id=uuid.uuid4(), name="Mine", slug=f"m-{uuid.uuid4().hex[:6]}")
    other = Organisation(id=uuid.uuid4(), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}")
    db_session.add_all([mine, other])
    await db_session.commit()
    user = await _totp_user(db_session, AdminRole.admin)
    user.org_id = mine.id
    await db_session.commit()
    client, act = acting_as
    act(user)
    assert (await _post(client, {"name": "Hijack", "org": str(other.id)})).status_code == 403
    assert (await client.get(f"/admin/branding?org={other.id}")).status_code == 403
    assert (await _post(client, {"name": "Mine Brand"})).status_code == 303
    own = await branding.row_for(db_session, mine.id)
    await db_session.refresh(own)
    assert own.name == "Mine Brand"
