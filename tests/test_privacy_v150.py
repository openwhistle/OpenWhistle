"""v1.5.0 whistleblower privacy: Office authors and thumbnails, encrypted
attachment names, batched notifications, encrypted submission drafts."""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.report import Report
from app.services.attachment import strip_metadata

# ── Office: comment and tracked-change authors, thumbnails ────────────────────

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_W15 = 'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"'
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_RT = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"
_TC = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _zip(parts: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return buf.getvalue()


def _assert_valid_package(data: bytes) -> zipfile.ZipFile:
    import xml.etree.ElementTree as ET  # noqa: N817, S405 — parsing our own output

    out = zipfile.ZipFile(io.BytesIO(data))
    assert out.testzip() is None
    for name in out.namelist():
        if name.endswith((".xml", ".rels")):
            ET.fromstring(out.read(name))  # noqa: S314 — still well-formed
    return out


def _docx() -> bytes:
    return _zip({
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Override PartName="/docProps/thumbnail.jpeg" ContentType="image/jpeg"/>'
            '<Override PartName="/word/document.xml" ContentType="application/xml"/></Types>'
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{_RELS}">'
            '<Relationship Id="rId1" Type="officeDocument" Target="word/document.xml"/>'
            f'<Relationship Id="rId2" Type="{_RT}" Target="docProps/thumbnail.jpeg"/>'
            "</Relationships>"
        ),
        "docProps/thumbnail.jpeg": b"\xff\xd8\xffMax Mustermann page one",
        "word/document.xml": (
            f"<w:document {_W}><w:body><w:p>"
            '<w:ins w:id="1" w:author="Max Mustermann" w:date="2026-01-01T00:00:00Z">'
            "<w:r><w:t>evidence</w:t></w:r></w:ins>"
            "<w:del w:id='2' w:author='Max Mustermann'><w:r><w:delText>x</w:delText></w:r></w:del>"
            "</w:p></w:body></w:document>"
        ),
        "word/comments.xml": (
            f'<w:comments {_W}><w:comment w:id="0" w:author="Max Mustermann" w:initials="MM">'
            "<w:p><w:r><w:t>see page 2</w:t></w:r></w:p></w:comment></w:comments>"
        ),
        "word/people.xml": (
            f'<w15:people {_W15}><w15:person w15:author="Max Mustermann">'
            '<w15:presenceInfo w15:providerId="AD" w15:userId="S::max@acme.example::1234"/>'
            "</w15:person></w15:people>"
        ),
    })


def test_docx_comment_and_tracked_change_authors_are_anonymised() -> None:
    out = _assert_valid_package(strip_metadata("a.docx", _docx()))
    for name in out.namelist():
        body = out.read(name)
        assert b"Mustermann" not in body, name
        assert b"max@acme" not in body, name
    assert b'w:initials="MM"' not in out.read("word/comments.xml")
    assert b'w:author="Author"' in out.read("word/comments.xml")
    assert b"evidence" in out.read("word/document.xml")
    assert b"see page 2" in out.read("word/comments.xml")


def test_docx_thumbnail_is_removed_with_its_references() -> None:
    out = _assert_valid_package(strip_metadata("a.docx", _docx()))
    assert not [n for n in out.namelist() if "thumbnail" in n]
    assert b"thumbnail" not in out.read("_rels/.rels")
    assert b"thumbnail" not in out.read("[Content_Types].xml")
    assert b"word/document.xml" in out.read("_rels/.rels")  # other relationships kept


def test_office_zip_entries_lose_timestamps_and_extra_fields() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("word/document.xml", date_time=(2026, 3, 4, 9, 41, 0))
        info.extra = b"ux\x0b\x00\x01\x04\xe8\x03\x00\x00\x04\xe8\x03\x00\x00"  # uid/gid 1000
        z.writestr(info, "<doc/>")
    [entry] = zipfile.ZipFile(io.BytesIO(strip_metadata("a.docx", buf.getvalue()))).infolist()
    assert entry.date_time == (1980, 1, 1, 0, 0, 0)
    assert entry.extra == b""


