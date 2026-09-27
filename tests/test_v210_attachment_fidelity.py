"""Cleaning an attachment removes who made it and nothing of what it shows:
colours, frames and pixels survive, the stored size stays under the limit, and
metadata outside the obvious places goes too."""

from __future__ import annotations

import io
import threading
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageFile
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from app.services import attachment
from app.services.attachment import MetadataError, strip_metadata


def _save(img: Image.Image, fmt: str, **kw: object) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def test_palette_png_keeps_its_colours_and_transparency() -> None:
    img = Image.new("RGB", (4, 4), (200, 10, 30)).convert("P", palette=Image.Palette.ADAPTIVE)
    out = Image.open(io.BytesIO(strip_metadata("a.png", _save(img, "PNG", transparency=0))))
    assert out.convert("RGB").getpixel((0, 0)) == (200, 10, 30)
    assert out.info.get("transparency") == 0


@pytest.mark.parametrize(("name", "fmt"), [("a.png", "PNG"), ("a.webp", "WEBP")])
def test_animated_png_and_webp_keep_every_frame(name: str, fmt: str) -> None:
    red, blue = Image.new("RGB", (8, 8), (255, 0, 0)), Image.new("RGB", (8, 8), (0, 0, 255))
    data = _save(red, fmt, save_all=True, append_images=[blue], duration=100, lossless=True)
    out = Image.open(io.BytesIO(strip_metadata(name, data)))
    assert out.n_frames == 2
    out.seek(1)
    assert out.convert("RGB").getpixel((0, 0)) == (0, 0, 255)


