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


# ── Account management: who may act on whom ─────────────────────────────────


@pytest_asyncio.fixture(loop_scope="function")
async def acting_as(client: AsyncClient, no_csrf):  # type: ignore[no-untyped-def]
    from app.api.deps import get_current_admin
    from app.main import app

    def _set(user):  # type: ignore[no-untyped-def]
        app.dependency_overrides[get_current_admin] = lambda: user

    yield client, _set
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_an_admin_cannot_reactivate_a_superadmin_another_superadmin_disabled(
    acting_as, db_session: AsyncSession
) -> None:
    from app.models.user import AdminRole

    client, act = acting_as
    target = await _totp_user(db_session, AdminRole.superadmin)
    target.is_active = False
    admin = await _totp_user(db_session, AdminRole.admin)
    await db_session.commit()

    act(admin)
    resp = await client.post(f"/admin/users/{target.id}/reactivate", follow_redirects=False)
    assert resp.status_code == 403
    await db_session.refresh(target)
    assert target.is_active is False


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["deactivate", "role"])
async def test_a_demo_visitor_cannot_lock_the_next_visitor_out(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from sqlalchemy import select

    from app.config import settings
    from app.models.user import AdminRole, AdminUser
    from app.services.demo_seed import DEMO_CM_USERNAME

    monkeypatch.setattr(settings, "demo_mode", True)
    client, act = acting_as
    demo_cm = await db_session.scalar(
        select(AdminUser).where(AdminUser.username == DEMO_CM_USERNAME)
    )
    if demo_cm is None:
        demo_cm = await _totp_user(db_session, AdminRole.case_manager)
        demo_cm.username = DEMO_CM_USERNAME
        await db_session.commit()
    act(await _totp_user(db_session, AdminRole.superadmin))

    data = {"role": AdminRole.admin.value} if action == "role" else {}
    resp = await client.post(
        f"/admin/users/{demo_cm.id}/{action}", data=data, follow_redirects=False
    )
    assert resp.status_code == 403


# ── Four-eyes deletion leaves a record ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_confirmed_deletion_is_in_the_audit_log(
    acting_as, db_session: AsyncSession
) -> None:
    import json as _json

    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.user import AdminRole
    from app.services.audit import AuditAction
    from app.services.report import create_report

    client, act = acting_as
    report, _ = await create_report(db_session, "financial_fraud", "A report to delete, agreed.")
    requester = await _totp_user(db_session, AdminRole.admin)
    confirmer = await _totp_user(db_session, AdminRole.admin)
    case = report.case_number

    act(requester)
    assert (await client.post(
        f"/admin/reports/{report.id}/request-delete", follow_redirects=False
    )).status_code == 302
    act(confirmer)
    resp = await client.post(f"/admin/reports/{report.id}/confirm-delete", follow_redirects=False)
    assert resp.status_code == 302

    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.REPORT_DELETE_CONFIRMED)
        .execution_options(populate_existing=True)
    )).scalars().all()
    details = [_json.loads(r.detail or "{}") for r in rows]
    mine = [d for d in details if d.get("case_number") == case]
    assert mine == [{
        "case_number": case,
        "requested_by": requester.username,
        "confirmed_by": confirmer.username,
    }]


# ── Sign-in: LDAP next to local accounts, and the lockout counter ────────────


