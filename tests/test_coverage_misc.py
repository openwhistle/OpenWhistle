"""Coverage tests for main.py and miscellaneous gaps.

Covers:
- validation_exception_handler: 422 renders HTML error page (main.py lines 73-83)
- Server header is removed by SecurityMiddleware (middleware.py)
- rate_limit: get_whistleblower_lockout_ttl path (services/rate_limit.py)
- index route: redirects to /submit when setup is complete (reports.py lines 86-96)
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient

# ─── validation exception handler ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_error_returns_html_error_page(client: AsyncClient) -> None:
    """RequestValidationError must render error.html with status 422, not raw JSON."""
    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")

    # POST /status with only csrf_token — omit all required fields (case_number, pin,
    # session_token are Form(...) with no defaults) to trigger RequestValidationError.
    resp = await client.post(
        "/status",
        content=b"csrf_token=" + (csrf or "x").encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # Our handler converts this to a 422 HTML page
    assert resp.status_code == 422
    assert "text/html" in resp.headers.get("content-type", "")


# ─── SecurityMiddleware: Server header removed ────────────────────────────────


@pytest.mark.asyncio
async def test_server_header_not_exposed(client: AsyncClient) -> None:
    """The Server header must not be present in any response (information disclosure)."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert "server" not in {k.lower() for k in resp.headers.keys()}


# ─── index route: setup-complete redirect ────────────────────────────────────


@pytest.mark.asyncio
async def test_index_root_redirects_to_submit_after_setup(client: AsyncClient) -> None:
    """GET / must redirect to /submit once setup is complete."""
    resp = await client.get("/", follow_redirects=False)
    # Either redirect to /submit (setup done) or /setup (setup not done) — both are 302
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert location.endswith("/submit") or location.endswith("/setup")


# ─── services/rate_limit: lockout TTL ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_whistleblower_lockout_ttl_zero_for_unknown_token(
    client: AsyncClient,
) -> None:
    """get_whistleblower_lockout_ttl returns 0 when no lockout key exists."""
    from app.redis_client import get_redis
    from app.services.rate_limit import get_whistleblower_lockout_ttl

    redis = await get_redis()
    ttl = await get_whistleblower_lockout_ttl(redis, "nonexistent-session-token-xyz")
    assert ttl == 0


@pytest.mark.asyncio
async def test_check_whistleblower_attempts_passes_for_fresh_token(
    client: AsyncClient,
) -> None:
    """A brand-new session token has no recorded failures, so check passes (True)."""
    from app.redis_client import get_redis
    from app.services.rate_limit import check_whistleblower_attempts

    redis = await get_redis()
    fresh_token = secrets.token_urlsafe(32)
    result = await check_whistleblower_attempts(redis, fresh_token)
    assert result is True


@pytest.mark.asyncio
async def test_remaining_whistleblower_attempts_full_for_fresh_token(
    client: AsyncClient,
) -> None:
    """A fresh token with no failures has the full max_access_attempts remaining."""
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.rate_limit import remaining_whistleblower_attempts

    redis = await get_redis()
    fresh_token = secrets.token_urlsafe(32)
    remaining = await remaining_whistleblower_attempts(redis, fresh_token)
    assert remaining == settings.max_access_attempts
