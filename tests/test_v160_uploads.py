"""Tests for v1.6.0 upload hardening: refusal of legacy .doc/.xls files."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services.attachment import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, validate_file, _anonymise_ooxml_part, strip_metadata

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
        b'<comments><authors><author>Max Mustermann</author></authors><commentList>'
        b'<comment ref="A1" authorId="0"><text><r><rPr><b/></rPr><t>Max Mustermann:</t></r>'
        b'<r><t xml:space="preserve">\nI spoke to Max Mustermann about it.</t></r></text></comment>'
        b'</commentList></comments>'
    )
    out = _anonymise_ooxml_part("xl/comments1.xml", part)
    assert b"<t>Max Mustermann:</t>" not in out
    assert b"<t>Author:</t>" in out
    assert b"I spoke to Max Mustermann about it." in out  # what they wrote stays


def test_xlsx_comment_author_removed_end_to_end() -> None:
    """Build a minimal .xlsx with comments, strip metadata, verify author name gone everywhere."""
    # Create a minimal XLSX structure with comments in memory
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # Minimal [Content_Types].xml
        zf.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="xml" ContentType="application/xml"/>'
            b'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            b'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            b'<Override PartName="/xl/comments1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>'
            b'<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            b'<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            b'</Types>'
        )
        # Minimal _rels/.rels
        zf.writestr(
            "_rels/.rels",
            b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            b'<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            b'</Relationships>'
        )
        # Workbook
        zf.writestr(
            "xl/workbook.xml",
            b'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets>'
            b'<sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
            b'</sheets></workbook>'
        )
        # Sheet
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            b'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>'
        )
        # Comments with author name in both the <author> tag and the <t> tag
        zf.writestr(
            "xl/comments1.xml",
            b'<?xml version="1.0"?><comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<authors><author>Alice Smith</author></authors>'
            b'<commentList>'
            b'<comment ref="A1" authorId="0"><text><r><rPr><b/></rPr><t>Alice Smith:</t></r>'
            b'<r><t xml:space="preserve"> This is a problem.</t></r></text></comment>'
            b'</commentList></comments>'
        )
        # Core properties
        zf.writestr("docProps/core.xml", b'<?xml version="1.0"?><coreProperties/>')
        zf.writestr("docProps/app.xml", b'<?xml version="1.0"?><Properties/>')

    xlsx_data = out.getvalue()

    # Strip metadata
    cleaned = strip_metadata("test.xlsx", xlsx_data)

    # Verify the author name is gone from the zip
    with zipfile.ZipFile(io.BytesIO(cleaned), "r") as zf:
        comments = zf.read("xl/comments1.xml")
        # Author name should be replaced with "Author"
        assert b"Alice Smith" not in comments, "Author name should be removed from comments"
        assert b"<author>Author</author>" in comments, "Author tag should be neutralized"
        assert b"<t>Author:</t>" in comments, "Comment label should be neutralized"
        # But the actual comment text should stay
        assert b"This is a problem." in comments, "Comment text should be preserved"
