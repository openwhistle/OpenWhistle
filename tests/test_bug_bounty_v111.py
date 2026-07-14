"""Bug-bounty regression tests — real defects found by an adversarial audit.

Every test here targets a concrete bug that existed before the accompanying fix
and would fail against the unpatched code. These are not coverage filler: each
one pins down a specific wrong behaviour (data loss, auth bypass, crash, …).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.main import app
from app.models.report import ReportStatus
from app.models.user import AdminRole, AdminUser

# ── shared helpers ─────────────────────────────────────────────────────────


def _user(role: AdminRole) -> AdminUser:
    return AdminUser(
        id=uuid.uuid4(),
        username=f"{role.value}-{uuid.uuid4().hex[:8]}",
        role=role,
        is_active=True,
        totp_secret="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        totp_enabled=True,
    )


@pytest_asyncio.fixture(loop_scope="function")
async def as_admin(client: AsyncClient):
    def _set(user: AdminUser) -> None:
        app.dependency_overrides[get_current_admin] = lambda: user

    yield client, _set
    app.dependency_overrides.pop(get_current_admin, None)


@pytest_asyncio.fixture(loop_scope="function")
async def no_csrf():
    from app.csrf import validate_csrf

    app.dependency_overrides[validate_csrf] = lambda: None
    yield
    app.dependency_overrides.pop(validate_csrf, None)


async def _mk_report(db: AsyncSession, description: str = "Bug bounty report body."):
    from app.services.report import create_report

    report, _ = await create_report(db, "financial_fraud", description)
    return report


# ══════════════════════════════════════════════════════════════════════════
# CRITICAL: reopened-then-reclosed report deleted on stale closure date
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reopen_clears_closed_at_and_reclose_refreshes_it(db_session: AsyncSession) -> None:
    from app.services.report import update_report_status

    report = await _mk_report(db_session)
    await update_report_status(db_session, report, ReportStatus.closed)
    first = report.closed_at
    assert first is not None

    await update_report_status(db_session, report, ReportStatus.in_review)  # reopen
    assert report.closed_at is None, "reopening must clear closed_at"

    await update_report_status(db_session, report, ReportStatus.closed)  # re-close
    assert report.closed_at is not None
    assert report.closed_at >= first, "re-close must stamp a fresh closure time"


@pytest.mark.asyncio
async def test_direct_double_close_keeps_original_timestamp(db_session: AsyncSession) -> None:
    """The fix must not regress the existing invariant: a direct re-close without
    a reopen keeps the first closure timestamp."""
    from app.services.report import update_report_status

    report = await _mk_report(db_session)
    await update_report_status(db_session, report, ReportStatus.closed)
    first = report.closed_at
    await update_report_status(db_session, report, ReportStatus.closed)
    assert report.closed_at == first


# ══════════════════════════════════════════════════════════════════════════
# HIGH: acknowledge must be idempotent (statutory deadline not resettable)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_acknowledge_is_idempotent(db_session: AsyncSession) -> None:
    from app.services.report import acknowledge_report

    report = await _mk_report(db_session)
    await acknowledge_report(db_session, report)
    first_due = report.feedback_due_at
    first_ack = report.acknowledged_at
    assert first_due is not None

    await acknowledge_report(db_session, report)  # second call must be a no-op
    assert report.feedback_due_at == first_due
    assert report.acknowledged_at == first_ack


# ══════════════════════════════════════════════════════════════════════════
# MEDIUM: empty decrypted description must not fall back to ciphertext
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_empty_description_decrypts_to_empty_not_ciphertext(db_session: AsyncSession) -> None:
    from app.services.report import create_report, decrypt_report_fields, get_report_by_id

    created, _ = await create_report(db_session, "financial_fraud", "")
    # Reload with relationships eagerly loaded (decrypt_report_fields iterates
    # report.messages, which would otherwise lazy-load in a sync context).
    report = await get_report_by_id(db_session, created.id)
    assert report is not None
    description, _ = decrypt_report_fields(report)
    assert description == "", "empty plaintext must not be replaced by raw ciphertext"


# ══════════════════════════════════════════════════════════════════════════
# HIGH: concurrent case-number collision must be retried, not 500
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_report_retries_on_case_number_collision(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report as report_svc

    # Occupy a case number, then force generate_case_number to hand out that
    # same (taken) number first, then a fresh one — the retry must recover.
    taken = await _mk_report(db_session)
    fresh_number = f"OW-9999-{uuid.uuid4().int % 100000:05d}"
    seq = iter([taken.case_number, fresh_number])

    def fake_gen() -> str:
        return next(seq)

    monkeypatch.setattr(report_svc, "generate_case_number", fake_gen)
    report, _ = await report_svc.create_report(db_session, "financial_fraud", "Collision test.")
    assert report.case_number == fresh_number


# ══════════════════════════════════════════════════════════════════════════
# HIGH: reminder dedup TTL must cover the warn window
# ══════════════════════════════════════════════════════════════════════════


def test_reminder_dedup_ttl_covers_warn_windows() -> None:
    from app.config import settings
    from app.services.reminders import _dedup_ttl_seconds

    # Entering the ack window (days_left == warn days) must suppress re-reminders
    # for at least the remaining window, not just one scheduler hour.
    assert _dedup_ttl_seconds(settings.reminder_ack_warn_days) > 3600
    assert _dedup_ttl_seconds(settings.reminder_feedback_warn_days) >= (
        settings.reminder_feedback_warn_days * 86400
    )


# ══════════════════════════════════════════════════════════════════════════
# CRITICAL: non-Latin-1 attachment filename must not break the download header
# ══════════════════════════════════════════════════════════════════════════


def test_content_disposition_handles_non_latin1_filename() -> None:
    from app.services.attachment import content_disposition_attachment

    header = content_disposition_attachment("报告.pdf")
    # The whole header value must be latin-1 encodable (Starlette requirement).
    header.encode("latin-1")
    assert "filename*=UTF-8''" in header
    assert "%E6" in header.upper()  # percent-encoded CJK bytes present


# ══════════════════════════════════════════════════════════════════════════
# HIGH: PDF export must not crash on a non-Latin-1 note author (LDAP/OIDC name)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pdf_export_survives_non_latin1_note_author(db_session: AsyncSession) -> None:
    from app.services.pdf import generate_report_pdf
    from app.services.report import add_note, get_report_by_id
    from app.services.users import create_user

    report = await _mk_report(db_session)
    author, _ = await create_user(
        db_session, f"noter-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    author.username = "王芳"  # simulates a directory-provisioned display name
    await add_note(db_session, report, author, "Note from a unicode-named admin.")
    loaded = await get_report_by_id(db_session, report.id)
    assert loaded is not None

    pdf_bytes = generate_report_pdf(loaded)
    assert isinstance(pdf_bytes, bytes) and len(pdf_bytes) > 0


# ══════════════════════════════════════════════════════════════════════════
# HIGH: attachment upload — bounded read + count-before-read
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_read_is_bounded() -> None:
    from app.services.attachment import MAX_SIZE_BYTES, read_upload_files

    upload = MagicMock()
    upload.filename = "huge.pdf"
    upload.content_type = "application/pdf"
    upload.read = AsyncMock(return_value=b"X" * (MAX_SIZE_BYTES + 1))

    _result, error = await read_upload_files([upload])
    assert error is not None  # rejected as too large
    upload.read.assert_awaited_once_with(MAX_SIZE_BYTES + 1)


@pytest.mark.asyncio
async def test_upload_count_limit_stops_reading_extra_files() -> None:
    from app.services.attachment import MAX_ATTACHMENTS, read_upload_files

    uploads = []
    for i in range(MAX_ATTACHMENTS + 1):
        u = MagicMock()
        u.filename = f"f{i}.pdf"
        u.content_type = "application/pdf"
        u.read = AsyncMock(return_value=b"X" * 100)
        uploads.append(u)

    _result, error = await read_upload_files(uploads)
    assert error is not None
    uploads[MAX_ATTACHMENTS].read.assert_not_called()  # the extra file is never read


# ══════════════════════════════════════════════════════════════════════════
# MEDIUM: case-insensitive duplicate usernames blocked
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_username_lookup_is_case_insensitive(db_session: AsyncSession) -> None:
    from app.services.users import create_user, get_user_by_username_ci

    uname = f"Bounty-{uuid.uuid4().hex[:6]}"
    await create_user(db_session, uname, "TestPassword123!", AdminRole.admin)
    found = await get_user_by_username_ci(db_session, uname.upper())
    assert found is not None, "a case-variant of an existing username must be found"


# ══════════════════════════════════════════════════════════════════════════
# MEDIUM: relinking already-linked reports is detectable (→ clean 409)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_link_between_is_order_independent(db_session: AsyncSession) -> None:
    from app.services.report import get_link_between, link_cases
    from app.services.users import create_user

    a = await _mk_report(db_session)
    b = await _mk_report(db_session)
    actor, _ = await create_user(
        db_session, f"lk-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    await link_cases(db_session, a, b, actor)
    # Order-independent detection is what lets the API return 409 instead of 500.
    assert await get_link_between(db_session, a.id, b.id) is not None
    assert await get_link_between(db_session, b.id, a.id) is not None


# ══════════════════════════════════════════════════════════════════════════
# CRITICAL / HIGH: admin-user management authz (API level)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_a_superadmin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    client, set_user = as_admin
    from app.services.users import create_user

    actor, _ = await create_user(
        db_session, f"a-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    sa, _ = await create_user(
        db_session, f"s-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    set_user(actor)
    resp = await client.post(f"/admin/users/{sa.id}/deactivate", data={}, follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_deactivate_last_privileged_admin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    client, set_user = as_admin
    from app.services.users import (
        count_active_privileged_admins,
        create_user,
        deactivate_user,
        get_all_users,
    )

    for u in await get_all_users(db_session):
        if u.role in (AdminRole.admin, AdminRole.superadmin) and u.is_active:
            await deactivate_user(db_session, u)
    sole, _ = await create_user(
        db_session, f"sole-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    await db_session.commit()
    if await count_active_privileged_admins(db_session) != 1:
        pytest.skip("could not reduce to one privileged admin")

    set_user(sole)
    # sole tries to deactivate... another superadmin that we make and then this
    # is the only one — deactivating any privileged account that is the last one
    # must fail. Here sole targets itself-equivalent: create a second, then it is
    # the last after removing the first. Simpler: sole cannot deactivate the only
    # other privileged (none exists) — so target sole via a second actor.
    actor, _ = await create_user(
        db_session, f"act-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    await deactivate_user(db_session, actor)  # back to exactly one active (sole)
    await db_session.commit()
    set_user(actor)  # authenticated (override bypasses is_active), acts on sole
    resp = await client.post(f"/admin/users/{sole.id}/deactivate", data={}, follow_redirects=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cannot_assign_report_to_deactivated_admin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    client, set_user = as_admin
    from app.services.users import create_user, deactivate_user

    actor, _ = await create_user(
        db_session, f"a-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    ghost, _ = await create_user(
        db_session, f"g-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.case_manager
    )
    await deactivate_user(db_session, ghost)
    report = await _mk_report(db_session)
    set_user(actor)
    resp = await client.post(
        f"/admin/reports/{report.id}/assign",
        data={"admin_id": str(ghost.id)},
        follow_redirects=False,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_linked_report_metadata_hidden_from_unauthorized_case_manager(
    db_session: AsyncSession, as_admin
) -> None:
    client, set_user = as_admin
    from app.services.report import assign_report, link_cases
    from app.services.users import create_user

    a = await _mk_report(db_session)
    b = await _mk_report(db_session)  # b.case_number is the secret we must not leak
    admin, _ = await create_user(
        db_session, f"ad-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    cm1, _ = await create_user(
        db_session, f"c1-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.case_manager
    )
    cm2, _ = await create_user(
        db_session, f"c2-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.case_manager
    )
    await assign_report(db_session, a, cm1)
    await assign_report(db_session, b, cm2)
    await link_cases(db_session, a, b, admin)

    set_user(cm1)
    resp = await client.get(f"/admin/reports/{a.id}", follow_redirects=False)
    assert resp.status_code == 200
    assert b.case_number not in resp.text  # cm1 is not authorized on report b


@pytest.mark.asyncio
async def test_download_non_latin1_filename_does_not_500(
    db_session: AsyncSession, as_admin
) -> None:
    client, set_user = as_admin
    from app.models.attachment import Attachment

    report = await _mk_report(db_session)
    att = Attachment(
        id=uuid.uuid4(),
        report_id=report.id,
        filename="报告.pdf",
        content_type="application/pdf",
        size=4,
        data=b"TEST",
    )
    db_session.add(att)
    await db_session.commit()

    set_user(_user(AdminRole.admin))
    resp = await client.get(
        f"/admin/reports/{report.id}/attachments/{att.id}", follow_redirects=False
    )
    assert resp.status_code == 200
    assert resp.content == b"TEST"


# ══════════════════════════════════════════════════════════════════════════
# HIGH: SUBMISSION_MODE_ENABLED=false must force anonymous
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_confidential_rejected_when_submission_mode_disabled(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import re

    from app.config import settings

    monkeypatch.setattr(settings, "submission_mode_enabled", False)

    get_resp = await client.get("/submit")
    m = re.search(r'name="csrf_token" value="([^"]+)"', get_resp.text)
    csrf = m.group(1) if m else ""
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "confidential",
            "confidential_name": "Jane Doe",
            "secure_email": "jane@example.com",
        },
    )
    # The identifying fields must not have been stored — the report is forced
    # anonymous. The confidential name must not be echoed on the next step.
    assert "Jane Doe" not in resp.text


# ══════════════════════════════════════════════════════════════════════════
# HIGH: whistleblower PIN lockout must not be bypassable by rotating the token
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pin_lockout_keyed_on_case_number_not_session_token(
    client: AsyncClient, no_csrf
) -> None:
    import re

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import rate_limit as rl

    case = f"OW-2026-{uuid.uuid4().int % 100000:05d}"
    # Guess repeatedly, minting a FRESH session_token before each attempt — the
    # old bypass reset the counter every time the token changed.
    for _ in range(settings.max_access_attempts + 1):
        get_resp = await client.get("/status")
        m = re.search(r'name="session_token" value="([^"]+)"', get_resp.text)
        token = m.group(1) if m else uuid.uuid4().hex
        await client.post(
            "/status",
            data={
                "case_number": case,
                "pin": "00000000-0000-0000-0000-000000000000",
                "session_token": token,
            },
        )

    redis = await get_redis()
    # The lockout counter must have accumulated on the case number despite the
    # rotating tokens, so further guesses are now blocked.
    assert await rl.check_whistleblower_attempts(redis, case.upper()) is False


# ══════════════════════════════════════════════════════════════════════════
# MEDIUM: org-less non-superadmin must not see other tenants' reports in list
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dashboard_hides_other_org_reports_from_orgless_admin(
    db_session: AsyncSession, as_admin, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.models.organisation import Organisation

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)

    other_org = Organisation(id=uuid.uuid4(), name="Other Org", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    await db_session.commit()

    report = await _mk_report(db_session)
    report.org_id = other_org.id  # belongs to some other organisation
    await db_session.commit()

    client, set_user = as_admin
    admin = _user(AdminRole.admin)  # org_id is None
    admin.org_id = None
    set_user(admin)
    resp = await client.get("/admin/dashboard", follow_redirects=False)
    assert resp.status_code == 200
    assert report.case_number not in resp.text


# ══════════════════════════════════════════════════════════════════════════
# WAVE 3 — maximal pass (incl. breaking config change)
# ══════════════════════════════════════════════════════════════════════════


def test_secret_key_minimum_length_enforced() -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(secret_key="short")  # type: ignore[call-arg]
    # A sufficiently long key is accepted.
    ok = Settings(secret_key="x" * 32)  # type: ignore[call-arg]
    assert ok.secret_key == "x" * 32


def test_decrypt_or_none_logs_on_tampered_token(caplog: pytest.LogCaptureFixture) -> None:
    from app.services.crypto import decrypt_or_none

    with caplog.at_level("WARNING"):
        assert decrypt_or_none("gAAAAA-not-a-valid-fernet-token") is None
    assert any("decrypt" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_submit_post_rejects_unknown_client_session_id(
    client: AsyncClient, no_csrf
) -> None:
    client.cookies.set("ow-submission-session", "attacker-chosen-id-000001")
    resp = await client.post(
        "/submit",
        data={"step": "1", "action": "next", "submission_mode": "anonymous"},
    )
    # The server must not persist state under an id it never issued.
    assert resp.cookies.get("ow-submission-session") not in (None, "attacker-chosen-id-000001")


@pytest.mark.asyncio
async def test_submit_post_rejects_jump_to_attachment_step(client: AsyncClient) -> None:
    resp = await client.get("/submit")
    import re

    m = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    csrf = m.group(1) if m else ""
    # Jump straight to step 5 (attachments) on a fresh session.
    jump = await client.post(
        "/submit",
        data={"csrf_token": csrf, "step": "5", "action": "next"},
    )
    # Must bounce back to the mode step, not advance to review (step 6).
    assert 'name="step" value="6"' not in jump.text


@pytest.mark.asyncio
async def test_totp_code_cannot_be_replayed_across_sessions(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyotp

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import auth as auth_service
    from app.services.users import create_user

    # CI runs with DEMO_MODE=true, which intentionally makes the static code
    # reusable; force it off so the one-time-use path is exercised.
    monkeypatch.setattr(settings, "demo_mode", False)

    secret = pyotp.random_base32()
    user, _ = await create_user(
        db_session, f"totp-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    user.totp_secret = secret
    user.totp_enabled = True
    await db_session.commit()

    redis = await get_redis()
    code = pyotp.TOTP(secret).now()

    temp1 = uuid.uuid4().hex
    await auth_service.store_totp_pending(redis, temp1, str(user.id))
    r1 = await client.post(
        "/admin/login/mfa", data={"totp_code": code, "temp_token": temp1}, follow_redirects=False
    )
    assert r1.status_code == 302  # first use succeeds

    temp2 = uuid.uuid4().hex
    await auth_service.store_totp_pending(redis, temp2, str(user.id))
    r2 = await client.post(
        "/admin/login/mfa", data={"totp_code": code, "temp_token": temp2}, follow_redirects=False
    )
    assert r2.status_code != 302  # replay of the same code must be rejected


@pytest.mark.asyncio
async def test_retention_cleanup_skipped_when_lock_held(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from redis.asyncio import Redis

    from app.config import settings
    from app.services.report import get_report_by_id
    from app.services.retention import run_retention_cleanup

    monkeypatch.setattr(settings, "retention_enabled", True)

    report = await _mk_report(db_session)
    report.status = ReportStatus.closed
    report.closed_at = datetime.now(UTC) - timedelta(days=settings.retention_days + 10)
    await db_session.commit()

    # Simulate another replica already holding the job lock. Use a dedicated
    # connection (not the shared request-scoped client) to avoid binding it to
    # this test's event loop.
    lock_redis = Redis.from_url(settings.redis_url)
    await lock_redis.set("openwhistle:job_lock:retention", "1", nx=True, ex=600)
    try:
        await run_retention_cleanup()
        # Lock held by "another replica" → this run is skipped (and must NOT
        # release a lock it does not own) → the eligible report survives.
        assert await get_report_by_id(db_session, report.id) is not None
    finally:
        await lock_redis.delete("openwhistle:job_lock:retention")
        await lock_redis.aclose()
