"""What every rendered diagram must hold: text fits its shape, and no text touches a line."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = {
    400: ROOT / "docs" / "fonts" / "sora-latin-400-normal.woff2",
    700: ROOT / "docs" / "fonts" / "sora-latin-700-normal.woff2",
}


@cache
def font(weight: int) -> TTFont:
    return TTFont(FONTS[weight])


def missing_glyphs(text: str, weight: int) -> list[str]:
    cmap = font(weight).getBestCmap()
    return sorted({ch for ch in text if ord(ch) not in cmap})
