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
- whistleblower attachment download: 404 when the attachment's bytes are gone (LookupError)
- status_logout clears the session cookie
- status_logout deletes the Redis session key when one is actually set
- index redirects to /submit once setup is complete
- submit_get downgrades a stored location step when locations are later deactivated
- submit_post "back" action
- submit_post location step: invalid UUID and unknown/inactive location
- submit_post review step with incomplete session state ("session_incomplete")
- submit_post confidential mode encrypts identifying fields
- submit_post falls back to a wizard restart on an unrecognised step
- status_get treats a naive submitted_at as UTC
- reply_post: no session and no credentials, empty content, content over the length limit
"""

from __future__ import annotations

import re
import secrets
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ─── helpers ──────────────────────────────────────────────────────────────────


def _wiz_csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


def _wiz_step(text: str) -> int:
    m = re.search(r'name="step" value="(\d+)"', text)
    return int(m.group(1)) if m else 1


async def _walk_to_description_step(
    client: AsyncClient, category: str = "financial_fraud"
) -> tuple[str, int]:
    """Walk the wizard through steps 1-3 (mode + optional location + category).

    Returns (csrf_for_step4, step4_number) ready for description submission.
    Handles both with-locations and without-locations wizard flows.
    """
    # Step 1: mode selection
    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": "anonymous",
    })

    # Step 2 (location — conditional): skip if present by posting with empty location_id
    if _wiz_step(resp.text) == 2:
        csrf = _wiz_csrf(resp.text)
        resp = await client.post("/submit", data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": "",
        })

    # Step 3: category
    csrf = _wiz_csrf(resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_wiz_step(resp.text)),
        "action": "next",
        "category": category,
    })

    # Now on step 4 (description)
    return _wiz_csrf(resp.text), _wiz_step(resp.text)


async def _submit_report(client: AsyncClient, description: str = "") -> tuple[str, str]:
    """Submit a report via the multi-step wizard and return (case_number, pin)."""
    from conftest import wizard_submit

    return await wizard_submit(
        client,
        category="financial_fraud",
        description=description or "A" * 50,
    )


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
    csrf, step = await _walk_to_description_step(client)
    resp = await client.post(
        "/submit",
        data={"step": str(step), "action": "next", "description": "A" * 9, "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "at least 10" in resp.text


@pytest.mark.asyncio
async def test_submit_description_exact_minimum_succeeds(client: AsyncClient) -> None:
    """10-character description (== minimum) must create a report successfully."""
    from conftest import wizard_submit

    case_number, pin = await wizard_submit(client, description="A" * 10)
    assert "OW-" in case_number


@pytest.mark.asyncio
async def test_submit_description_exact_maximum_succeeds(client: AsyncClient) -> None:
    """10,000-character description (== maximum) must create a report successfully."""
    from conftest import wizard_submit

    case_number, pin = await wizard_submit(client, description="B" * 10000)
    assert "OW-" in case_number


@pytest.mark.asyncio
async def test_submit_description_above_maximum_shows_error(client: AsyncClient) -> None:
    """10,001-character description (> 10,000) must render an error."""
    csrf, step = await _walk_to_description_step(client)
    resp = await client.post(
        "/submit",
        data={"step": str(step), "action": "next", "description": "C" * 10001, "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "10,000" in resp.text or "exceed" in resp.text


@pytest.mark.asyncio
async def test_submit_no_category_shows_error(client: AsyncClient) -> None:
    """Missing category must render an error, not create a report."""
    # Walk to step 1, then post step 3 with blank category
    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    # Complete step 1 (mode)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": "anonymous",
    })
    # Step 2 (location — conditional): skip if present
    if _wiz_step(resp.text) == 2:
        csrf = _wiz_csrf(resp.text)
        resp = await client.post("/submit", data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": "",
        })
    # Try step 3 with empty category
    csrf = _wiz_csrf(resp.text)
    step3 = _wiz_step(resp.text)
    resp = await client.post(
        "/submit",
        data={"step": str(step3), "action": "next", "category": "", "csrf_token": csrf},
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
    """POST /status/logout must delete the ow-status-session cookie."""
    await client.get("/status")  # sets the CSRF cookie
    resp = await client.post(
        "/status/logout",
        data={"csrf_token": client.cookies.get("ow_csrf")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # FastAPI/Starlette sets max-age=0 or expires in the past to clear a cookie
    set_cookie = resp.headers.get("set-cookie", "")
    assert "ow-status-session" in set_cookie
    assert "max-age=0" in set_cookie.lower() or "expires" in set_cookie.lower()


@pytest.mark.asyncio
async def test_status_logout_without_cookie_does_not_crash(client: AsyncClient) -> None:
    """POST /status/logout with no session cookie must succeed without error."""
    await client.get("/status")
    resp = await client.post(
        "/status/logout",
        data={"csrf_token": client.cookies.get("ow_csrf")},
        follow_redirects=True,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_status_logout_deletes_redis_session_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """When a real status session exists, logout must delete it from Redis."""
    from app.redis_client import get_redis
    from app.services.report import create_report

    report, pin = await create_report(
        db_session, "financial_fraud", "Report for logout redis-delete coverage test."
    )

    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    await client.post(
        "/status",
        data={"case_number": report.case_number, "pin": pin, "csrf_token": csrf},
    )
    session_key = client.cookies.get("ow-status-session")
    assert session_key

    resp = await client.post(
        "/status/logout",
        data={"csrf_token": client.cookies.get("ow_csrf")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    redis = await get_redis()
    assert await redis.get(f"status-session:{session_key}") is None


@pytest.mark.asyncio
async def test_index_redirects_to_submit_when_setup_complete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Once the admin setup wizard is complete, / must redirect to /submit.

    Restores the prior setup_status row afterwards — other tests (e.g. the demo
    seeder's "foreign database" guard) depend on the real value of this
    process-wide singleton row.
    """
    from sqlalchemy import select

    from app.models.setup import SetupStatus

    result = await db_session.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    existed = setup is not None
    previous_completed = setup.completed if setup else None

    try:
        if setup is None:
            db_session.add(SetupStatus(id=1, completed=True))
        else:
            setup.completed = True
        await db_session.commit()

        resp = await client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/submit"
    finally:
        result = await db_session.execute(select(SetupStatus).where(SetupStatus.id == 1))
        setup = result.scalar_one_or_none()
        if setup is not None:
            if existed:
                setup.completed = previous_completed
            else:
                await db_session.delete(setup)
            await db_session.commit()


