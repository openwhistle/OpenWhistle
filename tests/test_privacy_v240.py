"""Bug bounty after 2.3.0: traces of the whistleblower that survived the cleaning."""

from __future__ import annotations

import io
import logging
import re
import zipfile
import zlib
from datetime import UTC, datetime
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
    # Nor is its reporter's identity.
    from app.api.admin import can_reveal_identity

    assert can_reveal_identity(admin, report) is False
    assert can_reveal_identity(orgless_admin, report) is True


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


@pytest.mark.asyncio
async def test_reporter_sessions_end_with_the_browser(client, db_session) -> None:  # noqa: ANN001
    """A persistent cookie kept the draft and the open case on a shared PC after closing."""
    from app.services.report import create_report

    await client.get("/submit")
    draft = [h for h in client.cookies.jar if h.name == "ow-submission-session"]
    assert draft and draft[0].expires is None

    report, pin = await create_report(db_session, "financial_fraud", "Sent from a shared PC.")
    await client.get("/status")
    resp = await client.post(
        "/status",
        data={"case_number": report.case_number, "pin": pin, "csrf_token": client.cookies["ow_csrf"]},
        follow_redirects=False,
    )
    cookie = next(h for h in resp.headers.get_list("set-cookie") if h.startswith("ow-status-session="))
    assert "max-age" not in cookie.lower() and "expires" not in cookie.lower()


def test_ldap_refuses_to_bind_in_clear_text() -> None:
    """Measured: the default settings sent the service account's password readable on the wire."""
    from app.config import Settings

    base = {"secret_key": "x" * 40, "ldap_enabled": True, "ldap_server": "dc.corp"}
    with pytest.raises(ValueError, match="clear text"):
        Settings(**base)
    assert Settings(**base, ldap_start_tls=True).ldap_start_tls
    assert Settings(**base, ldap_use_ssl=True, ldap_port=636).ldap_use_ssl


def test_a_logo_url_a_browser_reads_as_another_server_is_ignored() -> None:
    from app.config import Settings

    assert Settings(secret_key="x" * 40, brand_logo_url="/\\evil.example/x.png").brand_logo_url == ""
    logo = Settings(secret_key="x" * 40, brand_logo_url="/static/logo.svg").brand_logo_url
    assert logo == "/static/logo.svg"


@pytest.mark.asyncio
async def test_an_sso_login_finishes_only_in_the_browser_that_started_it(
    client, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001
) -> None:
    """A callback URL with someone else's code and state signed this browser in as them."""
    from unittest.mock import AsyncMock, MagicMock
    from urllib.parse import parse_qs, urlsplit

    from app.config import settings
    from app.services import oidc as oidc_service
    from tests.test_oidc import _FAKE_METADATA

    monkeypatch.setattr(settings, "oidc_enabled", True)
    monkeypatch.setattr(oidc_service, "_get_metadata", AsyncMock(return_value=_FAKE_METADATA))
    started = await client.get("/admin/oidc/authorize", follow_redirects=False)
    assert "ow_oidc_login=" in started.headers["set-cookie"]
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]

    client.cookies.clear()  # the victim's browser: never asked for this state
    token_endpoint = MagicMock()
    monkeypatch.setattr(oidc_service.httpx, "AsyncClient", token_endpoint)
    resp = await client.get(f"/admin/oidc/callback?code=c&state={state}", follow_redirects=False)
    assert resp.status_code == 200 and "ow_session" not in resp.headers.get("set-cookie", "")
    token_endpoint.assert_not_called()  # refused before the code was even exchanged


@pytest.mark.asyncio
async def test_a_capped_content_search_says_so(client, db_session, monkeypatch) -> None:  # noqa: ANN001
    """Past CONTENT_SEARCH_LIMIT older cases went unsearched under a plain "no results"."""
    import uuid

    import app.services.report as report_service
    from app.models.user import AdminRole
    from tests.test_v160_final import _csrf_of
    from tests.test_v160_privacy import _login

    await _login(client, db_session, AdminRole.superadmin)
    word = f"Okapi{uuid.uuid4().hex[:6]}"
    oldest, _ = await report_service.create_report(db_session, "corruption", f"Only {word}.")
    oldest.submitted_at = datetime(2000, 1, 1, tzinfo=UTC)  # times are days: order by date
    await db_session.commit()
    from sqlalchemy import func, select

    from app.models.report import Report

    count = await db_session.scalar(select(func.count(Report.id)))  # every case in view
    monkeypatch.setattr(report_service, "CONTENT_SEARCH_LIMIT", count)
    page = await client.post("/admin/dashboard", data={"q": word, "csrf_token": _csrf_of(client)})
    assert "were searched for words" not in page.text
    await report_service.create_report(db_session, "corruption", "A newer case.")
    page = await client.post("/admin/dashboard", data={"q": word, "csrf_token": _csrf_of(client)})
    assert f"Only the newest {count:,} cases in this view were searched" in page.text
    assert oldest.case_number not in page.text


