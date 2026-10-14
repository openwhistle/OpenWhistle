"""Pages show the branding of the organisation they serve (spec: Resolution)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.organisation import Organisation
from app.redis_client import get_redis
from app.services import branding

pytestmark = pytest.mark.usefixtures("clean_branding")


async def _brand(db: AsyncSession, org_id: uuid.UUID | None, **fields: str) -> None:
    row = await branding.row_for(db, org_id)
    for key, value in fields.items():
        setattr(row, key, value)
    await db.commit()
    await branding.invalidate(await get_redis())


async def test_the_default_row_names_the_wizard(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _brand(db_session, None, name="Acme Reports")
    html = (await client.get("/submit")).text
    assert '<span translate="no">Acme Reports</span>' in html
    assert "<title>" in html and "Acme Reports</title>" in html


async def test_an_organisations_wizard_wears_its_own(
    client: AsyncClient, db_session: AsyncSession, tenants: None
) -> None:
    mine = Organisation(id=uuid.uuid4(), name="Mine", slug=f"mine-{uuid.uuid4().hex[:6]}")
    other = Organisation(id=uuid.uuid4(), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add_all([mine, other])
    await db_session.commit()
    await _brand(db_session, None, name="Default Brand")
    await _brand(db_session, mine.id, name="Mine Brand", primary_color="#aa3300")
    assert "Mine Brand" in (await client.get(f"/submit/{mine.slug}")).text
    other_html = (await client.get(f"/submit/{other.slug}")).text
    assert "Default Brand" in other_html and "Mine Brand" not in other_html


async def test_a_broken_cache_falls_back_to_the_environment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = await get_redis()
    await redis.set(branding.CACHE_KEY, "not json")
    monkeypatch.setattr(settings, "app_name", "Env Fallback")
    response = await client.get("/submit")
    await branding.invalidate(redis)
    assert response.status_code == 200 and "Env Fallback" in response.text


async def test_the_nav_logo_is_decorative(client: AsyncClient, db_session: AsyncSession) -> None:
    await _brand(db_session, None, name="Acme")
    html_with = (await client.get("/submit")).text
    assert 'alt="' + settings.app_name not in html_with
    sha = await branding.store_image(db_session, b"\x89PNG-logo")
    await _brand(db_session, None, logo_light=sha)
    html = (await client.get("/submit")).text
    assert f'<img src="/branding/{sha}.png" alt="" class="nav-logo-img nav-logo-light"' in html


def test_a_logo_cannot_widen_the_nav() -> None:
    import re
    from pathlib import Path

    css = Path("app/static/css/site.css").read_text(encoding="utf-8")
    rule = re.search(r"(?m)^\.nav-logo-img \{([^}]*)\}", css)
    assert rule and "max-width: min(12rem, 40vw);" in rule.group(1)


async def test_no_page_needs_unsafe_inline(client: AsyncClient, db_session: AsyncSession) -> None:
    await _brand(db_session, None, primary_color="#aa3300")
    response = await client.get("/submit")
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert "--brand-accent:" in response.text


async def test_an_unknown_path_wears_the_stored_branding(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _brand(db_session, None, name="Acme Default")
    response = await client.get("/no-such-page", headers={"accept": "text/html"})
    assert response.status_code == 404 and "Acme Default" in response.text
