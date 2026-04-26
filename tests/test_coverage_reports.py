"""Coverage tests for app/api/reports.py gaps.

Covers:
- set_language fallback: /admin/* sub-path → /admin/dashboard (lines 65-68)
- set_language fallback: unknown path → /submit (lines 65-68)
- submit description boundary: 9 chars (below min), 10 chars (min), 10000 (max), 10001 (above)
- submit with no category
- status cookie with invalid characters ignored (line 214)
- status cookie that is too long ignored (line 214)
- reply_post: session token rotated (lines 358-371)
- whistleblower attachment download: 401 without session cookie (line 404)
- whistleblower attachment download: 401 with valid-format key not in Redis (line 408)
- status_logout clears the session cookie
"""

from __future__ import annotations

import re
import secrets
import uuid

import pytest
from httpx import AsyncClient

# ─── helpers ──────────────────────────────────────────────────────────────────


async def _submit_report(client: AsyncClient, description: str = "") -> tuple[str, str]:
    """Submit a report and return (case_number, pin)."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/submit",
        data={
            "category": "financial_fraud",
            "description": description or "A" * 50,
            "csrf_token": csrf,
        },
    )
    case_m = re.search(r"OW-\d{4}-\d{5}", resp.text)
    pin_m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", resp.text
    )
    case_number = case_m.group(0) if case_m else ""
    pin = pin_m.group(1) if pin_m else ""
    return case_number, pin


async def _login_whistleblower(
    client: AsyncClient, case_number: str, pin: str
) -> None:
    """POST to /status to set the ow-status-session cookie."""
    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    session_token_m = re.search(
        r'name="session_token"\s+value="([^"]+)"', get_resp.text
    )
    session_token = session_token_m.group(1) if session_token_m else "fallback"
    await client.post(
        "/status",
        data={
            "case_number": case_number,
            "pin": pin,
            "session_token": session_token,
            "csrf_token": csrf,
        },
        follow_redirects=True,
    )


# ─── set_language: fallback paths ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_language_admin_subpath_falls_back_to_dashboard(
    client: AsyncClient,
) -> None:
    """/admin/reports/... is not in the allowlist, so it should fall back to /admin/dashboard."""
    resp = await client.post(
        "/set-language",
        data={"lang": "de", "next": "/admin/reports/some-id"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/admin/dashboard")


@pytest.mark.asyncio
async def test_set_language_unknown_path_falls_back_to_submit(
    client: AsyncClient,
) -> None:
    """An unknown path (not /admin/*) falls back to /submit."""
    resp = await client.post(
        "/set-language",
        data={"lang": "en", "next": "/some-unknown-path"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/submit")


@pytest.mark.asyncio
async def test_set_language_exact_allowlist_path_is_preserved(
    client: AsyncClient,
) -> None:
    """Exact allowlist entries (/status) are preserved without modification."""
    resp = await client.post(
        "/set-language",
        data={"lang": "en", "next": "/status"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/status")


@pytest.mark.asyncio
async def test_set_language_sets_lang_cookie(client: AsyncClient) -> None:
    """The ow-lang cookie must be set to the requested language."""
    resp = await client.post(
        "/set-language",
        data={"lang": "de", "next": "/submit"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cookie_header = resp.headers.get("set-cookie", "")
    assert "ow-lang=de" in cookie_header


# ─── submit: description boundary conditions ─────────────────────────────────


@pytest.mark.asyncio
async def test_submit_description_below_minimum_shows_error(client: AsyncClient) -> None:
    """9-character description (< 10) must render an error, not create a report."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/submit",
        data={"category": "financial_fraud", "description": "A" * 9, "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "at least 10" in resp.text


@pytest.mark.asyncio
async def test_submit_description_exact_minimum_succeeds(client: AsyncClient) -> None:
    """10-character description (== minimum) must create a report successfully."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/submit",
        data={"category": "financial_fraud", "description": "A" * 10, "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "OW-" in resp.text


@pytest.mark.asyncio
async def test_submit_description_exact_maximum_succeeds(client: AsyncClient) -> None:
    """10,000-character description (== maximum) must create a report successfully."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/submit",
        data={"category": "financial_fraud", "description": "B" * 10000, "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "OW-" in resp.text


@pytest.mark.asyncio
async def test_submit_description_above_maximum_shows_error(client: AsyncClient) -> None:
    """10,001-character description (> 10,000) must render an error."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/submit",
        data={"category": "financial_fraud", "description": "C" * 10001, "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "10,000" in resp.text or "exceed" in resp.text


@pytest.mark.asyncio
async def test_submit_no_category_shows_error(client: AsyncClient) -> None:
    """Missing category must render an error, not create a report."""
    get_resp = await client.get("/submit")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/submit",
        data={"category": "", "description": "A valid description here", "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "category" in resp.text.lower()


# ─── status: invalid session cookie values are ignored ───────────────────────


@pytest.mark.asyncio
async def test_status_cookie_with_pipe_char_is_ignored(client: AsyncClient) -> None:
    """A cookie value containing '|' does not match _SESSION_KEY_RE and is treated as absent."""
    resp = await client.get(
        "/status",
        headers={"Cookie": "ow-status-session=bad|value"},
    )
    assert resp.status_code == 200
    # Should show the login form, not a report
    assert "Case Number" in resp.text or "case_number" in resp.text.lower()


@pytest.mark.asyncio
async def test_status_cookie_too_long_is_ignored(client: AsyncClient) -> None:
    """A cookie value of 87+ characters exceeds the _SESSION_KEY_RE {1,86} limit."""
    long_key = "a" * 87
    resp = await client.get(
        "/status",
        headers={"Cookie": f"ow-status-session={long_key}"},
    )
    assert resp.status_code == 200
    assert "Case Number" in resp.text or "case_number" in resp.text.lower()


# ─── reply_post: session token rotation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_reply_post_rotates_session_token(client: AsyncClient) -> None:
    """The ow-status-session cookie must have a new value after a reply is posted."""
    case_number, pin = await _submit_report(client)
    assert case_number and pin

    await _login_whistleblower(client, case_number, pin)
    session_before = client.cookies.get("ow-status-session")
    assert session_before is not None

    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    csrf_m = re.search(
        r'name="csrf_token"\s+value="([^"]+)"', get_resp.text
    )
    csrf_token = csrf_m.group(1) if csrf_m else csrf

    await client.post(
        "/reply",
        data={
            "content": "This is a whistleblower follow-up message.",
            "session_token": "unused",
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )

    session_after = client.cookies.get("ow-status-session")
    assert session_after is not None
    assert session_after != session_before


# ─── whistleblower attachment download ───────────────────────────────────────


@pytest.mark.asyncio
async def test_whistleblower_download_attachment_no_cookie_returns_401(
    client: AsyncClient,
) -> None:
    """GET /status/attachments/<id> without a session cookie must return 401."""
    resp = await client.get(
        f"/status/attachments/{uuid.uuid4()}",
        follow_redirects=False,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_whistleblower_download_attachment_unknown_redis_key_returns_401(
    client: AsyncClient,
) -> None:
    """Valid-format session cookie not present in Redis must return 401."""
    valid_key = secrets.token_urlsafe(32)
    resp = await client.get(
        f"/status/attachments/{uuid.uuid4()}",
        headers={"Cookie": f"ow-status-session={valid_key}"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# ─── status_logout ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_logout_clears_session_cookie(client: AsyncClient) -> None:
    """GET /status/logout must delete the ow-status-session cookie."""
    resp = await client.get("/status/logout", follow_redirects=False)
    assert resp.status_code == 303
    # FastAPI/Starlette sets max-age=0 or expires in the past to clear a cookie
    set_cookie = resp.headers.get("set-cookie", "")
    assert "ow-status-session" in set_cookie
    assert "max-age=0" in set_cookie.lower() or "expires" in set_cookie.lower()


@pytest.mark.asyncio
async def test_status_logout_without_cookie_does_not_crash(client: AsyncClient) -> None:
    """GET /status/logout with no session cookie must succeed without error."""
    resp = await client.get("/status/logout", follow_redirects=True)
    assert resp.status_code == 200
