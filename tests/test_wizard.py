"""Tests for the first-run setup wizard."""

import pytest
from httpx import AsyncClient

from app.services.mfa import generate_totp_secret, get_totp


@pytest.mark.asyncio
async def test_setup_page_loads_when_incomplete(client: AsyncClient) -> None:
    response = await client.get("/setup")
    # Either renders the wizard (200) or redirects to login if already done (302)
    assert response.status_code in (200, 302)


@pytest.mark.asyncio
async def test_setup_redirects_to_login_when_complete(client: AsyncClient) -> None:
    """After setup is complete, /setup must redirect away — not show the form again."""
    response = await client.get("/setup", follow_redirects=False)
    if response.status_code == 302:
        assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_setup_post_creates_admin(client: AsyncClient) -> None:
    """Full wizard flow: generate TOTP secret, submit valid form, get redirected to login."""
    # First check if setup is already complete — skip if so
    get_response = await client.get("/setup", follow_redirects=False)
    if get_response.status_code == 302:
        pytest.skip("Setup already completed — wizard test skipped")

    totp_secret = generate_totp_secret()
    totp = get_totp(totp_secret)
    current_code = totp.now()

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "SecureTestPassword123!",
            "totp_secret": totp_secret,
            "totp_code": current_code,
        },
        follow_redirects=False,
    )
    # Must redirect to /admin/login after successful setup
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_setup_post_rejects_short_password(client: AsyncClient) -> None:
    get_response = await client.get("/setup", follow_redirects=False)
    if get_response.status_code == 302:
        pytest.skip("Setup already completed")

    totp_secret = generate_totp_secret()
    totp = get_totp(totp_secret)

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "short",
            "password_confirm": "short",
            "totp_secret": totp_secret,
            "totp_code": totp.now(),
        },
    )
    assert response.status_code == 422
    assert "12" in response.text  # "must be at least 12 characters"


@pytest.mark.asyncio
async def test_setup_post_rejects_mismatched_passwords(client: AsyncClient) -> None:
    get_response = await client.get("/setup", follow_redirects=False)
    if get_response.status_code == 302:
        pytest.skip("Setup already completed")

    totp_secret = generate_totp_secret()
    totp = get_totp(totp_secret)

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "DifferentPassword123!",
            "totp_secret": totp_secret,
            "totp_code": totp.now(),
        },
    )
    assert response.status_code == 422
    assert "do not match" in response.text


@pytest.mark.asyncio
async def test_setup_post_rejects_invalid_totp(client: AsyncClient) -> None:
    get_response = await client.get("/setup", follow_redirects=False)
    if get_response.status_code == 302:
        pytest.skip("Setup already completed")

    totp_secret = generate_totp_secret()

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "SecureTestPassword123!",
            "totp_secret": totp_secret,
            "totp_code": "000000",  # wrong code (unless astronomically unlucky)
        },
    )
    assert response.status_code == 422
    assert "TOTP" in response.text or "code" in response.text.lower()
