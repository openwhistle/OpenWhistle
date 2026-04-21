"""Tests for whistleblower report submission and status check."""

import pytest
from httpx import AsyncClient


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
