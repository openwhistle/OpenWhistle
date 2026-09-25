"""v1.6.0 privacy: one test per guard."""

from __future__ import annotations

import re
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.report import Report, SubmissionMode
from app.models.user import AdminRole, AdminUser
from app.services.audit import AuditAction
from app.services.auth import hash_password
from app.services.crypto import encrypt
from app.services.report import create_report

_PASSWORD = "V160-Privacy-Password"  # noqa: S105
_NAME = "Erika Musterfrau"
_REASON = "Needed to arrange the protected interview."


async def _login(client: AsyncClient, db: AsyncSession, role: AdminRole) -> AdminUser:
    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(), username=f"priv_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret, totp_enabled=True, role=role,
    )
    db.add(user)
    await db.commit()
    await client.get("/admin/login")
    r = await client.post("/admin/login", data={
        "username": user.username, "password": _PASSWORD,
        "csrf_token": client.cookies.get("ow_csrf")})
    temp = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    assert temp
    await client.post("/admin/login/mfa", data={
        "csrf_token": client.cookies.get("ow_csrf"), "temp_token": temp.group(1),
        "totp_code": pyotp.TOTP(secret).now()})
    return user


async def _confidential_report(db: AsyncSession, assigned: AdminUser | None = None) -> Report:
    report, _ = await create_report(
        db, "corruption", "Confidential identity test report.",
        submission_mode=SubmissionMode.confidential,
        confidential_name_enc=encrypt(_NAME), confidential_contact_enc=encrypt("+49 30 1234"),
    )
    report.assigned_to_id = assigned.id if assigned else None
    await db.commit()
    return report


async def _audit_count(db: AsyncSession, report: Report, action: str) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.report_id == report.id, AuditLog.action == action)
    ) or 0)


@pytest.mark.asyncio
async def test_case_page_hides_identity_and_records_the_view(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    resp = await client.get(f"/admin/reports/{report.id}")
    assert resp.status_code == 200
    assert _NAME not in resp.text and "+49 30 1234" not in resp.text
    await client.get(f"/admin/reports/{report.id}")
    assert await _audit_count(db_session, report, AuditAction.REPORT_VIEWED) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["", "too short"])
async def test_reveal_without_a_reason_is_refused(
    client: AsyncClient, db_session: AsyncSession, reason: str
) -> None:
    user = await _login(client, db_session, AdminRole.case_manager)
    report = await _confidential_report(db_session, assigned=user)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": reason, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 422
    assert _NAME not in resp.text
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 0


@pytest.mark.asyncio
async def test_handler_reveal_shows_identity_once_and_audits_the_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.crypto import decrypt

    user = await _login(client, db_session, AdminRole.case_manager)
    report = await _confidential_report(db_session, assigned=user)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 200
    assert _NAME in resp.text
    assert resp.headers["cache-control"] == "no-store"
    row = await db_session.scalar(select(AuditLog).where(
        AuditLog.report_id == report.id, AuditLog.action == AuditAction.IDENTITY_REVEALED))
    assert row is not None and row.admin_id == user.id
    assert _REASON not in (row.detail or "")
    import json
    assert decrypt(json.loads(row.detail or "{}")["reason"]) == _REASON
    again = await client.get(f"/admin/reports/{report.id}")
    assert _NAME not in again.text


@pytest.mark.asyncio
async def test_admin_who_is_not_the_handler_cannot_reveal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    other = AdminUser(
        id=uuid.uuid4(), username=f"handler_{uuid.uuid4().hex[:8]}", password_hash=None,
        totp_secret=pyotp.random_base32(), totp_enabled=True, role=AdminRole.case_manager,
    )
    db_session.add(other)
    await db_session.commit()
    await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=other)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 403
    assert _NAME not in resp.text


@pytest.mark.asyncio
async def test_unassigned_case_admin_may_reveal_case_manager_may_not_see_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=None)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 200 and _NAME in resp.text


def test_audit_detail_decrypts_a_reveal_reason_and_keeps_a_plain_one() -> None:
    import json

    from app.templating import audit_detail

    assert audit_detail(json.dumps({"reason": encrypt(_REASON)})) == [("reason", _REASON)]
    # The retention job writes a plaintext reason; it must still read as written.
    assert audit_detail(json.dumps({"reason": "retention period exceeded"})) == [
        ("reason", "retention period exceeded")
    ]


@pytest.mark.asyncio
async def test_audit_csv_carries_the_reason_decrypted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    csv = await client.get("/admin/audit-log/export.csv")
    assert f"reason={_REASON}" in csv.text
    assert _NAME not in csv.text
