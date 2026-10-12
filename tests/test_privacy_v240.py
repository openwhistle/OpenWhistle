"""Bug bounty after 2.3.0: traces of the whistleblower that survived the cleaning."""

from __future__ import annotations

import io
import logging
import re
import zipfile
import zlib
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

from app.services.attachment import strip_metadata


def _jpeg_with_camera() -> bytes:
    img = Image.new("RGB", (8, 8), "red")
    exif = img.getexif()
    exif[0x010F] = "SecretCam"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _jp2_with_xml() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "JPEG2000")
    xml = b"<x:xmpmeta>SecretScanner</x:xmpmeta>"
    return buf.getvalue() + (8 + len(xml)).to_bytes(4, "big") + b"xml " + xml


def _pdf_with_image(data: bytes, filters: list[str]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    image = StreamObject()
    image._data = data
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(8),
            NameObject("/Height"): NumberObject(8),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/Filter"): ArrayObject([NameObject(f) for f in filters]),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): writer._add_object(image)})}
    )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _image_of(pdf: bytes) -> bytes:
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    image = page["/Resources"]["/XObject"]["/Im0"].get_object()
    return bytes(image.get_data())


def test_pdf_jpeg_behind_a_flate_filter_loses_its_exif() -> None:
    pdf = _pdf_with_image(zlib.compress(_jpeg_with_camera()), ["/FlateDecode", "/DCTDecode"])
    assert b"SecretCam" in _image_of(pdf)
    image = _image_of(strip_metadata("scan.pdf", pdf))
    assert b"SecretCam" not in image
    assert Image.open(io.BytesIO(image)).size == (8, 8)


def test_pdf_jpeg2000_loses_its_metadata_boxes() -> None:
    pdf = _pdf_with_image(_jp2_with_xml(), ["/JPXDecode"])
    image = _image_of(strip_metadata("scan.pdf", pdf))
    assert b"SecretScanner" not in image
    assert Image.open(io.BytesIO(image)).size == (8, 8)


def test_bare_jpeg2000_codestream_loses_its_comment() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "JPEG2000", no_jp2=True)
    data = buf.getvalue()
    comment = b"\x00\x01SecretScanner"  # Rcom = 1: Latin text
    siz_end = 4 + int.from_bytes(data[4:6], "big")  # COM comes after SIZ
    com = b"\xff\x64" + (2 + len(comment)).to_bytes(2, "big") + comment
    data = data[:siz_end] + com + data[siz_end:]
    assert Image.open(io.BytesIO(data)).size == (8, 8)
    pdf = _pdf_with_image(data, ["/JPXDecode"])
    image = _image_of(strip_metadata("scan.pdf", pdf))
    assert b"SecretScanner" not in image
    assert Image.open(io.BytesIO(image)).size == (8, 8)


def _signed_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    signature = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Sig"),
            NameObject("/Name"): TextStringObject("Erika Signer"),
            NameObject("/ContactInfo"): TextStringObject("erika@corp.example"),
            NameObject("/M"): TextStringObject("D:20261012140300"),
            NameObject("/ByteRange"): ArrayObject([NumberObject(0)] * 4),
            NameObject("/Contents"): ByteStringObject(b"certificate of Erika"),
        }
    )
    sig_ref = writer._add_object(signature)
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Sig"),
            NameObject("/T"): TextStringObject("Signature1"),
            NameObject("/V"): sig_ref,
        }
    )
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject([writer._add_object(field)])}
    )
    writer._root_object[NameObject("/Perms")] = DictionaryObject({NameObject("/DocMDP"): sig_ref})
    writer._root_object[NameObject("/DSS")] = DictionaryObject(
        {NameObject("/Certs"): ArrayObject([writer._add_object(StreamObject())])}
    )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pdf_signature_does_not_name_the_signer() -> None:
    out = strip_metadata("signed.pdf", _signed_pdf())
    reader = PdfReader(io.BytesIO(out))
    field = reader.trailer["/Root"]["/AcroForm"]["/Fields"][0].get_object()
    assert "/V" not in field
    assert "/Perms" not in reader.trailer["/Root"]
    assert "/DSS" not in reader.trailer["/Root"]
    assert b"/ByteRange" not in out