def test_xlsx_comment_authors_and_persons_are_anonymised() -> None:
    person_id = "{5C0E2A1B-0000-4000-8000-000000000001}"
    xlsx = _zip({
        "[Content_Types].xml": "<Types/>",
        "xl/comments1.xml": (
            f'<comments xmlns="{_SML}"><authors><author>Max Mustermann</author>'
            f"<author>tc={person_id}</author></authors>"
            '<commentList><comment ref="A1" authorId="0"><text><t>check</t></text></comment>'
            "</commentList></comments>"
        ),
        "xl/persons/person.xml": (
            f'<personList xmlns="{_TC}"><person displayName="Max Mustermann" id="{person_id}" '
            'userId="max@acme.example" providerId="AD"/></personList>'
        ),
        "xl/threadedComments/threadedComment1.xml": (
            f'<ThreadedComments xmlns="{_TC}"><threadedComment ref="A1" personId="{person_id}">'
            "<text>check</text></threadedComment></ThreadedComments>"
        ),
        "xl/revisions/userNames.xml": (
            f'<users xmlns="{_SML}"><userInfo guid="{{1}}" name="Max Mustermann" id="1"/></users>'
        ),
        "xl/revisions/revisionHeaders.xml": (
            f'<headers xmlns="{_SML}"><header guid="{{2}}" userName="Max Mustermann"/></headers>'
        ),
        "xl/tables/table1.xml": '<table displayName="Payments" name="Payments"/>',
    })
    out = _assert_valid_package(strip_metadata("book.xlsx", xlsx))
    for name in out.namelist():
        assert b"Mustermann" not in out.read(name), name
        assert b"max@acme" not in out.read(name), name
    # Threaded comments still point at an existing person.
    assert person_id.encode() in out.read("xl/persons/person.xml")
    assert person_id.encode() in out.read("xl/threadedComments/threadedComment1.xml")
    assert f"tc={person_id}".encode() in out.read("xl/comments1.xml")
    # Attributes with the same local name elsewhere are not touched.
    assert out.read("xl/tables/table1.xml") == b'<table displayName="Payments" name="Payments"/>'


# ── Attachment filenames are encrypted ────────────────────────────────────────

_NAME = "Max_Mustermann_evidence.txt"


async def _report_with_named_attachment(db_session: AsyncSession) -> tuple[Report, Attachment]:
    from app.services.attachment import create_attachments
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Filename privacy test.")
    [att] = await create_attachments(db_session, report, [(_NAME, "text/plain", b"evidence")])
    return report, att


@pytest.mark.asyncio
async def test_attachment_filename_is_stored_encrypted(db_session: AsyncSession) -> None:
    from app.services.attachment import attachment_filename
    from app.services.report import decrypt_attachment_names, get_report_by_id

    report, att = await _report_with_named_attachment(db_session)
    stored = await db_session.scalar(
        text("SELECT filename FROM attachments WHERE id = :i"), {"i": att.id}
    )
    assert "Mustermann" not in stored
    assert await attachment_filename(db_session, att) == _NAME
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None
    assert decrypt_attachment_names(loaded) == [_NAME]