@pytest.mark.asyncio
async def test_a_local_account_signs_in_while_ldap_is_on(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wizard's superadmin has a local password. Switching LDAP on used
    to send every sign-in to the directory only: the owner was locked out."""
    from unittest.mock import AsyncMock

    from app.config import settings
    from app.services import ldap_auth

    monkeypatch.setattr(settings, "ldap_enabled", True)
    monkeypatch.setattr(
        ldap_auth, "authenticate_ldap",
        AsyncMock(side_effect=ldap_auth.LDAPAuthError("LDAP user not found")),
    )
    user = await _totp_user(db_session)
    resp = await client.post(
        "/admin/login", data={"username": user.username, "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert resp.status_code == 200 and 'name="temp_token"' in resp.text


@pytest.mark.asyncio
async def test_a_directory_user_named_like_a_local_account_is_refused_not_a_500(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.config import settings
    from app.services import ldap_auth

    user = await _totp_user(db_session)
    monkeypatch.setattr(settings, "ldap_enabled", True)
    monkeypatch.setattr(
        ldap_auth, "authenticate_ldap",
        AsyncMock(return_value=ldap_auth.LDAPUserInfo(username=user.username, email=None)),
    )
    resp = await client.post(
        "/admin/login", data={"username": user.username, "password": "directory-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_a_directory_entry_without_the_username_attribute_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The typed string used to stand in: 'ALICE' provisioned a second
    account next to 'alice', with no second factor enrolled yet."""
    from unittest.mock import MagicMock, patch

    from app.config import settings
    from app.services import ldap_auth

    for name, value in {
        "ldap_enabled": True, "ldap_server": "dir.example.org", "ldap_port": 389,
        "ldap_use_ssl": False, "ldap_start_tls": False, "ldap_bind_dn": "cn=svc",
        "ldap_bind_password": "svc-pw", "ldap_base_dn": "dc=example,dc=org",
        "ldap_user_filter": "(uid={username})", "ldap_attr_username": "uid",
        "ldap_attr_email": "mail",
    }.items():
        monkeypatch.setattr(settings, name, value)
    conn = MagicMock()
    conn.search_s.return_value = [("uid=alice,dc=example,dc=org", {"mail": [b"a@example.org"]})]
    with patch("ldap.initialize", return_value=conn), pytest.raises(ldap_auth.LDAPAuthError):
        ldap_auth._authenticate_ldap_sync("ALICE", "pw")


@pytest.mark.asyncio
async def test_case_variants_of_a_username_share_one_lockout(client: AsyncClient) -> None:
    import uuid

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import rate_limit as rl

    redis = await get_redis()
    name = f"alice{uuid.uuid4().hex[:6]}"
    for _ in range(settings.max_login_attempts):
        await rl.record_admin_login_failure(redis, name)
    assert not await rl.check_admin_login_attempts(redis, f" {name.upper()}")


@pytest.mark.asyncio
async def test_the_lock_lasts_lockout_minutes_from_the_last_failure(client: AsyncClient) -> None:
    """The window used to start at the first failure: ten wrong passwords
    spread over 29 minutes gave a one-minute lock."""
    import uuid

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import rate_limit as rl

    redis = await get_redis()
    name = f"bob{uuid.uuid4().hex[:6]}"
    await rl.record_admin_login_failure(redis, name)
    key = f"openwhistle:admin_ratelimit:{name}"
    await redis.expire(key, 60)  # the first failure was long ago
    for _ in range(settings.max_login_attempts - 1):
        await rl.record_admin_login_failure(redis, name)
    assert await redis.ttl(key) > settings.login_lockout_minutes * 60 - 5


# ── §17 HinSchG deadlines: one computation ──────────────────────────────────


def _frozen_datetime(at):  # type: ignore[no-untyped-def]
    from datetime import datetime as real

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return at if tz else at.replace(tzinfo=None)

    return Frozen


@pytest.mark.asyncio
async def test_every_report_has_a_feedback_deadline_from_receipt(
    db_session: AsyncSession,
) -> None:
    """Without an acknowledgement §17 Abs. 2 still runs: three months and
    seven days after receipt. A case moved straight to 'in review' had no
    deadline and never triggered a reminder."""
    from datetime import timedelta

    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Deadline from receipt, please.")
    assert report.feedback_due_at is not None
    lower = report.submitted_at + timedelta(days=7 + 89)
    upper = report.submitted_at + timedelta(days=7 + 92)
    assert lower <= report.feedback_due_at <= upper


@pytest.mark.asyncio
async def test_three_months_are_calendar_months(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acknowledged on 1 February 2027: feedback by 1 May, not 2 May (+90 days)."""
    from datetime import UTC, datetime

    from app.services import report as report_service

    report, _ = await report_service.create_report(
        db_session, "financial_fraud", "Acknowledged on the first of February."
    )
    report.submitted_at = datetime(2027, 1, 30, tzinfo=UTC)
    await db_session.commit()
    frozen = _frozen_datetime(datetime(2027, 2, 1, 9, tzinfo=UTC))
    monkeypatch.setattr(report_service, "datetime", frozen)
    await report_service.acknowledge_report(db_session, report)
    assert report.feedback_due_at == datetime(2027, 5, 1, 9, tzinfo=UTC)


def test_the_pdf_calls_seven_days_and_twelve_hours_late() -> None:
    """``timedelta.days`` truncates: 7 d 12 h was 7, so 'Compliant'."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.services import pdf

    submitted = datetime(2027, 3, 1, tzinfo=UTC)
    report = SimpleNamespace(
        submitted_at=submitted, acknowledged_at=submitted + timedelta(days=7, hours=12),
        feedback_due_at=None, closed_at=None,
    )
    assert pdf._ack_label(report, datetime(2027, 3, 20, tzinfo=UTC)) == "OK Acknowledged (late)"


@pytest.mark.asyncio
async def test_the_ack_rate_counts_only_reports_whose_week_is_over(
    db_session: AsyncSession, throwaway_db: AsyncSession
) -> None:
    """One on time, one received today: 100 %, not 50 %."""
    from datetime import UTC, datetime, timedelta

    from app.services import report as report_service

    on_time, _ = await report_service.create_report(
        throwaway_db, "financial_fraud", "Acknowledged in time."
    )
    on_time.submitted_at = datetime.now(UTC) - timedelta(days=20)
    on_time.acknowledged_at = on_time.submitted_at + timedelta(days=2)
    await report_service.create_report(throwaway_db, "financial_fraud", "Received a moment ago.")
    await throwaway_db.commit()
    stats = await report_service.get_dashboard_stats(throwaway_db)
    assert stats["sla_7day_rate"] == 100


@pytest.mark.asyncio
async def test_the_dashboard_and_the_case_page_agree_on_the_last_day(
    acting_as, db_session: AsyncSession
) -> None:
    """Twelve hours before the deadline the dashboard said 'overdue' and the
    case page '0 days remaining'."""
    from datetime import UTC, datetime, timedelta

    from app.models.user import AdminRole
    from app.services.report import create_report

    client, act = acting_as
    report, _ = await create_report(db_session, "financial_fraud", "Twelve hours left on this one.")
    report.acknowledged_at = datetime.now(UTC) - timedelta(days=80)
    report.feedback_due_at = datetime.now(UTC) + timedelta(hours=12)
    await db_session.commit()
    act(await _totp_user(db_session, AdminRole.admin))

    dash = (await client.post("/admin/dashboard", data={"q": report.case_number})).text
    case = (await client.get(f"/admin/reports/{report.id}")).text
    row = dash[dash.index(f'<span class="mono dash-nowrap">{report.case_number}'):]
    row = row[:row.index("</tr>")]
    assert "sla-overdue" not in row and "sla-overdue" not in case.split("detail.sla3m")[-1][:600]


# ── Form input: what the browser allows, the server accepts; the rest is a 4xx ─


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "data"), [
    ("/admin/categories", {"slug": "s" * 65, "label_en": "x", "label_de": "x"}),
    ("/admin/categories", {"slug": "ok", "label_en": "x" * 129, "label_de": "x"}),
    ("/admin/categories", {"slug": "big", "label_en": "x", "label_de": "x",
                           "sort_order": "99999999999"}),
    ("/admin/locations", {"name": "n", "code": "C" * 33}),
    ("/admin/locations", {"name": "n" * 129, "code": "C1"}),
    ("/admin/locations", {"name": "n", "code": "C2", "description": "d" * 513}),
    ("/admin/organisations", {"name": "n" * 129, "slug": "org-long-name"}),
])
async def test_an_oversized_admin_field_is_refused_not_a_500(
    acting_as, db_session: AsyncSession, path: str, data: dict[str, str]
) -> None:
    from app.models.user import AdminRole

    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.superadmin))
    resp = await client.post(path, data=data, follow_redirects=False)
    assert 400 <= resp.status_code < 500


