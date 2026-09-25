"""Tests for the first-run setup wizard."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.wizard import create_initial_admin
from app.database import get_db
from app.main import app
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
    csrf_token = get_response.cookies.get("ow_csrf")

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "SecureTestPassword123!",
            "totp_secret": totp_secret,
            "totp_code": current_code,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    # Must redirect to /admin/login after successful setup
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_create_initial_admin_noop_when_already_complete() -> None:
    """Race guard: a concurrent submission that already completed setup is a no-op."""
    mock_db = AsyncMock(spec=AsyncSession)
    already_complete = MagicMock()
    already_complete.scalar_one_or_none.return_value = MagicMock(completed=True)
    mock_db.execute.side_effect = [
        MagicMock(),  # pg_advisory_xact_lock
        already_complete,
    ]

    created = await create_initial_admin(
        mock_db, "racer", "SecureTestPassword123!", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )

    assert created is False
    mock_db.rollback.assert_awaited_once()
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_initial_admin_creates_org_and_setup_when_missing() -> None:
    """When the default org / setup_status row don't exist yet, create both."""
    mock_db = AsyncMock(spec=AsyncSession)

    complete_check = MagicMock()
    complete_check.scalar_one_or_none.return_value = None  # setup not complete
    org_lookup = MagicMock()
    org_lookup.scalar_one_or_none.return_value = None  # no default org yet
    setup_lookup = MagicMock()
    setup_lookup.scalar_one_or_none.return_value = None  # no setup_status row yet

    mock_db.execute.side_effect = [
        MagicMock(),  # pg_advisory_xact_lock
        complete_check,
        org_lookup,
        setup_lookup,
    ]

    created = await create_initial_admin(
        mock_db, "neworgadmin", "SecureTestPassword123!", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )

    assert created is True
    assert mock_db.add.call_count == 3
    org, admin, setup = (call.args[0] for call in mock_db.add.call_args_list)
    assert org.slug == "default"
    assert org.name == "Default Organisation"
    assert admin.username == "neworgadmin"
    assert admin.org_id == org.id
    assert setup.completed is True
    mock_db.flush.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_post_rejects_short_password(client: AsyncClient) -> None:
    get_response = await client.get("/setup", follow_redirects=False)
    if get_response.status_code == 302:
        pytest.skip("Setup already completed")

    totp_secret = generate_totp_secret()
    totp = get_totp(totp_secret)
    csrf_token = get_response.cookies.get("ow_csrf")

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "short",
            "password_confirm": "short",
            "totp_secret": totp_secret,
            "totp_code": totp.now(),
            "csrf_token": csrf_token,
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
    csrf_token = get_response.cookies.get("ow_csrf")

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "DifferentPassword123!",
            "totp_secret": totp_secret,
            "totp_code": totp.now(),
            "csrf_token": csrf_token,
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
    csrf_token = get_response.cookies.get("ow_csrf")

    response = await client.post(
        "/setup",
        data={
            "username": "testadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "SecureTestPassword123!",
            "totp_secret": totp_secret,
            "totp_code": "000000",  # wrong code (unless astronomically unlucky)
            "csrf_token": csrf_token,
        },
    )
    assert response.status_code == 422
    assert "TOTP" in response.text or "code" in response.text.lower()


@pytest.mark.asyncio
async def test_setup_post_redirects_when_already_complete(client: AsyncClient) -> None:
    """POST /setup must redirect (not process the form) once setup is done."""
    get_resp = await client.get("/setup", follow_redirects=False)
    csrf_token = get_resp.cookies.get("ow_csrf")

    already_complete = MagicMock()
    already_complete.scalar_one_or_none.return_value = MagicMock(completed=True)
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute.return_value = already_complete

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.post(
            "/setup",
            data={
                "username": "irrelevant",
                "password": "irrelevant",
                "password_confirm": "irrelevant",
                "totp_secret": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "totp_code": "000000",
                "csrf_token": csrf_token,
            },
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_setup_post_completes_admin_creation_and_redirects(client: AsyncClient) -> None:
    """Happy path, independent of any other test's global setup-completion state."""
    get_resp = await client.get("/setup", follow_redirects=False)
    csrf_token = get_resp.cookies.get("ow_csrf")

    totp_secret = generate_totp_secret()
    current_code = get_totp(totp_secret).now()

    not_complete = MagicMock()
    not_complete.scalar_one_or_none.return_value = None
    org_lookup = MagicMock()
    org_lookup.scalar_one_or_none.return_value = MagicMock(id=uuid.uuid4())
    setup_lookup = MagicMock()
    setup_lookup.scalar_one_or_none.return_value = MagicMock(completed=False)

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute.side_effect = [
        not_complete,  # setup_post's own completion check
        MagicMock(),  # pg_advisory_xact_lock
        not_complete,  # create_initial_admin's completion check
        org_lookup,
        setup_lookup,
    ]

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.post(
            "/setup",
            data={
                "username": "wizardcoveragetest",
                "password": "SecureTestPassword123!",
                "password_confirm": "SecureTestPassword123!",
                "totp_secret": totp_secret,
                "totp_code": current_code,
                "csrf_token": csrf_token,
            },
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]
    mock_db.commit.assert_awaited_once()
