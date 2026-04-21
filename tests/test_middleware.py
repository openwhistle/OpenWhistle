"""Tests for security middleware: IP header detection and security headers."""

from httpx import AsyncClient

from app.middleware import check_ip_warning, clear_ip_warning


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    headers = response.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert "x-xss-protection" in headers
    assert "referrer-policy" in headers


async def test_clear_ip_warning_does_not_raise(client: AsyncClient) -> None:
    await clear_ip_warning()


async def test_check_ip_warning_returns_bool(client: AsyncClient) -> None:
    result = await check_ip_warning()
    assert isinstance(result, bool)


async def test_request_with_forwarded_for_sets_warning(client: AsyncClient) -> None:
    await clear_ip_warning()
    response = await client.get("/health", headers={"X-Forwarded-For": "10.0.0.1"})
    assert response.status_code == 200
    warning = await check_ip_warning()
    assert warning is True


async def test_request_with_x_real_ip_sets_warning(client: AsyncClient) -> None:
    await clear_ip_warning()
    response = await client.get("/health", headers={"X-Real-Ip": "10.0.0.2"})
    assert response.status_code == 200
    warning = await check_ip_warning()
    assert warning is True


async def test_clear_ip_warning_resets_flag(client: AsyncClient) -> None:
    await client.get("/health", headers={"X-Forwarded-For": "10.0.0.3"})
    await clear_ip_warning()
    warning = await check_ip_warning()
    assert warning is False
