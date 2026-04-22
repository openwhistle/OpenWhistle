"""OIDC Authorization Code Flow for admin single sign-on."""

import secrets
from typing import Any

import httpx
from redis.asyncio import Redis

from app.config import settings

_STATE_PREFIX = "openwhistle:oidc_state:"
_STATE_TTL = 300  # 5 minutes


async def _get_metadata() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(settings.oidc_server_metadata_url, timeout=10)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


async def create_authorization_url(redis: Redis) -> str:
    """Generate OIDC authorization URL; store state in Redis. Returns the URL."""
    metadata = await _get_metadata()
    authorization_endpoint: str = metadata["authorization_endpoint"]

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    await redis.setex(f"{_STATE_PREFIX}{state}", _STATE_TTL, nonce)

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{authorization_endpoint}?{query}"


async def exchange_code(redis: Redis, code: str, state: str) -> dict[str, Any] | None:
    """Exchange authorization code for user info dict, or None if state is invalid."""
    state_key = f"{_STATE_PREFIX}{state}"
    nonce: str | None = await redis.getdel(state_key)
    if not nonce:
        return None

    metadata = await _get_metadata()
    issuer: str = metadata["issuer"]
    token_endpoint: str = metadata["token_endpoint"]
    userinfo_endpoint: str = metadata["userinfo_endpoint"]

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        tokens: dict[str, Any] = token_resp.json()
        access_token: str = tokens["access_token"]

        userinfo_resp = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
        userinfo: dict[str, Any] = userinfo_resp.json()

    userinfo["iss"] = issuer
    return userinfo