@pytest.mark.asyncio
async def test_an_admin_reply_has_the_limit_its_form_shows(
    acting_as, db_session: AsyncSession
) -> None:
    from app.models.user import AdminRole
    from app.services.report import create_report

    client, act = acting_as
    report, _ = await create_report(db_session, "financial_fraud", "Unbounded replies, anyone?")
    act(await _totp_user(db_session, AdminRole.admin))
    for path in ("reply", "notes"):
        resp = await client.post(
            f"/admin/reports/{report.id}/{path}", data={"content": "x" * 5001},
            follow_redirects=False,
        )
        assert resp.status_code == 422, path


@pytest.mark.asyncio
async def test_line_breaks_count_once_as_in_the_browser(
    acting_as, db_session: AsyncSession
) -> None:
    """A browser submits a textarea's line breaks as CRLF; maxlength counts
    each as one. 500 characters with a line break, as typed: accepted."""
    from app.models.report import SubmissionMode
    from app.models.user import AdminRole
    from app.services.crypto import encrypt
    from app.services.report import create_report

    client, act = acting_as
    report, _ = await create_report(
        db_session, "financial_fraud", "Identity reveal with a long reason.",
        submission_mode=SubmissionMode.confidential, confidential_name_enc=encrypt("Jane"),
    )
    act(await _totp_user(db_session, AdminRole.admin))
    reason = "r" * 250 + "\r\n" + "r" * 249  # 500 in the page (maxlength), 501 on the wire
    resp = await client.post(
        f"/admin/reports/{report.id}/identity", data={"reason": reason},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text[:300]


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["jane.example.com", "jane@", "jane@proton", "a b@c.de"])
async def test_a_mistyped_notification_address_is_caught_on_the_form(
    client: AsyncClient, email: str
) -> None:
    """The form is novalidate, so type=email checks nothing: the address was
    stored as typed and the whistleblower waited for mail that never came."""
    from tests.test_submit_prg import _post, _step

    await _post(
        client, submission_mode="confidential", confidential_name="Jane", secure_email=email
    )
    page = (await client.get("/submit")).text
    assert _step(page) == 1
    assert 'value="Jane"' in page


