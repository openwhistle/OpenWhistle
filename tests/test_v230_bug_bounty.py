"""Defects found by the bug bounty after v2.2.1, each reproduced before it was fixed."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# ── The lockout must not say when the reporter signed in ───────────────────


@pytest.mark.asyncio
async def test_a_correct_pin_leaves_the_lockout_as_it_was(
    client: object, db_session: AsyncSession
) -> None:
    """A correct PIN cleared the case's failure counter. Anyone who knows a case number
    (every admin does) could lock it with wrong PINs and probe again: the lock gone meant
    the reporter had signed in, to the minute of the probe. A correct PIN gets in
    whatever the counter says, so it no longer touches it."""
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.report import authenticate_whistleblower, create_report

    redis = await get_redis()
    report, pin = await create_report(db_session, "financial_fraud", "Probed for its sign-in.")
    for _ in range(settings.max_access_attempts + 1):
        _, locked = await authenticate_whistleblower(db_session, redis, report.case_number, "x")
    assert locked > 0

    found, _ = await authenticate_whistleblower(db_session, redis, report.case_number, pin)
    assert found is not None  # the reporter still gets in

    _, locked_after = await authenticate_whistleblower(db_session, redis, report.case_number, "x")
    assert locked_after > 0


# ── nginx clears every header the app knows to carry an address ─────────────


def test_nginx_clears_every_header_the_app_strips() -> None:
    """2.2.1 taught the app seven more address headers (Fastly, Envoy, Azure, App Engine,
    ingress-nginx, Cloudflare IPv6); the bundled nginx kept clearing the first seven only,
    while its comment said no IP data could reach the app "under any circumstances"."""
    import re
    from pathlib import Path

    from app.middleware import _IP_REVEAL_HEADERS

    conf = (Path(__file__).parents[1] / "nginx/snippets/proxy-headers.conf").read_text()
    cleared = {h.lower() for h in re.findall(r'^proxy_set_header\s+(\S+)\s+"";', conf, re.M)}
    assert set(_IP_REVEAL_HEADERS) <= cleared, sorted(set(_IP_REVEAL_HEADERS) - cleared)


# ── Deactivating an account ends its sessions ───────────────────────────────


@pytest.mark.asyncio
async def test_a_reactivated_account_does_not_get_its_old_sessions_back(
    acting_as, db_session: AsyncSession
) -> None:
    """Deactivation refused the account's sessions while it lasted but left them in
    Redis: reactivated within the hour, a browser it was signed in on (left at a desk,
    taken) was signed in again (measured: 200). A reset authenticator already ends them."""
    from app.models.user import AdminRole
    from app.redis_client import get_redis
    from app.services.auth import create_access_token, store_session
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    admin = await _totp_user(db_session, AdminRole.superadmin)
    user = await _totp_user(db_session)
    user.must_change_password = False
    await db_session.commit()
    token = create_access_token(str(user.id), role=user.role.value)
    await store_session(await get_redis(), str(user.id), token)
    client.cookies.set("ow_session", token)
    # /admin/account reads the session itself; acting_as replaces get_current_admin only.
    assert (await client.get("/admin/account")).status_code == 200

    act(admin)
    assert (
        await client.post(f"/admin/users/{user.id}/deactivate", follow_redirects=False)
    ).status_code == 302
    assert (
        await client.post(f"/admin/users/{user.id}/reactivate", follow_redirects=False)
    ).status_code == 302
    resp = await client.get("/admin/account", follow_redirects=False)
    assert resp.status_code != 200, resp.status_code


# ── A sign-in is in the audit log ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_sign_in_is_in_the_audit_log(client: object, db_session: AsyncSession) -> None:
    """AuditAction.AUTH_LOGIN had a label ("Signed in") and a place in the audit-log
    filter, and nothing ever wrote it: the filter always listed nothing."""
    from sqlalchemy import func, select

    from app.models.audit import AuditLog
    from tests.test_coverage_admin_extended import _create_admin, _login_admin

    admin, secret = await _create_admin(db_session)
    await _login_admin(client, admin, secret)  # type: ignore[arg-type]
    rows = await db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.admin_id == admin.id, AuditLog.action == "auth.login"
        )
    )
    assert rows == 1


# ── Instance-wide switches belong to the instance's superadmin ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/admin/ip-warning/dismiss"),
        ("post", "/admin/system/telemetry"),
        ("post", "/admin/system/telemetry/reset-id"),
        ("get", "/admin/system"),
    ],
)
async def test_an_organisations_admin_cannot_touch_the_instance(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    """With multi-tenancy, an organisation's admin could dismiss the instance-wide warning
    that a proxy forwards visitors' addresses (the superadmin then never saw it, and no
    audit row said who hid it) and switch the whole instance's installation count."""
    import uuid

    from app.config import settings
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from tests.test_v210_bug_bounty import _totp_user

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    org = Organisation(id=uuid.uuid4(), name="Tenant", slug=f"tenant-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    tenant_admin = await _totp_user(db_session, AdminRole.admin)
    tenant_admin.org_id = org.id
    await db_session.commit()

    from app.csrf import validate_csrf_header
    from app.main import app

    client, act = acting_as
    act(tenant_admin)
    # The dismiss route takes its token in a header; without this a 403 from CSRF would pass.
    app.dependency_overrides[validate_csrf_header] = lambda: None
    try:
        resp = await getattr(client, method)(path, follow_redirects=False)
    finally:
        app.dependency_overrides.pop(validate_csrf_header, None)
    assert resp.status_code == 403, resp.status_code


# ── The local-review barrier sees the address headers the middleware strips ──


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["x-real-ip", "x-forwarded-for", "fastly-client-ip"])
async def test_an_address_header_hides_the_local_review_button(
    client: object, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    """_local_review_reachable refused a request carrying any address header, but the
    middleware had stripped them before it looked: over HTTP only X-Forwarded-Proto and
    Via were ever checked, the other fourteen were not (the button showed)."""
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    html = (
        await client.get("/admin/login", headers={"host": "localhost", header: "203.0.113.7"})
    ).text  # type: ignore[attr-defined]
    assert "local-review-login-btn" not in html
    plain = (await client.get("/admin/login", headers={"host": "localhost"})).text  # type: ignore[attr-defined]
    assert "local-review-login-btn" in plain  # the button itself still renders


# ── The wizard's code is used up like every other ──────────────────────────


@pytest.mark.asyncio
async def test_the_setup_wizards_code_cannot_sign_in_again(
    throwaway_db: AsyncSession, client: object
) -> None:
    """Every login path marks a TOTP code used (consume_totp: "or a sign-in right after
    enrolment"); the wizard only verified it, so the code that created the first
    superadmin opened a session for 90 more seconds."""
    from sqlalchemy import select

    from app.models.user import AdminUser
    from app.redis_client import get_redis
    from app.services.mfa import consume_totp, generate_totp_secret, get_totp
    from tests.conftest import setup_token

    get_resp = await client.get("/setup", follow_redirects=False)  # type: ignore[attr-defined]
    secret = generate_totp_secret()
    code = get_totp(secret).now()
    resp = await client.post(  # type: ignore[attr-defined]
        "/setup",
        data={
            "username": "firstadmin",
            "password": "SecureTestPassword123!",
            "password_confirm": "SecureTestPassword123!",
            "totp_secret": secret,
            "totp_code": code,
            "csrf_token": get_resp.cookies.get("ow_csrf"),
            "setup_token": await setup_token(),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    user = await throwaway_db.scalar(select(AdminUser).where(AdminUser.username == "firstadmin"))
    assert user is not None
    assert await consume_totp(await get_redis(), user.id, secret, code) is False


# ── Redis holds no reporter's session token ─────────────────────────────────


@pytest.mark.asyncio
async def test_redis_holds_no_status_session_token(
    client: object, db_session: AsyncSession
) -> None:
    """The status session was stored under its own cookie value: anyone who could read
    Redis could open the reporter's case and reply as them for two hours. The failure
    counters were already hashed so "a Redis dump does not list which cases"."""
    from app.redis_client import get_redis
    from app.services.report import create_report

    report, pin = await create_report(db_session, "financial_fraud", "Whose session is this.")
    page = await client.get("/status")  # type: ignore[attr-defined]
    await client.post(  # type: ignore[attr-defined]
        "/status",
        data={
            "case_number": report.case_number,
            "pin": pin,
            "csrf_token": page.cookies.get("ow_csrf"),
        },
        follow_redirects=False,
    )
    token = client.cookies.get("ow-status-session")  # type: ignore[attr-defined]
    assert token
    redis = await get_redis()
    keys = [k async for k in redis.scan_iter(match="status-session:*")]
    assert keys and not any(token in (k.decode() if isinstance(k, bytes) else k) for k in keys)
    assert (await client.get("/status")).text.count(report.case_number) >= 1  # type: ignore[attr-defined]


# ── A percent-encoded database password migrates ───────────────────────────


def test_migrations_run_with_a_percent_encoded_password() -> None:
    """migrations/env.py handed DATABASE_URL to Alembic's ConfigParser, which reads
    "%" as interpolation: a password with a reserved character, which the Ansible role
    percent-encodes (env.j2), stopped `alembic upgrade head` and so the app's start
    ("invalid interpolation syntax"). "%65" decodes to "e": the same password."""
    import os
    import re
    import subprocess
    import sys
    from pathlib import Path

    url = os.environ["DATABASE_URL"]
    user_pw = re.match(r"(postgresql\+asyncpg://[^:]+:)([^@]+)(@.*)", url)
    assert user_pw and "e" in user_pw[2]
    encoded = user_pw[1] + user_pw[2].replace("e", "%65", 1) + user_pw[3]
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "current"],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "DATABASE_URL": encoded},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-500:]


