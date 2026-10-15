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
    sha = await branding.store_image(db_session, b"\x89PNG-logo")
    await _brand(db_session, None, name="Acme", logo_light=sha)
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


async def test_the_dark_logo_swap_needs_no_has_selector(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import re
    from pathlib import Path

    light = await branding.store_image(db_session, b"\x89PNG-light")
    dark = await branding.store_image(db_session, b"\x89PNG-dark")
    await _brand(db_session, None, logo_light=light, logo_dark=dark)
    html = (await client.get("/submit")).text
    light_img = f'<img src="/branding/{light}.png" alt=""'
    assert f'{light_img} class="nav-logo-img nav-logo-light has-dark"' in html
    css = Path("app/static/css/site.css").read_text(encoding="utf-8")
    # A browser without :has() drops a whole rule naming it: both logos showed in light.
    selectors = re.findall(r"(?m)^([^{}\n]*\.nav-logo-[^{}]*)\{", css)
    assert selectors and not [s for s in selectors if ":has(" in s]
    assert re.search(r"(?m)^\.nav-logo-dark \{\s*display: none;", css)
    dark_theme = r'(?m)^\[data-theme="dark"\] \.nav-logo-light\.has-dark \{\s*display: none;'
    assert re.search(dark_theme, css)


@pytest.mark.usefixtures("no_csrf")
async def test_a_validation_error_page_wears_the_stored_branding(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # FastAPI raises RequestValidationError only after the route's dependencies,
    # load_branding among them, have run (the app takes no JSON bodies).
    await _brand(db_session, None, name="Acme Invalid")
    response = await client.post("/set-language", data={})
    assert response.status_code == 422 and "Acme Invalid" in response.text


@pytest.mark.usefixtures("no_csrf")
async def test_a_body_that_never_parses_wears_the_stored_branding(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # FastAPI solves the app's dependencies (load_branding) before it reads a body, so
    # validation_exception_handler needs no load_branding of its own. This pins that order
    # with the earliest error there is, unparseable JSON; the app takes no JSON body today.
    from pydantic import BaseModel

    from app.main import app

    class Probe(BaseModel):
        n: int

    async def probe(body: Probe) -> None:  # pragma: no cover - never reached
        return None

    await _brand(db_session, None, name="Acme Unparsed")
    app.add_api_route("/_branding-probe", probe, methods=["POST"])
    try:
        response = await client.post(
            "/_branding-probe",
            content=b"{",
            headers={"content-type": "application/json", "accept": "text/html"},
        )
    finally:
        app.router.routes.pop()
    assert response.status_code == 422 and "Acme Unparsed" in response.text
