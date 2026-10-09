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
    resp = await client.post(
        "/setup",
        data={
            "username": "owner210",
            "password": "SecureTestPassword123!",
            "password_confirm": "SecureTestPassword123!",
            "totp_secret": secret,
            "totp_code": code,
            "csrf_token": get_resp.cookies.get("ow_csrf"),
            "setup_token": await setup_token(),
        },
        follow_redirects=False,
    )
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
            "/status/logout",
            data={"csrf_token": token.group(1)},
            headers=headers,
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
    assert (
        await client.post(f"/admin/reports/{report.id}/request-delete", follow_redirects=False)
    ).status_code == 302
    act(confirmer)
    resp = await client.post(f"/admin/reports/{report.id}/confirm-delete", follow_redirects=False)
    assert resp.status_code == 302

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == AuditAction.REPORT_DELETE_CONFIRMED)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    details = [_json.loads(r.detail or "{}") for r in rows]
    mine = [d for d in details if d.get("case_number") == case]
    assert mine == [
        {
            "case_number": case,
            "requested_by": requester.username,
            "confirmed_by": confirmer.username,
        }
    ]


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
        ldap_auth,
        "authenticate_ldap",
        AsyncMock(side_effect=ldap_auth.LDAPAuthError("LDAP user not found")),
    )
    user = await _totp_user(db_session)
    resp = await client.post(
        "/admin/login",
        data={"username": user.username, "password": "TestPassword123!"},
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
        ldap_auth,
        "authenticate_ldap",
        AsyncMock(return_value=ldap_auth.LDAPUserInfo(username=user.username, email=None)),
    )
    resp = await client.post(
        "/admin/login",
        data={"username": user.username, "password": "directory-password"},
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
        "ldap_enabled": True,
        "ldap_server": "dir.example.org",
        "ldap_port": 389,
        "ldap_use_ssl": False,
        "ldap_start_tls": False,
        "ldap_bind_dn": "cn=svc",
        "ldap_bind_password": "svc-pw",
        "ldap_base_dn": "dc=example,dc=org",
        "ldap_user_filter": "(uid={username})",
        "ldap_attr_username": "uid",
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
        submitted_at=submitted,
        acknowledged_at=submitted + timedelta(days=7, hours=12),
        feedback_due_at=None,
        closed_at=None,
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
    row = dash[dash.index(f'<span class="mono dash-nowrap">{report.case_number}') :]
    row = row[: row.index("</tr>")]
    assert "sla-overdue" not in row and "sla-overdue" not in case.split("detail.sla3m")[-1][:600]


# ── Form input: what the browser allows, the server accepts; the rest is a 4xx ─


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/admin/categories", {"slug": "s" * 65, "label_en": "x", "label_de": "x"}),
        ("/admin/categories", {"slug": "ok", "label_en": "x" * 129, "label_de": "x"}),
        (
            "/admin/categories",
            {"slug": "big", "label_en": "x", "label_de": "x", "sort_order": "99999999999"},
        ),
        ("/admin/locations", {"name": "n", "code": "C" * 33}),
        ("/admin/locations", {"name": "n" * 129, "code": "C1"}),
        ("/admin/locations", {"name": "n", "code": "C2", "description": "d" * 513}),
        ("/admin/organisations", {"name": "n" * 129, "slug": "org-long-name"}),
    ],
)
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
            f"/admin/reports/{report.id}/{path}",
            data={"content": "x" * 5001},
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
        db_session,
        "financial_fraud",
        "Identity reveal with a long reason.",
        submission_mode=SubmissionMode.confidential,
        confidential_name_enc=encrypt("Jane"),
    )
    act(await _totp_user(db_session, AdminRole.admin))
    reason = "r" * 250 + "\r\n" + "r" * 249  # 500 in the page (maxlength), 501 on the wire
    resp = await client.post(
        f"/admin/reports/{report.id}/identity",
        data={"reason": reason},
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
    # The summary banner too: it had its own list of codes and showed "email_invalid".
    assert page.count("Check the email address") == 2


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

    resp = await client.post(
        "/reply",
        data={
            "case_number": report.case_number,
            "pin": pin,
            "content": "Late addition.",
        },
        follow_redirects=False,
    )

    after = await db_session.scalar(
        select(func.count()).select_from(Message).where(Message.report_id == report.id)
    )
    assert after == before
    page = await client.get(resp.headers["location"])
    assert "was not sent" in page.text


@pytest.mark.asyncio
async def test_a_case_number_typed_in_lower_case_opens_the_case(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.redis_client import get_redis
    from app.services.report import authenticate_whistleblower, create_report

    report, pin = await create_report(db_session, "financial_fraud", "Typed on a phone keyboard.")
    found, _ = await authenticate_whistleblower(
        db_session, await get_redis(), f" {report.case_number.lower()} ", pin
    )
    assert found is not None and found.id == report.id


@pytest.mark.asyncio
async def test_retention_ends_the_status_sessions_of_what_it_deletes(
    client: AsyncClient, throwaway_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting a case on /admin ended its status sessions; retention did not.
    README: 'permanently deleted including ... Redis session data'."""
    from datetime import UTC, datetime, timedelta

    from app.config import settings
    from app.models.report import ReportStatus
    from app.redis_client import get_redis
    from app.services.report import create_report
    from app.services.retention import run_retention_cleanup

    report, _ = await create_report(throwaway_db, "financial_fraud", "Past its retention period.")
    report.status = ReportStatus.closed
    report.closed_at = datetime.now(UTC) - timedelta(days=settings.retention_days + 1)
    await throwaway_db.commit()
    redis = await get_redis()
    await redis.set("status-session:probe-retention", str(report.id), ex=600)

    monkeypatch.setattr(settings, "retention_enabled", True)
    await run_retention_cleanup()

    assert await redis.get("status-session:probe-retention") is None


@pytest.mark.asyncio
async def test_the_digest_says_cases_where_it_counts_cases(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three replies on one case were announced as '1 new message': the queue
    is a set of case numbers."""
    from unittest.mock import AsyncMock

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import notifications

    monkeypatch.setattr(settings, "notification_batch_minutes", 15)
    monkeypatch.setattr(settings, "notify_webhook_enabled", True)
    monkeypatch.setattr(settings, "notify_webhook_url", "https://hooks.example.org/x")
    await (await get_redis()).delete(*notifications._QUEUE_KEYS.values())
    for _ in range(3):
        await notifications.notify_whistleblower_message("OW-2026-00042")
    sent = AsyncMock()
    monkeypatch.setattr(notifications, "_send_webhook", sent)
    monkeypatch.setattr(notifications, "_send_email", AsyncMock())

    await notifications.deliver_notification_digest()

    _, messages, cfg = sent.call_args.args
    text = notifications._activity_text(0, len(messages))
    assert text == "0 new reports, 1 case with new messages"


# ── Multi-tenancy: accounts belong to an organisation ────────────────────────


@pytest.mark.asyncio
async def test_an_account_made_before_multi_tenancy_keeps_its_cases(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Made on /admin/users with multi-tenancy off, an admin had no
    organisation; switching multi-tenancy on scoped it to org-less reports,
    and every report has one."""
    import uuid

    from app.config import settings
    from app.models.user import AdminRole
    from app.services.auth import get_user_by_username
    from app.services.report import create_report

    client, act = acting_as
    monkeypatch.setattr(settings, "multi_tenancy_enabled", False)
    act(await _totp_user(db_session, AdminRole.superadmin))
    name = f"pre-mt-{uuid.uuid4().hex[:6]}"
    await client.post(
        "/admin/users",
        data={
            "username": name,
            "password": "A-Long-Enough-Password-1",
            "role": "admin",
        },
    )
    made = await get_user_by_username(db_session, name)
    report, _ = await create_report(db_session, "financial_fraud", "Filed under the default org.")
    assert made is not None and made.org_id == report.org_id


@pytest.mark.asyncio
async def test_a_superadmin_gives_another_organisation_its_admin(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There was no way to: a new account took its creator's organisation."""
    import uuid

    from app.config import settings
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from app.services.auth import get_user_by_username

    client, act = acting_as
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    org = Organisation(id=uuid.uuid4(), name="Branch B", slug=f"b-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.commit()
    act(await _totp_user(db_session, AdminRole.superadmin))

    page = await client.get("/admin/users")
    assert f'value="{org.id}"' in page.text
    name = f"b-admin-{uuid.uuid4().hex[:6]}"
    await client.post(
        "/admin/users",
        data={
            "username": name,
            "password": "A-Long-Enough-Password-1",
            "role": "admin",
            "org_id": str(org.id),
        },
    )
    made = await get_user_by_username(db_session, name)
    assert made is not None and made.org_id == org.id


@pytest.mark.asyncio
async def test_an_admin_cannot_place_an_account_in_another_organisation(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    from app.config import settings
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from app.services.auth import get_user_by_username
    from app.services.report import default_org_id

    client, act = acting_as
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    org = Organisation(id=uuid.uuid4(), name="Branch C", slug=f"c-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    admin = await _totp_user(db_session, AdminRole.admin)
    admin.org_id = await default_org_id(db_session)
    await db_session.commit()
    act(admin)
    name = f"c-cm-{uuid.uuid4().hex[:6]}"
    await client.post(
        "/admin/users",
        data={
            "username": name,
            "password": "A-Long-Enough-Password-1",
            "org_id": str(org.id),
        },
    )
    made = await get_user_by_username(db_session, name)
    assert made is not None and made.org_id == admin.org_id


@pytest.mark.asyncio
async def test_an_ldap_account_gets_the_default_organisation(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid
    from unittest.mock import AsyncMock

    from app.config import settings
    from app.services import ldap_auth
    from app.services.auth import get_user_by_username
    from app.services.report import default_org_id

    name = f"dir-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(settings, "ldap_enabled", True)
    monkeypatch.setattr(
        ldap_auth,
        "authenticate_ldap",
        AsyncMock(return_value=ldap_auth.LDAPUserInfo(username=name, email=None)),
    )
    await client.post("/admin/login", data={"username": name, "password": "pw"})
    made = await get_user_by_username(db_session, name)
    assert made is not None and made.org_id == await default_org_id(db_session)


# ── Four eyes: two people, not two accounts ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("who_requests", ["creator", "created"])
async def test_an_account_and_the_account_it_made_are_not_four_eyes(
    acting_as, db_session: AsyncSession, who_requests: str
) -> None:
    """An admin could make a second admin on /admin/users, sign in with the
    password they had just chosen before its owner did, and confirm their
    own deletion request."""
    import uuid

    from app.models.user import AdminRole
    from app.services.auth import get_user_by_username
    from app.services.report import create_report

    client, act = acting_as
    creator = await _totp_user(db_session, AdminRole.admin)
    act(creator)
    name = f"puppet-{uuid.uuid4().hex[:6]}"
    await client.post(
        "/admin/users",
        data={
            "username": name,
            "password": "A-Long-Enough-Password-1",
            "role": "admin",
        },
    )
    made = await get_user_by_username(db_session, name)
    assert made is not None
    report, _ = await create_report(db_session, "financial_fraud", "Delete with one pair of eyes.")

    first, second = (creator, made) if who_requests == "creator" else (made, creator)
    act(first)
    await client.post(f"/admin/reports/{report.id}/request-delete")
    act(second)
    resp = await client.post(f"/admin/reports/{report.id}/confirm-delete", follow_redirects=False)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_migration_012_finds_the_maker_in_the_audit_log(throwaway_db: AsyncSession) -> None:
    import uuid

    from sqlalchemy import text

    from app.config import settings

    def alembic(*args: str) -> None:
        run = subprocess.run(  # noqa: S603
            ["alembic", *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,  # noqa: S607
            env={**os.environ, "DATABASE_URL": settings.database_url},
        )
        assert run.returncode == 0, run.stderr

    alembic("downgrade", "b8d3f7a1c908")
    maker, made = uuid.uuid4(), uuid.uuid4()
    for uid, name in ((maker, "maker"), (made, "Made.One")):
        await throwaway_db.execute(
            text(
                "INSERT INTO admin_users (id, username, password_hash, totp_secret, totp_enabled,"
                " role, is_active) VALUES (:i, :u, 'x', 'x', true, 'admin', true)"
            ),
            {"i": uid, "u": name},
        )
    await throwaway_db.execute(
        text(
            "INSERT INTO audit_log (id, admin_id, admin_username, action, detail)"
            " VALUES (:i, :a, 'maker', 'admin.created', :d)"
        ),
        {"i": uuid.uuid4(), "a": maker, "d": '{"username": "made.one", "role": "admin"}'},
    )
    await throwaway_db.commit()
    alembic("upgrade", "head")
    got = await throwaway_db.scalar(
        text("SELECT created_by_id FROM admin_users WHERE id = :i"), {"i": made}
    )
    assert got == maker


# ── Scheduled jobs run at the UTC times the docs give ───────────────────────


def test_the_scheduler_keeps_utc_whatever_tz_says() -> None:
    """AsyncIOScheduler() takes the host's zone: with TZ=Europe/Berlin the
    '03:00 UTC' retention run fired at 01:00 UTC."""
    probe = (
        "import asyncio\n"
        "from app.main import new_scheduler\n"
        "async def m():\n"
        "    s = new_scheduler(); s.add_job(print, 'cron', hour=3, minute=0, id='r'); s.start()\n"
        "    print('OFFSET', s.get_job('r').next_run_time.utcoffset()); s.shutdown()\n"
        "asyncio.run(m())\n"
    )
    out = subprocess.run(  # noqa: S603
        ["python", "-c", probe],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,  # noqa: S607
        env={**os.environ, "TZ": "Europe/Berlin"},
    )
    assert "OFFSET 0:00:00" in out.stdout.splitlines()


def test_the_retention_page_names_the_next_run() -> None:
    """Between 00:00 and 03:00 UTC the page said tomorrow; the run is today."""
    from datetime import UTC, datetime

    from app.services.retention import next_run

    assert next_run(datetime(2027, 3, 4, 1, 30, tzinfo=UTC)) == datetime(2027, 3, 4, 3, tzinfo=UTC)
    assert next_run(datetime(2027, 3, 4, 3, 30, tzinfo=UTC)) == datetime(2027, 3, 5, 3, tzinfo=UTC)


# ── Audit log: the export is the page, whole; reading evidence is recorded ──


@pytest.mark.asyncio
async def test_the_export_holds_what_the_filtered_page_shows_and_all_of_it(
    throwaway_db: AsyncSession, acting_as
) -> None:
    """The export link carried only ?views, so a filtered page exported
    everything; and it stopped at 10 000 rows without saying so."""
    import csv
    import io

    from sqlalchemy import text

    from app.models.user import AdminRole

    client, act = acting_as
    await throwaway_db.execute(
        text(
            "INSERT INTO audit_log (id, admin_username, action, created_at)"
            " SELECT gen_random_uuid(), 'bulk', 'report.note_added', now() - n * interval '1 second'"  # noqa: E501
            " FROM generate_series(1, 10001) n"
        )
    )
    await throwaway_db.execute(
        text(
            "INSERT INTO audit_log (id, admin_username, action) VALUES"
            " (gen_random_uuid(), 'other', 'report.assigned')"
        )
    )
    await throwaway_db.commit()
    act(await _totp_user(throwaway_db, AdminRole.superadmin))

    page = (await client.get("/admin/audit-log?action=report.note_added")).text
    link = re.search(r'href="(/admin/audit-log/export\.csv[^"]*)"', page)
    assert link
    body = (await client.get(link.group(1).replace("&amp;", "&"))).text
    rows = list(csv.DictReader(io.StringIO(body)))
    assert {r["action"] for r in rows} == {"report.note_added"}
    assert len(rows) == 10001


@pytest.mark.asyncio
async def test_exporting_the_log_and_downloading_evidence_are_recorded(
    acting_as, db_session: AsyncSession
) -> None:
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.user import AdminRole
    from app.services.attachment import create_attachments
    from app.services.audit import AuditAction
    from app.services.report import create_report

    client, act = acting_as
    admin = await _totp_user(db_session, AdminRole.admin)
    act(admin)
    await client.get("/admin/audit-log/export.csv")

    report, _ = await create_report(db_session, "financial_fraud", "Has a piece of evidence.")
    [att] = await create_attachments(db_session, report, [("n.txt", "text/plain", b"evidence")])
    assert (await client.get(f"/admin/reports/{report.id}/attachments/{att.id}")).status_code == 200

    actions = set(
        (await db_session.execute(select(AuditLog.action).where(AuditLog.admin_id == admin.id)))
        .scalars()
        .all()
    )
    assert {AuditAction.AUDIT_EXPORTED, AuditAction.ATTACHMENT_DOWNLOADED} <= actions


@pytest.mark.asyncio
async def test_a_search_across_organisations_is_in_each_one_s_log(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A superadmin's search decrypted every organisation's reports, and was
    recorded under the superadmin's own: the others' admins never saw it."""
    import uuid

    from sqlalchemy import select

    from app.config import settings
    from app.models.audit import AuditLog
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from app.services.audit import AuditAction
    from app.services.report import create_report, default_org_id

    client, act = acting_as
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    org = Organisation(id=uuid.uuid4(), name="Branch S", slug=f"s-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.commit()
    word = f"zebra{uuid.uuid4().hex[:6]}"
    await create_report(db_session, "financial_fraud", f"Seen a {word} here.", org_id=org.id)
    superadmin = await _totp_user(db_session, AdminRole.superadmin)
    superadmin.org_id = await default_org_id(db_session)
    await db_session.commit()
    act(superadmin)

    await client.post("/admin/dashboard", data={"q": word})
    orgs = set(
        (
            await db_session.execute(
                select(AuditLog.org_id).where(
                    AuditLog.admin_id == superadmin.id,
                    AuditLog.action == AuditAction.CONTENT_SEARCHED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert org.id in orgs


@pytest.mark.asyncio
async def test_unassigning_is_recorded_as_unassigning(acting_as, db_session: AsyncSession) -> None:
    """The audit filter offered 'unassigned' and nothing ever wrote it."""
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.user import AdminRole
    from app.services.audit import AuditAction
    from app.services.report import create_report

    client, act = acting_as
    admin = await _totp_user(db_session, AdminRole.admin)
    report, _ = await create_report(db_session, "financial_fraud", "Assigned, then not.")
    act(admin)
    await client.post(f"/admin/reports/{report.id}/assign", data={"admin_id": str(admin.id)})
    await client.post(f"/admin/reports/{report.id}/assign", data={"admin_id": ""})
    actions = (
        (
            await db_session.execute(
                select(AuditLog.action)
                .where(AuditLog.report_id == report.id)
                .order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [a for a in actions if a.startswith("report.") and "assign" in a] == [
        AuditAction.REPORT_ASSIGNED,
        AuditAction.REPORT_UNASSIGNED,
    ]


@pytest.mark.parametrize("template", ["admin/users.html", "wizard/setup.html"])
@pytest.mark.parametrize(
    "name", ["jane.doe", "j@corp.example", "jane doe", "ab_c-1", "ab", "x" * 65, "jane!", "é-user"]
)
def test_the_username_field_accepts_what_the_server_accepts(template: str, name: str) -> None:
    """The forms allowed letters, digits, _ and - only; the server and the
    error message also . @ and spaces: 'jane.doe' was blocked in the browser."""
    from app.services.users import validate_username

    html = (ROOT / "app/templates" / template).read_text()
    field = re.search(r'name="username"[^>]*?pattern="([^"]+)"', html, re.S)
    assert field, template
    pattern = field.group(1).replace("\\-", "-").replace("-]", "\\-]")
    try:
        validate_username(name)
        server = True
    except ValueError:
        server = False
    assert bool(re.fullmatch(pattern, name)) == server


def test_no_published_page_calls_fernet_aes_256() -> None:
    """Fernet is AES-128-CBC with HMAC-SHA256. The security policy and the
    DPA template promised AES-256 and a SECRET_KEY-derived master key. The
    website checks its own pages."""
    assert not re.search(r"AES-?256", (ROOT / "README.md").read_text())


def test_every_deadline_state_is_reached() -> None:
    from datetime import UTC, datetime, timedelta

    from app.services import deadlines

    submitted = datetime(2027, 3, 1, tzinfo=UTC)
    later = submitted + timedelta(days=30)
    assert deadlines.ack_status(submitted, submitted + timedelta(days=2), later).state == "done"
    due = deadlines.feedback_due(submitted)
    assert deadlines.feedback_status(due, True, due + timedelta(days=1)).state == "done"
    assert deadlines.feedback_status(None, False, later) is None
    late = submitted + timedelta(days=7, seconds=1)
    assert deadlines.ack_status(submitted, None, late).state == "overdue"
    assert deadlines.feedback_status(due, False, due + timedelta(seconds=1)).state == "overdue"
    assert deadlines.feedback_status(due, False, due - timedelta(hours=12)).state == "warning"


@pytest.mark.asyncio
@pytest.mark.parametrize("org_id", ["not-a-uuid", "missing", "inactive"])
async def test_a_superadmin_cannot_place_an_account_in_an_unknown_organisation(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, org_id: str
) -> None:
    import uuid

    from app.config import settings
    from app.models.organisation import Organisation
    from app.models.user import AdminRole

    client, act = acting_as
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    if org_id == "missing":
        org_id = str(uuid.uuid4())
    elif org_id == "inactive":
        org = Organisation(
            id=uuid.uuid4(), name="Closed", slug=f"x-{uuid.uuid4().hex[:6]}", is_active=False
        )
        db_session.add(org)
        await db_session.commit()
        org_id = str(org.id)
    act(await _totp_user(db_session, AdminRole.superadmin))
    resp = await client.post(
        "/admin/users",
        data={
            "username": f"u-{uuid.uuid4().hex[:6]}",
            "password": "A-Long-Enough-Password-1",
            "org_id": org_id,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_draft_cookie_with_a_smuggled_newline_is_a_fresh_draft_not_a_500(
    client: AsyncClient,
) -> None:
    """``^…$`` with ``re.match`` lets a trailing newline through, and
    Starlette unquotes ``"…\\012"`` into one: the id passed the check and
    ``set_cookie`` raised CookieError on the way back out (CodeQL #306)."""
    from httpx import ASGITransport

    from app.main import app

    value = '"' + "a" * 43 + "." + "b" * 43 + '\\012"'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        page = await c.get("/submit")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf
        cookies = f"ow_csrf={csrf.group(1)}; ow-submission-session={value}"
        resp = await c.post(
            "/submit",
            headers={"cookie": cookies},
            follow_redirects=False,
            data={
                "csrf_token": csrf.group(1),
                "step": "1",
                "action": "next",
                "submission_mode": "anonymous",
            },
        )
    assert resp.status_code in (200, 303)
    assert "\n" not in resp.headers.get("set-cookie", "")


def test_an_onion_location_never_reaches_the_header_with_a_newline() -> None:
    """The value becomes the Onion-Location response header."""
    from app.config import Settings

    onion = "http://" + "a" * 56 + ".onion"
    assert Settings(onion_location=onion + "\n").onion_location == onion  # type: ignore[call-arg]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "next_url",
    [
        "//evil.example/submit/x",
        "https://evil.example/status",
        "/\\evil.example",
        "/status?x=1%0d%0aSet-Cookie:%20a=b",
        "/status?next=https://evil.example",
        "/submit/a\r\nX-Evil: 1",
        "javascript:alert(1)",
        "/admin/../../evil",
    ],
)
async def test_the_language_switch_redirects_only_within_the_site(
    client: AsyncClient, next_url: str
) -> None:
    """CodeQL #297: the redirect depends on ``next``. Only its path decides the
    target (an allow-list, or an organisation's /submit/<slug>); the query is
    carried as data. No host, scheme or header ever comes from it."""
    page = await client.get("/submit")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf
    resp = await client.post(
        "/set-language",
        data={
            "csrf_token": csrf.group(1),
            "lang": "de",
            "next": next_url,
        },
        follow_redirects=False,
    )
    location = resp.headers["location"]
    assert resp.status_code == 303
    assert location.startswith("/") and not location.startswith(("//", "/\\"))
    assert "\r" not in location and "\n" not in location
    assert "evil.example" not in location.split("?")[0]
