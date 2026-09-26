"""Tests for the PDF export service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminRole
from app.services.pdf import _fmt_dt, _safe, generate_report_pdf
from app.services.report import (
    acknowledge_report,
    add_note,
    create_report,
    get_report_by_id,
)
from app.services.users import create_user


@pytest.mark.asyncio
async def test_generate_report_pdf_returns_bytes(db_session: AsyncSession):
    report, _ = await create_report(
        db_session,
        category="financial_fraud",
        description="A detailed description for PDF testing purposes.",
        lang="en",
    )
    rid = report.id
    loaded = await get_report_by_id(db_session, rid)
    assert loaded is not None

    pdf_bytes = generate_report_pdf(loaded)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"  # PDF magic bytes


@pytest.mark.asyncio
async def test_generate_pdf_with_acknowledged_report(db_session: AsyncSession):
    report, _ = await create_report(
        db_session,
        category="corruption",
        description="Report with acknowledgement for PDF test.",
        lang="en",
    )
    await acknowledge_report(db_session, report)
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None

    pdf_bytes = generate_report_pdf(loaded)
    assert len(pdf_bytes) > 1500


@pytest.mark.asyncio
async def test_generate_pdf_with_note(db_session: AsyncSession):
    report, _ = await create_report(
        db_session,
        category="workplace_safety",
        description="Report with internal note for PDF.",
        lang="en",
    )
    user, _ = await create_user(
        db_session,
        username=f"pdf_noter_{uuid.uuid4().hex[:6]}",
        password="PDFTest12!-long",
        role=AdminRole.admin,
    )
    await add_note(db_session, report, user, "Internal note content for PDF test.")
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None

    pdf_bytes = generate_report_pdf(loaded)
    assert isinstance(pdf_bytes, bytes)


def test_fmt_dt_none():
    assert _fmt_dt(None) == "-"


def test_fmt_dt_datetime():
    dt = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)
    assert _fmt_dt(dt) == "2026-04-25 12:00 UTC"  # admin times keep the minute


def test_safe_ascii():
    assert _safe("hello world") == "hello world"


def test_safe_preserves_unicode_text():
    # DejaVu (loaded via app.services.pdf._register_font) renders these directly;
    # _safe no longer needs to transliterate or replace anything to fit latin-1.
    assert _safe("Ö test → value") == "Ö test → value"
    assert _safe("Zażółć gęślą jaźń, Ελληνικά, Кириллица, „Anführung“") == (
        "Zażółć gęślą jaźń, Ελληνικά, Кириллица, „Anführung“"
    )


def test_safe_strips_control_characters_but_keeps_layout_whitespace():
    assert _safe("\x00Hello\x01\x1fWorld\x7f") == "HelloWorld"
    assert _safe("line one\nline two\ttabbed\r\n") == "line one\nline two\ttabbed\r\n"


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


@pytest.mark.asyncio
async def test_generate_pdf_renders_latin_greek_and_cyrillic_text(db_session: AsyncSession):
    """DejaVu LGC Sans (app/fonts/) replaces core Helvetica so the printed
    record isn't limited to latin-1: a report written in Polish, Greek or
    Cyrillic must render intact, not as "?"."""
    polish = "Zażółć gęślą jaźń"
    greek = "Ελληνικά"
    cyrillic = "Кириллица"
    german_quotes = "„Anführung“"
    report, _ = await create_report(
        db_session,
        category="corruption",
        description=f"{polish} — {greek} — {cyrillic} — {german_quotes}",
        lang="en",
    )
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None

    text = _pdf_text(generate_report_pdf(loaded))
    assert polish in text
    assert greek in text
    assert cyrillic in text
    assert german_quotes in text
    assert "?" not in text  # no tofu/latin-1 substitution anywhere on the page


@pytest.mark.asyncio
async def test_generate_pdf_does_not_write_into_the_font_directory(
    db_session: AsyncSession,
):
    """fpdf2 must not need a writable font cache — the font directory ships
    read-only in the container image. Made the directory (and the two font
    files) actually read-only for the call, so a write would raise rather
    than silently succeed because the test process owns the files."""
    import os
    import stat

    from app.services.pdf import _FONT_DIR

    report, _ = await create_report(
        db_session, category="corruption", description="Read-only font dir check.", lang="en",
    )
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None

    before = {p: p.stat().st_mode for p in _FONT_DIR.iterdir()}
    original_dir_mode = _FONT_DIR.stat().st_mode
    try:
        for p in _FONT_DIR.iterdir():
            os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        # Deliberately read-only (not writable) — that's the point of the test.
        ro_dir = stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
        os.chmod(_FONT_DIR, ro_dir)  # noqa: S103
        pdf_bytes = generate_report_pdf(loaded)
    finally:
        os.chmod(_FONT_DIR, original_dir_mode)
        for p, mode in before.items():
            os.chmod(p, mode)

    assert pdf_bytes[:4] == b"%PDF"
    assert {p.name for p in _FONT_DIR.iterdir()} == {
        "DejaVuLGCSans.ttf", "DejaVuLGCSans-Bold.ttf", "LICENSE", "README",
    }


@pytest.mark.asyncio
async def test_generate_pdf_prints_the_localised_category_label(db_session: AsyncSession):
    """The PDF used to print the raw category slug ("financial_fraud") — the
    caller now resolves the exporting admin's localised label (falling back
    to English, then the slug) via get_category_labels() and passes it in,
    consistent with the case page's category_label filter."""
    report, _ = await create_report(
        db_session,
        category="financial_fraud",
        description="PDF category label test — falls back correctly too.",
        lang="en",
    )
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None

    text_labelled = _pdf_text(generate_report_pdf(loaded, category_label="Finanzbetrug"))
    assert "Finanzbetrug" in text_labelled
    assert "financial_fraud" not in text_labelled

    # No label supplied (e.g. a category deleted since) falls back to the slug,
    # never a blank field.
    text_fallback = _pdf_text(generate_report_pdf(loaded))
    assert "financial_fraud" in text_fallback
