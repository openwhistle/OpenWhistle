"""Operator logos: the content decides the type, Pillow re-encodes, nothing but pixels survives.

OWASP File Upload Cheat Sheet: allow-list the types, check the content not the
name, re-encode, drop metadata, bound the size. No SVG: a direct request runs
its scripts (GlobaLeaks, SecureDrop and Hush Line accept none either).
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 1_000_000
MAX_PIXELS = 16_000_000
HEIGHT = 96  # the nav shows 32 px; three times that for dense screens
WIDTH = HEIGHT * 16  # the nav caps a logo at 12rem; a 16000 x 1 strip stays bounded
# Pillow tries only these parsers: a file that is anything else is never parsed as it.
_FORMATS = ("PNG", "JPEG", "WEBP")


class BrandImageError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.info.clear()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    """The upload's pixels at full size, or BrandImageError naming why not."""
    if len(data) > MAX_BYTES:
        raise BrandImageError("admin.branding.error.too_large")
    try:
        with Image.open(io.BytesIO(data), formats=_FORMATS) as source:
            # Before any pixel is decoded: the header names the size.
            if source.width * source.height > MAX_PIXELS:
                raise BrandImageError("admin.branding.error.dimensions")
            return ImageOps.exif_transpose(source).convert("RGBA")
    except BrandImageError:
        raise
    except Image.DecompressionBombError:
        raise BrandImageError("admin.branding.error.dimensions") from None
    # A broken file surfaces as any of these, some only while the pixels decode.
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise BrandImageError("admin.branding.error.format") from exc


def logo(image: Image.Image) -> bytes:
    """The nav logo: at most HEIGHT high and WIDTH wide, never upscaled."""
    scaled = image.copy()
    scaled.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    return _png(scaled)


def favicon(image: Image.Image, size: int) -> bytes:
    """The logo letterboxed onto a transparent square, drawn from the full-size image."""
    scaled = image.copy()
    scaled.thumbnail((size, size), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return _png(square)
