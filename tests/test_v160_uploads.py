"""Tests for v1.6.0 upload hardening: refusal of legacy .doc/.xls files."""

from __future__ import annotations

import pytest

from app.services.attachment import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, validate_file

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
