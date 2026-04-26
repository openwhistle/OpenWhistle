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
        password="PDFTest12!",
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
    result = _fmt_dt(dt)
    assert "2026-04-25" in result
    assert "12:00" in result


def test_safe_ascii():
    assert _safe("hello world") == "hello world"


def test_safe_replaces_non_latin1():
    result = _safe("Ö test → value")
    assert isinstance(result, str)
    # Should not raise, replaces unmappable chars
