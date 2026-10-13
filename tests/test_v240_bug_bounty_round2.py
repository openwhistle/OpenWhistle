"""Defects found by the second bug bounty after v2.3.0, each reproduced before it was fixed."""

import pytest

# ── A WebSocket handshake reaches no log with the peer's address ──────────────


@pytest.mark.asyncio
async def test_a_websocket_handshake_loses_its_address_before_uvicorn_logs_it() -> None:
    """The middleware passed every scope that was not ``http`` through untouched. No route
    takes a WebSocket, so uvicorn refuses the handshake and logs it on ``uvicorn.error``,
    which ``--no-access-log`` does not silence — measured against uvicorn 0.54:
    ``127.0.0.1:37000 - "WebSocket /status?case=OW-2026-00001" 403``. uvicorn reads the
    address from the scope it handed over, so clearing it there clears the log line."""
    from app.middleware import SecurityMiddleware

    async def refuse(scope: dict, receive: object, send: object) -> None:  # type: ignore[type-arg]
        pass

    scope = {
        "type": "websocket",
        "path": "/status",
        "client": ("203.0.113.9", 51000),
        "headers": [(b"x-forwarded-for", b"203.0.113.9"), (b"host", b"example.org")],
    }
    await SecurityMiddleware(refuse)(scope, None, None)  # type: ignore[arg-type]
    assert scope["client"] is None
    assert scope["headers"] == [(b"host", b"example.org")]


# ── An uploaded PDF leaves no timestamped line in the log ─────────────────────


def _pdf_with_a_wrong_xref_pointer() -> bytes:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    start = data.rindex(b"startxref") + len(b"startxref\n")
    return data[:start] + b"9" + data[start + 1 :]  # as many PDF producers write it


def test_stripping_a_sloppy_pdf_logs_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """pypdf warns about every PDF with a wrong cross-reference pointer, which many
    producers write. The line carried the second a reporter uploaded the file, which
    README's day-only promise keeps out of the database (measured: ``incorrect startxref
    pointer(2)`` at WARNING through the app's own logging setup)."""
    from app.logging_config import configure_logging
    from app.services.attachment import strip_metadata

    configure_logging()  # replaces the root handlers, so read what reaches stdout
    assert strip_metadata("report.pdf", _pdf_with_a_wrong_xref_pointer())
    out, err = capsys.readouterr()
    assert "xref" not in out + err  # stderr too: docker logs stamps that stream as well


# ── Reading Redis yields no admin session ─────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_holds_no_admin_session_a_reader_could_present(client, db_session) -> None:  # type: ignore[no-untyped-def]
    """2.3.0 keyed the reporter's status session by an HMAC "so whoever reads Redis holds
    no session to open a case with"; the admin session kept the signed JWT itself as its
    key. Measured: the key from ``SCAN openwhistle:session:*``, set as ``ow_session`` in a
    second client, opened /admin/dashboard (200) with no password and no TOTP — and an
    admin opens every case. The TOTP login and setup tokens were keyed the same way."""
    import uuid

    import pyotp
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.models.user import AdminRole, AdminUser
    from app.redis_client import get_redis
    from app.services.auth import hash_password
    from tests.test_session_expiry import _login_admin

    secret = pyotp.random_base32()
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"rk_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Expiry!Test123"),
        totp_secret=secret,
        totp_enabled=True,
        role=AdminRole.admin,
    )
    db_session.add(admin)
    await db_session.commit()
    await _login_admin(client, admin, secret)
    assert (await client.get("/admin/dashboard", follow_redirects=False)).status_code == 200

    redis = await get_redis()
    keys = [
        k.decode() if isinstance(k, bytes) else k async for k in redis.scan_iter("openwhistle:*")
    ]
    assert any(k.startswith("openwhistle:session:") for k in keys)
    for key in keys:
        candidate = key.rsplit(":", 1)[-1]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as reader:
            reader.cookies.set("ow_session", candidate)
            resp = await reader.get("/admin/dashboard", follow_redirects=False)
            assert resp.status_code != 200, key


# ── A confidential identity goes to one handler ───────────────────────────────


def _admin(role=None, org=None):  # type: ignore[no-untyped-def]
    import uuid

    from app.models.user import AdminRole, AdminUser

    return AdminUser(
        id=uuid.uuid4(),
        username=f"bb_{uuid.uuid4().hex[:8]}",
        role=role or AdminRole.admin,
        org_id=org,
        is_active=True,
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_enabled=True,
    )


