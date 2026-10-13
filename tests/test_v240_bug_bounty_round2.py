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
async def test_no_account_is_made_in_a_deactivated_organisation(
    acting_as, db_session, tenants
) -> None:  # type: ignore[no-untyped-def]
    """A superadmin cannot give a deactivated organisation an account; its own admin
    could, on /admin/users, where only the superadmin's choice was checked (measured:
    302, a second account in the organisation)."""
    import uuid

    from sqlalchemy import func, select

    from app.models.organisation import Organisation
    from app.models.user import AdminUser

    client, act = acting_as
    org = Organisation(
        id=uuid.uuid4(), name="gone", slug=f"gone-{uuid.uuid4().hex[:6]}", is_active=False
    )
    db_session.add(org)
    await db_session.flush()
    admin = _admin(org=org.id)
    db_session.add(admin)
    await db_session.commit()

    act(admin)
    resp = await client.post(
        "/admin/users",
        data={
            "username": f"n{uuid.uuid4().hex[:6]}",
            "password": "Probe!Password-123",
            "role": "case_manager",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    count = select(func.count()).select_from(AdminUser).where(AdminUser.org_id == org.id)
    assert await db_session.scalar(count) == 1


# ── A PIN or password check does not stop every other request ─────────────────


async def _longest_stall(coro) -> float:  # type: ignore[no-untyped-def]
    """The longest the event loop went without serving anyone else while ``coro`` ran."""
    import asyncio
    import time

    task = asyncio.ensure_future(coro)
    longest, last = 0.0, time.perf_counter()
    while not task.done():
        await asyncio.sleep(0.005)
        now = time.perf_counter()
        longest, last = max(longest, now - last), now
    await task
    return longest


@pytest.mark.asyncio
async def test_a_pin_check_leaves_the_event_loop_free(db_session) -> None:  # type: ignore[no-untyped-def]
    """bcrypt ran on the event loop: each wrong PIN on /status held every request of
    every reporter and admin for its ~0.2 s (measured: /health 2 ms idle, 3921 ms
    during 20 parallel wrong PINs, a one-worker image)."""
    from app.services.report import get_report_by_credentials

    stall = await _longest_stall(get_report_by_credentials(db_session, "OW-2026-99999", "x"))
    assert stall < 0.1


@pytest.mark.asyncio
async def test_a_password_check_leaves_the_event_loop_free(client) -> None:  # type: ignore[no-untyped-def]
    csrf = (await client.get("/admin/login")).cookies.get("ow_csrf")
    login = client.post(
        "/admin/login",
        data={"username": "nobody-here", "password": "wrong-password", "csrf_token": csrf},
    )
    assert await _longest_stall(login) < 0.1


# ── Opening a case does not read its attachments' bytes ───────────────────────


@pytest.mark.asyncio
async def test_opening_a_case_leaves_the_attachment_bytes_in_the_database(db_session) -> None:  # type: ignore[no-untyped-def]
    """Every case view — the reporter's /status, each reply, the admin case page — loaded
    every attachment with its bytes (up to 5 x 10 MB) only to list names and sizes. 2.2.1
    stopped this for a wrong PIN; a right one and every admin view still paid it. The
    bytes are read on download only, which still works."""
    from sqlalchemy import inspect

    from app.services import report as report_service
    from app.services.attachment import create_attachments, read_attachment

    report, pin = await report_service.create_report(db_session, "financial_fraud", "With a file.")
    pdf = b"%PDF-1.4 x" * 1000
    await create_attachments(db_session, report, [("a.pdf", "application/pdf", pdf)])
    db_session.expunge_all()

    for opened in (
        await report_service.get_report_by_credentials(db_session, report.case_number, pin),
        await report_service.get_report_by_id(db_session, report.id),
    ):
        (attachment,) = opened.attachments
        assert "data" in inspect(attachment).unloaded
        assert await read_attachment(db_session, attachment) == pdf


# ── Migrations file under the organisation the app's settings name ────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["011", "017"])
async def test_migrations_011_and_017_read_the_default_organisation_like_the_app(
    number, db_session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """2.3.0 made alembic read the database URL as the app does, environment then
    .env. 011 and 017 still read DEFAULT_ORG_SLUG from the environment alone: set in
    .env only, it was ignored and accounts and cases went to the "default" one."""
    import importlib.util
    import uuid
    from pathlib import Path

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.config import settings
    from app.models.organisation import Organisation
    from app.services.report import create_report

    named = Organisation(id=uuid.uuid4(), name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
    db_session.add(named)
    await db_session.flush()
    monkeypatch.delenv("DEFAULT_ORG_SLUG", raising=False)
    monkeypatch.setattr(settings, "default_org_slug", named.slug)  # as read from .env

    report, _ = await create_report(db_session, "financial_fraud", "Filed without an org.")
    report.org_id = None
    account = _admin()
    db_session.add(account)
    await db_session.flush()
    account.org_id = None
    await db_session.commit()

    path = next((Path(__file__).parents[1] / "migrations/versions").glob(f"{number}_*.py"))
    spec = importlib.util.spec_from_file_location(f"m{number}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def upgrade(sync_conn) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(sync_conn)):
            module.upgrade()

    await (await db_session.connection()).run_sync(upgrade)
    target = report if number == "017" else account
    await db_session.refresh(target)
    assert target.org_id == named.id


# ── An erased case leaves no case number in Redis ─────────────────────────────


@pytest.mark.asyncio
async def test_an_erased_case_leaves_no_reminder_mark_behind() -> None:
    """The four-eyes deletion took the case out of the notification queue but left its
    reminder marks, ``reminder:ack:<case>`` and ``reminder:feedback:<case>``: the case
    number of an erased case, in plain text, for up to the reminder window plus a day."""
    from redis.asyncio import from_url

    from app.config import settings
    from app.services import reminders
    from app.services.notifications import forget_case

    redis = from_url(settings.redis_url)
    case = "OW-2026-77777"
    for key in (reminders._ack_dedup_key(case), reminders._feedback_dedup_key(case)):
        await redis.set(key, "1", ex=600)
    await forget_case(redis, case)
    assert not await redis.exists(
        reminders._ack_dedup_key(case), reminders._feedback_dedup_key(case)
    )
    await redis.aclose()


# ── The suite runs with the flags conftest says it sets ───────────────────────


def test_the_suite_runs_with_retention_off() -> None:
    """conftest set RETENTION_ENABLED=false after importing the app, whose settings were
    already built: the whole suite ran with retention on, as a comment in test_v100 said
    it did not."""
    from app.config import settings

    assert settings.retention_enabled is False


# ── TLS 1.2 offers forward-secret suites only ─────────────────────────────────


def test_the_bundled_nginx_offers_no_tls12_suite_without_forward_secrecy() -> None:
    """No ``ssl_ciphers``: nginx's default ``HIGH:!aNULL:!MD5`` negotiated
    AES128-GCM-SHA256 (RSA key exchange) with an operator's RSA certificate (measured with
    ``openssl s_client -tls1_2 -cipher AES128-GCM-SHA256``), while ``ssl_session_tickets
    off`` was there precisely so a later key leak could not decrypt recorded sessions."""
    import re
    from pathlib import Path

    conf = (Path(__file__).parents[1] / "nginx/nginx.conf").read_text()
    (ciphers,) = re.findall(r"^\s*ssl_ciphers\s+([^;]+);", conf, re.M)
    assert all(c.startswith("ECDHE-") for c in ciphers.split(":")), ciphers


# ── Ansible without TLS sends no HSTS ─────────────────────────────────────────


def test_the_ansible_nginx_without_tls_sends_no_hsts_on_its_own_error_pages() -> None:
    """With ``openwhistle_tls_enabled: false`` the only listener is plain HTTP on port 80,
    and the map's default gave nginx's own 413/429/50x pages HSTS there (RFC 6797 §8.1
    forbids it), while the app omits it on that instance since 2.3.0."""
    import re

    from tests.test_tls import _render_role_template

    conf = _render_role_template("nginx.conf.j2", openwhistle_tls_enabled=False)
    (mapping,) = re.findall(r"map \$server_port \$ow_hsts \{(.*?)\}", conf, re.S)
    assert "max-age" not in mapping
    tls = _render_role_template("nginx.conf.j2", openwhistle_tls_enabled=True)
    assert "max-age" in re.findall(r"map \$server_port \$ow_hsts \{(.*?)\}", tls, re.S)[0]


# ── The self-signed certificate is renewed before it expires ──────────────────


def test_an_expiring_self_signed_certificate_is_replaced(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """tls-init keeps its own certificate across restarts and replaced it only for a new
    hostname: after its 825 days every browser refused the instance, and every restart
    said "kept"."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    from tests.test_tls import _ensure

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "whistle.example.org")])
    now = datetime.datetime.now(datetime.UTC)
    old = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=820))
        .not_valid_after(now + datetime.timedelta(days=5))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("whistle.example.org")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    (tmp_path / "tls").mkdir()
    (tmp_path / "tls/fullchain.pem").write_bytes(old.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "tls/privkey.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ensure = _ensure()
    assert ensure(tmp_path / "none", tmp_path / "tls", "whistle.example.org") == "self-signed"
    cert = x509.load_pem_x509_certificate((tmp_path / "tls/fullchain.pem").read_bytes())
    assert cert.not_valid_after_utc > now + datetime.timedelta(days=800)


# ── Queued notifications survive a stop of the stack ──────────────────────────


@pytest.mark.asyncio
async def test_a_stopping_app_delivers_the_queued_notifications(db_engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The digest queue lives in Redis, which keeps nothing on disk (``--save ""``). Every
    deploy, reboot, ``systemctl restart`` and certbot renewal (its pre-hook stops the unit)
    emptied it: up to a day of new reports (NOTIFICATION_BATCH_MINUTES=1440, the default)
    of which no admin was told. Compose stops the app before Redis, so the app sends what
    is queued on its way down."""
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from redis.asyncio import from_url

    from app.config import settings
    from app.main import lifespan
    from app.services import notifications

    monkeypatch.setattr(settings, "notify_email_enabled", True)
    monkeypatch.setattr(settings, "notify_email_to", "office@example.org")
    monkeypatch.setattr(settings, "notification_batch_minutes", 1440)
    monkeypatch.setattr(settings, "update_check_enabled", False)
    deliver = AsyncMock(return_value=True)
    monkeypatch.setattr(notifications, "_deliver", deliver)
    redis = from_url(settings.redis_url, decode_responses=True)
    await redis.sadd(notifications._QUEUE_KEYS["new_reports"], "OW-2026-55555")
    await redis.aclose()

    # close_redis runs for real: it drops the client bound to this test's event loop.
    with patch("app.main._run_alembic_upgrade"):
        async with lifespan(FastAPI()):
            deliver.assert_not_awaited()
    deliver.assert_awaited_once_with(["OW-2026-55555"], [])


# ── Publishing: only commits on main; a re-publish is not blocked by :latest ──


def _workflow(name: str) -> dict:  # type: ignore[type-arg]
    from pathlib import Path

    import yaml

    return yaml.safe_load((Path(__file__).parents[1] / ".github/workflows" / name).read_text())


@pytest.mark.parametrize(
    ("ref", "on_main"),
    [("refs/heads/feature", False), ("refs/tags/v9.9.9", False), ("refs/heads/main", True)],
)
def test_the_publish_guard_refuses_every_ref_main_does_not_contain(tmp_path, ref, on_main) -> None:  # type: ignore[no-untyped-def]
    """ "Only reviewed commits are published" held for tags alone: ``gh workflow run
    docker-publish.yml --ref feature`` built, pushed and signed :sha-<sha> of an
    unreviewed branch in all three registries (the step ran its check only for
    ``refs/tags/*``; run here against a real repository)."""
    import os
    import subprocess

    steps = _workflow("docker-publish.yml")["jobs"]["on-main"]["steps"]
    script = next(s["run"] for s in steps if "run" in s)

    def git(*args: str) -> str:
        cmd = ["git", *args]
        done = subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True, text=True)  # noqa: S603
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "reviewed",
    )
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    if not on_main:
        git("checkout", "-q", "-b", "side")
        git(
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "not reviewed",
        )
    env = {
        **os.environ,
        "GITHUB_REF": ref,
        "GITHUB_REF_NAME": ref.rsplit("/", 1)[-1],
        "GITHUB_SHA": git("rev-parse", "HEAD"),
    }
    cmd = ["bash", "-c", script]
    result = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    assert (result.returncode == 0) is on_main, result.stdout


def test_a_republish_does_not_scan_the_image_it_replaces() -> None:
    """In a called workflow, ``github.event_name`` is the caller's: a re-publish started
    with ``gh workflow run docker-publish.yml`` ran security.yml's scan of the published
    :latest, which fails exactly when :latest has a fixed CVE — the reason to re-publish
    — and ``build`` needs it. (GitHub's documented behaviour; not run here.)"""
    condition = _workflow("security.yml")["jobs"]["published"]["if"]
    assert "docker-publish" in condition and "workflow_ref" in condition, condition


# ── Every translation carries the numbers the English text gives ──────────────


def test_every_locale_states_the_same_numbers_as_english() -> None:
    """de, fr and pt-br dropped the 1095-day (3-year) default from the retention notice,
    "change it only on legal advice" from the HinSchG note, the 4-eyes deletion from the
    GDPR Art. 17 note, and fr the 24/7 duty of critical industries: an admin reading
    them in those languages was told less than one reading English."""
    import json
    import re
    from collections import Counter
    from pathlib import Path

    def numbers(text: str) -> Counter[str]:
        # 10,000 / 10.000 / 10 000 are one number; markup attributes carry none.
        text = re.sub(r"(?<=\d)[.,\s  ](?=\d{3}\b)", "", text)
        return Counter(re.findall(r"\d+", text))

    # Written the local way, same meaning: "art. 5.1.e)", "24 horas, todos los días".
    local_form = {
        ("es", "admin.retention.legal.gdpr5.title"),
        ("es", "admin.telephone.checklist.7"),
    }
    locales = Path(__file__).parents[1] / "app/locales"
    english = json.loads((locales / "en.json").read_text())
    drift = []
    for path in sorted(locales.glob("*.json")):
        lang = path.stem
        for key, text in json.loads(path.read_text()).items():
            if (lang, key) not in local_form and numbers(text) != numbers(english.get(key, text)):
                drift.append((lang, key))
    assert not drift, drift


def test_the_reviewing_status_promises_no_investigation() -> None:
    """A case in review or awaiting feedback told the reporter "An investigation has been
    initiated. You will receive a final response by the feedback deadline." — whatever the
    office had decided. § 17 HinSchG promises feedback on the follow-up measures within
    three months, not an investigation and not a final answer."""
    import json
    from pathlib import Path

    for path in (Path(__file__).parents[1] / "app/locales").glob("*.json"):
        text = json.loads(path.read_text())["status.progress.acknowledged.desc"].lower()
        for claim in ("investigation", "untersuchung", "enquête", "investigación", "investigação"):
            assert claim not in text, (path.stem, text)