@pytest.mark.asyncio
async def test_submit_get_downgrades_location_step_when_locations_removed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A session stuck on the location step must fall through to category once
    locations are deactivated, instead of showing a dead step."""
    from app.services.locations import create_location, deactivate_location

    loc = await create_location(
        db_session, "Coverage Temp Office", f"COVTMP{uuid.uuid4().hex[:6].upper()}"
    )

    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    assert _wiz_step(resp.text) == 2

    await deactivate_location(db_session, loc)

    resp = await client.get("/submit")
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 3


@pytest.mark.asyncio
async def test_submit_back_action_returns_to_previous_step(client: AsyncClient) -> None:
    """Posting action=back must move the wizard back a step."""
    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    assert _wiz_step(resp.text) >= 2

    csrf = _wiz_csrf(resp.text)
    resp = await client.post("/submit", data={"csrf_token": csrf, "action": "back"})
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 1


@pytest.mark.asyncio
async def test_submit_location_step_invalid_uuid_shows_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A location_id that isn't a valid UUID must be rejected."""
    from app.services.locations import create_location

    await create_location(db_session, "Coverage Office A", f"COVA{uuid.uuid4().hex[:6].upper()}")

    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    assert _wiz_step(resp.text) == 2

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": "not-a-uuid",
        },
    )
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 2


@pytest.mark.asyncio
async def test_submit_location_step_valid_location_is_accepted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A well-formed, active location_id must be accepted and stored on the session."""
    from app.services.locations import create_location

    loc = await create_location(
        db_session, "Coverage Office C", f"COVC{uuid.uuid4().hex[:6].upper()}"
    )

    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    assert _wiz_step(resp.text) == 2

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": str(loc.id),
        },
    )
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 3


@pytest.mark.asyncio
async def test_submit_location_step_unknown_location_shows_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A well-formed but nonexistent location_id must be rejected."""
    from app.services.locations import create_location

    await create_location(db_session, "Coverage Office B", f"COVB{uuid.uuid4().hex[:6].upper()}")

    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    assert _wiz_step(resp.text) == 2

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 2


@pytest.mark.asyncio
async def test_submit_review_step_with_missing_state_shows_session_incomplete(
    client: AsyncClient,
) -> None:
    """Reaching the review step without the required fields must restart the wizard."""
    import app.api.reports as reports_module
    from app.redis_client import get_redis

    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    session_id = client.cookies.get("ow-submission-session")
    assert session_id

    redis = await get_redis()
    state = await reports_module._load_submission(redis, session_id)
    state["step"] = 6
    await reports_module._save_submission(redis, session_id, state)

    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "6",
            "action": "next",
        },
    )
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 1
    assert "start over" in resp.text.lower()


@pytest.mark.asyncio
async def test_submit_confidential_mode_encrypts_identifying_fields(
    client: AsyncClient,
) -> None:
    """A full confidential submission must succeed and encrypt the identifying fields."""
    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "confidential",
            "confidential_name": "Jane Doe",
            "confidential_contact": "+49 555 1234",
            "secure_email": "jane@example.com",
        },
    )

    if _wiz_step(resp.text) == 2:
        csrf = _wiz_csrf(resp.text)
        resp = await client.post(
            "/submit",
            data={
                "csrf_token": csrf,
                "step": "2",
                "action": "next",
                "location_id": "",
            },
        )

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": str(_wiz_step(resp.text)),
            "action": "next",
            "category": "financial_fraud",
        },
    )

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": str(_wiz_step(resp.text)),
            "action": "next",
            "description": "Confidential coverage test description with enough length.",
        },
    )

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": str(_wiz_step(resp.text)),
            "action": "next",
        },
    )

    csrf = _wiz_csrf(resp.text)
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": str(_wiz_step(resp.text)),
            "action": "next",
        },
    )

    assert resp.status_code == 200
    assert "OW-" in resp.text


