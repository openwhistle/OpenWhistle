"""K3 is one geometry, drawn in every place the brand appears (cf. easywall's mark test)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("render_icons", ROOT / "scripts/render_icons.py")
assert _spec and _spec.loader
icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(icons)

# Task 5b extends this list with docs/_includes/nav.html, docs/_includes/footer.html
# and app/templates/base.html.
MARK_FILES = ["docs/favicon.svg", "app/static/favicon.svg"]
_PATH = re.compile(r'<path fill-rule="evenodd" d="([^"]+)"')


@pytest.mark.parametrize("rel", MARK_FILES)
def test_every_copy_draws_the_one_geometry(rel: str) -> None:
    found = _PATH.findall((ROOT / rel).read_text(encoding="utf-8"))
    assert found == [icons.MARK], f"{rel}: {found}"


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