@pytest.mark.asyncio
async def test_revealing_an_unassigned_identity_makes_the_revealer_its_handler(
    acting_as, db_session
) -> None:  # type: ignore[no-untyped-def]
    """README and the reporter's form promise the name goes to "the case handler only";
    on an unassigned case every admin of the organisation could reveal it, one after the
    other, and the case stayed unassigned (measured: two admins, 200 and the name twice,
    ``assigned_to_id`` None). Revealing now takes the case; the next admin is refused."""
    from app.models.report import SubmissionMode
    from app.services import report as report_service
    from app.services.crypto import encrypt

    client, act = acting_as
    first, second = _admin(), _admin()
    db_session.add_all([first, second])
    report, _ = await report_service.create_report(
        db_session,
        "financial_fraud",
        "A confidential report with a name on file.",
        SubmissionMode.confidential,
        confidential_name_enc=encrypt("Jane Roe"),
    )
    reason = {"reason": "Needed to arrange the interview."}

    act(first)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data=reason)
    assert resp.status_code == 200 and "Jane Roe" in resp.text
    await db_session.refresh(report)
    assert report.assigned_to_id == first.id

    act(second)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data=reason)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_the_reveal_form_says_it_takes_an_unassigned_case(acting_as, db_session) -> None:  # type: ignore[no-untyped-def]
    from app.models.report import SubmissionMode
    from app.services import report as report_service
    from app.services.crypto import encrypt

    client, act = acting_as
    act(admin := _admin())
    db_session.add(admin)
    report, _ = await report_service.create_report(
        db_session,
        "financial_fraud",
        "A confidential report with a name on file.",
        SubmissionMode.confidential,
        confidential_name_enc=encrypt("Jane Roe"),
    )
    page = await client.get(f"/admin/reports/{report.id}")
    assert "assigns the case to you" in page.text


# ── A reminder that SMTP refused is sent again ────────────────────────────────


@pytest.mark.asyncio
async def test_a_reminder_smtp_refused_is_tried_again_on_the_next_run(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The reminder was marked as sent whatever SMTP said: one refused delivery and the
    7-day deadline passed without a reminder, since the mark lives until the deadline
    (measured: 1 attempt over two runs, mark set). The run every 30 minutes now retries."""
    import uuid
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from redis.asyncio import from_url

    from app.config import settings
    from app.services import reminders

    monkeypatch.setattr(settings, "notify_email_enabled", True)
    monkeypatch.setattr(settings, "notify_email_to", "office@example.org")
    send = AsyncMock(side_effect=OSError("SMTP unreachable"))
    monkeypatch.setattr("aiosmtplib.send", send)
    redis = from_url(settings.redis_url)  # its own: the shared client is bound to another loop
    report = SimpleNamespace(
        case_number=f"OW-2026-{uuid.uuid4().int % 100000:05d}",
        acknowledged_at=None,
        submitted_at=datetime.now(UTC) - timedelta(days=6),
    )
    for _ in range(2):
        await reminders._check_ack_reminder(report, datetime.now(UTC), None, redis, settings)
    assert send.await_count == 2
    assert not await redis.exists(reminders._ack_dedup_key(report.case_number))

    send.side_effect = None
    await reminders._check_ack_reminder(report, datetime.now(UTC), None, redis, settings)
    assert await redis.exists(reminders._ack_dedup_key(report.case_number))
    await redis.aclose()


# ── A busy second at 03:00 does not cost a day of retention ───────────────────


@pytest.mark.asyncio
async def test_a_job_whose_moment_finds_the_loop_busy_still_runs() -> None:
    """APScheduler drops a run that starts more than ``misfire_grace_time`` late, and
    its default is one second. A PDF export or a bcrypt check at 03:00 UTC skipped that
    day's retention run, at midnight the digest (measured: the loop blocked 3 s,
    "was missed by 0:00:02", the job never ran)."""
    import asyncio
    import time
    from datetime import UTC, datetime, timedelta

    from app.main import new_scheduler

    ran: list[int] = []
    scheduler = new_scheduler()
    scheduler.add_job(
        lambda: ran.append(1), "date", run_date=datetime.now(UTC) + timedelta(seconds=1)
    )
    scheduler.start()
    try:
        await asyncio.sleep(0)
        time.sleep(2.5)  # a busy event loop
        await asyncio.sleep(1)
    finally:
        scheduler.shutdown(wait=False)
    assert ran


# ── The superadmin's statistics keep each organisation's categories apart ─────


@pytest.mark.asyncio
async def test_superadmin_stats_label_each_organisations_category(
    acting_as, db_session, tenants
) -> None:  # type: ignore[no-untyped-def]
    """A slug is unique per organisation only. The statistics counted by slug alone, so
    two organisations' "probe" categories became one row of 2 under one organisation's
    label (measured: "Label A" missing, "Label B" shown) — the case page and the PDF had
    been fixed for this in 2.3.0, the statistics had not."""
    import uuid

    from app.models.category import ReportCategory
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from app.services import report as report_service

    client, act = acting_as
    orgs = [Organisation(id=uuid.uuid4(), name=n, slug=f"{n}-{uuid.uuid4().hex[:6]}") for n in "ab"]
    db_session.add_all(orgs)
    await db_session.flush()
    for org, label in zip(orgs, ("Label A", "Label B"), strict=True):
        db_session.add(ReportCategory(slug="probe", label_en=label, label_de=label, org_id=org.id))
    await db_session.commit()
    for org in orgs:
        await report_service.create_report(db_session, "probe", "One case each.", org_id=org.id)

    act(_admin(AdminRole.superadmin))
    page = (await client.get("/admin/stats")).text
    assert "Label A" in page and "Label B" in page


# ── Every account that appears has an audit entry ─────────────────────────────


@pytest.mark.asyncio
async def test_an_account_made_by_a_first_directory_login_is_on_record(
    client, db_session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The audit log "records every admin action", and an account made on /admin/users
    gets ``admin.created``; the account a first LDAP login provisions got nothing — an
    account that can read cases appeared with no record of how (measured: account made,
    0 rows)."""
    import uuid

    from sqlalchemy import func, select

    from app.config import settings
    from app.models.audit import AuditLog
    from app.services import ldap_auth

    name = f"dir{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "ldap_enabled", True)

    async def directory_says_yes(username: str, password: str) -> ldap_auth.LDAPUserInfo:
        return ldap_auth.LDAPUserInfo(username=name)

    monkeypatch.setattr(ldap_auth, "authenticate_ldap", directory_says_yes)
    csrf = (await client.get("/admin/login")).cookies.get("ow_csrf")
    await client.post(
        "/admin/login", data={"username": name, "password": "Directory-pass-1", "csrf_token": csrf}
    )
    rows = await db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "admin.created", AuditLog.detail.contains(name))
    )
    assert rows == 1


