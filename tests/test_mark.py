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

MARK_FILES = [
    "docs/favicon.svg",
    "app/static/favicon.svg",
    "docs/_includes/nav.html",
    "docs/_includes/footer.html",
    "app/templates/base.html",
]
_PATH = re.compile(r'<path fill-rule="evenodd" d="([^"]+)"')


@pytest.mark.parametrize("rel", MARK_FILES)
def test_every_copy_draws_the_one_geometry(rel: str) -> None:
    found = _PATH.findall((ROOT / rel).read_text(encoding="utf-8"))
    assert found == [icons.MARK], f"{rel}: {found}"


def test_the_old_shield_is_gone_everywhere() -> None:
    for rel in [*MARK_FILES, "docs/assets/css/base.css", "app/static/css/site.css"]:
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
    # Without it the path fills black: invisible on the dark nav. The site's rule is checked
    # in a browser (tests/e2e/test_site_look.py); the app has no docs-server e2e.
    css = (ROOT / "app/static/css/site.css").read_text(encoding="utf-8")
    rule = re.search(r"\.nav-brand \.mark \{([^}]*)\}", css)
    assert rule and "color: var(--ink);" in rule[1] and "fill: currentColor;" in rule[1]


def test_both_favicons_are_the_same_file() -> None:
    docs, app = ROOT / "docs/favicon.svg", ROOT / "app/static/favicon.svg"
    assert docs.read_bytes() == app.read_bytes()


def test_the_favicon_switches_ink_with_the_colour_scheme() -> None:
    svg = (ROOT / "docs/favicon.svg").read_text(encoding="utf-8")
    assert re.search(r"path\s*\{\s*fill:\s*#0a0a0b", svg)
    dark = r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*path\s*\{\s*fill:\s*#fafafa"
    assert re.search(dark, svg)


@pytest.mark.parametrize(
    "rel,size",
    [
        ("docs/apple-touch-icon.png", (180, 180)),
        ("docs/github-avatar.png", (500, 500)),
    ],
)
def test_rasters_have_their_size_and_show_an_ink_mark_on_white(
    rel: str, size: tuple[int, int]
) -> None:
    with Image.open(ROOT / rel) as img:
        rgb = img.convert("RGB")
        assert rgb.size == size
        assert rgb.getpixel((0, 0)) == (255, 255, 255)
        # Left of the keyhole, inside the bubble: ink. The centre column is the keyhole (white).
        assert sum(rgb.getpixel((size[0] // 5, size[1] * 7 // 20))) < 200, (
            "bubble body should be ink"
        )
        assert rgb.getpixel((size[0] // 2, size[1] * 5 // 12)) == (255, 255, 255), "keyhole is open"


def test_the_ico_holds_16_and_32() -> None:
    with Image.open(ROOT / "docs/favicon.ico") as ico:
        assert set(ico.info["sizes"]) == {(16, 16), (32, 32)}


@pytest.mark.parametrize("name", ["favicon.ico", "apple-touch-icon.png"])
def test_the_app_serves_the_same_rasters(name: str) -> None:
    assert (ROOT / "app/static" / name).read_bytes() == (ROOT / "docs" / name).read_bytes()


def test_both_heads_link_exactly_the_three_icons() -> None:
    # ico first with sizes=32x32: without it Chrome prefers the ico over the theme-aware svg.
    for rel, prefix in [("docs/_includes/head.html", "/"), ("app/templates/base.html", "/static/")]:
        links = re.findall(
            r"<link rel=\"[^\"]*icon\"[^>]*>", (ROOT / rel).read_text(encoding="utf-8")
        )
        assert links == [
            f'<link rel="icon" href="{prefix}favicon.ico" sizes="32x32">',
            f'<link rel="icon" href="{prefix}favicon.svg" type="image/svg+xml">',
            f'<link rel="apple-touch-icon" href="{prefix}apple-touch-icon.png" sizes="180x180">',
        ], rel


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
