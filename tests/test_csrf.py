"""Tests for CSRF protection: Double-Submit Cookie pattern."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_csrf_cookie_set_on_get(client: AsyncClient) -> None:
    """Every GET response sets the ow_csrf cookie."""
    response = await client.get("/admin/login")
    assert response.status_code == 200
    assert "ow_csrf" in response.cookies


@pytest.mark.asyncio
async def test_csrf_cookie_stable_across_requests(client: AsyncClient) -> None:
    """The CSRF token stays the same once the cookie is set."""
    r1 = await client.get("/admin/login")
    token1 = r1.cookies.get("ow_csrf")
    r2 = await client.get("/admin/login")
    token2 = r2.cookies.get("ow_csrf")
    assert token1 == token2


@pytest.mark.asyncio
async def test_admin_login_post_without_csrf_token_is_rejected(client: AsyncClient) -> None:
    """POST to /admin/login without csrf_token field is rejected (422 from form validation)."""
    await client.get("/admin/login")  # ensure cookie is set
    response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": "password"},
    )
    # FastAPI validates required Form fields before running dependencies, so
    # a missing csrf_token yields 422 (Unprocessable Entity), not 403.
    assert response.status_code in (403, 422)


@pytest.mark.asyncio
async def test_admin_login_post_with_wrong_csrf_token_is_rejected(client: AsyncClient) -> None:
    """POST to /admin/login with mismatched csrf_token returns 403."""
    await client.get("/admin/login")
    response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": "password", "csrf_token": "wrong-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_login_post_with_valid_csrf_token_proceeds(client: AsyncClient) -> None:
    """POST to /admin/login with correct csrf_token passes CSRF check (may fail auth, not CSRF)."""
    get_resp = await client.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")
    response = await client.post(
        "/admin/login",
        data={"username": "nonexistent", "password": "wrong", "csrf_token": csrf_token},
    )
    # CSRF passes; auth fails → 401 (not 403)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_setup_post_without_csrf_rejected(client: AsyncClient) -> None:
    """POST to /setup without csrf_token is rejected."""
    get_resp = await client.get("/setup", follow_redirects=False)
    if get_resp.status_code == 302:
        pytest.skip("Setup already completed")

    response = await client.post(
        "/setup",
        data={
            "username": "admin",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
            "totp_secret": "JBSWY3DPEHPK3PXP",
            "totp_code": "000000",
        },
    )
    # Missing required Form field → 422; wrong token → 403. Both mean rejected.
    assert response.status_code in (403, 422)


@pytest.mark.asyncio
async def test_csrf_missing_cookie_returns_403(client: AsyncClient) -> None:
    """POST with csrf_token in form but no ow_csrf cookie returns 403."""
    # Fresh client has no cookies — send token in form without prior GET
    response = await client.post(
        "/admin/login",
        data={"username": "admin", "password": "password", "csrf_token": "some-token"},
    )
    assert response.status_code == 403
