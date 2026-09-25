"""v1.6.0 privacy: one test per guard."""

from __future__ import annotations

import re
import unicodedata
import uuid

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.report import Report, ReportStatus, SubmissionMode
from app.models.user import AdminRole, AdminUser
from app.services.audit import AuditAction
from app.services.auth import hash_password
from app.services.crypto import encrypt
from app.services.report import content_match_ids, create_report, get_reports_paginated
from app.templating import REASON_UNREADABLE

_PASSWORD = "V160-Privacy-Password"  # noqa: S105
_NAME = "Erika Musterfrau"
_REASON = "Needed to arrange the protected interview."


async def _login(
    client: AsyncClient, db: AsyncSession, role: AdminRole, org_id: uuid.UUID | None = None
) -> AdminUser:
    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(), username=f"priv_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=secret, totp_enabled=True, role=role,
        org_id=org_id,
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


async def _bare_admin(db: AsyncSession) -> AdminUser:
    """An admin row with no login, used only to isolate a report by assigned_to_id
    (a real foreign key) from every other report ever created in this test run."""
    user = AdminUser(
        id=uuid.uuid4(), username=f"iso_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD), totp_secret=pyotp.random_base32(),
        totp_enabled=True,
    )
    db.add(user)
    await db.commit()
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
# Empty, too short, whitespace padding up to 10 (strip), one past the maximum.
@pytest.mark.parametrize("reason", ["", "too short", " " * 10 + "a", "x" * 501])
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
    # The refusal renders the whole case, so it is an audited view.
    assert await _audit_count(db_session, report, AuditAction.REPORT_VIEWED) == 1
    # What was typed comes back, so the handler need not retype it.
    assert f">{reason}</textarea>" in resp.text


@pytest.mark.asyncio
async def test_reveal_without_csrf_token_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.case_manager)
    report = await _confidential_report(db_session, assigned=user)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": "forged-token"})
    assert resp.status_code == 403
    assert _NAME not in resp.text
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 0


@pytest.mark.asyncio
async def test_superadmin_may_reveal_an_unassigned_case(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.superadmin)
    report = await _confidential_report(db_session, assigned=None)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 200 and _NAME in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "same_org", "org_less_report", "expected"), [
    (AdminRole.admin, True, False, 200),
    (AdminRole.superadmin, True, False, 200),
    (AdminRole.superadmin, False, False, 403),
    # A report with no organisation belongs to no tenant: any admin may handle it.
    (AdminRole.admin, False, True, 200),
])
async def test_multi_tenant_unassigned_reveal_is_for_the_case_org_only(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
    role: AdminRole, same_org: bool, org_less_report: bool, expected: int,
) -> None:
    from app.config import settings
    from app.models.organisation import Organisation

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    orgs = [Organisation(id=uuid.uuid4(), name=n, slug=f"{n}-{uuid.uuid4().hex[:6]}") for n in "ab"]
    db_session.add_all(orgs)
    await db_session.commit()
    await _login(client, db_session, role, org_id=orgs[0].id if same_org else orgs[1].id)
    report = await _confidential_report(db_session, assigned=None)
    report.org_id = None if org_less_report else orgs[0].id
    await db_session.commit()
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == expected
    assert (_NAME in resp.text) == (expected == 200)


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
    await _login(client, db_session, AdminRole.case_manager)
    resp = await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 404
    assert _NAME not in resp.text
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 1