def test_pdf_last_modified_is_removed() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    page[NameObject("/LastModified")] = TextStringObject("D:20261012091400+02'00'")
    buf = io.BytesIO()
    writer.write(buf)
    out = strip_metadata("memo.pdf", buf.getvalue())
    assert "/LastModified" not in PdfReader(io.BytesIO(out)).pages[0]


def _package(parts: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return buf.getvalue()


_PRINTER_REL = (
    b'<Relationships><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    b'officeDocument/2006/relationships/printerSettings" Target="../printerSettings/'
    b'printerSettings1.bin"/><Relationship Id="rId2" Type="drawing" Target="d.xml"/></Relationships>'
)


def test_xlsx_printer_settings_are_dropped_and_unreferenced() -> None:
    xlsx = _package(
        {
            "[Content_Types].xml": b'<Types><Override PartName="/xl/printerSettings/'
            b'printerSettings1.bin" ContentType="x"/></Types>',
            "xl/worksheets/sheet1.xml": b'<worksheet><drawing r:id="rId2"/>'
            b'<pageSetup orientation="portrait" r:id="rId1"/></worksheet>',
            "xl/worksheets/_rels/sheet1.xml.rels": _PRINTER_REL,
            "xl/printerSettings/printerSettings1.bin": "\\\\SRV\\HP-Finance-3".encode("utf-16-le"),
        }
    )
    out = zipfile.ZipFile(io.BytesIO(strip_metadata("a.xlsx", xlsx)))
    assert not [n for n in out.namelist() if "printerSettings/" in n]
    assert b"printerSettings" not in out.read("[Content_Types].xml")
    rels = out.read("xl/worksheets/_rels/sheet1.xml.rels")
    assert b"printerSettings" not in rels
    assert b'Id="rId2"' in rels
    sheet = out.read("xl/worksheets/sheet1.xml")
    assert sheet == b'<worksheet><drawing r:id="rId2"/><pageSetup orientation="portrait"/></worksheet>'


def test_docx_printer_settings_element_goes_with_its_part() -> None:
    docx = _package(
        {
            "word/settings.xml": b'<w:settings><w:printerSettings r:id="rId1"/><w:zoom/></w:settings>',
            "word/_rels/settings.xml.rels": _PRINTER_REL,
            "word/printerSettings/printerSettings1.bin": b"HP-Finance-3",
        }
    )
    out = zipfile.ZipFile(io.BytesIO(strip_metadata("a.docx", docx)))
    assert out.read("word/settings.xml") == b"<w:settings><w:zoom/></w:settings>"
    assert "word/printerSettings/printerSettings1.bin" not in out.namelist()


def test_office_edit_times_and_accounts_are_neutral() -> None:
    xlsx = _package(
        {
            "xl/threadedComments/threadedComment1.xml": b'<c dT="2026-10-12T09:14:00.00"/>',
            "xl/revisions/revisionHeaders.xml": b'<h dateTime="2026-10-12T09:14:00Z" userName="Erika"/>',
            "xl/pivotCache/pivotCacheDefinition1.xml": b'<p refreshedBy="Erika" refreshedDate="46307.38"/>',
            "xl/connections.xml": b'<c><dbPr connection="Provider=SQLOLEDB;User ID=erika;Data Source=fin"/></c>',
            "xl/externalLinks/_rels/externalLink1.xml.rels": b'<Relationships><Relationship Id="rId1" '
            b'Target="file:///\\\\fs01\\home$\\erika\\budget.xlsx"/></Relationships>',
        }
    )
    out = strip_metadata("a.xlsx", xlsx)
    package = zipfile.ZipFile(io.BytesIO(out))
    text = b"".join(package.read(n) for n in package.namelist())
    for trace in (b"2026-10-12", b"46307", b"Erika", b"erika"):
        assert trace not in text
    assert b"budget.xlsx" in text  # the file name is content; the account is not

    docx = _package(
        {
            "word/document.xml": b'<w:ins w:author="Erika" w:date="2026-10-12T09:14:00Z"/>',
            "word/commentsExtensible.xml": b'<w16cex:commentExtensible w16cex:dateUtc="2026-10-12T07:14:00Z"/>',
            "word/settings.xml": b'<w:mailMerge><w:connectString w:val="User ID=erika"/></w:mailMerge>',
        }
    )
    package = zipfile.ZipFile(io.BytesIO(strip_metadata("a.docx", docx)))
    text = b"".join(package.read(n) for n in package.namelist())
    for trace in (b"2026-10-12", b"Erika", b"erika"):
        assert trace not in text


async def test_refused_reply_notice_does_not_log_the_reporters_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aiosmtplib import SMTPRecipientRefused, SMTPRecipientsRefused

    from app.services.notifications import notify_reply_to_whistleblower

    refused = SMTPRecipientsRefused(
        [SMTPRecipientRefused(550, "5.1.1 <wb@private.example>: unknown", "wb@private.example")]
    )
    with (
        patch("app.config.settings") as cfg,
        patch("aiosmtplib.send", side_effect=refused),
        caplog.at_level(logging.DEBUG),
    ):
        cfg.notify_email_enabled = True
        cfg.notify_smtp_user = cfg.notify_smtp_password = ""
        cfg.app_name = cfg.notify_email_from = cfg.notify_smtp_host = "x"
        await notify_reply_to_whistleblower("wb@private.example", "https://example.com")
    assert "Failed to send whistleblower reply notification" in caplog.text
    assert "private.example" not in caplog.text


def test_every_container_runs_hardened() -> None:
    """README: "Hardened containers — read-only root, no capabilities". The database and
    Redis had a writable root and Docker's default capabilities; Quick Start had none of it."""
    from pathlib import Path

    import yaml

    root = Path(__file__).parents[1]
    files = [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "ansible/roles/openwhistle/templates/docker-compose.yml.j2",
    ]
    for name in files:
        text = re.sub(r"\{\{ \w+ \}\}", "x", (root / name).read_text())
        for service, conf in yaml.safe_load(text)["services"].items():
            where = f"{name}: {service}"
            assert conf.get("read_only") is True, where
            assert conf.get("cap_drop") == ["ALL"], where
            assert "no-new-privileges:true" in conf.get("security_opt", []), where


def test_an_org_less_report_is_no_other_organisations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The list hid it from an organisation's admin; the case page opened it."""
    import uuid

    from app.api.admin import _can_access_report
    from app.config import settings
    from app.models.report import Report
    from app.models.user import AdminRole, AdminUser

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    report = Report(id=uuid.uuid4(), assigned_to_id=None, org_id=None)
    admin = AdminUser(id=uuid.uuid4(), role=AdminRole.admin, org_id=uuid.uuid4())
    assert _can_access_report(admin, report) is False
    orgless_admin = AdminUser(id=uuid.uuid4(), role=AdminRole.admin, org_id=None)
    assert _can_access_report(orgless_admin, report) is True


@pytest.mark.asyncio
async def test_a_pin_typed_in_capitals_opens_the_case(client, db_session) -> None:  # noqa: ANN001
    """"The correct case number and PIN always open your report" — not in capitals."""
    from app.redis_client import get_redis
    from app.services.report import authenticate_whistleblower, create_report

    report, pin = await create_report(db_session, "financial_fraud", "Typed with caps lock on.")
    found, _ = await authenticate_whistleblower(
        db_session, await get_redis(), report.case_number, pin.upper()
    )
    assert found is not None and found.id == report.id