@pytest.mark.asyncio
async def test_the_first_account_is_on_record(throwaway_db) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.api.wizard import create_initial_admin
    from app.models.audit import AuditLog

    assert await create_initial_admin(throwaway_db, "owner", "pw-" + "x" * 20, "JBSWY3DPEHPK3PXP")
    actions = (await throwaway_db.execute(select(AuditLog.action, AuditLog.detail))).all()
    assert [a for a, d in actions if a == "admin.created" and "owner" in d]


# ── The address-header warning goes only with its audit entry ────────────────


@pytest.mark.asyncio
async def test_the_ip_warning_stays_when_its_dismissal_is_not_recorded(
    client, db_session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The flag was deleted from Redis before the audit entry was written: when that
    failed, the warning that visitors' addresses arrive was gone with nothing on record.
    2.3.0 moved thirteen actions behind their audit entry; this one stayed in front."""
    from app.middleware import _REDIS_IP_WARNING_KEY, check_ip_warning
    from app.redis_client import get_redis
    from app.services import audit as audit_service
    from tests.test_coverage_admin_extended import _create_admin, _login_admin

    admin, secret = await _create_admin(db_session)
    await _login_admin(client, admin, secret)
    await (await get_redis()).set(_REDIS_IP_WARNING_KEY, "1")

    async def refused(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit write refused")

    monkeypatch.setattr(audit_service, "log", refused)
    with pytest.raises(RuntimeError):
        await client.post(
            "/admin/ip-warning/dismiss", headers={"X-CSRF-Token": client.cookies.get("ow_csrf")}
        )
    assert await check_ip_warning()


# ── A deactivated organisation gets no new accounts ───────────────────────────


@pytest.mark.asyncio
async def test_no_account_is_made_in_a_deactivated_organisation(acting_as, db_session, tenants) -> None:  # type: ignore[no-untyped-def]
    """A superadmin cannot give a deactivated organisation an account; its own admin
    could, on /admin/users, where only the superadmin's choice was checked (measured:
    302, a second account in the organisation)."""
    import uuid

    from sqlalchemy import func, select

    from app.models.organisation import Organisation
    from app.models.user import AdminUser

    client, act = acting_as
    org = Organisation(id=uuid.uuid4(), name="gone", slug=f"gone-{uuid.uuid4().hex[:6]}", is_active=False)
    db_session.add(org)
    await db_session.flush()
    admin = _admin(org=org.id)
    db_session.add(admin)
    await db_session.commit()

    act(admin)
    resp = await client.post(
        "/admin/users",
        data={"username": f"n{uuid.uuid4().hex[:6]}", "password": "Probe!Password-123", "role": "case_manager"},
        follow_redirects=False,
    )
    assert resp.status_code == 422
    count = select(func.count()).select_from(AdminUser).where(AdminUser.org_id == org.id)
    assert await db_session.scalar(count) == 1
