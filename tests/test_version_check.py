"""Tests for the opt-in GitHub update-check service and the admin System page."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_current_admin
from app.main import app
from app.models.user import AdminRole, AdminUser
from app.services import version_check as vc

# ── Unit: version parsing / comparison ─────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.2.3", (1, 2, 3)),
        ("v1.2.3", (1, 2, 3)),
        ("V2.0", (2, 0)),
        ("1.2.3-rc1", (1, 2, 3)),
        ("1.2.3+build5", (1, 2, 3)),
        ("garbage", (0,)),
    ],
)
def test_parse_version(raw: str, expected: tuple[int, ...]) -> None:
    assert vc.parse_version(raw) == expected


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("1.1.1", "1.2.0", "update_available"),
        ("1.1.1", "v1.1.1", "up_to_date"),
        ("1.2.0", "1.1.1", "ahead"),
        ("1.1.1", "1.1.2", "update_available"),
        ("2.0.0", "v2.0.0-rc1", "up_to_date"),  # prerelease core equals
    ],
)
def test_compare_versions(current: str, latest: str, expected: str) -> None:
    assert vc.compare_versions(current, latest) == expected


# ── fetch_latest_release: 200 / 304 / error paths ──────────────────────────


def _mock_httpx(status_code: int, json_body: dict | None = None, etag: str | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body or {})
    resp.headers = {"ETag": etag} if etag else {}
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_fetch_200_caches_payload_and_etag() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # no prior etag
    redis.setex = AsyncMock()
    body = {
        "tag_name": "v1.2.0",
        "html_url": "https://x/rel",
        "published_at": "2026-07-13T00:00:00Z",
    }

    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, body, etag='W/"abc"')):
        result = await vc.fetch_latest_release(redis)

    assert result is not None
    assert result["tag_name"] == "v1.2.0"
    assert "checked_at" in result
    # payload + etag both cached
    assert redis.setex.await_count == 2


@pytest.mark.asyncio
async def test_fetch_304_keeps_cache() -> None:
    cached = {"tag_name": "v1.2.0", "html_url": "https://x/rel", "checked_at": "old"}
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=['W/"abc"', json.dumps(cached)])  # etag, then cache
    redis.setex = AsyncMock()

    with patch("httpx.AsyncClient", return_value=_mock_httpx(304)):
        result = await vc.fetch_latest_release(redis)

    assert result is not None
    assert result["tag_name"] == "v1.2.0"
    assert result["checked_at"] != "old"  # timestamp refreshed


@pytest.mark.asyncio
async def test_fetch_network_error_serves_stale_cache() -> None:
    cached = {"tag_name": "v1.1.0", "html_url": "https://x", "checked_at": "t"}
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=[None, json.dumps(cached)])  # no etag, then cache read

    failing = AsyncMock()
    failing.__aenter__ = AsyncMock(return_value=failing)
    failing.__aexit__ = AsyncMock(return_value=None)
    failing.get = AsyncMock(side_effect=RuntimeError("network down"))

    with patch("httpx.AsyncClient", return_value=failing):
        result = await vc.fetch_latest_release(redis)  # must not raise

    assert result == cached


# ── get_update_status: shape + flag ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_update_status_reports_update_available(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "update_check_enabled", True)
    cached = {"tag_name": "v9.9.9", "html_url": "https://x/rel", "checked_at": "t"}
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(cached))

    status = await vc.get_update_status(redis, "1.1.1")
    assert status["enabled"] is True
    assert status["latest"] == "v9.9.9"
    assert status["status"] == "update_available"
    assert status["html_url"] == "https://x/rel"


@pytest.mark.asyncio
async def test_get_update_status_no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "update_check_enabled", False)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    status = await vc.get_update_status(redis, "1.1.1")
    assert status["enabled"] is False
    assert status["latest"] is None
    assert status["current"] == "1.1.1"


@pytest.mark.asyncio
async def test_refresh_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "update_check_enabled", False)
    # Must return immediately without touching Redis/httpx.
    with patch("httpx.AsyncClient") as httpx_client:
        await vc.refresh_update_check()
    httpx_client.assert_not_called()


# ── Integration: admin System page ─────────────────────────────────────────


@pytest_asyncio.fixture(loop_scope="function")
async def as_admin(client: AsyncClient):
    admin = AdminUser(
        id=__import__("uuid").uuid4(),
        username="sysadmin",
        role=AdminRole.admin,
        is_active=True,
        totp_secret="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        totp_enabled=True,
    )
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield client
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_admin_system_page_shows_version(as_admin: AsyncClient) -> None:
    from app.config import settings

    resp = await as_admin.get("/admin/system", follow_redirects=False)
    assert resp.status_code == 200
    assert f"v{settings.app_version}" in resp.text
