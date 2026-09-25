"""Tests for v1.6.0 upload hardening: refusal of legacy .doc/.xls files, and the
S3 re-keying of attachments stored under filename keys before v1.5.0.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.attachment import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    _anonymise_ooxml_part,
    strip_metadata,
    validate_file,
)
from app.services.report import create_report

_OLE_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 8


@pytest.mark.parametrize("name", ["minutes.doc", "budget.xls"])
def test_legacy_office_files_are_refused_with_a_way_out(name: str) -> None:
    error = validate_file(name, "application/msword", 100, head=_OLE_HEAD)
    assert error is not None
    assert ".docx" in error and ".xlsx" in error


def test_legacy_office_refusal_has_its_own_key() -> None:
    error = validate_file("minutes.doc", "application/msword", 100, head=_OLE_HEAD)
    assert error.key == "upload.error.legacy_office"


def test_legacy_office_refused_even_when_oversized() -> None:
    # The .doc/.xls check runs before the size check: a huge legacy file gets
    # the "save as .docx" message, not a generic "too large" one.
    error = validate_file("huge.doc", "application/msword", 999_999_999, head=_OLE_HEAD)
    assert error is not None
    assert error.key == "upload.error.legacy_office"


def test_doc_and_xls_removed_from_allow_lists() -> None:
    assert ".doc" not in ALLOWED_EXTENSIONS
    assert ".xls" not in ALLOWED_EXTENSIONS
    assert "application/msword" not in ALLOWED_MIME_TYPES
    assert "application/vnd.ms-excel" not in ALLOWED_MIME_TYPES


@pytest.mark.parametrize("name", ["MINUTES.DOC", "BUDGET.XLS"])
def test_legacy_office_files_are_refused_regardless_of_case(name: str) -> None:
    error = validate_file(name, "application/msword", 100, head=_OLE_HEAD)
    assert error is not None
    assert error.key == "upload.error.legacy_office"


def test_dotted_stem_with_pdf_extension_is_treated_as_pdf() -> None:
    # "report.doc.pdf" ends in .pdf; only the true extension is checked, not
    # every dot in the name.
    error = validate_file("report.doc.pdf", "application/pdf", 100, head=b"%PDF-1.4")
    assert error is None


def test_ole_bytes_under_a_docx_name_are_a_content_mismatch() -> None:
    # Renaming a .doc to .docx doesn't fool the magic-number check; this is a
    # disguised file, not a legacy-office refusal.
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    error = validate_file("fake.docx", mime, 100, head=_OLE_HEAD)
    assert error is not None
    assert error.key == "upload.error.content_mismatch"


def test_real_zip_docx_is_still_accepted() -> None:
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<document/>")
    data = buf.getvalue()
    error = validate_file("real.docx", mime, len(data), head=data[:16])
    assert error is None


def test_xlsx_comment_author_label_is_removed_but_the_comment_is_kept() -> None:
    part = (
        b'<comments><authors><author>Max Mustermann</author></authors>'
        b'<commentList>'
        b'<comment ref="A1" authorId="0"><text><r><rPr><b/></rPr>'
        b'<t>Max Mustermann:</t></r>'
        b'<r><t xml:space="preserve">\nI spoke to Max Mustermann about it.'
        b'</t></r></text></comment>'
        b'</commentList></comments>'
    )
    out = _anonymise_ooxml_part("xl/comments1.xml", part)
    assert b"<t>Max Mustermann:</t>" not in out
    assert b"<t>Author:</t>" in out
    assert b"I spoke to Max Mustermann about it." in out  # what they wrote stays


def test_xlsx_comment_only_first_run_label_is_replaced() -> None:
    """Excel's label is only the first run; a whistleblower's later run starting
    with the author name should not be altered."""
    part = (
        b'<comments><authors><author>Max Mustermann</author></authors>'
        b'<commentList>'
        b'<comment ref="A1" authorId="0"><text><r><rPr><b/></rPr>'
        b'<t>Max Mustermann:</t></r>'
        b'<r><t>Max Mustermann told me this himself.</t></r>'
        b'</text></comment>'
        b'</commentList></comments>'
    )
    out = _anonymise_ooxml_part("xl/comments1.xml", part)
    # First run label is replaced
    assert b"<t>Author:</t>" in out
    # But the name in the second run (whistleblower's own text) is preserved
    assert b"Max Mustermann told me this himself." in out


def test_xlsx_comment_author_removed_end_to_end() -> None:
    """Build a minimal .xlsx with comments, strip metadata, verify author name gone
    everywhere in the archive."""
    # Create a minimal XLSX structure with comments in memory
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # Minimal [Content_Types].xml
        content_types = (
            b'<?xml version="1.0"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels"'
            b' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="xml" ContentType="application/xml"/>'
            b'<Override PartName="/xl/workbook.xml"'
            b' ContentType="application/vnd.openxmlformats-officedocument.'
            b'spreadsheetml.sheet.main+xml"/>'
            b'<Override PartName="/xl/worksheets/sheet1.xml"'
            b' ContentType="application/vnd.openxmlformats-officedocument.'
            b'spreadsheetml.worksheet+xml"/>'
            b'<Override PartName="/xl/comments1.xml"'
            b' ContentType="application/vnd.openxmlformats-officedocument.'
            b'spreadsheetml.comments+xml"/>'
            b'<Override PartName="/docProps/core.xml"'
            b' ContentType="application/vnd.openxmlformats-package.'
            b'core-properties+xml"/>'
            b'<Override PartName="/docProps/app.xml"'
            b' ContentType="application/vnd.openxmlformats-officedocument.'
            b'extended-properties+xml"/>'
            b'</Types>'
        )
        zf.writestr("[Content_Types].xml", content_types)

        # Minimal _rels/.rels
        rels = (
            b'<?xml version="1.0"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            b'2006/relationships">'
            b'<Relationship Id="rId1"'
            b' Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            b'relationships/officeDocument" Target="xl/workbook.xml"/>'
            b'<Relationship Id="rId2"'
            b' Type="http://schemas.openxmlformats.org/package/2006/'
            b'relationships/metadata/core-properties"'
            b' Target="docProps/core.xml"/>'
            b'<Relationship Id="rId3"'
            b' Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            b'relationships/extended-properties" Target="docProps/app.xml"/>'
            b'</Relationships>'
        )
        zf.writestr("_rels/.rels", rels)

        # Workbook
        workbook = (
            b'<?xml version="1.0"?>'
            b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            b'2006/main"><sheets>'
            b'<sheet name="Sheet1" sheetId="1" r:id="rId1"'
            b' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
            b'relationships"/>'
            b'</sheets></workbook>'
        )
        zf.writestr("xl/workbook.xml", workbook)

        # Sheet
        sheet = (
            b'<?xml version="1.0"?>'
            b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            b'2006/main"><sheetData/></worksheet>'
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet)

        # Comments with author name in both the <author> tag and the <t> tag
        comments = (
            b'<?xml version="1.0"?>'
            b'<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            b'2006/main">'
            b'<authors><author>Alice Smith</author></authors>'
            b'<commentList>'
            b'<comment ref="A1" authorId="0"><text><r><rPr><b/></rPr>'
            b'<t>Alice Smith:</t></r>'
            b'<r><t xml:space="preserve"> This is a problem.</t></r>'
            b'</text></comment>'
            b'</commentList></comments>'
        )
        zf.writestr("xl/comments1.xml", comments)

        # Core properties with creator (author) metadata
        core_props = (
            b'<?xml version="1.0"?>'
            b'<coreProperties xmlns="http://schemas.openxmlformats.org/package/'
            b'2006/metadata/core-properties">'
            b'<creator>Alice Smith</creator>'
            b'</coreProperties>'
        )
        zf.writestr("docProps/core.xml", core_props)

        zf.writestr("docProps/app.xml", b'<?xml version="1.0"?><Properties/>')

    xlsx_data = out.getvalue()

    # Strip metadata
    cleaned = strip_metadata("test.xlsx", xlsx_data)

    # Verify the author name is gone from EVERY zip entry
    with zipfile.ZipFile(io.BytesIO(cleaned), "r") as zf:
        for filename in zf.namelist():
            entry_data = zf.read(filename)
            assert (
                b"Alice Smith" not in entry_data
            ), f"Author name found in {filename}"

        # Also verify specific transformations in comments
        comments_data = zf.read("xl/comments1.xml")
        assert b"<author>Author</author>" in comments_data
        assert b"<t>Author:</t>" in comments_data
        assert b"This is a problem." in comments_data


# ── S3 re-keying: objects stored under filename keys before v1.5.0 ─────────


class _FakeBucket:
    def __init__(self, objects: dict[str, bytes], fail_copy: bool = False) -> None:
        self.objects, self.fail_copy = objects, fail_copy

    async def copy(self, src: str, dst: str) -> None:
        if self.fail_copy:
            raise OSError("bucket unreachable")
        self.objects[dst] = self.objects[src]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_legacy_s3_keys_are_moved_to_bare_uuids(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.attachment import Attachment
    from app.services import attachment as att_service

    report, _ = await create_report(db_session, "corruption", "S3 rekey test report text.")
    legacy = Attachment(
        id=uuid.uuid4(), report_id=report.id, filename="x", content_type="application/pdf",
        size=3, storage_key="Max_Mustermann_evidence.pdf", encrypted=True,
    )
    modern_key = str(uuid.uuid4())
    modern = Attachment(
        id=uuid.uuid4(), report_id=report.id, filename="y", content_type="application/pdf",
        size=3, storage_key=modern_key, encrypted=True,
    )
    db_session.add_all([legacy, modern])
    await db_session.commit()
    bucket = _FakeBucket({"Max_Mustermann_evidence.pdf": b"abc", modern_key: b"def"})
    monkeypatch.setattr(att_service, "_storage", lambda: bucket)

    assert await att_service.rekey_legacy_objects(db_session) == 1
    await db_session.refresh(legacy)
    assert uuid.UUID(legacy.storage_key or "")
    assert bucket.objects[legacy.storage_key or ""] == b"abc"  # copied before the row moved
    assert "Max_Mustermann_evidence.pdf" not in bucket.objects
    assert modern.storage_key == modern_key


@pytest.mark.asyncio
async def test_failed_copy_leaves_the_row_untouched(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.attachment import Attachment
    from app.services import attachment as att_service

    report, _ = await create_report(db_session, "corruption", "S3 rekey failure report text.")
    legacy = Attachment(
        id=uuid.uuid4(), report_id=report.id, filename="x", content_type="application/pdf",
        size=3, storage_key="old-name.pdf", encrypted=True,
    )
    db_session.add(legacy)
    await db_session.commit()
    monkeypatch.setattr(att_service, "_storage", lambda: _FakeBucket({"old-name.pdf": b"a"}, True))
    await att_service.rekey_legacy_objects(db_session)
    await db_session.refresh(legacy)
    assert legacy.storage_key == "old-name.pdf"


@pytest.mark.asyncio
async def test_run_s3_rekey_noop_when_another_replica_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replica that loses the Redis lock race must not touch the DB at all."""
    from app.redis_client import close_redis, get_redis
    from app.services import attachment as att_service

    redis = await get_redis()
    lock_key = "openwhistle:job_lock:s3_rekey"
    assert await redis.set(lock_key, "1", nx=True)
    try:
        rekey_mock = AsyncMock()
        monkeypatch.setattr(att_service, "rekey_legacy_objects", rekey_mock)
        await att_service.run_s3_rekey()
        rekey_mock.assert_not_called()
    finally:
        await redis.delete(lock_key)
        # get_redis() was called outside the `client` fixture: close it now, or
        # it leaks a connection bound to this test's event loop into the next
        # test, which fails with "Event loop is closed" (RTK/lane note).
        await close_redis()


@pytest.mark.asyncio
async def test_lifespan_does_not_schedule_rekey_when_backend_is_not_s3() -> None:
    """STORAGE_BACKEND=db (the default): no S3 re-key job is ever scheduled."""
    from fastapi import FastAPI

    mock_settings = MagicMock()
    mock_settings.demo_mode = False
    mock_settings.reminder_enabled = False
    mock_settings.retention_enabled = False
    mock_settings.update_check_enabled = False
    mock_settings.storage_backend = "db"

    with (
        patch("app.main._run_alembic_upgrade"),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("app.main.settings", mock_settings),
        patch("app.services.notifications.batching_enabled", return_value=False),
        patch("app.services.attachment.run_s3_rekey", new_callable=AsyncMock) as rekey_mock,
    ):
        from app.main import lifespan

        app_tmp = FastAPI()
        async with lifespan(app_tmp):
            pass

    rekey_mock.assert_not_called()
