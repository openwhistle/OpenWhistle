"""The voluntary installation count: what leaves the host, when, and who may switch it."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_admin
from app.config import Settings, settings
from app.main import app
from app.models.audit import AuditLog
from app.models.telemetry import TelemetryState
from app.models.user import AdminRole, AdminUser
from app.services import telemetry
from app.services.audit import AuditAction
from app.services.auth import hash_password
from app.services.mfa import generate_totp_secret, get_totp
from tests.conftest import setup_token

# ── A local stand-in for telemetry.wdkro.de ────────────────────────────────


class _Hits(list[dict[str, Any]]):
    pass


def _handler(hits: _Hits) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server API
            path = urlsplit(self.path).path
            hits.append({"path": path, "query": urlsplit(self.path).query,
                         "headers": dict(self.headers.items()), "method": "GET"})
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.end_headers()
                return
            if path == "/slow":
                time.sleep(1.5)
            if path == "/fail":
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    return Handler


@pytest.fixture
def fake_server() -> Iterator[tuple[str, _Hits]]:
    hits = _Hits()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(hits))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", hits
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def consent_from_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """conftest forces TELEMETRY_ENABLED=false for every test; these need the in-app answer."""
    monkeypatch.setattr(settings, "telemetry_enabled", None)
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "local_review_login", False)


@pytest_asyncio.fixture(loop_scope="function")
async def redis() -> AsyncGenerator[Redis]:
    r = Redis.from_url(settings.redis_url)
    await r.delete(telemetry.LOCK_KEY)
    yield r
    await r.delete(telemetry.LOCK_KEY)
    await r.aclose()


async def _set_row(db: AsyncSession, *, enabled: bool | None,
                   last_sent_at: datetime | None = None) -> None:
    """enabled=None: no row at all (an installation never asked)."""
    await db.execute(text("DELETE FROM telemetry_state"))
    if enabled is not None:
        db.add(TelemetryState(id=1, enabled=enabled, installation_id="ab" * 16,
                              last_sent_at=last_sent_at))
    await db.commit()


async def _row(db: AsyncSession) -> TelemetryState | None:
    return await db.scalar(
        select(TelemetryState).execution_options(populate_existing=True)
    )


# ── The request itself ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_report_is_one_get_with_the_id_and_the_version_and_nothing_else(
    fake_server: tuple[str, _Hits], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/v1/openwhistle/count")

    assert await telemetry.send_report("0123456789abcdef" * 2) is True

    assert len(hits) == 1
    hit = hits[0]
    assert hit["method"] == "GET"
    assert hit["path"] == "/v1/openwhistle/count"
    assert parse_qs(hit["query"]) == {"id": ["0123456789abcdef" * 2], "v": [settings.app_version]}
    headers = {k.lower(): v for k, v in hit["headers"].items()}
    assert headers["user-agent"] == f"openwhistle/{settings.app_version}"
    assert set(headers) <= {"host", "user-agent", "accept", "accept-encoding", "connection"}


def test_the_production_endpoint_is_the_documented_one() -> None:
    assert telemetry.TELEMETRY_ENDPOINT == "https://telemetry.wdkro.de/v1/openwhistle/count"


@pytest.mark.asyncio
async def test_a_redirect_is_refused_not_followed(
    fake_server: tuple[str, _Hits], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/redirect")

    assert await telemetry.send_report("ab" * 16) is False
    assert [h["path"] for h in hits] == ["/redirect"]


@pytest.mark.asyncio
async def test_a_slow_endpoint_is_given_up_on(
    fake_server: tuple[str, _Hits], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _ = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/slow")
    monkeypatch.setattr(telemetry, "TIMEOUT_SECONDS", 0.2)

    started = time.monotonic()
    assert await telemetry.send_report("ab" * 16) is False
    assert time.monotonic() - started < 1.2


def test_the_timeout_is_ten_seconds() -> None:
    assert telemetry.TIMEOUT_SECONDS == 10


@pytest.mark.asyncio
async def test_a_failure_is_one_debug_line_and_no_error(
    fake_server: tuple[str, _Hits], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base, _ = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/fail")
    with caplog.at_level(logging.DEBUG, logger="app.services.telemetry"):
        assert await telemetry.send_report("ab" * 16) is False
    records = [r for r in caplog.records if r.name == "app.services.telemetry"]
    assert [r.levelno for r in records] == [logging.DEBUG]


@pytest.mark.asyncio
async def test_an_unreachable_endpoint_is_a_debug_line_too(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", "http://127.0.0.1:9/count")
    with caplog.at_level(logging.DEBUG, logger="app.services.telemetry"):
        assert await telemetry.send_report("ab" * 16) is False
    assert all(r.levelno == logging.DEBUG for r in caplog.records
               if r.name == "app.services.telemetry")


def test_a_new_identifier_is_16_random_bytes_as_hex() -> None:
    a, b = telemetry.new_installation_id(), telemetry.new_installation_id()
    assert re.fullmatch(r"[0-9a-f]{32}", a)
    assert a != b


# ── When a report is made ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consented_and_never_sent_reports_and_records_the_success(
    db_session: AsyncSession, redis: Redis, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/count")
    await _set_row(db_session, enabled=True)

    assert await telemetry.report_if_due(db_session, redis) is True

    assert len(hits) == 1
    assert parse_qs(hits[0]["query"])["id"] == ["ab" * 16]
    row = await _row(db_session)
    assert row is not None and row.last_sent_at is not None
    assert datetime.now(UTC) - row.last_sent_at < timedelta(minutes=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(("enabled", "setting", "value"), [
    (False, None, None),                       # consent off
    (None, None, None),                        # never asked (upgrade to 2.0)
    (True, "telemetry_enabled", False),        # TELEMETRY_ENABLED=false beats the DB
    (True, "demo_mode", True),                 # the public demo is never counted
    (True, "local_review_login", True),        # nor a local review stack
])
async def test_nothing_is_sent_without_consent_or_under_a_hard_off(
    db_session: AsyncSession, redis: Redis, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
    enabled: bool | None, setting: str | None, value: bool | None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/count")
    if setting:
        monkeypatch.setattr(settings, setting, value)
    await _set_row(db_session, enabled=enabled)

    assert await telemetry.report_if_due(db_session, redis) is False
    assert hits == []


@pytest.mark.asyncio
async def test_telemetry_enabled_true_reports_without_a_row(
    db_session: AsyncSession, redis: Redis, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/count")
    monkeypatch.setattr(settings, "telemetry_enabled", True)
    await _set_row(db_session, enabled=None)

    assert await telemetry.report_if_due(db_session, redis) is True
    assert len(hits) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("hours_ago", "sends"), [(1, False), (23.9, False), (24.1, True)])
async def test_a_report_is_due_24_hours_after_the_last_success(
    db_session: AsyncSession, redis: Redis, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None, hours_ago: float, sends: bool,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/count")
    await _set_row(db_session, enabled=True,
                   last_sent_at=datetime.now(UTC) - timedelta(hours=hours_ago))

    assert await telemetry.report_if_due(db_session, redis) is sends
    assert len(hits) == int(sends)


@pytest.mark.asyncio
async def test_a_failed_report_is_not_recorded_as_sent(
    db_session: AsyncSession, redis: Redis, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/fail")
    await _set_row(db_session, enabled=True)

    assert await telemetry.report_if_due(db_session, redis) is False
    assert len(hits) == 1
    row = await _row(db_session)
    assert row is not None and row.last_sent_at is None


@pytest.mark.asyncio
async def test_of_two_replicas_at_the_same_moment_only_one_sends(
    db_session: AsyncSession, redis: Redis, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/slow")
    await _set_row(db_session, enabled=True)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other_redis = Redis.from_url(settings.redis_url)
    try:
        async with factory() as a, factory() as b:
            results = await asyncio.gather(
                telemetry.report_if_due(a, redis), telemetry.report_if_due(b, other_redis)
            )
    finally:
        await other_redis.aclose()
        await engine.dispose()

    assert sorted(results) == [False, True]
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_a_redis_outage_sends_nothing(
    db_session: AsyncSession, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/count")
    await _set_row(db_session, enabled=True)
    broken = Redis.from_url("redis://127.0.0.1:9/1")
    try:
        assert await telemetry.report_if_due(db_session, broken) is False
    finally:
        await broken.aclose()
    assert hits == []


@pytest.mark.asyncio
async def test_the_scheduled_job_swallows_everything(monkeypatch: pytest.MonkeyPatch,
                                                     consent_from_db: None) -> None:
    async def boom(*_: Any) -> bool:
        raise RuntimeError("database down")

    monkeypatch.setattr(telemetry, "report_if_due", boom)
    await telemetry.run_telemetry_job()  # no exception


@pytest.mark.asyncio
async def test_the_scheduled_job_reports_through_its_own_connections(
    db_session: AsyncSession, fake_server: tuple[str, _Hits],
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    base, hits = fake_server
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", f"{base}/count")
    await _set_row(db_session, enabled=True)
    r = Redis.from_url(settings.redis_url)
    await r.delete(telemetry.LOCK_KEY)
    try:
        await telemetry.run_telemetry_job()
    finally:
        await r.delete(telemetry.LOCK_KEY)
        await r.aclose()
    assert len(hits) == 1


# ── Scheduling ─────────────────────────────────────────────────────────────


def test_the_job_ticks_hourly_after_a_random_first_delay_of_up_to_an_hour(
    consent_from_db: None,
) -> None:
    scheduler = MagicMock()
    before = datetime.now(UTC)
    assert telemetry.schedule(scheduler) is True
    (func, trigger), kwargs = scheduler.add_job.call_args
    assert func is telemetry.run_telemetry_job
    assert trigger == "interval"
    assert kwargs["hours"] == 1
    first = kwargs["next_run_time"]
    assert before <= first <= datetime.now(UTC) + timedelta(hours=1)


def test_the_first_delays_are_spread(consent_from_db: None) -> None:
    firsts = set()
    for _ in range(5):
        scheduler = MagicMock()
        telemetry.schedule(scheduler)
        firsts.add(scheduler.add_job.call_args.kwargs["next_run_time"].replace(microsecond=0))
    assert len(firsts) > 1


@pytest.mark.parametrize(("setting", "value"), [
    ("telemetry_enabled", False), ("demo_mode", True), ("local_review_login", True),
])
def test_a_hard_off_never_schedules_the_job(
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None, setting: str, value: bool
) -> None:
    monkeypatch.setattr(settings, setting, value)
    scheduler = MagicMock()
    assert telemetry.schedule(scheduler) is False
    scheduler.add_job.assert_not_called()


@pytest.mark.parametrize(("raw", "parsed"), [("", None), ("  ", None), ("false", False),
                                             ("true", True)])
def test_telemetry_enabled_env_values(
    monkeypatch: pytest.MonkeyPatch, raw: str, parsed: bool | None
) -> None:
    monkeypatch.setenv("TELEMETRY_ENABLED", raw)
    assert Settings().telemetry_enabled is parsed  # type: ignore[call-arg]


# ── The System page and its switch ─────────────────────────────────────────


async def _admin(db: AsyncSession, role: AdminRole = AdminRole.admin) -> AdminUser:
    admin = AdminUser(
        id=uuid.uuid4(), username=f"tel_{uuid.uuid4().hex[:8]}", role=role, is_active=True,
        password_hash=hash_password("TelemetryTest!Pass1"),
        totp_secret=pyotp.random_base32(), totp_enabled=True,
    )
    db.add(admin)
    await db.commit()
    return admin


@pytest_asyncio.fixture(loop_scope="function")
async def signed_in(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[tuple[AsyncClient, AdminUser, str]]:
    admin = await _admin(db_session)
    app.dependency_overrides[get_current_admin] = lambda: admin
    csrf = (await client.get("/admin/login")).cookies.get("ow_csrf") or ""
    yield client, admin, csrf
    app.dependency_overrides.pop(get_current_admin, None)


async def _audit(db: AsyncSession, admin: AdminUser) -> list[str]:
    rows = await db.scalars(select(AuditLog.action).where(AuditLog.admin_id == admin.id)
                            .execution_options(populate_existing=True))
    return list(rows)


@pytest.mark.asyncio
async def test_the_system_page_shows_the_exact_request_and_this_installations_id(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    consent_from_db: None,
) -> None:
    client, _, _ = signed_in
    await _set_row(db_session, enabled=False)

    resp = await client.get("/admin/system")

    assert resp.status_code == 200
    assert 'id="heading-telemetry"' in resp.text
    assert telemetry.TELEMETRY_ENDPOINT in resp.text
    assert "ab" * 16 in resp.text
    assert f"v={settings.app_version}" in resp.text
    assert 'action="/admin/system/telemetry"' in resp.text
    assert 'action="/admin/system/telemetry/reset-id"' in resp.text


@pytest.mark.asyncio
async def test_the_system_page_creates_the_identifier_on_first_use(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    consent_from_db: None,
) -> None:
    client, _, _ = signed_in
    await _set_row(db_session, enabled=None)

    resp = await client.get("/admin/system")

    row = await _row(db_session)
    assert row is not None and row.enabled is False
    assert re.fullmatch(r"[0-9a-f]{32}", row.installation_id)
    assert row.installation_id in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("setting", "value", "key"), [
    ("telemetry_enabled", False, "admin.system.telemetry.locked.env_off"),
    ("telemetry_enabled", True, "admin.system.telemetry.locked.env_on"),
    ("demo_mode", True, "admin.system.telemetry.locked.demo"),
])
async def test_a_locked_switch_says_why_and_offers_no_toggle(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
    setting: str, value: bool, key: str,
) -> None:
    from app.i18n import make_translator

    client, _, _ = signed_in
    monkeypatch.setattr(settings, setting, value)
    await _set_row(db_session, enabled=False)

    resp = await client.get("/admin/system")

    assert make_translator("en")(key).split("<")[0][:30] in resp.text
    assert 'action="/admin/system/telemetry"' not in resp.text


@pytest.mark.asyncio
async def test_the_toggle_switches_on_and_off_with_one_audit_row_per_change(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    consent_from_db: None,
) -> None:
    client, admin, csrf = signed_in
    await _set_row(db_session, enabled=False)

    for value in ("1", "1", "0"):
        resp = await client.post("/admin/system/telemetry",
                                 data={"csrf_token": csrf, "enabled": value},
                                 follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/admin/system")

    row = await _row(db_session)
    assert row is not None and row.enabled is False
    assert sorted(await _audit(db_session, admin)) == sorted(
        [AuditAction.TELEMETRY_ENABLED, AuditAction.TELEMETRY_DISABLED]
    )


@pytest.mark.asyncio
async def test_the_toggle_needs_the_csrf_token(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    consent_from_db: None,
) -> None:
    client, admin, _ = signed_in
    await _set_row(db_session, enabled=False)

    resp = await client.post("/admin/system/telemetry",
                             data={"csrf_token": "not-the-cookie", "enabled": "1"},
                             follow_redirects=False)

    assert resp.status_code == 403
    row = await _row(db_session)
    assert row is not None and row.enabled is False
    assert await _audit(db_session, admin) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/admin/system/telemetry", "/admin/system/telemetry/reset-id"])
async def test_a_case_manager_cannot_switch_or_reset(
    client: AsyncClient, db_session: AsyncSession, consent_from_db: None, path: str
) -> None:
    manager = await _admin(db_session, AdminRole.case_manager)
    await _set_row(db_session, enabled=False)
    app.dependency_overrides[get_current_admin] = lambda: manager
    try:
        csrf = (await client.get("/admin/login")).cookies.get("ow_csrf") or ""
        resp = await client.post(path, data={"csrf_token": csrf, "enabled": "1"},
                                 follow_redirects=False)
    finally:
        app.dependency_overrides.pop(get_current_admin, None)

    assert resp.status_code == 403
    row = await _row(db_session)
    assert row is not None and row.enabled is False and row.installation_id == "ab" * 16


@pytest.mark.asyncio
async def test_the_toggle_is_refused_while_the_environment_decides(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None,
) -> None:
    client, admin, csrf = signed_in
    monkeypatch.setattr(settings, "telemetry_enabled", False)
    await _set_row(db_session, enabled=False)

    resp = await client.post("/admin/system/telemetry",
                             data={"csrf_token": csrf, "enabled": "1"}, follow_redirects=False)

    assert resp.status_code == 409
    row = await _row(db_session)
    assert row is not None and row.enabled is False
    assert await _audit(db_session, admin) == []


@pytest.mark.asyncio
async def test_reset_gives_a_new_random_identifier(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    consent_from_db: None,
) -> None:
    client, admin, csrf = signed_in
    await _set_row(db_session, enabled=True, last_sent_at=datetime.now(UTC))

    resp = await client.post("/admin/system/telemetry/reset-id", data={"csrf_token": csrf},
                             follow_redirects=False)

    assert resp.status_code == 302
    row = await _row(db_session)
    assert row is not None
    assert re.fullmatch(r"[0-9a-f]{32}", row.installation_id)
    assert row.installation_id != "ab" * 16
    assert row.enabled is True
    assert row.last_sent_at is None  # a new installation as far as the far end can tell
    assert await _audit(db_session, admin) == [AuditAction.TELEMETRY_ID_RESET]


@pytest.mark.asyncio
async def test_reset_needs_the_csrf_token(
    signed_in: tuple[AsyncClient, AdminUser, str], db_session: AsyncSession,
    consent_from_db: None,
) -> None:
    client, _, _ = signed_in
    await _set_row(db_session, enabled=False)
    resp = await client.post("/admin/system/telemetry/reset-id",
                             data={"csrf_token": "not-the-cookie"}, follow_redirects=False)
    assert resp.status_code == 403
    row = await _row(db_session)
    assert row is not None and row.installation_id == "ab" * 16


# ── The setup wizard asks, and the answer defaults to no ────────────────────


@pytest.mark.asyncio
async def test_the_wizard_asks_with_the_box_unchecked(client: AsyncClient) -> None:
    resp = await client.get("/setup", follow_redirects=False)
    if resp.status_code != 200:
        pytest.skip("setup already completed on the shared test database")
    box = re.search(r'<input[^>]*name="telemetry"[^>]*>', resp.text)
    assert box is not None
    assert "checked" not in box.group(0)
    assert "telemetry.wdkro.de" in resp.text
    assert "#counting-installations" in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer", "stored", "row_first"), [
    (None, False, False), ("1", True, False),
    ("1", True, True),  # the hourly job already created the row, switched off
])
async def test_the_wizard_stores_the_answer(
    throwaway_db: AsyncSession, client: AsyncClient, answer: str | None, stored: bool,
    row_first: bool,
) -> None:
    if row_first:
        await _set_row(throwaway_db, enabled=False)
    get_resp = await client.get("/setup", follow_redirects=False)
    assert get_resp.status_code == 200
    secret = generate_totp_secret()
    data = {
        "username": "telemetryfirst", "password": "SecureTestPassword123!",
        "password_confirm": "SecureTestPassword123!", "totp_secret": secret,
        "totp_code": get_totp(secret).now(), "csrf_token": get_resp.cookies.get("ow_csrf"),
        "setup_token": await setup_token(),
    }
    if answer is not None:
        data["telemetry"] = answer

    resp = await client.post("/setup", data=data, follow_redirects=False)

    assert resp.status_code == 302
    row = await _row(throwaway_db)
    assert row is not None and row.enabled is stored
    assert re.fullmatch(r"[0-9a-f]{32}", row.installation_id)


# ── Migration 007 ──────────────────────────────────────────────────────────


def _alembic(*args: str) -> None:
    run = subprocess.run(  # noqa: S603
        ["alembic", *args], capture_output=True, text=True, check=False,  # noqa: S607
        env={**os.environ, "DATABASE_URL": settings.database_url},
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.asyncio
async def test_migration_007_round_trip(throwaway_db: AsyncSession) -> None:
    exists = text("SELECT to_regclass('public.telemetry_state') IS NOT NULL")
    assert (await throwaway_db.scalar(exists)) is True
    assert (await throwaway_db.scalar(text("SELECT count(*) FROM telemetry_state"))) == 0
    await throwaway_db.commit()

    _alembic("downgrade", "c3e8a2b6d403")
    assert (await throwaway_db.scalar(exists)) is False
    await throwaway_db.commit()

    _alembic("upgrade", "head")
    assert (await throwaway_db.scalar(exists)) is True


@pytest.mark.asyncio
async def test_startup_registers_the_job_even_while_the_switch_is_off(
    monkeypatch: pytest.MonkeyPatch, consent_from_db: None
) -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI

    from app.main import lifespan

    for name in ("reminder_enabled", "retention_enabled", "update_check_enabled"):
        monkeypatch.setattr(settings, name, False)
    scheduler = MagicMock()
    with (
        patch("app.main._run_alembic_upgrade"),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("apscheduler.schedulers.asyncio.AsyncIOScheduler", return_value=scheduler),
        patch("app.services.notifications.batching_enabled", return_value=False),
    ):
        async with lifespan(FastAPI()):
            pass

    ids = [c.kwargs.get("id") for c in scheduler.add_job.call_args_list]
    assert ids == ["telemetry"]
    scheduler.start.assert_called_once()
