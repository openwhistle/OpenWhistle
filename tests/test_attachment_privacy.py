"""Attachments must not identify the whistleblower: metadata is stripped on
upload, and the bytes are stored encrypted with the report's data key."""

from __future__ import annotations

import io
import uuid
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, PngImagePlugin
from pypdf import PdfWriter
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.attachment import MetadataError, strip_metadata


def _exif_jpeg() -> bytes:
    img = Image.new("RGB", (40, 20), "red")
    exif = img.getexif()
    exif[0x010F] = "SecretCam"  # camera make
    exif[0x0112] = 6  # orientation: rotate 90°
    exif.get_ifd(0x8825)[2] = (52.0, 31.0, 0.0)  # GPS latitude
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_jpeg_loses_exif_and_gps_but_keeps_orientation() -> None:
    out = strip_metadata("photo.jpg", _exif_jpeg())
    img = Image.open(io.BytesIO(out))
    assert len(img.getexif()) == 0
    assert b"SecretCam" not in out
    assert img.size == (20, 40)  # orientation baked into the pixels


def test_png_text_chunks_are_removed() -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Max Mustermann")
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG", pnginfo=info)
    assert b"Mustermann" not in strip_metadata("scan.png", buf.getvalue())


def test_png_icc_profile_is_removed() -> None:
    """ICC profiles can name the device; Pillow copies them from im.info by default."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG", icc_profile=b"Pixel 8 Pro display profile")
    out = Image.open(io.BytesIO(strip_metadata("screen.png", buf.getvalue())))
    assert "icc_profile" not in out.info


def test_webp_exif_is_removed() -> None:
    exif = Image.new("RGB", (1, 1)).getexif()
    exif[0x010F] = "SecretCam"
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "WEBP", exif=exif)
    assert b"SecretCam" not in strip_metadata("a.webp", buf.getvalue())


def test_gif_comment_is_removed() -> None:
    buf = io.BytesIO()
    Image.new("P", (4, 4)).save(buf, "GIF", comment=b"Max Mustermann")
    assert b"Mustermann" not in strip_metadata("a.gif", buf.getvalue())


_XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/'
    b'22-rdf-syntax-ns#"><rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
    b"<dc:creator>Erika XMP</dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>"
)


def test_pdf_document_info_is_removed() -> None:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_metadata({"/Author": "Max Mustermann", "/Producer": "SecretTool"})
    writer.xmp_metadata = _XMP
    buf = io.BytesIO()
    writer.write(buf)
    out = strip_metadata("memo.pdf", buf.getvalue())
    assert b"Mustermann" not in out
    assert b"SecretTool" not in out
    assert b"Erika XMP" not in out


def test_office_properties_are_emptied_and_content_kept() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("docProps/core.xml", "<cp><dc:creator>Max Mustermann</dc:creator></cp>")
        z.writestr("docProps/app.xml", "<Properties><Company>ACME</Company></Properties>")
        z.writestr("word/document.xml", "<doc>evidence</doc>")
    out = zipfile.ZipFile(io.BytesIO(strip_metadata("a.docx", buf.getvalue())))
    assert b"Mustermann" not in out.read("docProps/core.xml")
    assert b"ACME" not in out.read("docProps/app.xml")
    assert out.read("word/document.xml") == b"<doc>evidence</doc>"


def test_unparseable_file_is_refused_not_stored_as_is() -> None:
    with pytest.raises(MetadataError):
        strip_metadata("x.pdf", b"%PDF-garbage")


def test_plain_text_passes_unchanged() -> None:
    assert strip_metadata("notes.txt", b"hello") == b"hello"


@pytest.mark.asyncio
async def test_upload_refuses_a_file_that_cannot_be_cleaned() -> None:
    from app.services.attachment import read_upload_files

    upload = MagicMock(filename="x.pdf", content_type="application/pdf")
    upload.read = AsyncMock(return_value=b"%PDF-garbage")
    files, error = await read_upload_files([upload])
    assert files == []
    assert error and "metadata" in error


@pytest.mark.asyncio
async def test_attachment_is_stored_encrypted_and_read_back(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.services.attachment import create_attachments, read_attachment
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Encrypted attachment test.")
    [att] = await create_attachments(db_session, report, [("n.txt", "text/plain", b"evidence")])

    assert att.encrypted is True
    assert att.data is not None and b"evidence" not in att.data
    assert await read_attachment(db_session, att) == b"evidence"

    # External storage receives ciphertext too.
    from app.services import storage

    backend = MagicMock(put=AsyncMock(), get=AsyncMock())
    monkeypatch.setattr(storage, "get_storage_backend", lambda: backend)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    [s3_att] = await create_attachments(db_session, report, [("m.txt", "text/plain", b"secret")])
    stored = backend.put.await_args.args[1]
    assert s3_att.data is None and b"secret" not in stored
    backend.get.return_value = stored
    assert await read_attachment(db_session, s3_att) == b"secret"


@pytest.mark.asyncio
async def test_legacy_plaintext_attachment_is_still_readable(db_session: AsyncSession) -> None:
    from app.models.attachment import Attachment
    from app.services.attachment import read_attachment
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Legacy attachment test.")
    att = Attachment(
        id=uuid.uuid4(), report_id=report.id, filename="old.txt",
        content_type="text/plain", size=3, data=b"old", encrypted=False,
    )
    db_session.add(att)
    await db_session.commit()
    assert await read_attachment(db_session, att) == b"old"


def test_pdf_that_needs_a_password_is_refused() -> None:
    writer = PdfWriter()
    writer.add_blank_page(72, 72)
    writer.encrypt("pw")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(MetadataError):
        strip_metadata("locked.pdf", buf.getvalue())


def test_owner_password_only_pdf_is_accepted_and_cleaned() -> None:
    """Permission-restricted PDFs are common and readable without a password."""
    from pypdf import PdfReader

    writer = PdfWriter()
    writer.add_blank_page(72, 72)
    writer.add_metadata({"/Author": "Max Mustermann"})
    writer.encrypt(user_password="", owner_password="owner")
    buf = io.BytesIO()
    writer.write(buf)
    out = PdfReader(io.BytesIO(strip_metadata("restricted.pdf", buf.getvalue())))
    assert not out.is_encrypted
    assert not (out.metadata or {}).get("/Author")


def test_office_zip_bomb_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import attachment

    monkeypatch.setattr(attachment, "MAX_SIZE_BYTES", 1000)  # bomb threshold: 20 kB
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * 21_000)
    with pytest.raises(MetadataError):
        strip_metadata("bomb.docx", buf.getvalue())


@pytest.mark.asyncio
async def test_read_attachment_without_bytes_raises_lookup_error(db_session: AsyncSession) -> None:
    from app.models.attachment import Attachment
    from app.services.attachment import read_attachment

    att = Attachment(id=uuid.uuid4(), report_id=uuid.uuid4(), filename="x", content_type="t",
                     size=0, data=None)
    with pytest.raises(LookupError):
        await read_attachment(db_session, att)


@pytest.mark.asyncio
async def test_whistleblower_downloads_decrypted_attachment(
    client: object, db_session: AsyncSession
) -> None:
    from httpx import AsyncClient
    from redis.asyncio import Redis

    from app.config import settings
    from app.services.attachment import create_attachments
    from app.services.report import create_report

    ac: AsyncClient = client  # type: ignore[assignment]
    report, _ = await create_report(db_session, "financial_fraud", "WB download test.")
    [att] = await create_attachments(db_session, report, [("n.txt", "text/plain", b"evidence")])

    session_key = uuid.uuid4().hex
    redis = Redis.from_url(settings.redis_url)
    await redis.set(f"status-session:{session_key}", str(report.id), ex=60)
    await redis.aclose()

    ac.cookies.set("ow-status-session", session_key)
    resp = await ac.get(f"/status/attachments/{att.id}")
    assert resp.status_code == 200
    assert resp.content == b"evidence"

    missing = await ac.get(f"/status/attachments/{uuid.uuid4()}")
    assert missing.status_code == 404
