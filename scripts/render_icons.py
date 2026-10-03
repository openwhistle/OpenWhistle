"""Render the K3 rasters: favicon.ico (16+32), favicon-32.png, apple-touch-icon.png,
github-avatar.png.

    uv run python scripts/render_icons.py

An ink mark on a white tile, drawn by Chromium from the one geometry below; tests/test_mark.py
holds every SVG copy of the mark to this path. The app serves byte-identical copies of the
browser icons. github-avatar.png is uploaded by hand to the GitHub organisation, Docker Hub
and quay.io (docs-tech/specs/2026-10-02-website-p2-design.md).
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MARK = (
    "M7,3 H17 A4,4 0 0 1 21,7 V13 A4,4 0 0 1 17,17 H11.5 L7,20.8 V17 A4,4 0 0 1 3,13 V7 "
    "A4,4 0 0 1 7,3 Z M10.60,11.81 A3.5,3.5 0 1 1 13.40,11.81 L14.50,15.4 H9.50 Z"
)
INK = "#0a0a0b"
APP_COPIES = ("favicon.ico", "favicon-32.png", "apple-touch-icon.png")


def _tile(size: int) -> str:
    return (
        f'<html><body style="margin:0"><div style="width:{size}px;height:{size}px;background:#fff;'
        f'display:grid;place-items:center"><svg width="{size}" height="{size}" viewBox="0 0 24 24">'
        f'<path fill-rule="evenodd" fill="{INK}" d="{MARK}"/></svg></div></body></html>'
    )


def render(size: int) -> Image.Image:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(_tile(size))
        png = page.screenshot(clip={"x": 0, "y": 0, "width": size, "height": size})
        browser.close()
    return Image.open(io.BytesIO(png)).convert("RGB")


def main() -> int:
    docs = ROOT / "docs"
    render(180).save(docs / "apple-touch-icon.png", optimize=True)
    render(32).save(docs / "favicon-32.png", optimize=True)
    render(500).save(docs / "github-avatar.png", optimize=True)
    render(32).save(docs / "favicon.ico", sizes=[(16, 16), (32, 32)])
    for name in APP_COPIES:
        shutil.copyfile(docs / name, ROOT / "app" / "static" / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
