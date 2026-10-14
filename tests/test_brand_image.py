"""The logo pipeline: content-checked, re-encoded, stripped, bounded (spec: Logo pipeline)."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.services import brand_image as bi


def _image(fmt: str, size: tuple[int, int] = (400, 200), **save: object) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (12, 114, 83)).save(out, format=fmt, **save)
    return out.getvalue()


def _png_claiming(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + crc

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_each_allowed_format_becomes_a_png_96_px_high(fmt: str) -> None:
    out = Image.open(io.BytesIO(bi.process_logo(_image(fmt))))
    assert out.format == "PNG" and out.height == 96 and out.width == 192


def test_a_small_logo_is_not_upscaled() -> None:
    out = Image.open(io.BytesIO(bi.process_logo(_image("PNG", (60, 30)))))
    assert out.size == (60, 30)


def test_metadata_does_not_survive() -> None:
    info = PngInfo()
    info.add_text("Author", "secret-author")
    exif = Image.Exif()
    exif[0x010E] = "secret-description"
    png = bi.process_logo(_image("PNG", pnginfo=info))
    jpg = bi.process_logo(_image("JPEG", exif=exif.tobytes()))
    for out in (png, jpg):
        assert b"secret" not in out
        assert not Image.open(io.BytesIO(out)).info.get("exif")


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "admin.branding.error.format"),
        (b"<html><script>alert(1)</script></html>", "admin.branding.error.format"),
        (_image("GIF"), "admin.branding.error.format"),
        (b"\x89PNG" + b"\0" * (bi.MAX_BYTES + 1), "admin.branding.error.too_large"),
        (_png_claiming(20_000, 20_000), "admin.branding.error.dimensions"),
    ],
)
def test_refused_uploads(data: bytes, key: str) -> None:
    with pytest.raises(bi.BrandImageError) as caught:
        bi.process_logo(data)
    assert caught.value.key == key


@pytest.mark.parametrize("size", [32, 180])
def test_a_favicon_is_square(size: int) -> None:
    out = Image.open(io.BytesIO(bi.favicon(bi.process_logo(_image("PNG")), size)))
    assert out.size == (size, size) and out.format == "PNG"