@pytest.mark.asyncio
async def test_a_real_notification_address_passes(client: AsyncClient) -> None:
    from tests.test_submit_prg import _post, _step

    await _post(client, submission_mode="confidential", secure_email="jane.doe+ow@proton.me")
    assert _step((await client.get("/submit")).text) != 1


@pytest.mark.asyncio
async def test_a_closed_case_takes_no_reply_and_says_so(
    client: AsyncClient, db_session: AsyncSession, no_csrf
) -> None:
    """The status page hides the reply form of a closed case; the server took
    the reply anyway, onto a case retention will delete."""
    from sqlalchemy import func, select

    from app.models.report import ReportMessage as Message
    from app.models.report import ReportStatus
    from app.services.report import create_report

    report, pin = await create_report(db_session, "financial_fraud", "Closed before the reply.")
    report.status = ReportStatus.closed
    await db_session.commit()
    before = await db_session.scalar(
        select(func.count()).select_from(Message).where(Message.report_id == report.id)
    )

    resp = await client.post("/reply", data={
        "case_number": report.case_number, "pin": pin, "content": "Late addition.",
    }, follow_redirects=False)

    after = await db_session.scalar(
        select(func.count()).select_from(Message).where(Message.report_id == report.id)
    )
    assert after == before
    page = await client.get(resp.headers["location"])
    assert "was not sent" in page.text
