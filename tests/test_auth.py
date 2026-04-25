"""Tests for admin authentication flow."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_page_loads(client: AsyncClient) -> None:
    response = await client.get("/admin/login")
    assert response.status_code == 200
    assert "username" in response.text.lower()


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    get_resp = await client.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")
    response = await client.post(
        "/admin/login",
        data={"username": "nonexistent", "password": "wrongpassword", "csrf_token": csrf_token},
    )
    assert response.status_code == 401
    assert "Invalid" in response.text


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/admin/dashboard", follow_redirects=False)
    assert response.status_code in (302, 401)


@pytest.mark.asyncio
async def test_logout_clears_session(client: AsyncClient) -> None:
    response = await client.get("/admin/logout", follow_redirects=True)
    assert response.status_code == 200
