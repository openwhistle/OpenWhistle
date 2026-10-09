"""K3 is one geometry, drawn in every place the brand appears (cf. easywall's mark test)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from app.templating import templates

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("render_icons", ROOT / "scripts/render_icons.py")
assert _spec and _spec.loader
icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(icons)

# The website draws the same geometry and compares its copies with the release's
# (openwhistle/website); this repository checks its own.
MARK_FILES = ["app/static/favicon.svg", "app/templates/base.html"]
_PATH = re.compile(r'<path fill-rule="evenodd" d="([^"]+)"')


@pytest.mark.parametrize("rel", MARK_FILES)
def test_every_copy_draws_the_one_geometry(rel: str) -> None:
    found = _PATH.findall((ROOT / rel).read_text(encoding="utf-8"))
    assert found == [icons.MARK], f"{rel}: {found}"


def test_the_old_shield_is_gone_everywhere() -> None:
    for rel in [*MARK_FILES, "app/static/css/site.css"]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "M11 1 L20 5" not in text and "M14 2 L25 6.5" not in text, rel
        assert ".nav-logo svg" not in text and ".footer-logo svg" not in text, rel


async def test_an_operator_logo_replaces_the_mark(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(templates.env.globals["brand"], "logo_url", "/static/operator.png")
    html = (await client.get("/submit")).text
    assert 'class="nav-logo-img"' in html and 'class="mark"' not in html


async def test_without_an_operator_logo_the_nav_draws_k3(client: AsyncClient) -> None:
    html = (await client.get("/submit")).text
    assert 'class="nav-logo-img"' not in html
    assert _PATH.findall(html) == [icons.MARK]


def test_the_app_mark_takes_the_ink() -> None:
    # Without it the path fills black: invisible on the dark nav.
    css = (ROOT / "app/static/css/site.css").read_text(encoding="utf-8")
    rule = re.search(r"\.nav-brand \.mark \{([^}]*)\}", css)
    assert rule and "color: var(--ink);" in rule[1] and "fill: currentColor;" in rule[1]


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


def test_the_head_links_exactly_the_three_icons() -> None:
    # ico first with sizes=32x32: without it Chrome prefers the ico over the theme-aware svg.
    head = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    assert re.findall(r"<link rel=\"[^\"]*icon\"[^>]*>", head) == [
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
    monkeypatch.setitem(templates.env.globals["brand"], "name", "Acme Speak-Up")
    nav = _WORDMARK.search((await client.get("/submit")).text)
    assert nav and '<span translate="no">Acme Speak-Up</span>' in nav[0]
    assert "<strong" not in nav[0]


def test_the_app_wordmark_has_no_accent_rule() -> None:
    css = (ROOT / "app/static/css/site.css").read_text(encoding="utf-8")
    assert ".nav-brand strong" not in css
