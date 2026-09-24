"""v1.5 usability: field-tied errors, case-number search, readable audit log, copy."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from markupsafe import Markup
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.report import Report
from app.models.setup import SetupStatus
from app.models.user import AdminRole
from app.services.audit import ALL_ACTIONS
from app.services.mfa import generate_totp_secret
from app.services.report import create_report, get_reports_paginated
from app.templating import audit_detail, template_translator
from tests.conftest import _wizard_detect_step, _wizard_get_csrf, _wizard_skip_location_if_needed
from tests.test_v030_api import _login, _make_admin

_LOCALES = Path(__file__).resolve().parents[1] / "app" / "locales"


def _field(text: str, field_id: str) -> str:
    """The opening tag of the control with this id."""
    m = re.search(
        r'<(?:input|select|textarea)\b[^>]*\bid="' + re.escape(field_id) + r'"[^>]*>', text
    )
    assert m, f"no control #{field_id}"
    return m.group(0)


def _assert_invalid(text: str, field_id: str, error_id: str) -> None:
    tag = _field(text, field_id)
    assert 'aria-invalid="true"' in tag, tag
    described = re.search(r'aria-describedby="([^"]+)"', tag)
    assert described and error_id in described.group(1).split(), tag
    assert re.search(r'<p class="field-error" id="' + re.escape(error_id) + r'">[^<]+</p>', text)


async def _to_step(client: AsyncClient, target: str) -> str:
    """Walk the wizard (anonymous) to the category or description step; return its HTML."""
    resp = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    text, csrf = await _wizard_skip_location_if_needed(client, resp.text)
    if target == "category":
        return text
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": str(_wizard_detect_step(text)),
            "action": "next",
            "category": "financial_fraud",
        },
    )
    return resp.text


# ── 1. errors tied to fields ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_mode_error_marks_the_radios(client: AsyncClient) -> None:
    resp = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "step": "1",
            "action": "next",
            "submission_mode": "",
        },
    )
    _assert_invalid(resp.text, "mode-anonymous", "submission_mode-error")
    assert 'role="alert"' in resp.text  # the banner stays as the summary


@pytest.mark.asyncio
async def test_submit_category_error_marks_the_select(client: AsyncClient) -> None:
    text = await _to_step(client, "category")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(text),
            "step": str(_wizard_detect_step(text)),
            "action": "next",
            "category": "",
        },
    )
    _assert_invalid(resp.text, "category", "category-error")
    assert "category-hint" in _field(resp.text, "category")


@pytest.mark.asyncio
async def test_submit_description_error_marks_the_textarea(client: AsyncClient) -> None:
    text = await _to_step(client, "description")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(text),
            "step": str(_wizard_detect_step(text)),
            "action": "next",
            "description": "short",
        },
    )
    _assert_invalid(resp.text, "description", "description-error")
    assert "at least 10" in resp.text


@pytest.mark.asyncio
async def test_submit_file_error_marks_the_file_input(client: AsyncClient) -> None:
    text = await _to_step(client, "description")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(text),
            "step": str(_wizard_detect_step(text)),
            "action": "next",
            "description": "A description that is long enough to pass.",
        },
    )
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "step": str(_wizard_detect_step(resp.text)),
            "action": "next",
        },
        files={"files": ("tool.exe", b"MZ\x90\x00binary", "application/octet-stream")},
    )
    _assert_invalid(resp.text, "files", "files-error")
    assert "cannot be attached" in resp.text


@pytest.mark.asyncio
async def test_upload_error_follows_the_language(client: AsyncClient) -> None:
    """Upload refusals were English whatever language the whistleblower chose."""
    client.cookies.set("ow-lang", "de")
    text = await _to_step(client, "description")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(text),
            "step": str(_wizard_detect_step(text)),
            "action": "next",
            "description": "Eine Beschreibung, die lang genug ist.",
        },
    )
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "step": str(_wizard_detect_step(resp.text)),
            "action": "next",
        },
        files={"files": ("tool.exe", b"MZ\x90\x00binary", "application/octet-stream")},
    )
    assert "kann nicht angehängt werden" in resp.text
    assert "cannot be attached" not in resp.text


@pytest.mark.asyncio
async def test_submit_valid_step_has_no_invalid_field(client: AsyncClient) -> None:
    text = await _to_step(client, "description")
    assert 'aria-invalid="true"' not in text
    assert 'aria-describedby="description-hint char-counter"' in _field(text, "description")


@pytest.mark.asyncio
async def test_status_wrong_pin_marks_both_fields(client: AsyncClient) -> None:
    resp = await client.get("/status")
    resp = await client.post(
        "/status",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "case_number": f"OW-NONE-{uuid.uuid4().hex[:5]}",
            "pin": "wrong-pin",
        },
    )
    assert resp.status_code == 401
    _assert_invalid(resp.text, "case_number", "credentials-error")
    _assert_invalid(resp.text, "pin", "credentials-error")
    assert "No report matches this case number and PIN" in resp.text
    # No countdown of attempts: a correct PIN always works, nothing runs out.
    assert "Attempts left" not in resp.text


@pytest.mark.asyncio
async def test_status_message_is_translated(client: AsyncClient) -> None:
    client.cookies.set("ow-lang", "de")
    resp = await client.get("/status")
    resp = await client.post(
        "/status",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "case_number": f"OW-NONE-{uuid.uuid4().hex[:5]}",
            "pin": "wrong-pin",
        },
    )
    assert "Zu dieser Vorgangsnummer und PIN gibt es keine Meldung" in resp.text


@pytest.mark.asyncio
async def test_login_wrong_password_marks_both_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, _ = await _make_admin(db_session)
    resp = await client.get("/admin/login")
    resp = await client.post(
        "/admin/login",
        data={
            "csrf_token": resp.cookies.get("ow_csrf"),
            "username": admin.username,
            "password": "nope",
        },
    )
    assert resp.status_code == 401
    _assert_invalid(resp.text, "username", "credentials-error")
    _assert_invalid(resp.text, "password", "credentials-error")


@pytest.mark.asyncio
async def test_login_empty_fields_answer_on_the_form(client: AsyncClient) -> None:
    """The form is novalidate: blank fields get inline errors, not a 422 JSON body."""
    resp = await client.get("/admin/login")
    resp = await client.post(
        "/admin/login",
        data={
            "csrf_token": resp.cookies.get("ow_csrf"),
            "username": "",
            "password": "",
        },
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("text/html")
    _assert_invalid(resp.text, "username", "username-error")
    _assert_invalid(resp.text, "password", "password-error")


@pytest.mark.asyncio
async def test_mfa_wrong_code_marks_the_code_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, _ = await _make_admin(db_session)
    resp = await client.get("/admin/login")
    resp = await client.post(
        "/admin/login",
        data={
            "csrf_token": resp.cookies.get("ow_csrf"),
            "username": admin.username,
            "password": "AdminTest!Pass1",
        },
    )
    temp = re.search(r'name="temp_token" value="([^"]+)"', resp.text).group(1)  # type: ignore[union-attr]
    resp = await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": _wizard_get_csrf(resp.text),
            "temp_token": temp,
            "totp_code": "000001",
        },
    )
    _assert_invalid(resp.text, "totp_code", "totp_code-error")
    assert "totp-hint" in _field(resp.text, "totp_code")


@pytest.mark.asyncio
async def test_setup_wizard_errors_sit_next_to_their_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    row = (
        await db_session.execute(select(SetupStatus).where(SetupStatus.id == 1))
    ).scalar_one_or_none()
    was_completed = bool(row and row.completed)
    if row is not None:
        await db_session.execute(
            update(SetupStatus).where(SetupStatus.id == 1).values(completed=False)
        )
        await db_session.commit()
    try:
        resp = await client.get("/setup", follow_redirects=False)
        assert resp.status_code == 200
        resp = await client.post(
            "/setup",
            data={
                "csrf_token": resp.cookies.get("ow_csrf"),
                "username": "ab",
                "password": "short",
                "password_confirm": "different",
                "totp_secret": generate_totp_secret(),
                "totp_code": "000000",
            },
            follow_redirects=False,
        )
        for name in ("username", "password", "password_confirm", "totp_code"):
            _assert_invalid(resp.text, name, f"{name}-error")
        assert '<a href="#password_confirm">' in resp.text  # summary links to the field
    finally:
        if row is not None:
            await db_session.execute(
                update(SetupStatus).where(SetupStatus.id == 1).values(completed=was_completed)
            )
            await db_session.commit()


def test_plain_message_passed_through_t_is_never_marked_safe() -> None:
    t = template_translator("en")
    assert not isinstance(t("<img src=x onerror=alert(1)>.html"), Markup)
    assert isinstance(t("success.next.body.html"), Markup)


# ── 2. dashboard search ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_matches_case_number_substring(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, category="other", description="x" * 20, lang="en")
    digits = report.case_number.split("-")[-1]
    found, total = await get_reports_paginated(db_session, case_query=digits.lower(), per_page=100)
    assert report.id in {r.id for r in found}
    found, _ = await get_reports_paginated(
        db_session, case_query=report.case_number.lower(), per_page=100
    )
    assert [r.id for r in found] == [report.id]


@pytest.mark.asyncio
async def test_search_escapes_like_wildcards(db_session: AsyncSession) -> None:
    await create_report(db_session, category="other", description="x" * 20, lang="en")
    for wildcard in ("%", "_", "OW%"):
        found, total = await get_reports_paginated(db_session, case_query=wildcard)
        assert total == 0, wildcard


@pytest.mark.asyncio
async def test_search_keeps_the_case_manager_restriction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mine, _ = await create_report(db_session, category="other", description="x" * 20, lang="en")
    other, _ = await create_report(db_session, category="other", description="x" * 20, lang="en")
    cm, secret = await _make_admin(db_session, role=AdminRole.case_manager)
    await db_session.execute(
        update(Report).where(Report.id == mine.id).values(assigned_to_id=cm.id)
    )
    await db_session.commit()
    await _login(client, cm, secret)

    def row(case: str) -> str:
        return f'<span class="mono dash-nowrap">{case}</span>'

    resp = await client.get("/admin/dashboard", params={"q": "OW-"})
    assert row(mine.case_number) in resp.text
    assert row(other.case_number) not in resp.text
    resp = await client.get("/admin/dashboard", params={"q": other.case_number})
    assert row(other.case_number) not in resp.text


@pytest.mark.asyncio
async def test_dashboard_search_form_and_links_keep_the_query(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    report, _ = await create_report(db_session, category="other", description="x" * 20, lang="en")
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    q = report.case_number.split("-")[-1]
    resp = await client.get("/admin/dashboard", params={"q": q})
    assert resp.status_code == 200
    assert 'name="q"' in resp.text and f'value="{q}"' in resp.text
    assert "encrypted and cannot be searched" in resp.text
    # column sort links and status pills carry the search
    assert re.search(r"sort=case_number&dir=\w+&q=" + q + "\"", resp.text)
    assert re.search(r"&status=closed&q=" + q + "\"", resp.text)
    assert report.case_number in resp.text
    resp = await client.get("/admin/dashboard", params={"q": "zz-no-such-case"})
    assert "No case number contains" in resp.text


# ── 3. readable audit log ────────────────────────────────────────────────────


def test_every_audit_action_has_a_label_in_every_language() -> None:
    for lang in ("en", "de", "fr", "pt-br"):
        strings = json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        missing = [a for a in ALL_ACTIONS if f"audit.action.{a}" not in strings]
        assert not missing, (lang, missing)


def test_audit_detail_splits_json_and_keeps_free_text() -> None:
    assert audit_detail('{"old_status": "received", "x": null}') == [
        ("old_status", "received"),
        ("x", "—"),
    ]
    assert audit_detail("not json") == [("", "not json")]
    assert audit_detail("[1, 2]") == [("", "[1, 2]")]
    assert audit_detail(None) == []


@pytest.mark.asyncio
async def test_audit_log_shows_labels_and_readable_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, secret = await _make_admin(db_session)
    report, _ = await create_report(db_session, category="other", description="x" * 20, lang="en")
    db_session.add_all(
        [
            AuditLog(
                id=uuid.uuid4(),
                admin_id=admin.id,
                admin_username=admin.username,
                action="report.status_changed",
                report_id=report.id,
                detail=json.dumps({"old_status": "received", "new_status": "in_review"}),
            ),
            AuditLog(
                id=uuid.uuid4(),
                admin_id=admin.id,
                admin_username=admin.username,
                action="custom.unknown",
                report_id=report.id,
                detail=json.dumps({"weird_key": "<script>x</script>"}),
            ),
        ]
    )
    await db_session.commit()
    await _login(client, admin, secret)

    for url in ("/admin/audit-log", f"/admin/reports/{report.id}"):
        resp = await client.get(url)
        assert "Status changed" in resp.text, url
        assert "<dt>From</dt><dd>Received</dd>" in resp.text, url
        assert "<dt>To</dt><dd>In review</dd>" in resp.text, url
        assert "custom.unknown" in resp.text and "weird_key" in resp.text, url  # shown plainly
        assert "<script>x</script>" not in resp.text, url  # escaped
        assert "&lt;script&gt;x&lt;/script&gt;" in resp.text, url
        assert '{"old_status"' not in resp.text, url

    csv = (await client.get("/admin/audit-log/export.csv")).text
    assert csv.splitlines()[0] == "timestamp,admin,action,action_label,report_id,detail"
    assert "report.status_changed,Status changed," in csv


@pytest.mark.asyncio
async def test_location_creation_is_logged_as_location(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, secret = await _make_admin(db_session)
    await _login(client, admin, secret)
    csrf = _wizard_get_csrf((await client.get("/admin/locations")).text)
    code = f"LOC-{uuid.uuid4().hex[:6]}".upper()
    await client.post(
        "/admin/locations",
        data={
            "csrf_token": csrf,
            "name": "Test site",
            "code": code,
            "description": "",
            "sort_order": "0",
        },
    )
    rows = (
        (await db_session.execute(select(AuditLog.action).where(AuditLog.detail.contains(code))))
        .scalars()
        .all()
    )
    assert rows == ["location.created"]
    # Remove it again so later wizard tests keep their usual step count.
    from app.models.location import Location

    await db_session.execute(delete(Location).where(Location.code == code))
    await db_session.commit()


# ── 4. copy ──────────────────────────────────────────────────────────────────


def test_whistleblower_copy_makes_no_absolute_promise() -> None:
    for lang, words in {
        "en": ("guarantee", "completely protected", "UUID", "Two-Factor"),
        "de": ("garantiert", "vollständig geschützt", "UUID", "Zwei-Faktor-Zugang"),
        "fr": ("garantie", "totalement protégée", "UUID"),
        "pt-br": ("garantida", "completamente protegida", "UUID"),
    }.items():
        strings = json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        public = {
            k: v for k, v in strings.items() if k.startswith(("submit.", "status.", "success."))
        }
        for key, value in public.items():
            for word in words:
                assert word.lower() not in value.lower(), (lang, key, value)


@pytest.mark.asyncio
async def test_demo_banner_follows_the_language(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.templating import templates

    monkeypatch.setitem(templates.env.globals, "is_demo", True)
    client.cookies.set("ow-lang", "fr")
    resp = await client.get("/status")
    assert "démo publique" in resp.text
    assert "Essayez ces signalements" in resp.text
    assert "This is a live demonstration" not in resp.text