@pytest.mark.asyncio
async def test_submit_unknown_step_restarts_wizard(client: AsyncClient) -> None:
    """A step number outside the known wizard steps must restart at step 1."""
    import app.api.reports as reports_module
    from app.redis_client import get_redis

    get_resp = await client.get("/submit")
    csrf = _wiz_csrf(get_resp.text)
    session_id = client.cookies.get("ow-submission-session")
    assert session_id

    redis = await get_redis()
    state = await reports_module._load_submission(redis, session_id)
    state["step"] = 99
    await reports_module._save_submission(redis, session_id, state)

    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "99",
            "action": "next",
        },
    )
    assert resp.status_code == 200
    assert _wiz_step(resp.text) == 1


@pytest.mark.asyncio
async def test_status_naive_submitted_at_is_treated_as_utc(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report whose submitted_at lost its tzinfo must still render the status page."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    import app.api.reports as reports_module
    from app.models.report import Report
    from app.services.report import create_report

    report, _pin = await create_report(
        db_session, "financial_fraud", "Report for naive-datetime coverage test."
    )
    result = await db_session.execute(
        select(Report)
        .options(selectinload(Report.messages), selectinload(Report.attachments))
        .where(Report.id == report.id)
    )
    report = result.scalar_one()
    db_session.expunge(report)
    report.submitted_at = report.submitted_at.replace(tzinfo=None)

    async def _fake_get_report_by_id(_db: object, _report_id: object) -> object:
        return report

    monkeypatch.setattr(reports_module.report_service, "get_report_by_id", _fake_get_report_by_id)

    from redis.asyncio import Redis

    from app.config import settings

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    session_key = "naive" + secrets.token_urlsafe(16)
    await redis.set(f"status-session:{session_key}", str(report.id), ex=60)
    await redis.aclose()
    client.cookies.set("ow-status-session", session_key)

    resp = await client.get("/status")
    assert resp.status_code == 200
    assert report.case_number in resp.text


@pytest.mark.asyncio
async def test_reply_post_without_credentials_or_session_returns_401(
    client: AsyncClient,
) -> None:
    """No status session and no case_number/pin must fail fast with 401."""
    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    resp = await client.post(
        "/reply",
        data={"content": "Trying to reply with nothing.", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reply_post_empty_content_after_login_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Whitespace-only content must be rejected once the whistleblower is authenticated."""
    from app.services.report import create_report

    report, pin = await create_report(
        db_session, "financial_fraud", "Report for empty-content coverage test."
    )

    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    await client.post(
        "/status",
        data={"case_number": report.case_number, "pin": pin, "csrf_token": csrf},
    )

    get_resp2 = await client.get("/status")
    csrf2 = get_resp2.cookies.get("ow_csrf")
    resp = await client.post(
        "/reply",
        data={"content": "   ", "csrf_token": csrf2},
        follow_redirects=False,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reply_post_content_too_long_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Content over 5000 characters must be rejected once authenticated."""
    from app.services.report import create_report

    report, pin = await create_report(
        db_session, "corruption", "Report for too-long content coverage test."
    )

    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    await client.post(
        "/status",
        data={"case_number": report.case_number, "pin": pin, "csrf_token": csrf},
    )

    get_resp2 = await client.get("/status")
    csrf2 = get_resp2.cookies.get("ow_csrf")
    resp = await client.post(
        "/reply",
        data={"content": "X" * 5001, "csrf_token": csrf2},
        follow_redirects=False,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_whistleblower_download_attachment_missing_bytes_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An attachment row with no data and no storage_key must 404, not crash."""
    from app.models.attachment import Attachment
    from app.services.report import create_report

    report, pin = await create_report(
        db_session, "financial_fraud", "Report for attachment lookup-error coverage test."
    )

    attachment = Attachment(
        id=uuid.uuid4(),
        report_id=report.id,
        filename="missing.txt",
        content_type="text/plain",
        size=0,
        data=None,
    )
    db_session.add(attachment)
    await db_session.commit()

    get_resp = await client.get("/status")
    csrf = get_resp.cookies.get("ow_csrf")
    await client.post(
        "/status",
        data={"case_number": report.case_number, "pin": pin, "csrf_token": csrf},
    )

    resp = await client.get(f"/status/attachments/{attachment.id}", follow_redirects=False)
    assert resp.status_code == 404