def test_audit_detail_decrypts_a_reveal_reason_and_keeps_a_plain_one() -> None:
    import json

    from app.templating import audit_detail

    assert audit_detail(json.dumps({"reason": encrypt(_REASON)})) == [("reason", _REASON)]
    # The retention job writes a plaintext reason; it must still read as written.
    assert audit_detail(json.dumps({"reason": "retention period exceeded"})) == [
        ("reason", "retention period exceeded")
    ]
    # A token that no longer decrypts is not the same as no reason.
    assert audit_detail(json.dumps({"reason": "gAAAAAbroken"})) == [
        ("reason", REASON_UNREADABLE)
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
    assert _REASON in csv.text
    assert _NAME not in csv.text


async def _csv_rows(client: AsyncClient, query: str = "") -> list[dict[str, str]]:
    import csv
    import io

    resp = await client.get(f"/admin/audit-log/export.csv{query}")
    return list(csv.DictReader(io.StringIO(resp.text)))


@pytest.mark.asyncio
async def test_audit_csv_detail_cannot_be_forged_by_a_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import json

    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    forged = "Needed for the call; via=forged"
    await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": forged, "csrf_token": client.cookies.get("ow_csrf")})
    rows = [r for r in await _csv_rows(client) if r["action"] == AuditAction.IDENTITY_REVEALED
            and r["report_id"] == str(report.id)]
    assert [json.loads(r["detail"]) for r in rows] == [{"reason": forged}]


@pytest.mark.asyncio
async def test_audit_csv_neutralises_formulas(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.admin)
    db_session.add(AuditLog(
        id=uuid.uuid4(), admin_id=None, admin_username="=cmd|' /C calc'!A0",
        action="legacy.entry", detail='=HYPERLINK("https://evil.test","x")',
    ))
    await db_session.commit()
    row = next(r for r in await _csv_rows(client) if r["action"] == "legacy.entry")
    assert row["admin"].startswith("'=")
    assert row["detail"].startswith("'=")


@pytest.mark.asyncio
async def test_audit_csv_keeps_every_key_of_a_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import json

    await _login(client, db_session, AdminRole.admin)
    db_session.add(AuditLog(
        id=uuid.uuid4(), admin_id=None, admin_username="system",
        action="keys.entry", detail=json.dumps({"": "blank key", "via": "kept"}),
    ))
    await db_session.commit()
    row = next(r for r in await _csv_rows(client) if r["action"] == "keys.entry")
    assert json.loads(row["detail"]) == {"": "blank key", "via": "kept"}


@pytest.mark.asyncio
async def test_audit_csv_marks_an_unreadable_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import json

    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    db_session.add(AuditLog(
        id=uuid.uuid4(), admin_id=user.id, admin_username=user.username, report_id=report.id,
        action=AuditAction.IDENTITY_REVEALED, detail=json.dumps({"reason": "gAAAAAbroken"}),
    ))
    await db_session.commit()
    row = next(r for r in await _csv_rows(client) if r["report_id"] == str(report.id))
    assert json.loads(row["detail"]) == {"reason": "Reason unreadable (decryption failed)"}


@pytest.mark.asyncio
async def test_case_page_says_a_reason_was_recorded_but_not_what(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    await client.post(f"/admin/reports/{report.id}/identity", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    page = await client.get(f"/admin/reports/{report.id}")
    assert _REASON not in page.text
    assert "Reason recorded (see audit log)" in page.text
    trail = await client.get(f"/admin/audit-log?report_id={report.id}")
    assert _REASON in trail.text


@pytest.mark.asyncio
async def test_audit_trail_hides_case_views_unless_asked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    await client.get(f"/admin/reports/{report.id}")
    viewed = f'title="{AuditAction.REPORT_VIEWED}"'
    page = await client.get(f"/admin/audit-log?report_id={report.id}")
    assert viewed not in page.text
    page = await client.get(f"/admin/audit-log?report_id={report.id}&views=1")
    assert viewed in page.text
    assert 'href="/admin/audit-log/export.csv?views=1"' in page.text

    def views(rows: list[dict[str, str]]) -> int:
        return sum(r["action"] == AuditAction.REPORT_VIEWED and r["report_id"] == str(report.id)
                   for r in rows)

    assert views(await _csv_rows(client)) == 0
    assert views(await _csv_rows(client, "?views=1")) == 1


@pytest.mark.asyncio
async def test_dashboard_search_finds_words_inside_reports(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.admin)
    word = f"Zebra{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, "corruption", f"The invoice mentions {word} twice.")
    other, _ = await create_report(db_session, "corruption", "Nothing to see in this report here.")
    resp = await client.get(f"/admin/dashboard?q={word.lower()}")
    assert report.case_number in resp.text
    assert other.case_number not in resp.text


@pytest.mark.asyncio
async def test_case_manager_search_never_reaches_other_cases(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.case_manager)
    word = f"Okapi{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, "corruption", f"Unassigned report about {word}.")
    resp = await client.get(f"/admin/dashboard?q={word}")
    assert report.case_number not in resp.text


@pytest.mark.asyncio
async def test_dashboard_search_never_matches_the_confidential_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A hit on the confidential name would confirm an identity guess with no
    reveal recorded, so content search must never look at that field."""
    await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session)
    resp = await client.get("/admin/dashboard", params={"q": _NAME})
    assert report.case_number not in resp.text


@pytest.mark.asyncio
async def test_content_search_limit_caps_how_many_reports_are_decrypted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTENT_SEARCH_LIMIT is the only thing bounding per-request decryption
    cost; this goes RED if the `.limit()` call is dropped or the constant is
    raised without a matching test."""
    import app.services.report as report_service

    monkeypatch.setattr(report_service, "CONTENT_SEARCH_LIMIT", 2)
    isolate_to = await _bare_admin(db_session)
    word = f"Capybara{uuid.uuid4().hex[:6]}"
    for _ in range(3):
        report, _ = await create_report(db_session, "corruption", f"Report about {word}.")
        report.assigned_to_id = isolate_to.id
        await db_session.commit()

    hits = await content_match_ids(db_session, word, assigned_to_id=isolate_to.id)
    assert len(hits) == 2


@pytest.mark.asyncio
async def test_content_search_normalizes_unicode_composition_before_matching(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A precomposed accented character (NFC) must match a query typed in the
    decomposed form (NFD, base letter + combining accent), and vice versa."""
    await _login(client, db_session, AdminRole.admin)
    nfd_e = "é"  # "e" + combining acute accent (U+0301)
    suffix = uuid.uuid4().hex[:6]
    nfc_word = unicodedata.normalize("NFC", f"caf{nfd_e}{suffix}")  # "café..." precomposed
    nfd_query = f"caf{nfd_e}{suffix}"  # same text, decomposed
    assert nfc_word != nfd_query  # sanity: genuinely different code point sequences
    report, _ = await create_report(db_session, "corruption", f"Meeting at the {nfc_word}.")
    resp = await client.get("/admin/dashboard", params={"q": nfd_query})
    assert report.case_number in resp.text


@pytest.mark.asyncio
async def test_content_search_matches_strasse_case_folded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """casefold() expands "ß" to "ss"; normalizing for composition must not
    break that expansion."""
    await _login(client, db_session, AdminRole.admin)
    word = f"Straße{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, "corruption", f"Address: {word} 12.")
    resp = await client.get("/admin/dashboard", params={"q": word.upper()})  # "STRASSE..."
    assert report.case_number in resp.text


@pytest.mark.asyncio
async def test_dashboard_search_matches_an_uppercase_query_against_lowercase_content(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The existing search test only checks a lowercased query against mixed-case
    content; this checks the reverse direction."""
    await _login(client, db_session, AdminRole.admin)
    word = f"lemur{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(
        db_session, "corruption", f"A note about the {word} in the field."
    )
    resp = await client.get("/admin/dashboard", params={"q": word.upper()})
    assert report.case_number in resp.text


@pytest.mark.asyncio
async def test_combined_case_number_and_content_match_has_no_duplicates(
    db_session: AsyncSession,
) -> None:
    """A report matching both by case number and by decrypted content must be
    counted, and returned, exactly once."""
    from app.services.encryption import encrypt_field, make_report_fernet

    report, _ = await create_report(db_session, "corruption", "placeholder")
    digits = report.case_number.split("-")[-1]
    fernet = make_report_fernet(report.encrypted_dek)
    report.description = encrypt_field(fernet, f"Mentions case {digits} in the body too.")
    isolate_to = await _bare_admin(db_session)
    report.assigned_to_id = isolate_to.id
    await db_session.commit()

    hits = await content_match_ids(db_session, digits, assigned_to_id=isolate_to.id)
    assert hits == [report.id]

    reports, total = await get_reports_paginated(
        db_session, assigned_to_id=isolate_to.id, case_query=digits, content_ids=hits
    )
    assert total == 1
    assert [r.id for r in reports] == [report.id]


@pytest.mark.asyncio
async def test_content_search_respects_the_active_status_and_location_filter(
    db_session: AsyncSession,
) -> None:
    """Ruling: content_match_ids takes the same location_id/status_filter as
    get_reports_paginated, so the CONTENT_SEARCH_LIMIT budget follows the
    caller's current view — a report outside the active filter must not be
    decrypted/matched."""
    isolate_to = await _bare_admin(db_session)
    word = f"Otter{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, "corruption", f"About the {word}.")
    report.assigned_to_id = isolate_to.id
    await db_session.commit()
    assert report.status == ReportStatus.received

    # Filtered to a status the report is not in: no match.
    hits = await content_match_ids(
        db_session, word, assigned_to_id=isolate_to.id, status_filter=ReportStatus.closed.value
    )
    assert hits == []

    # Filtered to a location the report is not in: no match.
    hits = await content_match_ids(
        db_session, word, assigned_to_id=isolate_to.id, location_id=uuid.uuid4()
    )
    assert hits == []

    # No status/location filter beyond assignment: matches.
    hits = await content_match_ids(db_session, word, assigned_to_id=isolate_to.id)
    assert hits == [report.id]
