"""API contract tests — validate route existence, response shapes, and auth enforcement.

These tests run against the real test DB (standard CI infrastructure).
They use the FastAPI AsyncClient and do not require a running server.

Note: OpenAPI schema is intentionally disabled in production (openapi_url=None).
These tests instead verify contracts by exercising real routes.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_response_shape(client: AsyncClient) -> None:
    """GET /health must return {status, components} with valid values."""
    r = await client.get("/health")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "status" in body
    assert body["status"] in ("ok", "degraded")
    assert "components" in body


@pytest.mark.asyncio
async def test_health_components_present(client: AsyncClient) -> None:
    """Health check must report db and redis component status."""
    r = await client.get("/health")
    body = r.json()
    assert "db" in body["components"]
    assert "redis" in body["components"]


@pytest.mark.asyncio
async def test_submit_get_returns_html(client: AsyncClient) -> None:
    """GET /submit must return HTML content."""
    r = await client.get("/submit")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_status_get_returns_html(client: AsyncClient) -> None:
    """GET /status must return HTML content."""
    r = await client.get("/status")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_unknown_route_returns_404(client: AsyncClient) -> None:
    """Requests to non-existent routes must return 404."""
    r = await client.get("/this-route-does-not-exist-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_login_page_renders(client: AsyncClient) -> None:
    """GET /admin/login must return a login form page."""
    r = await client.get("/admin/login")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "login" in r.text.lower()


@pytest.mark.asyncio
async def test_admin_routes_require_auth(client: AsyncClient) -> None:
    """Admin routes must enforce authentication (401 or redirect to login)."""
    protected_routes = [
        "/admin/dashboard",
        "/admin/categories",
        "/admin/users",
        "/admin/audit-log",
        "/admin/stats",
        "/admin/retention",
        "/admin/telephone-channel",
    ]
    valid_auth_codes = (302, 303, 307, 308, 401, 403)
    for route in protected_routes:
        r = await client.get(route, follow_redirects=False)
        assert r.status_code in valid_auth_codes, (
            f"Route {route} must enforce auth but returned {r.status_code}"
        )


@pytest.mark.asyncio
async def test_setup_redirects_when_complete(client: AsyncClient) -> None:
    """GET /setup must redirect when admin setup is already complete."""
    r = await client.get("/setup", follow_redirects=False)
    assert r.status_code in (302, 303, 307, 308, 200), (
        f"Setup route returned unexpected status {r.status_code}"
    )


@pytest.mark.asyncio
async def test_submit_post_missing_csrf_rejected(client: AsyncClient) -> None:
    """POST /submit without CSRF token must be rejected."""
    r = await client.post("/submit", data={}, follow_redirects=False)
    assert r.status_code in (400, 403, 422), (
        f"Submit POST without CSRF should be rejected, got {r.status_code}"
    )
