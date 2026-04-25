"""Generate favicon assets for OpenWhistle.

Produces:
  app/static/favicon.svg          — scalable (primary, modern browsers)
  app/static/favicon.ico          — 16×16 + 32×32 multi-res (legacy/tab fallback)
  app/static/apple-touch-icon.png — 180×180 (iOS home screen)
  docs/favicon.svg                — same SVG for the docs site
  docs/apple-touch-icon.png       — same PNG for the docs site

Design: brand-blue shield (#0f4c81) with a white sound-wave polyline
matching the nav logo in base.html (viewBox 0 0 28 33).
"""

import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

# ─── paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
APP_STATIC = ROOT / "app" / "static"
DOCS = ROOT / "docs"

# ─── SVG source ───────────────────────────────────────────────────────────────

SVG_CONTENT = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 33" width="32" height="32">
  <!-- Shield -->
  <path d="M14 2L25 6.5L25 16.5C25 22.5 20.5 27.5 14 30C7.5 27.5 3 22.5 3 16.5L3 6.5Z"
        fill="#0f4c81" stroke="#1a6aaa" stroke-width="0.8" stroke-linejoin="round"/>
  <!-- Sound-wave / W mark -->
  <polyline points="5.5,14 8.5,21 14,15 19.5,21 22.5,14"
            stroke="white" stroke-width="2.1"
            stroke-linecap="round" stroke-linejoin="round" fill="none"/>
</svg>
"""

# ─── helpers ──────────────────────────────────────────────────────────────────

BLUE  = (15, 76, 129)        # #0f4c81
BLUE2 = (26, 106, 170)       # #1a6aaa  (border)
WHITE = (255, 255, 255, 255)
TRANS = (0, 0, 0, 0)


def _shield_polygon(size: int) -> list[tuple[float, float]]:
    """Return shield polygon scaled to a square canvas of `size` pixels.

    ViewBox: 0 0 28 33. We fit the shield (x: 3–25, y: 2–30) centered in the
    canvas with a small margin.
    """
    margin = size * 0.06
    sx = (size - 2 * margin) / 22   # 22 = 25 - 3 (x span)
    sy = (size - 2 * margin) / 28   # 28 = 30 - 2 (y span)
    s = min(sx, sy)
    # Center offset
    ox = (size - 22 * s) / 2
    oy = (size - 28 * s) / 2

    def pt(x: float, y: float) -> tuple[float, float]:
        return (ox + (x - 3) * s, oy + (y - 2) * s)

    # Approximate bezier shield with straight lines; good enough at favicon size
    pts = [
        pt(14, 2),   # top center
        pt(25, 6.5), # top-right
        pt(25, 16.5),# mid-right
    ]
    # Right curve (25,16.5) → (20.5,27.5) → (14,30): approximate with 4 steps
    for t in [0.25, 0.5, 0.75, 1.0]:
        # Quadratic bezier: B(t) = (1-t)^2 * P0 + 2*(1-t)*t * P1 + t^2 * P2
        p0x, p0y = 25, 16.5
        p1x, p1y = 25, 27.5   # control point
        p2x, p2y = 20.5, 27.5
        x = (1 - t)**2 * p0x + 2 * (1 - t) * t * p1x + t**2 * p2x
        y = (1 - t)**2 * p0y + 2 * (1 - t) * t * p1y + t**2 * p2y
        pts.append(pt(x, y))
    pts.append(pt(14, 30))
    # Left curve mirror
    for t in [0.25, 0.5, 0.75, 1.0]:
        p0x, p0y = 14, 30
        p1x, p1y = 3, 27.5
        p2x, p2y = 3, 27.5
        x = (1 - t)**2 * p0x + 2 * (1 - t) * t * p1x + t**2 * p2x
        y = (1 - t)**2 * p0y + 2 * (1 - t) * t * p1y + t**2 * p2y
        pts.append(pt(x, y))
    pts.append(pt(3, 16.5))
    pts.append(pt(3, 6.5))
    return pts


def _wave_points(size: int) -> list[tuple[float, float]]:
    """Scale the wave polyline to the canvas."""
    margin = size * 0.06
    sx = (size - 2 * margin) / 22
    sy = (size - 2 * margin) / 28
    s = min(sx, sy)
    ox = (size - 22 * s) / 2
    oy = (size - 28 * s) / 2

    raw = [(5.5, 14), (8.5, 21), (14, 15), (19.5, 21), (22.5, 14)]
    return [(ox + (x - 3) * s, oy + (y - 2) * s) for x, y in raw]


def _draw_favicon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), TRANS)
    draw = ImageDraw.Draw(img)

    shield = _shield_polygon(size)
    draw.polygon(shield, fill=(*BLUE, 255), outline=(*BLUE2, 255))

    wave = _wave_points(size)
    lw = max(1, round(size * 0.065))
    draw.line(wave, fill=WHITE, width=lw, joint="curve")

    # Round dots at each wave vertex for the "linecap=round" effect
    r = lw / 2
    for x, y in wave:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=WHITE)

    return img


def _make_ico(sizes: list[int]) -> bytes:
    """Pack multiple RGBA PNGs into an ICO file."""
    images = []
    for s in sizes:
        img = _draw_favicon(s)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        images.append(buf.getvalue())

    # ICO header: ICONDIR
    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type=1, count
    offset = 6 + 16 * len(images)
    entries = b""
    for i, data in enumerate(images):
        s = sizes[i]
        w = 0 if s == 256 else s   # 0 = 256 in ICO spec
        h = 0 if s == 256 else s
        entries += struct.pack(
            "<BBBBHHII",
            w, h,     # width, height
            0, 0,     # color count, reserved
            1, 32,    # color planes, bits per pixel
            len(data),
            offset,
        )
        offset += len(data)

    return header + entries + b"".join(images)


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # favicon.svg
    for dest in [APP_STATIC / "favicon.svg", DOCS / "favicon.svg"]:
        dest.write_text(SVG_CONTENT, encoding="utf-8")
        print(f"  wrote {dest.relative_to(ROOT)}")

    # favicon.ico (16 + 32)
    ico_bytes = _make_ico([16, 32])
    ico_path = APP_STATIC / "favicon.ico"
    ico_path.write_bytes(ico_bytes)
    print(f"  wrote {ico_path.relative_to(ROOT)} ({len(ico_bytes)} bytes)")

    # apple-touch-icon.png (180×180)
    for dest in [APP_STATIC / "apple-touch-icon.png", DOCS / "apple-touch-icon.png"]:
        img = _draw_favicon(180)
        # Apple touch icon needs solid background (iOS masks it with a squircle)
        bg = Image.new("RGBA", (180, 180), (*BLUE, 255))
        bg.paste(img, mask=img)
        bg.convert("RGB").save(str(dest), "PNG")
        print(f"  wrote {dest.relative_to(ROOT)}")

    # favicon-32.png (for docs og consistency; optional but useful)
    img32 = _draw_favicon(32)
    p32 = APP_STATIC / "favicon-32.png"
    img32.save(str(p32), "PNG")
    print(f"  wrote {p32.relative_to(ROOT)}")

    print("Done.")


if __name__ == "__main__":
    main()
