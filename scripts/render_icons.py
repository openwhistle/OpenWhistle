"""Render the app's K3 rasters: app/static/favicon.ico (16+32) and apple-touch-icon.png.

    uv run python scripts/render_icons.py

An ink mark on a white tile, drawn by Chromium from the one geometry below; tests/test_mark.py
holds every SVG copy of the mark to this path. The website (openwhistle/website) renders its
own copies and compares them with the release's app/static files.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MARK = (
    "M7,3 H17 A4,4 0 0 1 21,7 V13 A4,4 0 0 1 17,17 H11.5 L7,20.8 V17 A4,4 0 0 1 3,13 V7 "
    "A4,4 0 0 1 7,3 Z M10.60,11.81 A3.5,3.5 0 1 1 13.40,11.81 L14.50,15.4 H9.50 Z"
)
INK = "#0a0a0b"


def _tile(size: int) -> str:
    return (
        f'<html><body style="margin:0"><div style="width:{size}px;height:{size}px;background:#fff;'
        f'display:grid;place-items:center"><svg width="{size}" height="{size}" viewBox="0 0 24 24">'
        f'<path fill-rule="evenodd" fill="{INK}" d="{MARK}"/></svg></div></body></html>'
    )


def render(sizes: tuple[int, ...]) -> dict[int, Image.Image]:
    from playwright.sync_api import sync_playwright  # CI's test job has no Playwright

    out: dict[int, Image.Image] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in sizes:
            page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
            page.set_content(_tile(size))
            png = page.screenshot(clip={"x": 0, "y": 0, "width": size, "height": size})
            out[size] = Image.open(io.BytesIO(png)).convert("RGB")
        browser.close()
    return out


def main() -> int:
    static = ROOT / "app" / "static"
    img = render((32, 180))
    img[180].save(static / "apple-touch-icon.png", optimize=True)
    img[32].save(static / "favicon.ico", sizes=[(16, 16), (32, 32)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
