"""/admin/branding: who may brand what, and what a save does (spec: Permissions and audit)."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit import AuditLog
from app.models.branding import BrandImage, Branding
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
    assert response.status_code == 422 and 'id="branding-error"' in response.text
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


async def _admin(
    acting_as: Any, db_session: AsyncSession, role: AdminRole = AdminRole.admin
) -> Any:
    client, act = acting_as
    act(await _totp_user(db_session, role))
    return client


async def _row(db_session: AsyncSession) -> Branding:
    row = await branding.row_for(db_session, None)
    await db_session.refresh(row)
    return row


async def test_a_bad_dark_logo_stores_neither_logo(
    acting_as: Any, db_session: AsyncSession
) -> None:
    client = await _admin(acting_as, db_session)
    files = {
        "logo_light": ("logo.png", _png(), "image/png"),
        "logo_dark": ("dark.svg", b"<svg/>", "image/svg+xml"),
    }
    assert (await _post(client, {}, files)).status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(BrandImage)) == 0


@pytest.mark.parametrize(
    ("how", "data"),
    [
        ("reset", {"field": "logo_light"}),
        ("remove", {"remove_logo_light": "1"}),
    ],
)
async def test_dropping_the_light_logo_drops_the_favicons(
    acting_as: Any, db_session: AsyncSession, how: str, data: dict[str, str]
) -> None:
    client = await _admin(acting_as, db_session)
    await _post(client, {}, {"logo_light": ("logo.png", _png(), "image/png")})
    assert (await _row(db_session)).favicon_32
    url = "/admin/branding/reset" if how == "reset" else "/admin/branding"
    response = await client.post(url, data={"csrf_token": "x", **data}, follow_redirects=False)
    assert response.status_code == 303
    row = await _row(db_session)
    assert (row.logo_light, row.favicon_32, row.favicon_180) == (None, None, None)
    assert await db_session.scalar(select(func.count()).select_from(BrandImage)) == 0


async def test_a_logo_over_one_megabyte_is_refused_on_the_page(
    acting_as: Any, db_session: AsyncSession
) -> None:
    client = await _admin(acting_as, db_session)
    big = ("big.png", b"\x89PNG" + b"\0" * 1_000_001, "image/png")
    response = await _post(client, {}, {"logo_light": big})
    assert response.status_code == 422 and "The image is over 1 MB." in response.text


async def test_an_organisation_needs_multi_tenancy(
    acting_as: Any, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "multi_tenancy_enabled", False)
    client = await _admin(acting_as, db_session, AdminRole.superadmin)
    org = str(uuid.uuid4())
    assert (await client.get(f"/admin/branding?org={org}")).status_code == 404
    assert (await _post(client, {"name": "Lost", "org": org})).status_code == 404
    assert await db_session.scalar(select(Branding)) is None


async def test_a_superadmin_picks_an_organisation(
    acting_as: Any, db_session: AsyncSession, tenants: None
) -> None:
    org = Organisation(id=uuid.uuid4(), name="Picked Org", slug=f"p-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.commit()
    client = await _admin(acting_as, db_session, AdminRole.superadmin)
    page = (await client.get("/admin/branding")).text
    assert f'<option value="{org.id}">Picked Org</option>' in page
    assert (await client.get(f"/admin/branding?org={uuid.uuid4()}")).status_code == 404
    assert (await client.get("/admin/branding?org=not-a-uuid")).status_code == 404
    assert (await _post(client, {"name": "Org Brand", "org": str(org.id)})).status_code == 303
    own = await branding.row_for(db_session, org.id)
    await db_session.refresh(own)
    assert own.name == "Org Brand"


async def test_the_dark_preview_keeps_a_stored_dark_logo(
    acting_as: Any, db_session: AsyncSession
) -> None:
    # branding.js leaves a preview marked data-own-dark alone when a new light logo is picked.
    client = await _admin(acting_as, db_session)
    page = (await client.get("/admin/branding")).text
    assert "data-own-dark" not in page
    await _post(client, {}, {"logo_dark": ("dark.png", _png(), "image/png")})
    page = (await client.get("/admin/branding")).text
    assert 'data-preview-img="dark"' in page and 'data-own-dark="1"' in page


async def test_one_full_size_image_lives_at_a_time(
    acting_as: Any, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import brand_image

    client = await _admin(acting_as, db_session)
    events: list[str] = []
    for name in ("decode", "favicon", "logo"):
        real = getattr(brand_image, name)

        def spy(*args: Any, _real: Any = real, _name: str = name) -> Any:
            events.append(_name)
            return _real(*args)

        monkeypatch.setattr(brand_image, name, spy)
    files = {
        "logo_light": ("l.png", _png(), "image/png"),
        "logo_dark": ("d.png", _png(), "image/png"),
    }
    assert (await _post(client, {}, files)).status_code == 303
    assert events == ["decode", "favicon", "favicon", "logo", "decode", "logo"]