# ── The form offers only what the server keeps ─────────────────────────────


@pytest.mark.asyncio
async def test_without_mode_choice_the_form_offers_no_confidential_report(
    client: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SUBMISSION_MODE_ENABLED=false made the server file every report as anonymous, but
    the form still offered "Confidential" with name and contact fields: what a reporter
    typed there was dropped without a word."""
    from app.config import settings

    monkeypatch.setattr(settings, "submission_mode_enabled", False)
    html = (await client.get("/submit")).text  # type: ignore[attr-defined]
    assert 'id="mode-anonymous"' in html
    assert 'id="mode-confidential"' not in html and 'name="confidential_name"' not in html


@pytest.mark.asyncio
async def test_without_mail_the_form_asks_for_no_address(
    client: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The e-mail field promised a notice on every reply; with NOTIFY_EMAIL_ENABLED off
    (the default) none is ever sent, and the address was stored for nothing."""
    from app.config import settings

    monkeypatch.setattr(settings, "notify_email_enabled", False)
    assert 'name="secure_email"' not in (await client.get("/submit")).text  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "notify_email_enabled", True)
    assert 'name="secure_email"' in (await client.get("/submit")).text  # type: ignore[attr-defined]


# ── The audit log shows what was recorded ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_username_that_reads_like_a_role_stays_a_username(
    client: object, db_session: AsyncSession
) -> None:
    """Every detail value that matched a status or role code was shown as its label,
    whatever the field: an account called "admin" read as "Administrator", one called
    "closed" as "Closed", so the audit trail named someone who never acted."""
    import json
    import uuid

    from app.models.audit import AuditLog
    from tests.test_v150_ux import _login, _make_admin

    admin, secret = await _make_admin(db_session)
    db_session.add(
        AuditLog(
            id=uuid.uuid4(),
            admin_id=admin.id,
            admin_username=admin.username,
            action="report.assigned",
            detail=json.dumps({"from": "closed", "to": "admin", "username": "superadmin"}),
        )
    )
    await db_session.commit()
    await _login(client, admin, secret)
    html = (await client.get("/admin/audit-log")).text  # type: ignore[attr-defined]
    assert "<dd>admin</dd>" in html and "<dd>closed</dd>" in html and "<dd>superadmin</dd>" in html


