"""The logo pipeline: content-checked, re-encoded, stripped, bounded (spec: Logo pipeline)."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image, ImageCms
from PIL.PngImagePlugin import PngInfo

from app.services import brand_image as bi


def _image(fmt: str, size: tuple[int, int] = (400, 200), **save: object) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (12, 114, 83)).save(out, format=fmt, **save)
    return out.getvalue()


def _logo(data: bytes) -> bytes:
    return bi.logo(bi.decode(data))


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _png_claiming(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IEND", b"")


def _png_with_a_garbled_chunk() -> bytes:
    """Pillow raises SyntaxError ("broken PNG file") only while decoding the pixels."""
    png = _image("PNG")
    at = png.index(b"IDAT") - 4
    data = png[at + 8 : at + 8 + struct.unpack(">I", png[at : at + 4])[0]]
    half = len(data) // 2
    garbled = struct.pack(">I", len(data) - half) + b"\x01\x02\x03\x04" + data[half:] + b"\0" * 4
    return png[:at] + _chunk(b"IDAT", data[:half]) + garbled + _chunk(b"IEND", b"")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_each_allowed_format_becomes_a_png_96_px_high(fmt: str) -> None:
    out = Image.open(io.BytesIO(_logo(_image(fmt))))
    assert out.format == "PNG" and out.height == 96 and out.width == 192


def test_a_small_logo_is_not_upscaled() -> None:
    out = Image.open(io.BytesIO(_logo(_image("PNG", (60, 30)))))
    assert out.size == (60, 30)


def test_metadata_does_not_survive() -> None:
    info = PngInfo()
    info.add_text("Author", "secret-author")
    exif = Image.Exif()
    exif[0x010E] = "secret-description"
    png = _logo(_image("PNG", pnginfo=info))
    jpg = _logo(_image("JPEG", exif=exif.tobytes()))
    for out in (png, jpg):
        assert b"secret" not in out
        assert not Image.open(io.BytesIO(out)).info.get("exif")


def test_icc_profile_does_not_survive() -> None:
    srgb = ImageCms.createProfile("sRGB")
    icc_data = ImageCms.ImageCmsProfile(srgb).tobytes()
    png_with_icc = _logo(_image("PNG", icc_profile=icc_data))
    jpg_with_icc = _logo(_image("JPEG", icc_profile=icc_data))
    for out in (png_with_icc, jpg_with_icc):
        assert b"iCCP" not in out
        assert not Image.open(io.BytesIO(out)).info.get("icc_profile")


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "admin.branding.error.format"),
        (b"<html><script>alert(1)</script></html>", "admin.branding.error.format"),
        (_image("GIF"), "admin.branding.error.format"),
        (_image("BMP"), "admin.branding.error.format"),
        # Pillow raises ValueError ("Truncated IHDR chunk") and SyntaxError for these.
        (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", b"\0\0\0\x10"), "admin.branding.error.format"),
        (_png_with_a_garbled_chunk(), "admin.branding.error.format"),
        (b"\x89PNG" + b"\0" * (bi.MAX_BYTES + 1), "admin.branding.error.too_large"),
        (_png_claiming(20_000, 20_000), "admin.branding.error.dimensions"),
        # Over our 16 MP cap but under Pillow's own bomb limit: only our check refuses it.
        (_png_claiming(5_000, 4_000), "admin.branding.error.dimensions"),
    ],
)
def test_refused_uploads(data: bytes, key: str) -> None:
    with pytest.raises(bi.BrandImageError) as caught:
        bi.decode(data)
    assert caught.value.key == key


@pytest.mark.parametrize("size", [32, 180])
def test_a_favicon_is_square(size: int) -> None:
    out = Image.open(io.BytesIO(bi.favicon(bi.decode(_image("PNG")), size)))
    assert out.size == (size, size) and out.format == "PNG"


def test_a_touch_icon_is_drawn_from_the_full_size_logo() -> None:
    # From the 96 px nav logo, a square logo filled only 96 of the touch icon's 180 px.
    out = Image.open(io.BytesIO(bi.favicon(bi.decode(_image("PNG", (400, 400))), 180)))
    assert out.getbbox() == (0, 0, 180, 180)


def test_a_very_wide_logo_is_capped_in_width() -> None:
    out = Image.open(io.BytesIO(_logo(_image("PNG", (16_000, 1)))))
    assert out.width <= bi.HEIGHT * 16