@pytest.mark.asyncio
async def test_s3_object_key_does_not_carry_the_filename(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.services import storage
    from app.services.attachment import create_attachments
    from app.services.report import create_report

    backend = MagicMock(put=AsyncMock())
    monkeypatch.setattr(storage, "get_storage_backend", lambda: backend)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    report, _ = await create_report(db_session, "financial_fraud", "S3 key privacy test.")
    [att] = await create_attachments(db_session, report, [(_NAME, "text/plain", b"x")])
    assert att.storage_key and "Mustermann" not in att.storage_key
    assert "Mustermann" not in backend.put.await_args.args[0]


@pytest.mark.asyncio
async def test_legacy_plaintext_filename_is_shown_as_stored(db_session: AsyncSession) -> None:
    from app.services.attachment import attachment_filename
    from app.services.report import create_report, decrypt_attachment_names, get_report_by_id

    report, _ = await create_report(db_session, "financial_fraud", "Legacy filename test.")
    att = Attachment(id=uuid.uuid4(), report_id=report.id, filename="old.txt",
                     content_type="text/plain", size=1, data=b"x")
    db_session.add(att)
    await db_session.commit()
    assert await attachment_filename(db_session, att) == "old.txt"
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None
    assert decrypt_attachment_names(loaded) == ["old.txt"]


@pytest.mark.asyncio
async def test_status_page_download_and_pdf_show_the_decrypted_filename(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from pypdf import PdfReader
    from redis.asyncio import Redis

    from app.config import settings
    from app.services.pdf import generate_report_pdf
    from app.services.report import get_report_by_id

    report, att = await _report_with_named_attachment(db_session)
    session_key = uuid.uuid4().hex
    redis = Redis.from_url(settings.redis_url)
    await redis.set(f"status-session:{session_key}", str(report.id), ex=60)
    await redis.aclose()
    client.cookies.set("ow-status-session", session_key)

    status_page = await client.get("/status")
    assert _NAME in status_page.text
    download = await client.get(f"/status/attachments/{att.id}")
    assert _NAME in download.headers["content-disposition"]

    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None
    pdf = PdfReader(io.BytesIO(generate_report_pdf(loaded)))
    assert _NAME in "".join(page.extract_text() for page in pdf.pages)


@pytest.mark.asyncio
async def test_admin_report_page_and_download_show_the_decrypted_filename(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.user import AdminRole
    from tests.test_coverage_admin import _create_admin, _login_admin

    report, att = await _report_with_named_attachment(db_session)
    admin, totp = await _create_admin(db_session)
    admin.role = AdminRole.admin
    await db_session.commit()
    await _login_admin(client, admin, totp)
    page = await client.get(f"/admin/reports/{report.id}")
    assert page.status_code == 200
    assert _NAME in page.text
    assert 'gAAAA' not in page.text  # no ciphertext anywhere on the page
    download = await client.get(f"/admin/reports/{report.id}/attachments/{att.id}")
    assert _NAME in download.headers["content-disposition"]


@pytest.mark.asyncio
async def _walk_to_attachments(
    client: AsyncClient, mode: dict[str, str] | None = None
) -> Response:
    """Walk the wizard to the attachment step; return that step's page."""
    from tests.conftest import _wizard_detect_step, _wizard_get_csrf

    resp = await client.get("/submit")
    for data in (mode or {"submission_mode": "anonymous"}, {"category": "financial_fraud"},
                 {"description": "Enough characters to pass validation."}):
        if _wizard_detect_step(resp.text) == 2:  # location step, when locations exist
            resp = await client.post("/submit", data={
                "csrf_token": _wizard_get_csrf(resp.text), "step": "2", "action": "next"})
        resp = await client.post("/submit", data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "step": str(_wizard_detect_step(resp.text)), "action": "next", **data})
    return resp


async def _upload(client: AsyncClient, page: Response, content: bytes = b"evidence") -> Response:
    from tests.conftest import _wizard_get_csrf

    return await client.post(
        "/submit",
        data={"csrf_token": _wizard_get_csrf(page.text), "step": "5", "action": "next"},
        files={"files": (_NAME, content, "text/plain")},
    )


@pytest.mark.asyncio
async def test_submit_success_page_lists_the_plaintext_filename(client: AsyncClient) -> None:
    from tests.conftest import _wizard_get_csrf

    resp = await _upload(client, await _walk_to_attachments(client))
    resp = await client.post("/submit", data={
        "csrf_token": _wizard_get_csrf(resp.text), "step": "6", "action": "next"})
    assert _NAME in resp.text
    assert "gAAAA" not in resp.text


def _alembic(*args: str) -> None:
    import subprocess

    run = subprocess.run(  # noqa: S603
        ["alembic", *args], capture_output=True, text=True, check=False  # noqa: S607
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.asyncio
async def test_migration_encrypts_existing_filenames_idempotently(
    db_session: AsyncSession,
) -> None:
    from app.services.encryption import make_report_fernet
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Migration filename test.")
    assert report.encrypted_dek
    # create_report() ends with db.refresh(report), whose SELECT LEFT OUTER JOINs
    # admin_users (Report.assigned_to is lazy="joined"). That leaves this session's
    # transaction open, holding a lock on admin_users, until the next commit. The
    # alembic downgrade below now also rewrites admin_users (migration 004), so
    # that lock must be released first or the subprocess's ALTER TABLE deadlocks
    # against this very session.
    await db_session.commit()
    fernet = make_report_fernet(report.encrypted_dek)
    already = fernet.encrypt(b"done.txt").decode()
    legacy_id, done_id = uuid.uuid4(), uuid.uuid4()
    _alembic("downgrade", "3c1f0a7e9b42")
    try:
        for att_id, name in ((legacy_id, _NAME), (done_id, already)):
            await db_session.execute(text(
                "INSERT INTO attachments (id, report_id, filename, content_type, size, encrypted)"
                " VALUES (:i, :r, :f, 'text/plain', 1, false)"
            ), {"i": att_id, "r": report.id, "f": name})
        await db_session.commit()
    finally:
        _alembic("upgrade", "head")

    rows = dict((await db_session.execute(text(
        "SELECT id, filename FROM attachments WHERE id IN (:a, :b)"
    ), {"a": legacy_id, "b": done_id})).tuples().all())
    assert fernet.decrypt(rows[legacy_id].encode()) == _NAME.encode()
    assert rows[done_id] == already  # not encrypted twice


# ── Submission drafts are encrypted with a key only the browser holds ─────────


async def _draft_in_redis(cookie: str) -> str:
    from redis.asyncio import Redis

    from app.config import settings

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return await redis.get(f"submission-session:{cookie.split('.')[0]}") or ""
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_draft_in_redis_reveals_nothing_without_the_cookie_key(client: AsyncClient) -> None:
    from cryptography.fernet import Fernet

    await _upload(client, await _walk_to_attachments(client, {
        "submission_mode": "confidential", "confidential_name": "Max Mustermann",
        "confidential_contact": "+49 170 0000000",
    }))
    cookie = client.cookies["ow-submission-session"]
    stored = await _draft_in_redis(cookie)
    assert stored
    for secret in ("Mustermann", "+49 170", "Enough characters", "evidence", "ZXZpZGVuY2"):
        assert secret not in stored
    plain = Fernet(cookie.split(".")[1] + "=").decrypt(stored).decode()
    assert "Max Mustermann" in plain


@pytest.mark.asyncio
async def test_draft_with_the_wrong_key_counts_as_expired(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    draft_id = client.cookies["ow-submission-session"].split(".")[0]
    client.cookies.set("ow-submission-session", f"{draft_id}.{'A' * 43}")
    resp = await client.get("/submit")
    assert 'name="step" value="1"' in resp.text
    assert not resp.cookies["ow-submission-session"].startswith(draft_id)


@pytest.mark.asyncio
async def test_draft_attachments_are_capped_in_total(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import attachment

    monkeypatch.setattr(attachment, "MAX_DRAFT_ATTACHMENT_BYTES", 4)
    resp = await _upload(client, await _walk_to_attachments(client))
    assert "too large in total" in resp.text
    assert 'name="step" value="5"' in resp.text


@pytest.mark.asyncio
async def test_draft_attachments_are_refused_when_redis_is_nearly_full(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import reports

    monkeypatch.setattr(reports, "_redis_has_room", AsyncMock(return_value=False))
    page = await _walk_to_attachments(client)
    resp = await _upload(client, page)
    assert "cannot take attachments right now" in resp.text
    assert 'name="step" value="5"' in resp.text
    # Without attachments the report still goes through.
    from tests.conftest import _wizard_get_csrf

    resp = await client.post("/submit", data={
        "csrf_token": _wizard_get_csrf(resp.text), "step": "5", "action": "next"})
    assert 'name="step" value="6"' in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("info", "room"), [
    ({"maxmemory": 0, "used_memory": 10**12}, True),     # no limit configured
    ({"maxmemory": 1000, "used_memory": 790}, True),
    ({"maxmemory": 1000, "used_memory": 800}, False),    # at 80 %
    (RuntimeError("INFO disabled"), True),                # never blocks a report
])
async def test_redis_has_room(info: dict[str, int] | Exception, room: bool) -> None:
    from app.api.reports import _redis_has_room

    redis = MagicMock(info=AsyncMock(side_effect=[info]))
    assert await _redis_has_room(redis) is room


# ── Notifications are batched: their timing must not identify anyone ──────────


@pytest_asyncio.fixture(loop_scope="function")
async def notify_settings(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncMock]:
    """Email channel on, batching at 60 minutes, delivery replaced by a mock."""
    from redis.asyncio import Redis

    from app.config import settings
    from app.redis_client import close_redis
    from app.services import notifications

    monkeypatch.setattr(settings, "notify_email_enabled", True)
    monkeypatch.setattr(settings, "notify_email_to", "compliance@example.com")
    monkeypatch.setattr(settings, "notification_batch_minutes", 60)
    deliver = AsyncMock()
    monkeypatch.setattr(notifications, "_deliver", deliver)

    async def _clear() -> None:
        redis = Redis.from_url(settings.redis_url)
        await redis.delete(*notifications._QUEUE_KEYS.values())
        await redis.aclose()

    await close_redis()
    await _clear()
    yield deliver
    await _clear()
    await close_redis()


@pytest.mark.asyncio
async def test_new_report_and_reply_are_queued_not_sent(notify_settings: AsyncMock) -> None:
    from app.services.notifications import (
        deliver_notification_digest,
        notify_new_report,
        notify_whistleblower_message,
    )

    await notify_new_report("OW-2026-00002")
    await notify_new_report("OW-2026-00001")
    await notify_whistleblower_message("OW-2026-00003")
    await notify_whistleblower_message("OW-2026-00003")
    notify_settings.assert_not_called()

    await deliver_notification_digest()
    notify_settings.assert_awaited_once_with(["OW-2026-00001", "OW-2026-00002"], ["OW-2026-00003"])
    await deliver_notification_digest()  # queue emptied: nothing more to send
    notify_settings.assert_awaited_once()


@pytest.mark.asyncio
async def test_digest_is_delivered_once_when_replicas_run_together(
    notify_settings: AsyncMock,
) -> None:
    import asyncio

    from app.services.notifications import deliver_notification_digest, notify_new_report

    await notify_new_report("OW-2026-00001")
    await asyncio.gather(*(deliver_notification_digest() for _ in range(5)))
    notify_settings.assert_awaited_once()


@pytest.mark.asyncio
async def test_whistleblower_reply_queues_a_notification(
    notify_settings: AsyncMock, db_session: AsyncSession
) -> None:
    from app.services.notifications import deliver_notification_digest
    from app.services.report import add_whistleblower_message, create_report

    report, _ = await create_report(db_session, "financial_fraud", "Reply notification test.")
    await add_whistleblower_message(db_session, report, "More details.")
    await deliver_notification_digest()
    notify_settings.assert_awaited_once_with([], [report.case_number])


@pytest.mark.asyncio
async def test_batch_zero_sends_immediately(
    notify_settings: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from app.config import settings
    from app.services import notifications

    monkeypatch.setattr(settings, "notification_batch_minutes", 0)
    await notifications.notify_new_report("OW-2026-00001")
    await asyncio.gather(*notifications._background)
    notify_settings.assert_awaited_once_with(new_reports=["OW-2026-00001"])


def test_batching_needs_an_interval_and_a_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.services.notifications import batching_enabled

    monkeypatch.setattr(settings, "notify_email_enabled", True)
    monkeypatch.setattr(settings, "notify_email_to", "compliance@example.com")
    monkeypatch.setattr(settings, "notification_batch_minutes", 60)
    assert batching_enabled()
    monkeypatch.setattr(settings, "notification_batch_minutes", 0)
    assert not batching_enabled()
    monkeypatch.setattr(settings, "notification_batch_minutes", 60)
    monkeypatch.setattr(settings, "notify_email_enabled", False)
    assert not batching_enabled()


@pytest.mark.asyncio
async def test_digest_carries_counts_and_case_numbers_only() -> None:
    from app.config import settings
    from app.services.notifications import _build_webhook_payload, _send_email

    sent = AsyncMock()
    cfg = settings.model_copy(update={"notify_email_to": "compliance@example.com"})
    with patch("aiosmtplib.send", sent):
        await _send_email(["OW-2026-00001", "OW-2026-00002"], ["OW-2026-00003"], cfg)
    body = sent.await_args.args[0].get_payload(decode=True).decode()
    assert "2 (OW-2026-00001, OW-2026-00002)" in body
    assert "1 (OW-2026-00003)" in body
    assert "UTC" not in body and "Received" not in body  # no per-event time
    assert _build_webhook_payload(["OW-2026-00001"], [], "generic", "OW", "https://x") == {
        "event": "new_activity", "new_reports": ["OW-2026-00001"], "new_messages": [],
    }


# ── Retention is on by default ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retention_page_explains_the_default(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.models.user import AdminRole
    from tests.test_coverage_admin import _create_admin, _login_admin

    monkeypatch.setattr(settings, "retention_enabled", True)
    admin, totp = await _create_admin(db_session)
    admin.role = AdminRole.admin
    await db_session.commit()
    await _login_admin(client, admin, totp)
    page = await client.get("/admin/retention")
    assert "on by default since v1.5.0" in page.text
    assert "1095 days after it was closed" in page.text


# ── No client address reaches the application ─────────────────────────────────


@pytest.mark.asyncio
async def test_ip_headers_and_peer_address_never_reach_the_app() -> None:
    from app.middleware import SecurityMiddleware

    seen: dict[str, object] = {}

    async def app(scope: dict[str, object], receive: object, send: object) -> None:
        seen.update(scope)

    scope = {
        "type": "http", "client": ("203.0.113.7", 50000),
        "headers": [(b"x-forwarded-for", b"203.0.113.7"), (b"x-real-ip", b"203.0.113.7"),
                    (b"accept", b"text/html")],
    }
    with patch("app.redis_client.get_redis", AsyncMock()):
        await SecurityMiddleware(app)(scope, AsyncMock(), AsyncMock())  # type: ignore[arg-type]
    assert seen["client"] is None
    assert seen["headers"] == [(b"accept", b"text/html")]


@pytest.mark.asyncio
async def test_pages_are_never_cached_but_static_files_are(client: AsyncClient) -> None:
    for path in ("/submit", "/status", "/health"):
        assert (await client.get(path)).headers["cache-control"] == "no-store", path
    static = await client.get("/static/css/fonts.css")
    assert static.status_code == 200
    assert static.headers.get("cache-control") != "no-store"


def test_helm_ingress_turns_the_nginx_access_log_off() -> None:
    from pathlib import Path

    import yaml

    values = yaml.safe_load(Path("charts/openwhistle/values.yaml").read_text())
    annotations = values["ingress"]["annotations"]
    assert annotations["nginx.ingress.kubernetes.io/enable-access-log"] == "false"
