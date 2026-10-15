"""K3 is one geometry, drawn in every place the brand appears (cf. easywall's mark test)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("render_icons", ROOT / "scripts/render_icons.py")
assert _spec and _spec.loader
icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(icons)

# The website draws the same geometry and compares its copies with the release's
# (openwhistle/website); this repository checks its own.
MARK_FILES = ["app/static/favicon.svg", "app/templates/base.html"]
# base.html draws it twice, in the nav and in the footer, as the website does.
MARK_COPIES = {"app/static/favicon.svg": 1, "app/templates/base.html": 2}
_PATH = re.compile(r'<path fill-rule="evenodd" d="([^"]+)"')


@pytest.mark.parametrize("rel", MARK_FILES)
def test_every_copy_draws_the_one_geometry(rel: str) -> None:
    found = _PATH.findall((ROOT / rel).read_text(encoding="utf-8"))
    assert found == [icons.MARK] * MARK_COPIES[rel], f"{rel}: {found}"


def test_the_old_shield_is_gone_everywhere() -> None:
    for rel in [*MARK_FILES, "app/static/css/site.css"]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "M11 1 L20 5" not in text and "M14 2 L25 6.5" not in text, rel
        assert ".nav-logo svg" not in text and ".footer-logo svg" not in text, rel


async def test_an_operator_logo_replaces_the_mark(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "brand_logo_url", "/static/operator.png")
    html = (await client.get("/submit")).text
    assert 'class="nav-logo-img nav-logo-light"' in html and 'class="mark"' not in html


async def test_without_an_operator_logo_the_nav_draws_k3(client: AsyncClient) -> None:
    html = (await client.get("/submit")).text
    assert "nav-logo-img" not in html
    assert _PATH.findall(html) == [icons.MARK] * 2  # nav and footer


def test_the_app_mark_takes_the_ink() -> None:
    # Without it the path fills black: invisible on the dark nav.
    css = (ROOT / "app/static/css/site.css").read_text(encoding="utf-8")
    mark = re.search(r"^\.mark \{([^}]*)\}", css, re.M)
    brand = re.search(r"^\.nav-brand \{([^}]*)\}", css, re.M)
    assert mark and "fill: currentColor;" in mark[1]
    assert brand and "color: var(--ink);" in brand[1]


def test_the_favicon_switches_ink_with_the_colour_scheme() -> None:
    svg = (ROOT / "app/static/favicon.svg").read_text(encoding="utf-8")
    assert re.search(r"path\s*\{\s*fill:\s*#0a0a0b", svg)
    dark = r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*path\s*\{\s*fill:\s*#fafafa"
    assert re.search(dark, svg)


def test_the_touch_icon_has_its_size_and_shows_an_ink_mark_on_white() -> None:
    size = (180, 180)
    with Image.open(ROOT / "app/static/apple-touch-icon.png") as img:
        rgb = img.convert("RGB")
        assert rgb.size == size
        assert rgb.getpixel((0, 0)) == (255, 255, 255)
        # Left of the keyhole, inside the bubble: ink. The centre column is the keyhole (white).
        assert sum(rgb.getpixel((size[0] // 5, size[1] * 7 // 20))) < 200, (
            "bubble body should be ink"
        )
        assert rgb.getpixel((size[0] // 2, size[1] * 5 // 12)) == (255, 255, 255), "keyhole is open"


def test_the_ico_holds_16_and_32() -> None:
    with Image.open(ROOT / "app/static/favicon.ico") as ico:
        assert set(ico.info["sizes"]) == {(16, 16), (32, 32)}


def test_the_head_links_the_operators_two_favicons_or_the_three_default_icons() -> None:
    # ico first with sizes=32x32: without it Chrome prefers the ico over the theme-aware svg.
    head = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    # The first two are the operator's favicons, shown instead of the other three.
    assert re.findall(r"<link rel=\"[^\"]*icon\"[^>]*>", head) == [
        '<link rel="icon" href="{{ brand.favicon_32_url }}" sizes="32x32" type="image/png">',
        '<link rel="apple-touch-icon" href="{{ brand.favicon_180_url }}">',
        '<link rel="icon" href="/static/favicon.ico" sizes="32x32">',
        '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">',
        '<link rel="apple-touch-icon" href="/static/apple-touch-icon.png" sizes="180x180">',
    ]


_WORDMARK = re.compile(r'<a href="/" class="nav-brand".*?</a>', re.S)


async def test_the_app_wordmark_is_one_ink_weight_and_untranslated(client: AsyncClient) -> None:
    nav = _WORDMARK.search((await client.get("/submit")).text)
    assert nav
    assert '<span translate="no">OpenWhistle</span>' in nav[0]
    assert "<strong" not in nav[0]


async def test_a_custom_brand_name_is_the_wordmark(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_name", "Acme Speak-Up")
    nav = _WORDMARK.search((await client.get("/submit")).text)
    assert nav and '<span translate="no">Acme Speak-Up</span>' in nav[0]
    assert "<strong" not in nav[0]


def test_the_app_wordmark_has_no_accent_rule() -> None:
    css = (ROOT / "app/static/css/site.css").read_text(encoding="utf-8")
    assert ".nav-brand strong" not in css


@pytest.mark.usefixtures("clean_branding")
async def test_a_stored_favicon_replaces_the_default_icons(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services import branding

    row = await branding.row_for(db_session, None)
    row.logo_light = await branding.store_image(db_session, b"\x89PNG-logo")
    row.favicon_32 = await branding.store_image(db_session, b"\x89PNG-32")
    row.favicon_180 = await branding.store_image(db_session, b"\x89PNG-180")
    await db_session.commit()
    await branding.invalidate(await get_redis())
    icons = re.findall(r'<link rel="[^"]*icon" href="([^"]+)"', (await client.get("/submit")).text)
    assert icons == [f"/branding/{row.favicon_32}.png", f"/branding/{row.favicon_180}.png"]