@pytest.mark.parametrize(("name", "fmt"), [("a.jpg", "JPEG"), ("a.png", "PNG"), ("a.webp", "WEBP")])
def test_pixels_are_not_decoded(name: str, fmt: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Decoding is what cost 1.1 GB of RAM for a 450 KB PNG of 12000×12000."""
    data = _save(Image.new("RGB", (8, 8), "red"), fmt)

    def _no_decode(self: Image.Image) -> None:
        raise AssertionError("pixels decoded")

    monkeypatch.setattr(Image.Image, "load", _no_decode)
    monkeypatch.setattr(ImageFile.ImageFile, "load", _no_decode)
    strip_metadata(name, data)


def test_a_truncated_png_is_refused() -> None:
    data = _save(Image.new("RGB", (8, 8), "red"), "PNG", exif=_exif())
    with pytest.raises(MetadataError):
        strip_metadata("a.png", data[: len(data) - 20])


def test_gif_over_the_pixel_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachment, "MAX_IMAGE_PIXELS", 250)  # 10×10 × 3 frames = 300
    frames = [Image.new("L", (10, 10), i * 80) for i in range(3)]
    with pytest.raises(MetadataError):
        strip_metadata("a.gif", _save(frames[0], "GIF", save_all=True, append_images=frames[1:]))
    strip_metadata("b.gif", _save(frames[0], "GIF"))  # one frame, 100 pixels: accepted


def _exif(orientation: int = 6) -> Image.Exif:
    exif = Image.new("RGB", (1, 1)).getexif()
    exif[0x010F] = "SecretCam"
    exif[0x0112] = orientation
    return exif


@pytest.mark.parametrize(("name", "fmt"), [("a.jpg", "JPEG"), ("a.png", "PNG"), ("a.webp", "WEBP")])
def test_only_the_orientation_is_left_of_the_exif(name: str, fmt: str) -> None:
    out = strip_metadata(name, _save(Image.new("RGB", (40, 20), "red"), fmt, exif=_exif()))
    assert b"SecretCam" not in out
    assert dict(Image.open(io.BytesIO(out)).getexif()) == {0x0112: 6}


def test_webp_icc_profile_and_xmp_are_removed() -> None:
    img = Image.new("RGB", (4, 4))
    out = strip_metadata(
        "a.webp", _save(img, "WEBP", icc_profile=b"Pixel 8 Pro", xmp=b"<x>Erika</x>")
    )
    assert b"Pixel 8 Pro" not in out and b"Erika" not in out
    assert out[20] & 0x24 == 0  # the ICC and XMP flags are cleared with the chunks


def test_webp_without_orientation_clears_the_exif_flag() -> None:
    out = strip_metadata("a.webp", _save(Image.new("RGB", (4, 4)), "WEBP", exif=_exif(1)))
    assert b"SecretCam" not in out and out[20] & 0x08 == 0
    Image.open(io.BytesIO(out)).load()


def test_jpeg_pixels_are_untouched_and_the_file_does_not_grow() -> None:
    """Re-encoding at quality 95 grew a 5.5 MB quality-40 photo to 14.4 MB."""
    import os

    noise = Image.frombytes("RGB", (256, 256), os.urandom(256 * 256 * 3))
    data = _save(noise, "JPEG", quality=40, exif=_exif(1))
    out = strip_metadata("a.jpg", data)
    assert len(out) < len(data)
    assert Image.open(io.BytesIO(out)).tobytes() == Image.open(io.BytesIO(data)).tobytes()


def test_jpeg_trailer_after_the_image_is_dropped() -> None:
    """A motion photo appends a video (with its own GPS) after the end-of-image marker."""
    data = _save(Image.new("RGB", (8, 8)), "JPEG") + b"ftypmp42 GPS 52.5200,13.4050"
    out = strip_metadata("a.jpg", data)
    assert b"GPS" not in out and out.endswith(b"\xff\xd9")


def test_jfif_segment_and_its_thumbnail_are_dropped() -> None:
    """A JFIF thumbnail can show the picture as it was before it was cropped."""
    data = _save(Image.new("RGB", (8, 8)), "JPEG")
    app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x01\x01" + b"UNCROPPED"
    data = data[:2] + b"\xff\xe0" + (len(app0) + 2).to_bytes(2, "big") + app0 + data[2:]
    assert b"UNCROPPED" not in strip_metadata("a.jpg", data)


def test_palette_tiff_inside_office_files_keeps_its_colours() -> None:
    img = Image.new("RGB", (4, 4), (200, 10, 30)).convert("P", palette=Image.Palette.ADAPTIVE)
    out = Image.open(io.BytesIO(attachment._strip_image(_save(img, "TIFF"))))
    assert out.convert("RGB").getpixel((0, 0)) == (200, 10, 30)


def test_mpo_photo_is_accepted_as_its_first_picture() -> None:
    """iPhone and many cameras write MPO (a JPEG with more pictures); it used to be refused."""
    first, second = Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")
    out = Image.open(
        io.BytesIO(
            strip_metadata("a.jpg", _save(first, "MPO", save_all=True, append_images=[second]))
        )
    )
    assert out.format == "JPEG" and getattr(out, "n_frames", 1) == 1


def _xmp_stream(writer: PdfWriter) -> object:
    xmp = DecodedStreamObject()
    xmp.set_data(b"<x:xmpmeta><dc:creator>Max Mustermann</dc:creator></x:xmpmeta>")
    xmp[NameObject("/Type")] = NameObject("/Metadata")
    xmp[NameObject("/Subtype")] = NameObject("/XML")
    return writer._add_object(xmp)


def test_pdf_page_xmp_is_removed() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    page[NameObject("/Metadata")] = _xmp_stream(writer)
    buf = io.BytesIO()
    writer.write(buf)
    out = strip_metadata("a.pdf", buf.getvalue())
    assert b"Mustermann" not in out
    assert "/Metadata" not in PdfReader(io.BytesIO(out)).pages[0]


def test_pdf_with_an_embedded_file_is_refused() -> None:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_attachment("notes.docx", b"a Word file nobody cleaned")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(MetadataError):
        strip_metadata("a.pdf", buf.getvalue())


def test_office_paths_sharepoint_columns_and_session_ids_are_removed() -> None:
    sp = "http://schemas.microsoft.com/office/2006/metadata/properties"
    parts = {
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": (
            '<workbook><fileSharing userName="Max Mustermann"/><mc:AlternateContent>'
            '<mc:Choice><x15ac:absPath url="D:\\Private\\Leaks\\"/></mc:Choice>'
            "</mc:AlternateContent><sheets/></workbook>"
        ),
        "word/_rels/settings.xml.rels": (
            '<Relationships><Relationship Id="rId1" Type="attachedTemplate" Target='
            '"file:///C:\\Users\\mmustermann\\AppData\\Normal.dotm" TargetMode="External"/>'
            "</Relationships>"
        ),
        "xl/connections.xml": '<c odcFile="/Users/mmustermann/Library/q.odc"/>',
        "customXml/item1.xml": f'<p:properties xmlns:p="{sp}"><Owner>Max Mustermann</Owner>'
        "</p:properties>",
        "word/settings.xml": (
            '<w:settings><w:docVars><w:docVar w:name="DMSUser" w:val="mmustermann"/></w:docVars>'
            '<w:rsids><w:rsidRoot w:val="00A1B2C3"/></w:rsids></w:settings>'
        ),
        "word/document.xml": '<w:p w:rsidR="00A1B2C3"><w:t>C:\\Users\\mmustermann is evidence'
        "</w:t></w:p>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in parts.items():
            z.writestr(name, body)
    out = zipfile.ZipFile(io.BytesIO(strip_metadata("a.docx", buf.getvalue())))
    for name in parts:
        body = out.read(name)
        if name != "word/document.xml":
            assert b"mmustermann" not in body and b"Mustermann" not in body, name
        assert b"00A1B2C3" not in body and b"Private" not in body, name
    assert b"Normal.dotm" in out.read("word/_rels/settings.xml.rels")
    assert b"<sheets/>" in out.read("xl/workbook.xml")
    assert b"C:\\Users\\mmustermann is evidence" in out.read("word/document.xml")  # text is content


def _upload(name: str, data: bytes) -> MagicMock:
    upload = MagicMock(filename=name, content_type="image/png")
    upload.read = AsyncMock(return_value=data)
    return upload


@pytest.mark.asyncio
async def test_cleaning_runs_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(
        attachment, "strip_metadata", lambda _n, d: seen.append(threading.get_ident()) or d
    )
    files, error = await attachment.read_upload_files(
        [_upload("a.png", _save(Image.new("RGB", (2, 2)), "PNG"))]
    )
    assert error is None and files
    assert seen and seen[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_a_file_that_grows_past_the_limit_when_cleaned_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grown = b"\x89PNG" + b"0" * attachment.MAX_SIZE_BYTES
    monkeypatch.setattr(attachment, "strip_metadata", lambda _n, _d: grown)
    files, error = await attachment.read_upload_files(
        [_upload("a.png", _save(Image.new("RGB", (2, 2)), "PNG"))]
    )
    assert files == []
    assert error and error.key == "upload.error.too_large"  # type: ignore[union-attr]
