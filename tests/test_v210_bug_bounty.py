"""Regression tests for the v2.1.0 bug bounty.

Each test reproduces a defect that looked right while reading: it fails on the
code as it was and passes on the fix.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parent.parent


@pytest_asyncio.fixture(loop_scope="function")
async def no_csrf():  # type: ignore[no-untyped-def]
    from app.csrf import validate_csrf
    from app.main import app

    app.dependency_overrides[validate_csrf] = lambda: None
    yield
    app.dependency_overrides.pop(validate_csrf, None)


def _dockerfile_cmd() -> list[str]:
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("CMD "):
            return list(json.loads(line[4:]))
    raise AssertionError("Dockerfile has no CMD")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_image_command_writes_no_request_line() -> None:
    """The shipped CMD, run for real: a request leaves no trace in stdout.

    ``--no-access-log`` only empties uvicorn's access handlers; importing the
    app then gave them a handler back, so every path and query string was
    logged, the setup token included.
    """
    port = _free_port()
    cmd = _dockerfile_cmd()
    cmd[cmd.index("--host") + 1] = "127.0.0.1"
    cmd[cmd.index("--port") + 1] = str(port)
    proc = subprocess.Popen(  # noqa: S603 - the Dockerfile's own command
        cmd,
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{base}/health", timeout=1)  # noqa: S310
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise AssertionError("app did not start")
        try:
            urllib.request.urlopen(f"{base}/setup?token=PROBE-SECRET-TOKEN", timeout=5)  # noqa: S310
        except OSError:
            pass  # the status code is irrelevant; the log line is what is measured
    finally:
        proc.terminate()
        output, _ = proc.communicate(timeout=20)
    assert "PROBE-SECRET-TOKEN" not in output
    assert not re.search(r'"GET /health', output), output[-2000:]


# ── TOTP: one code, one action ────────────────────────────────────────────────


def _fullwidth(code: str) -> str:
    return "".join(chr(ord(d) - ord("0") + 0xFF10) for d in code)


async def _totp_user(db_session, role=None):  # type: ignore[no-untyped-def]
    import uuid

    import pyotp

    from app.models.user import AdminRole
    from app.services.users import create_user

    user, _ = await create_user(
        db_session, f"totp-{uuid.uuid4().hex[:6]}", "TestPassword123!", role or AdminRole.admin
    )
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled = True
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_a_fullwidth_copy_of_a_used_code_opens_no_second_session(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    import pyotp

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import auth as auth_service

    monkeypatch.setattr(settings, "demo_mode", False)
    user = await _totp_user(db_session)
    redis = await get_redis()
    code = pyotp.TOTP(user.totp_secret).now()

    results = []
    for submitted in (code, _fullwidth(code)):
        temp = uuid.uuid4().hex
        await auth_service.store_totp_pending(redis, temp, str(user.id))
        r = await client.post(
            "/admin/login/mfa",
            data={"totp_code": submitted, "temp_token": temp},
            follow_redirects=False,
        )
        results.append(r.status_code)
    assert results == [302, 200]


@pytest.mark.asyncio
async def test_the_enrolment_code_cannot_sign_in_a_second_session(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    import pyotp

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import auth as auth_service

    monkeypatch.setattr(settings, "demo_mode", False)
    user = await _totp_user(db_session)
    user.totp_enabled = False
    await db_session.commit()
    redis = await get_redis()
    code = pyotp.TOTP(user.totp_secret).now()

    setup = uuid.uuid4().hex
    await auth_service.store_totp_setup_pending(redis, setup, str(user.id))
    r1 = await client.post(
        "/admin/mfa/setup", data={"totp_code": code, "temp_token": setup}, follow_redirects=False
    )
    assert r1.status_code == 302

    temp = uuid.uuid4().hex
    await auth_service.store_totp_pending(redis, temp, str(user.id))
    r2 = await client.post(
        "/admin/login/mfa", data={"totp_code": code, "temp_token": temp}, follow_redirects=False
    )
    assert r2.status_code != 302


# ── Setup wizard: the TOTP secret from the hidden field ──────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", ["", "AAAA", "!!!!"])
async def test_the_wizard_refuses_a_secret_it_did_not_issue(
    throwaway_db: AsyncSession, client: AsyncClient, secret: str
) -> None:
    import pyotp
    from sqlalchemy import func, select

    from app.models.user import AdminUser
    from tests.conftest import setup_token

    get_resp = await client.get("/setup", follow_redirects=False)
    assert get_resp.status_code == 200
    try:
        code = pyotp.TOTP(secret).now()
    except Exception:  # noqa: BLE001 - "!!!!" has no code; any will do
        code = "123456"
    resp = await client.post("/setup", data={
        "username": "owner210", "password": "SecureTestPassword123!",
        "password_confirm": "SecureTestPassword123!", "totp_secret": secret,
        "totp_code": code, "csrf_token": get_resp.cookies.get("ow_csrf"),
        "setup_token": await setup_token(),
    }, follow_redirects=False)
    assert resp.status_code in (200, 422)  # "" is refused by FastAPI already
    assert await throwaway_db.scalar(select(func.count()).select_from(AdminUser)) == 0


# ── CSRF ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_non_ascii_csrf_token_is_a_403_not_a_500(client: AsyncClient) -> None:
    client.cookies.set("ow_csrf", "abc")
    resp = await client.post("/status/logout", data={"csrf_token": "é"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_the_page_token_matches_the_cookie_the_server_checks() -> None:
    """Two ow_csrf cookies (a sibling subdomain can set one): the token put
    into the page came from the first, the check read the last — every form
    was refused until the cookies were cleared by hand."""
    from httpx import ASGITransport

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        headers = {"cookie": "ow_csrf=first-value; ow_csrf=second-value"}
        page = await c.get("/status", headers=headers)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert token
        resp = await c.post(
            "/status/logout", data={"csrf_token": token.group(1)}, headers=headers,
            follow_redirects=False,
        )
    assert resp.status_code != 403
