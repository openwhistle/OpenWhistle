"""Defects found by the bug bounty after v2.4.1, each reproduced before it was fixed."""

import uuid

import pytest

# ── A refresh between the sweep's SCAN and its GET survives a password change ──


@pytest.mark.asyncio
async def test_a_refresh_inside_the_sweep_does_not_survive_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep read a SCAN page, then fetched and deleted each key one by one. A refresh
    that stored its new session and deleted the old one after the page was read and before
    the old key was fetched left the sweep nothing to delete — measured: the new session
    still validated after ``revoke_user_sessions``. A password change, a deactivation and a
    reset authenticator all end sessions this way."""
    from redis.asyncio import from_url

    from app.config import settings
    from app.services import auth as auth_service

    redis = from_url(settings.redis_url, decode_responses=True)
    user_id = str(uuid.uuid4())
    old = auth_service.create_access_token(user_id, role="admin")
    await auth_service.store_session(redis, user_id, old)
    new = auth_service.create_access_token(user_id, role="admin")
    old_key = auth_service._key(auth_service._SESSION_PREFIX, old)

    real_get = redis.get
    refreshed: list[bool] = []

    async def refresh_before_the_sweep_reads(key):  # type: ignore[no-untyped-def]
        if key == old_key and not refreshed:
            # The refresh handler's two steps: store the new session, delete the old one.
            await auth_service.store_session(redis, user_id, new)
            refreshed.append(await auth_service.revoke_session(redis, old))
        return await real_get(key)

    monkeypatch.setattr(redis, "get", refresh_before_the_sweep_reads)
    await auth_service.revoke_user_sessions(redis, user_id)
    monkeypatch.undo()

    # Either the refresh ran before an atomic sweep and lost its old session, or it ran
    # after it; either way no session of the user is left.
    assert not await auth_service.validate_session(redis, new)
    assert not await auth_service.validate_session(redis, old)
    await redis.aclose()


@pytest.mark.asyncio
async def test_the_sweep_keeps_the_callers_session_and_other_users() -> None:
    from redis.asyncio import from_url

    from app.config import settings
    from app.services import auth as auth_service

    redis = from_url(settings.redis_url, decode_responses=True)
    user_id, other = str(uuid.uuid4()), str(uuid.uuid4())
    mine, theirs, gone = (
        auth_service.create_access_token(u, role="admin") for u in (user_id, other, user_id)
    )
    for owner, token in ((user_id, mine), (other, theirs), (user_id, gone)):
        await auth_service.store_session(redis, owner, token)
    await auth_service.store_totp_pending(redis, "pending-" + user_id, user_id)

    removed = await auth_service.revoke_user_sessions(redis, user_id, keep=mine)

    assert removed == 2
    assert await auth_service.validate_session(redis, mine)
    assert await auth_service.validate_session(redis, theirs)
    assert not await auth_service.validate_session(redis, gone)
    assert await auth_service.consume_totp_pending(redis, "pending-" + user_id) is None
    await redis.aclose()


# ── A burst of setup tokens is checked against the limit, not past it ─────────


@pytest.mark.asyncio
async def test_a_burst_of_wrong_setup_tokens_checks_no_more_than_the_limit(
    client, setup_incomplete
) -> None:  # type: ignore[no-untyped-def]
    """The lock was read before the token was checked and the failure counted after it,
    so a burst all read the same count: 50 wrong tokens sent together were all checked
    (50 × 403, 0 × 429) against MAX_LOGIN_ATTEMPTS=10. Sent one by one, the eleventh was
    refused — the race ``claim_admin_attempt`` closed for the sign-in form in 2.1.0."""
    import asyncio
    import re

    from redis.asyncio import from_url

    from app.config import settings
    from app.services.rate_limit import reset_setup_token_failures

    redis = from_url(settings.redis_url)
    await reset_setup_token_failures(redis)
    page = await client.get("/setup")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    data = {
        "csrf_token": csrf.group(1) if csrf else "",
        "setup_token": "wrong-" + "x" * 40,
        "username": "burstadmin",
        "password": "Correct-horse-9-battery",
        "password_confirm": "Correct-horse-9-battery",
        "totp_secret": "x",
        "totp_code": "000000",
    }
    codes = [
        r.status_code
        for r in await asyncio.gather(*(client.post("/setup", data=data) for _ in range(50)))
    ]
    await reset_setup_token_failures(redis)
    await redis.aclose()
    assert codes.count(403) == settings.max_login_attempts
    assert codes.count(429) == 50 - settings.max_login_attempts


# ── Automatic deletion clears what the four-eyes deletion clears ─────────────


@pytest.mark.asyncio
async def test_retention_leaves_no_reminder_mark_or_queue_entry_behind(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """The four-eyes deletion calls ``forget_case``; the automatic one did not. An erased
    case kept ``reminder:feedback:<case>`` (up to the warn window plus a day) and its place
    in the digest queue — its number in plain text after the erasure."""
    from datetime import UTC, datetime, timedelta

    from redis.asyncio import from_url

    import app.services.retention as retention
    from app.config import settings
    from app.models.report import ReportStatus
    from app.services import reminders
    from app.services.notifications import _QUEUE_KEYS
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Erased by retention.")
    report.status = ReportStatus.closed
    report.closed_at = datetime.now(UTC) - timedelta(days=3)
    await db_session.commit()
    case = report.case_number

    redis = from_url(settings.redis_url, decode_responses=True)
    await redis.set(reminders._feedback_dedup_key(case), "1", ex=3600)
    await redis.set(reminders._ack_dedup_key(case), "1", ex=3600)
    await redis.sadd(_QUEUE_KEYS["new_messages"], case)

    monkeypatch.setattr(settings, "retention_enabled", True)
    monkeypatch.setattr(settings, "retention_days", 1)
    await retention.run_retention_cleanup()

    left = await redis.exists(reminders._feedback_dedup_key(case), reminders._ack_dedup_key(case))
    queued = await redis.sismember(_QUEUE_KEYS["new_messages"], case)
    await redis.aclose()
    assert (left, queued) == (0, 0)


# ── Without JavaScript the success page's way on is reachable ────────────────


def test_the_success_pages_link_on_is_not_rendered_disabled() -> None:
    """``Go to status`` was rendered with ``tabindex="-1"`` and ``aria-disabled="true"``,
    and only the page's script turned them off. In Tor Browser's Safest mode (no script)
    a keyboard could not reach the link and a screen reader announced it as disabled —
    on the page whose PIN cannot be recovered. The script disables it on load instead."""
    from pathlib import Path

    html = (Path(__file__).parents[1] / "app/templates/submit_success.html").read_text()
    tag = html[html.index('id="go-to-status"') :].split(">", 1)[0]
    assert 'tabindex="-1"' not in tag
    assert "aria-disabled" not in tag


def test_no_script_scrolls_smoothly_past_reduced_motion() -> None:
    """``scrollIntoView({behavior: 'smooth'})`` overrides the stylesheet, whose
    reduced-motion rule sets ``scroll-behavior: auto`` (DESIGN.md: with reduced motion,
    state changes are instant). Left at ``auto``, a script follows that rule."""
    import re
    from pathlib import Path

    root = Path(__file__).parents[1] / "app"
    files = [*root.glob("templates/**/*.html"), *root.glob("static/js/*.js")]
    smooth = [f.name for f in files if re.search(r"behavior:\s*['\"]smooth", f.read_text())]
    assert smooth == []


# ── An organisation's dark logo alone is shown ───────────────────────────────


def test_an_organisations_dark_logo_alone_is_shown() -> None:
    """The images came from the organisation's row only when it had a light logo. An
    organisation admin who uploaded only a dark logo saw "saved" and an audit entry, and
    every page kept the default's images — the upload was stored and never shown. The
    default row with only a dark logo pairs it with BRAND_LOGO_URL; an organisation's
    row now does the same."""
    from app.config import settings
    from app.services import branding

    org = uuid.uuid4()
    snap = {
        "default": {"logo_light": "a" * 64, "logo_dark": "b" * 64},
        str(org): {"logo_light": None, "logo_dark": "c" * 64},
    }
    brand = branding.resolve(snap, org)
    assert brand.logo_dark_url == f"/branding/{'c' * 64}.png"
    assert brand.logo_url == settings.brand_logo_url


# ── A demo visitor cannot rebrand the public demo ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "data"),
    [("/admin/branding", {"name": "Defaced"}), ("/admin/branding/reset", {"field": "all"})],
)
async def test_the_demo_branding_is_shown_but_not_saved(
    acting_as, db_session, clean_branding, monkeypatch: pytest.MonkeyPatch, path: str, data: dict
) -> None:  # type: ignore[no-untyped-def]
    """Every demo visitor signs in as the same admin. Name, logo and colour saved on
    /admin/branding were what every later visitor of the public demo saw until the next
    reset, six hours on. The page still opens and previews; it does not save."""
    from sqlalchemy import select

    from app.config import settings
    from app.models.branding import Branding
    from app.models.user import AdminRole
    from tests.test_v210_bug_bounty import _totp_user

    monkeypatch.setattr(settings, "demo_mode", True)
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))

    assert (await client.get("/admin/branding")).status_code == 200
    resp = await client.post(path, data={"csrf_token": "x", **data}, follow_redirects=False)
    assert resp.status_code == 403
    assert await db_session.scalar(select(Branding.name).where(Branding.org_id.is_(None))) is None


# ── §17 deadlines end at the end of their last day (§§ 187, 188 BGB) ─────────


def test_an_acknowledgement_on_the_seventh_day_is_on_time() -> None:
    """Received on 1 March, the seven days of § 17 Abs. 1 Nr. 1 start on 2 March (§ 187
    Abs. 1 BGB: the day of receipt does not count) and end with 8 March (§ 188 Abs. 1).
    The deadline was 8 March 00:00, so an acknowledgement on 8 March at noon read
    "Acknowledged (late)" in the PDF export and counted as missed in the SLA rate."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.i18n import make_translator
    from app.services import deadlines, pdf

    received = datetime(2027, 3, 1, tzinfo=UTC)
    on_the_last_day = datetime(2027, 3, 8, 23, 30, tzinfo=UTC)
    assert deadlines.ack_on_time(received, on_the_last_day)
    assert not deadlines.ack_on_time(received, datetime(2027, 3, 9, 0, 5, tzinfo=UTC))
    report = SimpleNamespace(submitted_at=received, acknowledged_at=on_the_last_day)
    t = make_translator("en")
    assert pdf._ack_label(report, datetime(2027, 3, 20, tzinfo=UTC), t) == t("pdf.ack.compliant")
    last_day = deadlines.ack_status(received, None, datetime(2027, 3, 8, 22, tzinfo=UTC))
    assert last_day.state == "warning"


