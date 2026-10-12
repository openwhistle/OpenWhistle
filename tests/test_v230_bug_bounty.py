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


# ── Switching the language stays on the page ───────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("next_url", "lands"),
    [
        (
            "/admin/reports/5f0c2a1e-0000-4000-8000-000000000001",
            "/admin/reports/5f0c2a1e-0000-4000-8000-000000000001",
        ),
        ("/admin/users?page=2", "/admin/users?page=2"),
        ("//evil.example/x", "/submit"),
        ("https://evil.example/", "/submit"),
        ("/\\evil.example", "/submit"),
        ("/admin/\\\\evil", "/admin/dashboard"),
    ],
)
async def test_a_language_switch_returns_to_the_same_page(
    client: object, next_url: str, lands: str
) -> None:
    """Outside a six-path allowlist every admin page sent the switch to the dashboard: an
    admin reading a case or the users page lost their place. Any path on this host is
    fine; another host never is."""
    page = await client.get("/submit")  # type: ignore[attr-defined]
    resp = await client.post(  # type: ignore[attr-defined]
        "/set-language",
        data={"lang": "de", "next": next_url, "csrf_token": page.cookies.get("ow_csrf")},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == lands


@pytest.mark.asyncio
async def test_the_mfa_step_offers_no_language_switch_that_loses_it(
    client: object, db_session: AsyncSession
) -> None:
    """The authenticator step is the answer to a POST: a switch sent the admin back to
    /admin/login and the password had to be typed again."""
    from tests.test_coverage_admin_extended import _create_admin

    admin, _ = await _create_admin(db_session)
    page = await client.get("/admin/login")  # type: ignore[attr-defined]
    html = (
        await client.post(  # type: ignore[attr-defined]
            "/admin/login",
            data={
                "username": admin.username,
                "password": "AdminExt!Pass1",
                "csrf_token": page.cookies.get("ow_csrf"),
            },
        )
    ).text
    assert 'name="totp_code"' in html
    assert 'action="/set-language"' not in html


@pytest.mark.asyncio
async def test_a_deletion_notice_needs_a_deletion(acting_as, db_session: AsyncSession) -> None:
    """/admin/dashboard?deleted=<anything> showed a green "deleted" notice: a crafted link
    could tell an admin that a case was gone while it was not."""
    from app.models.user import AdminRole
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    html = (await client.get("/admin/dashboard?deleted=OW-2026-99999")).text
    assert "Report permanently deleted" not in html


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/submit", "/status", "/admin/login"])
async def test_the_tab_title_carries_the_operators_name(
    client: object, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """APP_NAME renamed the nav and footer, but nineteen page titles said "| OpenWhistle"
    in the tab and the browser history."""
    import re

    from app.templating import templates

    monkeypatch.setitem(templates.env.globals["brand"], "name", "Acme Reports")
    html = (await client.get(path)).text  # type: ignore[attr-defined]
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    assert title and "Acme Reports" in title[1] and "OpenWhistle" not in title[1], title


def test_the_description_field_takes_what_its_counter_allows() -> None:
    """maxlength counts UTF-16 units, the counter and the server count characters: text
    with emoji stopped at 5,000 characters while the counter read "5,000 / 10,000"."""
    import re
    from pathlib import Path

    html = (Path(__file__).parents[1] / "app/templates/submit.html").read_text()
    textarea = re.search(r'<textarea[^>]*id="description"[^>]*>', html, re.S)
    assert textarea and "maxlength" not in textarea[0]


# ── Creating an account says what is wrong, on the form ─────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username", "password", "field_text"),
    [
        ("new-person", "ä" * 37, "at most 72 bytes"),  # 74 bytes, 37 characters
        ("x!", "LongEnoughPass123!", "3 to 64 characters"),
        ("taken", "LongEnoughPass123!", "already"),
    ],
)
async def test_a_refused_account_is_explained_on_the_form(
    acting_as,
    db_session: AsyncSession,
    username: str,
    password: str,
    field_text: str,
) -> None:
    """A password over 72 bytes, an invalid or a taken username each gave a bare 400/409
    error page: the form was gone and the reason was not given in the admin's language."""
    import uuid

    from app.models.user import AdminRole
    from app.services.users import create_user
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    if username == "taken":
        username = f"taken-{uuid.uuid4().hex[:6]}"
        await create_user(db_session, username, "LongEnoughPass123!", AdminRole.case_manager)
    resp = await client.post(
        "/admin/users", data={"username": username, "password": password, "role": "case_manager"}
    )
    assert resp.status_code == 422, resp.status_code
    assert field_text in resp.text
    assert f'value="{username}"' in resp.text  # what was typed is kept


@pytest.mark.asyncio
async def test_the_update_check_does_not_tell_github_the_version() -> None:
    """README: "nothing about the instance is sent"; the request's User-Agent was
    OpenWhistle/<version>, the one fact the installation count asks consent for."""
    from unittest.mock import AsyncMock, patch

    from app.config import settings
    from app.services import version_check as vc
    from tests.test_version_check import _mock_httpx

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    client = _mock_httpx(304)
    with patch("httpx.AsyncClient", return_value=client):
        await vc.fetch_latest_release(redis)
    headers = client.get.await_args.kwargs["headers"]
    assert settings.app_version not in " ".join(headers.values())


@pytest.mark.asyncio
async def test_each_organisations_search_entry_counts_its_own_hits(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A superadmin's search was written into every organisation's log with the hits of
    all of them: one organisation's admins read how many of another's reports matched."""
    import json
    import uuid

    from sqlalchemy import select

    from app.config import settings
    from app.models.audit import AuditLog
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from app.services.audit import AuditAction
    from app.services.report import create_report, default_org_id
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    one = Organisation(id=uuid.uuid4(), name="One", slug=f"one-{uuid.uuid4().hex[:6]}")
    three = Organisation(id=uuid.uuid4(), name="Three", slug=f"three-{uuid.uuid4().hex[:6]}")
    db_session.add_all([one, three])
    await db_session.commit()
    word = f"okapi{uuid.uuid4().hex[:6]}"
    await create_report(db_session, "financial_fraud", f"A {word} once.", org_id=one.id)
    for i in range(3):
        await create_report(db_session, "financial_fraud", f"A {word} {i}.", org_id=three.id)
    superadmin = await _totp_user(db_session, AdminRole.superadmin)
    superadmin.org_id = await default_org_id(db_session)
    await db_session.commit()
    act(superadmin)

    await client.post("/admin/dashboard", data={"q": word})
    rows = (
        await db_session.execute(
            select(AuditLog.org_id, AuditLog.detail).where(
                AuditLog.admin_id == superadmin.id,
                AuditLog.action == AuditAction.CONTENT_SEARCHED,
            )
        )
    ).all()
    hits = {org: json.loads(detail)["hits"] for org, detail in rows}
    assert hits[one.id] == 1 and hits[three.id] == 3, hits


@pytest.mark.asyncio
async def test_plain_http_carries_no_hsts(client: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 6797 § 8.1, quoted in the middleware: a host MUST NOT send HSTS over a
    connection that is not secure. Only the onion listener was spared; an instance run
    on plain HTTP on purpose (SECURE_COOKIES=false) sent it on every response."""
    from app.config import settings

    monkeypatch.setattr(settings, "secure_cookies", False)
    assert "strict-transport-security" not in (await client.get("/health")).headers  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "secure_cookies", True)
    assert "strict-transport-security" in (await client.get("/health")).headers  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_pdf_export_is_its_own_audit_entry(acting_as, db_session: AsyncSession) -> None:
    """A case exported to a file was written as "report viewed": indistinguishable from
    opening the page, and hidden by default with the views. README: every admin action
    recorded."""
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.user import AdminRole
    from app.services.report import create_report
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    admin = await _totp_user(db_session, AdminRole.admin)
    act(admin)
    report, _ = await create_report(db_session, "financial_fraud", "Exported to a file.")
    assert (await client.get(f"/admin/reports/{report.id}/export.pdf")).status_code == 200
    actions = (
        (await db_session.execute(select(AuditLog.action).where(AuditLog.report_id == report.id)))
        .scalars()
        .all()
    )
    assert "report.exported" in actions, actions


# ── An action and its audit entry commit together ───────────────────────────


@pytest.mark.asyncio
async def test_a_status_change_without_its_audit_entry_does_not_stand(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """audit.log says the caller "commits as part of their own transaction", but the
    services committed the action first: when writing the audit entry failed, the status
    change stood with nothing in the log (HinSchG § 11 documentation)."""
    from sqlalchemy import select

    from app.models.report import Report, ReportStatus
    from app.models.user import AdminRole
    from app.services import audit as audit_service
    from app.services.report import create_report
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    report, _ = await create_report(db_session, "financial_fraud", "Status without a trail.")

    async def broken_log(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(audit_service, "log", broken_log)
    with pytest.raises(RuntimeError):
        await client.post(f"/admin/reports/{report.id}/status", data={"new_status": "in_review"})
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            status = await conn.scalar(select(Report.status).where(Report.id == report.id))
    finally:
        await engine.dispose()
    assert status == ReportStatus.received


# ── Drafts cannot push Redis past its limit ─────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_attachment_drafts_stay_below_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The room check measured Redis before the upload and without its size, and nothing
    serialised it: uploads arriving together all passed just below 80 % and together
    went past maxmemory, where noeviction refuses every write (admin sessions too)."""
    import asyncio

    import app.api.reports as reports
    from app.config import settings

    monkeypatch.setattr(settings, "draft_redis_memory_percent", 80)
    used = {"bytes": 700}

    class _Redis:
        async def info(self, section: str) -> dict[str, int]:
            await asyncio.sleep(0)  # concurrent requests interleave here
            return {"maxmemory": 1000, "used_memory": used["bytes"]}

        def lock(self, *args: object, **kwargs: object) -> _Lock:
            return _Lock()

    shared = asyncio.Lock()

    class _Lock:  # redis.asyncio.lock.Lock: both coroutines
        async def acquire(self) -> bool:
            return await shared.acquire()

        async def release(self) -> None:
            shared.release()

    async def upload(size: int) -> bool:
        async with reports._draft_room(_Redis(), size) as room:  # type: ignore[arg-type]
            if room:
                await asyncio.sleep(0)
                used["bytes"] += size
            return room

    results = await asyncio.gather(*(upload(60) for _ in range(5)))
    assert used["bytes"] <= 800, (used, results)
    assert results.count(True) == 1


@pytest.mark.asyncio
async def test_a_category_bar_is_its_share_of_all_reports(
    acting_as, db_session: AsyncSession
) -> None:
    """The category bars were scaled to the largest category: 75 % of all reports drew a
    full bar beside the label "75 %", while the status bars beside them were shares."""
    import re

    from app.models.user import AdminRole
    from app.services.report import create_report
    from tests.test_v210_bug_bounty import _totp_user

    for category in ("financial_fraud", "financial_fraud", "corruption"):
        await create_report(db_session, category, "Counted on the stats page.")
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    html = (await client.get("/admin/stats")).text
    bars = re.findall(r'stat-bar-fill-outline" data-pct="([\d.]+)"', html)
    assert bars and abs(sum(map(float, bars)) - 100) < 1, bars
