"""A reporter whose request arrived with address headers is told the proxy may log them."""

import pytest
from httpx import AsyncClient

from app.config import settings

_NOTICE = 'id="ip-notice"'


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/submit", "/status"])
async def test_notice_shown_when_the_proxy_forwards_the_address(
    client: AsyncClient, path: str
) -> None:
    response = await client.get(path, headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.status_code == 200
    assert _NOTICE in response.text
    assert "203.0.113.7" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/submit", "/status"])
async def test_no_notice_without_address_headers(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 200
    assert _NOTICE not in response.text


@pytest.mark.asyncio
async def test_no_notice_over_the_onion_listener(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind Tor the proxy only ever sees the local Tor daemon, never the reporter."""
    monkeypatch.setattr(settings, "onion_location", "http://example2345.onion")
    response = await client.get(
        "/submit", headers={"X-Forwarded-For": "127.0.0.1", "X-OW-Onion": "1"}
    )
    assert response.status_code == 200
    assert _NOTICE not in response.text


@pytest.mark.asyncio
async def test_notice_names_the_onion_address_when_one_is_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", "http://example2345.onion")
    response = await client.get("/submit", headers={"X-Real-IP": "203.0.113.7"})
    # The submit sidebar names the address too; it must be inside the notice.
    notice = response.text.split(_NOTICE, 1)[1].split("\n</div>", 1)[0]
    assert "http://example2345.onion" in notice
