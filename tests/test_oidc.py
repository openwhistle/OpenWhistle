"""Tests for OIDC service and endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import oidc as oidc_service
from app.services.auth import get_user_by_oidc_sub

_FAKE_METADATA = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/auth",
    "token_endpoint": "https://idp.example.com/token",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
}


# ── Endpoint tests (OIDC disabled in test env) ────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_authorize_returns_404_when_disabled(client: AsyncClient) -> None:
    response = await client.get("/admin/oidc/authorize", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_callback_returns_404_when_disabled(client: AsyncClient) -> None:
    response = await client.get("/admin/oidc/callback?code=x&state=y", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_callback_no_params_when_disabled(client: AsyncClient) -> None:
    response = await client.get("/admin/oidc/callback", follow_redirects=False)
    assert response.status_code == 404


# ── Service unit tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_oidc_sub_not_found(db_session: AsyncSession) -> None:
    result = await get_user_by_oidc_sub(db_session, "nonexistent-sub", "https://idp.example.com")
    assert result is None


@pytest.mark.asyncio
async def test_oidc_exchange_code_invalid_state() -> None:
    """exchange_code returns None when state key is not in Redis."""
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value=None)

    result = await oidc_service.exchange_code(mock_redis, "some-code", "invalid-state")

    assert result is None
    mock_redis.getdel.assert_called_once()


@pytest.mark.asyncio
async def test_oidc_create_authorization_url_format() -> None:
    """create_authorization_url returns a URL with required OAuth parameters."""
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock(return_value=True)

    with patch("app.services.oidc._get_metadata", new=AsyncMock(return_value=_FAKE_METADATA)):
        url = await oidc_service.create_authorization_url(mock_redis)

    assert url.startswith("https://idp.example.com/auth?")
    assert "response_type=code" in url
    assert "scope=openid" in url
    assert "state=" in url
    assert "nonce=" in url
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_oidc_exchange_code_returns_userinfo() -> None:
    """exchange_code fetches userinfo and injects issuer from metadata."""
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value="test-nonce")

    fake_token_resp = MagicMock()
    fake_token_resp.raise_for_status = MagicMock()
    fake_token_resp.json = MagicMock(return_value={"access_token": "test-access-token"})

    fake_userinfo_resp = MagicMock()
    fake_userinfo_resp.raise_for_status = MagicMock()
    fake_userinfo_resp.json = MagicMock(
        return_value={"sub": "user-123", "email": "user@example.com"}
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=fake_token_resp)
    mock_http_client.get = AsyncMock(return_value=fake_userinfo_resp)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.oidc._get_metadata", new=AsyncMock(return_value=_FAKE_METADATA)):
        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await oidc_service.exchange_code(mock_redis, "auth-code", "valid-state")

    assert result is not None
    assert result["sub"] == "user-123"
    assert result["iss"] == "https://idp.example.com"


@pytest.mark.asyncio
async def test_oidc_get_metadata_calls_correct_url() -> None:
    """_get_metadata fetches the OIDC well-known endpoint."""
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value=_FAKE_METADATA)

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=fake_resp)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_http_client):
        result = await oidc_service._get_metadata()  # noqa: SLF001

    assert result["issuer"] == "https://idp.example.com"