def test_the_feedback_deadline_ends_with_its_last_day() -> None:
    """§ 17 Abs. 2: three months from the acknowledgement end with the day of the
    same number (§ 188 Abs. 2 BGB) — acknowledged 1 February 09:00, the last day is
    1 May, not 1 May 09:00. Without an acknowledgement it is three months *and then*
    seven days after receipt: received 24 November, the last day is 3 March, where
    seven days first and three months after gave 1 March."""
    from datetime import UTC, datetime

    from app.services import deadlines

    acked = deadlines.feedback_due(
        datetime(2027, 1, 30, tzinfo=UTC), datetime(2027, 2, 1, 9, tzinfo=UTC)
    )
    assert (
        acked.date().isoformat(),
        deadlines.feedback_status(acked, None, datetime(2027, 5, 1, 20, tzinfo=UTC)).state,
    ) == ("2027-05-01", "warning")
    unacked = deadlines.feedback_due(datetime(2026, 11, 24, tzinfo=UTC))
    assert unacked.date().isoformat() == "2027-03-03"


@pytest.mark.asyncio
async def test_the_sla_rate_counts_an_acknowledgement_on_the_seventh_day(throwaway_db) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    from app.services import report as report_service

    report, _ = await report_service.create_report(throwaway_db, "financial_fraud", "Day seven.")
    day = (datetime.now(UTC) - timedelta(days=30)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    report.submitted_at = day
    report.acknowledged_at = day + timedelta(days=7, hours=22)
    await throwaway_db.commit()
    assert (await report_service.get_dashboard_stats(throwaway_db))["sla_7day_rate"] == 100


# ── Feedback is the office's first message after the acknowledgement ────────


@pytest.mark.asyncio
async def test_feedback_counts_as_given_once_the_office_writes_not_once_the_case_closes(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    """ "Delivered" (§ 17 Abs. 2) followed the case's status: a case closed without
    a word to the reporter read "Delivered" on the status page, the case page and in the
    PDF, and a case the office had answered stayed "Overdue" — for the reporter too — and
    was reminded about every day until it was closed."""
    from datetime import UTC, datetime, timedelta

    from app.models.report import ReportStatus
    from app.services import deadlines
    from app.services import report as report_service

    answered, _ = await report_service.create_report(db_session, "financial_fraud", "Answered.")
    await report_service.acknowledge_report(db_session, answered)
    assert answered.feedback_sent_at is None  # the receipt message is not feedback
    await report_service.add_admin_message(db_session, answered, "We are looking into it.")
    later = datetime.now(UTC) + timedelta(days=400)
    assert answered.status == ReportStatus.in_review
    state = deadlines.feedback_status(answered.feedback_due_at, answered.feedback_sent_at, later)
    assert state is not None and state.state == "done"

    silent, _ = await report_service.create_report(db_session, "financial_fraud", "Closed.")
    await report_service.acknowledge_report(db_session, silent)
    silent.status = ReportStatus.closed
    silent.closed_at = datetime.now(UTC)
    await db_session.commit()
    state = deadlines.feedback_status(silent.feedback_due_at, silent.feedback_sent_at, later)
    assert state is not None and state.state == "overdue"


@pytest.mark.asyncio
async def test_a_case_with_feedback_given_is_not_reminded(db_session) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    from app.config import settings
    from app.services import reminders
    from app.services import report as report_service

    report, _ = await report_service.create_report(db_session, "financial_fraud", "Reminded?")
    await report_service.acknowledge_report(db_session, report)
    await report_service.add_admin_message(db_session, report, "Feedback.")
    due = report.feedback_due_at
    assert due is not None
    sent = await reminders._check_feedback_reminder(
        report, due + timedelta(days=2), db_session, object(), settings
    )
    assert sent is False
    assert report.feedback_sent_at <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_migration_020_backfills_feedback_and_moves_deadlines_to_their_last_day(
    throwaway_db,
) -> None:  # type: ignore[no-untyped-def]
    import os
    import subprocess
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.config import settings
    from app.services import report as report_service

    env = {**os.environ, "DATABASE_URL": settings.database_url}

    def alembic(*args: str) -> None:
        run = subprocess.run(["alembic", *args], capture_output=True, text=True, env=env)  # noqa: S603, S607
        assert run.returncode == 0, run.stderr

    report, _ = await report_service.create_report(throwaway_db, "financial_fraud", "Old row.")
    await throwaway_db.commit()
    alembic("downgrade", "d4f1b8c6e203")
    acked = datetime(2027, 2, 1, 9, tzinfo=UTC)
    await throwaway_db.execute(
        text(
            "UPDATE reports SET submitted_at = :sub, acknowledged_at = :ack,"
            " feedback_due_at = :old WHERE id = :id"
        ),
        {
            "sub": datetime(2027, 1, 30, tzinfo=UTC),
            "ack": acked,
            "old": datetime(2027, 5, 1, 9, tzinfo=UTC),
            "id": report.id,
        },
    )
    await throwaway_db.execute(
        text(
            "INSERT INTO report_messages (id, report_id, sender, content, sent_at) VALUES"
            " (gen_random_uuid(), :id, 'admin', 'x', :before),"
            " (gen_random_uuid(), :id, 'whistleblower', 'x', :wb),"
            " (gen_random_uuid(), :id, 'admin', 'x', :first),"
            " (gen_random_uuid(), :id, 'admin', 'x', :second)"
        ),
        {
            "id": report.id,
            "before": datetime(2027, 1, 31, tzinfo=UTC),
            "wb": datetime(2027, 2, 2, tzinfo=UTC),
            "first": datetime(2027, 3, 1, 10, tzinfo=UTC),
            "second": datetime(2027, 4, 1, 10, tzinfo=UTC),
        },
    )
    await throwaway_db.commit()
    alembic("upgrade", "head")
    row = (
        await throwaway_db.execute(
            text("SELECT feedback_sent_at, feedback_due_at FROM reports WHERE id = :id"),
            {"id": report.id},
        )
    ).one()
    assert row.feedback_sent_at == datetime(2027, 3, 1, 10, tzinfo=UTC)
    assert row.feedback_due_at.astimezone(UTC).isoformat() == "2027-05-01T23:59:59.999999+00:00"


# ── The integrity check covers what runs, per replica, comparably ────────────


def test_the_integrity_manifest_covers_the_migrations_and_scripts_that_run() -> None:
    """Only ``app/`` was hashed. ``migrations/`` runs at every start (alembic) and
    ``scripts/ensure_tls_cert.py`` runs as root in the ``tls-init`` container; a changed
    file there left the System page at "All files verified"."""
    from app.services import integrity as ig

    index = ig.build_file_index(ig.SHIPPED_ROOTS)
    assert {"app/main.py", "migrations/env.py", "scripts/ensure_tls_cert.py"} <= set(index)


def test_the_manifest_hash_is_the_same_for_the_same_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """The manifest carried ``generated_at``, so its SHA-256 — shown on the System page
    "to be compared against a value published out-of-band" — differed on every build and
    matched nothing. Without it, a checkout of the release tag prints the same hash."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "gen", Path(__file__).parents[1] / "scripts/generate_integrity_manifest.py"
    )
    gen = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(gen)  # type: ignore[union-attr]
    out = tmp_path / "m.json"
    monkeypatch.setattr(gen, "DEFAULT_MANIFEST_PATH", out)
    gen.main()
    first = out.read_bytes()
    gen.main()
    assert out.read_bytes() == first


@pytest.mark.asyncio
async def test_each_replica_caches_its_own_integrity_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One Redis key for every replica: replica B showed replica A's "All files
    verified" for five minutes, and during a rolling upgrade the other image's
    manifest."""
    from unittest.mock import AsyncMock

    from app.services import integrity as ig

    keys = []
    for host in ("replica-a", "replica-b"):
        monkeypatch.setattr(ig.socket, "gethostname", lambda h=host: h)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        await ig.get_integrity_status(redis)
        keys.append(redis.get.await_args.args[0])
    assert keys[0] != keys[1]


# ── An error page's way back works without JavaScript ───────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "back"), [("/no-such-page", "/"), ("/admin/no-such-page", "/admin/dashboard")]
)
async def test_the_error_pages_way_back_is_a_real_link(client, path: str, back: str) -> None:  # type: ignore[no-untyped-def]
    """ "Go back" was ``href="#"`` and worked only through ``history.back()`` — the one
    control on a reporter's 404, 422 or 429 page did nothing in Tor Browser's Safest
    mode. It now leads home; with JavaScript it still goes back."""
    resp = await client.get(path, headers={"accept": "text/html"})
    assert resp.status_code == 404
    assert f'id="err-back-link" href="{back}"' in resp.text


def test_every_language_says_retention_counts_from_closing() -> None:
    """English said deletion counts from ``closed_at``; German and French said only
    "older than {days} days", which reads as counted from the report."""
    import json
    from pathlib import Path

    for path in (Path(__file__).parents[1] / "app/locales").glob("*.json"):
        assert (
            "<code>closed_at</code>" in json.loads(path.read_text())["admin.retention.how.2.html"]
        ), path.name


# ── bcrypt never runs on the event loop ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_password_change_hashes_off_the_event_loop(
    client, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """The sign-in form checks passwords in a thread ("bcrypt on the event loop stalled
    every request for each guess"); the password change checked the current one and
    hashed the new one on the loop — about 0.25 s each with every other request waiting.
    Creating an account, the setup wizard and a superadmin's reset hashed there too."""
    import asyncio

    from app.services import auth as auth_service
    from tests.test_v210_own_account import _change, _sign_in, _user

    on_loop: list[str] = []

    def off_loop(fn):  # type: ignore[no-untyped-def]
        def wrapped(*args):  # type: ignore[no-untyped-def]
            try:
                asyncio.get_running_loop()
                on_loop.append(fn.__name__)
            except RuntimeError:
                pass
            return fn(*args)

        return wrapped

    user = await _user(db_session)
    csrf = await _sign_in(client, user)
    for name in ("verify_password", "hash_password"):
        monkeypatch.setattr(auth_service, name, off_loop(getattr(auth_service, name)))
    resp = await _change(client, csrf, user)
    assert resp.status_code == 303
    assert on_loop == []


# ── nginx streams uploads instead of writing them to its disk ───────────────


def test_every_bundled_nginx_streams_request_bodies_to_the_app() -> None:
    """Buffered, nginx wrote each body over 16k to client_temp — the original
    attachments on its disk — and on a full disk logged ``[crit] pwrite() … failed
    (28: No space left on device), client: <address>``: three uploads at the 55 MB
    limit fill the 128 MB tmpfs. CI replays it against the shipped image."""
    from pathlib import Path

    root = Path(__file__).parents[1]
    snippet = (root / "nginx/snippets/proxy-headers.conf").read_text()
    assert "\nproxy_request_buffering off;" in snippet
    for conf in (
        "nginx/nginx.conf",
        "nginx/nginx.behind-proxy.conf",
        "ansible/roles/openwhistle/templates/nginx.conf.j2",
    ):
        text = (root / conf).read_text()
        assert "include /etc/nginx/snippets/proxy-headers.conf;" in text, conf
        assert "proxy_request_buffering on" not in text, conf


# ── Uploads beyond what /tmp holds are refused up front, not half-parsed ─────


@pytest.mark.asyncio
async def test_an_upload_the_spool_cannot_hold_gets_a_busy_page_not_a_broken_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starlette spools every file part over 1 MB to /tmp (128 MB, in memory). Uploads
    in flight beyond that failed mid-parse: measured with an 8 MB /tmp, three 6 MB
    uploads at once gave one 200 and two "400 There was an error parsing the body" —
    in production the third 55 MB submission at once. Now each multipart request
    reserves its declared size first; one that does not fit is drained and answered
    with 503, Retry-After and a page that says to send it again."""
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from app import middleware

    monkeypatch.setattr(middleware, "_spool_capacity", lambda: 10_000)
    held = asyncio.Event()
    release = asyncio.Event()

    async def slow_app(scope, receive, send):  # type: ignore[no-untyped-def]
        while (await receive()).get("more_body"):
            pass
        held.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def busy(scope, send):  # type: ignore[no-untyped-def]
        await send(
            {"type": "http.response.start", "status": 503, "headers": [(b"retry-after", b"60")]}
        )
        await send({"type": "http.response.body", "body": b"busy"})

    app = middleware.UploadBudgetMiddleware(slow_app, refuse=busy)
    files = {"files": ("a.bin", b"x" * 6_000, "application/octet-stream")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = asyncio.create_task(client.post("/submit", files=files))
        await held.wait()
        # A bounded wait: without the budget the second upload waits on the first.
        second = await asyncio.wait_for(client.post("/submit", files=files), 5)
        release.set()
        assert (await first).status_code == 200
        third = await client.post("/submit", files=files)  # the first one's share is back
        plain = await client.post("/submit", data={"step": "1"})  # not multipart: untouched
    assert (second.status_code, second.headers["retry-after"]) == (503, "60")
    assert third.status_code == 200
    release.set()
    assert plain.status_code == 200


@pytest.mark.asyncio
async def test_the_app_answers_a_full_spool_with_its_own_busy_page(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from app import middleware

    monkeypatch.setattr(middleware, "_spool_capacity", lambda: 1)
    resp = await client.post(
        "/submit",
        files={"files": ("a.bin", b"x" * 2048, "application/octet-stream")},
        headers={"accept": "text/html"},
    )
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "60"
    assert "send the form again in a minute" in resp.text
