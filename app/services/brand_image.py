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
_FORMATS = {"PNG", "JPEG", "WEBP"}


class BrandImageError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def process_logo(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise BrandImageError("admin.branding.error.too_large")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in _FORMATS:
                raise BrandImageError("admin.branding.error.format")
            # Before any pixel is decoded: the header names the size.
            if source.width * source.height > MAX_PIXELS:
                raise BrandImageError("admin.branding.error.dimensions")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except Image.DecompressionBombError:
        raise BrandImageError("admin.branding.error.dimensions") from None
    except (UnidentifiedImageError, OSError) as exc:
        raise BrandImageError("admin.branding.error.format") from exc
    if image.height > HEIGHT:
        width = max(1, round(image.width * HEIGHT / image.height))
        image = image.resize((width, HEIGHT), Image.Resampling.LANCZOS)
    return _png(image)


def favicon(png: bytes, size: int) -> bytes:
    with Image.open(io.BytesIO(png)) as source:
        logo = source.convert("RGBA")
    logo.thumbnail((size, size), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    return _png(square)