async def _legacy_attachment(db, **where):  # noqa: ANN001, ANN202
    """A row as v1.3 left it: the bytes stored as uploaded (encrypted = false)."""
    import uuid

    from app.models.attachment import Attachment
    from app.services.report import create_report

    report, _ = await create_report(db, "corruption", "Uploaded before v1.4.0.")
    att = Attachment(
        id=uuid.uuid4(), report_id=report.id, filename="x", content_type="image/jpeg",
        size=9, encrypted=False, **where,
    )
    db.add(att)
    await db.commit()
    return att


@pytest.mark.asyncio
async def test_migration_016_encrypts_attachments_stored_in_the_clear(throwaway_db) -> None:  # noqa: ANN001
    import os
    import subprocess

    from sqlalchemy import select

    from app.config import settings
    from app.models.attachment import Attachment
    from app.services.attachment import read_attachment

    def alembic(*args: str) -> None:
        env = {**os.environ, "DATABASE_URL": settings.database_url}
        run = subprocess.run(["alembic", *args], capture_output=True, text=True, env=env)  # noqa: S603, S607
        assert run.returncode == 0, run.stderr

    alembic("downgrade", "f6b3d9e5a012")
    att_id = (await _legacy_attachment(throwaway_db, data=b"GPS-PHOTO")).id
    alembic("upgrade", "head")
    throwaway_db.expire_all()
    row = await throwaway_db.scalar(select(Attachment).where(Attachment.id == att_id))
    assert row.encrypted and b"GPS-PHOTO" not in row.data
    assert await read_attachment(throwaway_db, row) == b"GPS-PHOTO"


class _Bucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def copy(self, src: str, dst: str) -> None:
        self.objects[dst] = self.objects[src]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_the_s3_startup_job_encrypts_objects_stored_in_the_clear(
    db_session, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001
) -> None:
    import uuid

    from app.services import attachment as att_service

    key = str(uuid.uuid4())  # already a bare UUID: re-keyed by 1.5, never encrypted
    bucket = _Bucket({key: b"GPS-PHOTO"})
    monkeypatch.setattr(att_service, "_storage", lambda: bucket)
    monkeypatch.setattr("app.services.storage.get_storage_backend", lambda: bucket)
    att = await _legacy_attachment(db_session, storage_key=key)
    await att_service.rekey_legacy_objects(db_session)
    await db_session.refresh(att)
    assert att.encrypted and att.storage_key != key and key not in bucket.objects
    assert b"GPS-PHOTO" not in bucket.objects[att.storage_key]
    assert await att_service.read_attachment(db_session, att) == b"GPS-PHOTO"


def test_the_ansible_stack_serves_the_onion_listener_it_advertises() -> None:
    """env.j2 offers ONION_LOCATION; the onion page sends Tor to 127.0.0.1:8080, where
    the role's nginx listened on nothing."""
    from pathlib import Path

    role = Path(__file__).parents[1] / "ansible/roles/openwhistle/templates"
    nginx = (role / "nginx.conf.j2").read_text()
    block = re.search(r"server \{\s*listen 8080;.*?\n    \}", nginx, re.DOTALL)
    assert block and 'proxy_set_header X-OW-Onion "1";' in block.group()
    assert '"127.0.0.1:8080:8080"' in (role / "docker-compose.yml.j2").read_text()


def test_the_ip_is_dropped_by_the_first_middleware() -> None:
    """The Kubernetes page: "OpenWhistle drops them, and the peer address, in its first
    middleware". The CSRF middleware ran first."""
    from app.main import app
    from app.middleware import SecurityMiddleware

    assert app.user_middleware[0].cls is SecurityMiddleware


@pytest.mark.asyncio
async def test_the_pdf_export_speaks_the_admins_language(client, db_session) -> None:  # noqa: ANN001
    """"Five languages": every label of the case export was English."""
    from app.models.user import AdminRole
    from app.services.report import create_report
    from tests.test_pdf_service import _pdf_text
    from tests.test_v160_privacy import _login

    await _login(client, db_session, AdminRole.superadmin)
    report, _ = await create_report(db_session, "corruption", "Exported in German.")
    client.cookies.set("ow-lang", "de")
    text = _pdf_text((await client.get(f"/admin/reports/{report.id}/export.pdf")).content)
    for label in ("Fallnummer", "Meldeart", "Eingangsbestätigung (7 Tage)", "Anonym", "Eingegangen"):
        assert label in text, label
    for english in ("Case Number", "Submission Mode", "Initial Report", "Generated:"):
        assert english not in text, english


@pytest.mark.asyncio
async def test_a_deleted_case_leaves_the_notification_queue(client, db_session) -> None:  # noqa: ANN001
    """The next digest mailed the number of a case erased since it was queued."""
    import uuid

    from app.redis_client import get_redis
    from app.services.notifications import _QUEUE_KEYS
    from app.services.report import create_report
    from tests.test_ux_fixes import _delete_report_4eyes

    report, _ = await create_report(db_session, "corruption", "Deleted before the digest.")
    redis = await get_redis()
    await redis.sadd(_QUEUE_KEYS["new_reports"], report.case_number)
    tag = uuid.uuid4().hex[:6]
    await _delete_report_4eyes(client, db_session, str(report.id), f"q1{tag}", f"q2{tag}")
    assert not await redis.sismember(_QUEUE_KEYS["new_reports"], report.case_number)
