"""Tests for whistleblower report submission and status check."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_submit_page_loads(client: AsyncClient) -> None:
    response = await client.get("/submit")
    assert response.status_code == 200
    assert "Submit" in response.text


@pytest.mark.asyncio
async def test_status_page_loads(client: AsyncClient) -> None:
    response = await client.get("/status")
    assert response.status_code == 200
    assert "Case Number" in response.text


@pytest.mark.asyncio
async def test_submit_report_success(client: AsyncClient) -> None:
    response = await client.post(
        "/submit",
        data={
            "category": "financial_fraud",
            "description": "Test description that is long enough to pass validation.",
        },
    )
    assert response.status_code == 200
    assert "Case Number" in response.text or "PIN" in response.text


@pytest.mark.asyncio
async def test_submit_report_description_too_short(client: AsyncClient) -> None:
    response = await client.post(
        "/submit",
        data={
            "category": "financial_fraud",
            "description": "Short",
        },
    )
    assert response.status_code in (200, 422)


@pytest.mark.asyncio
async def test_submit_report_invalid_category(client: AsyncClient) -> None:
    response = await client.post(
        "/submit",
        data={
            "category": "invalid_category",
            "description": "This is a valid description for testing purposes.",
        },
    )
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_status_invalid_credentials(client: AsyncClient) -> None:
    response = await client.post(
        "/status",
        data={
            "case_number": "OW-2026-99999",
            "pin": "00000000-0000-0000-0000-000000000000",
            "session_token": "a" * 32,
        },
    )
    assert response.status_code == 401
    assert "Invalid" in response.text


@pytest.mark.asyncio
async def test_index_redirects(client: AsyncClient) -> None:
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] in ("/setup", "/submit")


@pytest.mark.asyncio
async def test_reply_invalid_credentials(client: AsyncClient) -> None:
    response = await client.post(
        "/reply",
        data={
            "case_number": "OW-9999-99999",
            "pin": "00000000-0000-0000-0000-000000000000",
            "session_token": "c" * 32,
            "content": "Some reply content.",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reply_empty_content(client: AsyncClient) -> None:
    """Empty content is rejected (422) even if credentials are wrong (401 comes first)."""
    response = await client.post(
        "/reply",
        data={
            "case_number": "OW-9999-99999",
            "pin": "00000000-0000-0000-0000-000000000000",
            "session_token": "d" * 32,
            "content": "   ",
        },
    )
    assert response.status_code in (401, 422)


@pytest.mark.asyncio
async def test_status_valid_credentials(client: AsyncClient, db_session: AsyncSession) -> None:
    """Status page shows report details with correct case_number and PIN."""
    from app.services.report import create_report

    report, pin = await create_report(
        db_session, "financial_fraud", "Valid test report for status check."
    )
    response = await client.post(
        "/status",
        data={
            "case_number": report.case_number,
            "pin": pin,
            "session_token": "e" * 32,
        },
    )
    assert response.status_code == 200
    assert report.case_number in response.text


@pytest.mark.asyncio
async def test_reply_valid_credentials(client: AsyncClient, db_session: AsyncSession) -> None:
    """Reply with valid credentials succeeds and shows confirmation."""
    from app.services.report import create_report

    report, pin = await create_report(db_session, "corruption", "Valid report for reply endpoint.")
    response = await client.post(
        "/reply",
        data={
            "case_number": report.case_number,
            "pin": pin,
            "session_token": "f" * 32,
            "content": "This is my reply to the investigation team.",
        },
    )
    assert response.status_code == 200
