"""API contract tests — validate OpenAPI schema and response shape consistency.

These tests run against the real test DB (standard CI infrastructure).
They do NOT require a running server — they use the FastAPI TestClient
which loads the app in-process.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_openapi_json_is_valid(client: AsyncClient) -> None:
    """GET /openapi.json must return a valid OpenAPI 3.x document."""
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["openapi"].startswith("3.")
    assert "info" in schema
    assert "paths" in schema
    assert schema["info"]["title"] != ""


@pytest.mark.asyncio
async def test_openapi_has_required_paths(client: AsyncClient) -> None:
    """All critical route paths must be present in the schema."""
    r = await client.get("/openapi.json")
    paths = r.json()["paths"]
    required = [
        "/health",
        "/status",
        "/submit",
    ]
    for path in required:
        assert path in paths, f"Expected path {path!r} missing from OpenAPI schema"


@pytest.mark.asyncio
async def test_openapi_info_fields(client: AsyncClient) -> None:
    """OpenAPI info block must contain title and version."""
    r = await client.get("/openapi.json")
    info = r.json()["info"]
    assert "title" in info
    assert "version" in info


@pytest.mark.asyncio
async def test_openapi_snapshot_stability(client: AsyncClient, tmp_path: Path) -> None:
    """Fetch the current schema and compare to stored snapshot if it exists.

    On first run, writes the snapshot to tests/fixtures/openapi_snapshot.json.
    On subsequent runs, asserts no paths were removed (additions are fine).
    """
    r = await client.get("/openapi.json")
    current = r.json()
    current_paths = set(current["paths"].keys())

    snapshot_path = Path("tests/fixtures/openapi_snapshot.json")
    if not snapshot_path.exists():
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(current, indent=2))
        pytest.skip("Snapshot created — re-run to validate against it")

    snapshot = json.loads(snapshot_path.read_text())
    snapshot_paths = set(snapshot["paths"].keys())

    removed = snapshot_paths - current_paths
    assert not removed, (
        f"Breaking change: these paths were removed from the API: {removed}. "
        "If intentional, update tests/fixtures/openapi_snapshot.json."
    )


@pytest.mark.asyncio
async def test_health_response_shape(client: AsyncClient) -> None:
    """GET /health must return {status, components} with specific fields."""
    r = await client.get("/health")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "status" in body
    assert body["status"] in ("ok", "degraded")
    assert "components" in body


@pytest.mark.asyncio
async def test_submit_get_returns_html(client: AsyncClient) -> None:
    """GET /submit must return HTML with correct content-type."""
    r = await client.get("/submit")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_status_get_returns_html(client: AsyncClient) -> None:
    """GET /status must return HTML with correct content-type."""
    r = await client.get("/status")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_unknown_route_returns_404(client: AsyncClient) -> None:
    """Requests to non-existent routes must return 404."""
    r = await client.get("/this-route-does-not-exist-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_routes_require_auth(client: AsyncClient) -> None:
    """Admin routes must redirect unauthenticated requests to login."""
    protected_routes = [
        "/admin/dashboard",
        "/admin/categories",
        "/admin/users",
        "/admin/audit-log",
        "/admin/stats",
        "/admin/retention",
        "/admin/telephone-channel",
    ]
    for route in protected_routes:
        r = await client.get(route, follow_redirects=False)
        assert r.status_code in (302, 303, 307, 308), (
            f"Route {route} should redirect unauthenticated users but returned {r.status_code}"
        )