def test_every_audit_detail_field_has_a_label_in_every_language() -> None:
    """confirmed_by, requested_by, rows, window_minutes, issuer, attachment_id, … showed
    as raw snake_case in every language."""
    import json
    import re
    from pathlib import Path

    root = Path(__file__).parents[1]
    keys: set[str] = set()
    for path in (root / "app").rglob("*.py"):
        for block in re.findall(r"detail=\{(.*?)\}", path.read_text(), re.S):
            keys |= set(re.findall(r'"([a-z_]+)"\s*:', block))
    assert len(keys) > 20
    for locale in (root / "app/locales").glob("*.json"):
        strings = json.loads(locale.read_text())
        missing = sorted(k for k in keys if f"audit.detail.{k}" not in strings)
        assert not missing, (locale.name, missing)


# ── The audit-log filter takes the case number it asks for ──────────────────


@pytest.mark.asyncio
async def test_the_audit_log_filters_by_case_number(
    client: object, db_session: AsyncSession
) -> None:
    """The "report" filter took only a UUID, which no page shows; a case number was
    dropped without a word and the whole log listed and exported, while the box kept
    the value and "Clear filters" made it look applied."""
    import json
    import uuid

    from app.models.audit import AuditLog
    from app.services.report import create_report
    from tests.test_v150_ux import _login, _make_admin

    admin, secret = await _make_admin(db_session)
    mine, _ = await create_report(db_session, "financial_fraud", "The one to filter for.")
    other, _ = await create_report(db_session, "financial_fraud", "Not this one.")
    for report, marker in ((mine, "wanted-row"), (other, "unwanted-row")):
        db_session.add(
            AuditLog(
                id=uuid.uuid4(),
                admin_id=admin.id,
                admin_username=admin.username,
                action="report.note_added",
                report_id=report.id,
                detail=json.dumps({"name": marker}),
            )
        )
    await db_session.commit()
    await _login(client, admin, secret)

    html = (await client.get(f"/admin/audit-log?report_id={mine.case_number}")).text  # type: ignore[attr-defined]
    assert "wanted-row" in html and "unwanted-row" not in html
    csv = (await client.get(f"/admin/audit-log/export.csv?report_id={mine.case_number}")).text  # type: ignore[attr-defined]
    assert "wanted-row" in csv and "unwanted-row" not in csv
    unknown = (await client.get("/admin/audit-log?report_id=OW-0000-00000")).text  # type: ignore[attr-defined]
    assert "wanted-row" not in unknown and "unwanted-row" not in unknown


def test_the_session_countdown_is_not_read_out_every_second() -> None:
    """The countdown sat inside the banner's live region and changed every second, so a
    screen reader announced "4:59", "4:58", … A nested aria-live="off" keeps the banner
    announced once and the clock silent."""
    import re
    from pathlib import Path

    base = (Path(__file__).parents[1] / "app/templates/base.html").read_text()
    countdown = re.search(r'<strong id="session-expiry-countdown"[^>]*>', base)
    assert countdown and 'aria-live="off"' in countdown[0]
