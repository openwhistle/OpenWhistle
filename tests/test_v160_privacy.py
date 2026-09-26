"""v1.6.0 privacy: one test per guard."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.report import Report, ReportStatus, SubmissionMode
from app.models.user import AdminRole, AdminUser
from app.services.audit import AuditAction
from app.services.auth import hash_password
from app.services.crypto import encrypt
from app.services.report import content_match_ids, create_report, get_reports_paginated
from app.templating import REASON_UNREADABLE


async def _search(client: AsyncClient, q: str, **form: str):  # type: ignore[no-untyped-def]
    """Dashboard search: POST, so the term never sits in a URL."""
    return await client.post(
        "/admin/dashboard", data={"q": q, "csrf_token": client.cookies.get("ow_csrf"), **form}
    )

_PASSWORD = "V160-Privacy-Password"  # noqa: S105
_NAME = "Erika Musterfrau"
_CONTACT = "+49 30 1234"
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
        confidential_name_enc=encrypt(_NAME), confidential_contact_enc=encrypt(_CONTACT),
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
    assert _NAME not in resp.text and _CONTACT not in resp.text
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
    # Nor is the form offered to them: the page says who may see the identity.
    page = (await client.get(f"/admin/reports/{report.id}")).text
    assert f'action="/admin/reports/{report.id}/identity"' not in page
    assert "Only the person handling this case can see the identity." in page


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
async def test_audit_csv_translates_the_via_label_for_a_pdf_export(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import json

    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    await client.post(f"/admin/reports/{report.id}/export.pdf", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    rows = [r for r in await _csv_rows(client) if r["action"] == AuditAction.IDENTITY_REVEALED
            and r["report_id"] == str(report.id)]
    assert [json.loads(r["detail"])["via"] for r in rows] == ["PDF export"]


@pytest.mark.asyncio
async def test_audit_trail_shows_a_localised_via_label_for_pdf(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    await client.post(f"/admin/reports/{report.id}/export.pdf", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    trail = await client.get(f"/admin/audit-log?report_id={report.id}")
    assert "PDF export" in trail.text
    assert ">pdf<" not in trail.text


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
    resp = await _search(client, word.lower())
    assert report.case_number in resp.text
    assert other.case_number not in resp.text


@pytest.mark.asyncio
async def test_case_manager_search_never_reaches_other_cases(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.case_manager)
    word = f"Okapi{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, "corruption", f"Unassigned report about {word}.")
    resp = await _search(client, word)
    assert report.case_number not in resp.text


@pytest.mark.asyncio
async def test_dashboard_search_never_matches_the_confidential_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A hit on the confidential name would confirm an identity guess with no
    reveal recorded, so content search must never look at that field."""
    await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session)
    resp = await _search(client, _NAME)
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
async def test_content_search_limit_tiebreaks_deterministically_on_equal_timestamp(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """order_by(submitted_at.desc()) alone leaves ties (equal timestamps)
    non-deterministic once the corpus exceeds CONTENT_SEARCH_LIMIT — Report.id
    is a secondary sort key so "which N get searched" is pinned. Goes RED if
    that tiebreaker is removed: with two equal-timestamp matching reports and
    the limit patched to 1, only the report with the larger id must be kept."""
    import app.services.report as report_service

    monkeypatch.setattr(report_service, "CONTENT_SEARCH_LIMIT", 1)
    isolate_to = await _bare_admin(db_session)
    word = f"Wombat{uuid.uuid4().hex[:6]}"
    same_time = datetime.now(UTC)
    report_a, _ = await create_report(db_session, "corruption", f"About the {word}, first.")
    report_a.assigned_to_id = isolate_to.id
    report_a.submitted_at = same_time
    report_b, _ = await create_report(db_session, "corruption", f"About the {word}, second.")
    report_b.assigned_to_id = isolate_to.id
    report_b.submitted_at = same_time
    await db_session.commit()

    # Which of two tied rows Postgres returns without the tiebreaker depends
    # on their physical order and random uuids: the result alone is a coin
    # flip against the mutation. The statement itself is not.
    statements: list[str] = []

    def _capture(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        winner = max(report_a.id, report_b.id)
        hits = await content_match_ids(db_session, word, assigned_to_id=isolate_to.id)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    assert hits == [winner]
    assert any(
        "ORDER BY reports.submitted_at DESC, reports.id DESC" in s for s in statements
    ), statements


@pytest.mark.asyncio
async def test_content_search_normalizes_unicode_composition_before_matching(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A precomposed accented character (NFC) must match a query typed in the
    decomposed form (NFD, base letter + combining accent), and vice versa."""
    await _login(client, db_session, AdminRole.admin)
    nfd_e = "é"  # "e" + combining acute accent (U+0301)
    suffix = uuid.uuid4().hex[:6]
    nfc_word = unicodedata.normalize("NFC", f"Andr{nfd_e}{suffix}")  # "André..." precomposed
    nfd_query = f"Andr{nfd_e}{suffix}"  # same text, decomposed
    assert nfc_word != nfd_query  # sanity: genuinely different code point sequences
    report, _ = await create_report(db_session, "corruption", f"Meeting at the {nfc_word}.")
    resp = await _search(client, nfd_query)
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
    resp = await _search(client, word.upper())  # "STRASSE..."
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
    resp = await _search(client, word.upper())
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


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


@pytest.mark.asyncio
async def test_pdf_export_omits_identity_by_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.case_manager)
    report = await _confidential_report(db_session, assigned=user)
    resp = await client.get(f"/admin/reports/{report.id}/export.pdf")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert _NAME not in text
    assert _CONTACT not in text
    assert "[on file — not included]" in text
    assert await _audit_count(db_session, report, AuditAction.REPORT_VIEWED) == 1


@pytest.mark.asyncio
async def test_pdf_export_csrf_is_required_for_the_identity_export(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.case_manager)
    report = await _confidential_report(db_session, assigned=user)
    resp = await client.post(f"/admin/reports/{report.id}/export.pdf", data={
        "reason": _REASON, "csrf_token": "forged-token"})
    assert resp.status_code == 403
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 0


@pytest.mark.asyncio
async def test_pdf_export_with_identity_is_refused_to_a_non_handler(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    other = AdminUser(
        id=uuid.uuid4(), username=f"pdf_handler_{uuid.uuid4().hex[:8]}", password_hash=None,
        totp_secret=pyotp.random_base32(), totp_enabled=True, role=AdminRole.case_manager,
    )
    db_session.add(other)
    await db_session.commit()
    # An admin can reach the report (object-level access) but is not its handler
    # (can_reveal_identity), unlike a case manager who is refused earlier, at 404,
    # for not being able to see the case at all.
    await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=other)
    resp = await client.post(f"/admin/reports/{report.id}/export.pdf", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.status_code == 403
    assert _NAME not in resp.text
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 0


@pytest.mark.asyncio
async def test_pdf_with_identity_needs_a_reason_and_is_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _login(client, db_session, AdminRole.case_manager)
    report = await _confidential_report(db_session, assigned=user)
    refused = await client.post(f"/admin/reports/{report.id}/export.pdf", data={
        "reason": "too short", "csrf_token": client.cookies.get("ow_csrf")})
    assert refused.status_code == 422
    assert _NAME not in refused.text
    assert ">too short</textarea>" in refused.text
    # The refusal is still an audited view of the whole case, and only that.
    assert await _audit_count(db_session, report, AuditAction.REPORT_VIEWED) == 1
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 0

    resp = await client.post(f"/admin/reports/{report.id}/export.pdf", data={
        "reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")})
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["cache-control"] == "no-store"
    text = _pdf_text(resp.content)
    assert _NAME in text
    assert _CONTACT in text
    assert await _audit_count(db_session, report, AuditAction.IDENTITY_REVEALED) == 1
    import json

    from app.services.crypto import decrypt

    row = await db_session.scalar(select(AuditLog).where(
        AuditLog.report_id == report.id, AuditLog.action == AuditAction.IDENTITY_REVEALED))
    assert row is not None
    detail = json.loads(row.detail or "{}")
    assert detail["via"] == "pdf"
    assert decrypt(detail["reason"]) == _REASON


@pytest.mark.asyncio
async def test_content_search_respects_the_active_status_and_location_filter(
    db_session: AsyncSession,
) -> None:
    """content_match_ids takes the same location_id/status_filter as
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


# ── Times the whistleblower caused are stored and shown as the day ────────────


def _is_midnight(moment: datetime) -> bool:
    return (moment.hour, moment.minute, moment.second, moment.microsecond) == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_submission_and_receipt_carry_only_the_day(db_session: AsyncSession) -> None:
    report, _ = await create_report(db_session, "corruption", "Day rounding test report text.")
    await db_session.refresh(report, ["messages"])
    for moment in [report.submitted_at, *(m.sent_at for m in report.messages)]:
        assert _is_midnight(moment.astimezone(UTC))


@pytest.mark.asyncio
async def test_attachment_upload_time_is_the_day(db_session: AsyncSession) -> None:
    from app.services.attachment import create_attachments

    report, _ = await create_report(db_session, "corruption", "Attachment day test report text.")
    [att] = await create_attachments(db_session, report, [("n.txt", "text/plain", b"hello")])
    await db_session.refresh(att)
    assert _is_midnight(att.uploaded_at.astimezone(UTC))


@pytest.mark.asyncio
async def test_same_day_whistleblower_reply_stays_after_the_admin_reply(
    db_session: AsyncSession,
) -> None:
    from app.models.report import ReportSender
    from app.services.report import add_admin_message, add_whistleblower_message

    report, _ = await create_report(db_session, "corruption", "Thread order test report text.")
    admin_msg = await add_admin_message(
        db_session, report, "Admin answer", notify_whistleblower=False
    )
    wb_msg = await add_whistleblower_message(db_session, report, "Whistleblower follow-up")
    assert wb_msg.sent_at > admin_msg.sent_at
    await db_session.refresh(report, ["messages"])
    senders = [m.sender for m in report.messages]
    assert senders[-2:] == [ReportSender.admin, ReportSender.whistleblower]


@pytest.mark.asyncio
async def test_whistleblower_reply_on_a_new_day_is_that_midnight(db_session: AsyncSession) -> None:
    from sqlalchemy import text

    from app.services.report import add_whistleblower_message

    report, _ = await create_report(db_session, "corruption", "New day reply test report text.")
    await db_session.execute(text(
        "UPDATE report_messages SET sent_at = sent_at - interval '3 days' WHERE report_id = :r"
    ), {"r": report.id})
    await db_session.commit()
    wb_msg = await add_whistleblower_message(db_session, report, "Next-day follow-up")
    assert _is_midnight(wb_msg.sent_at.astimezone(UTC))
    assert wb_msg.sent_at.date() == datetime.now(UTC).date()


def test_day_floor_is_the_utc_day() -> None:
    from datetime import timedelta, timezone

    from app.services.report import day_floor

    berlin_early = datetime(2026, 9, 2, 1, 30, tzinfo=timezone(timedelta(hours=2)))
    assert day_floor(berlin_early) == datetime(2026, 9, 1, tzinfo=UTC)


def _alembic(*args: str) -> None:
    """Run alembic against settings.database_url — the throwaway DB in these tests."""
    import os
    import subprocess

    from app.config import settings

    run = subprocess.run(  # noqa: S603
        ["alembic", *args], capture_output=True, text=True, check=False,  # noqa: S607
        env={**os.environ, "DATABASE_URL": settings.database_url},
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.asyncio
async def test_migration_006_rounds_existing_rows_keeps_order_and_round_trips(
    throwaway_db: AsyncSession,
) -> None:
    from datetime import timedelta

    from sqlalchemy import text

    from app.services.attachment import create_attachments
    from app.services.report import add_admin_message, add_whistleblower_message

    db = throwaway_db
    tick = timedelta(microseconds=1)

    def at(day: int, h: int, m: int = 0, s: int = 0) -> datetime:
        return datetime(2026, 9, day, h, m, s, tzinfo=UTC)

    # A: receipt 09:05:07, office 14:00, reporter 16:30 and 17:00 on the same day.
    # B: receipt day 1, reporter day 2 08:00, office day 3 10:15.
    a, _ = await create_report(db, "corruption", "Migration 006 report A.")
    a_ids = [
        (await add_admin_message(db, a, "Office")).id,
        (await add_whistleblower_message(db, a, "Reporter 1")).id,
        (await add_whistleblower_message(db, a, "Reporter 2")).id,
    ]
    b, _ = await create_report(db, "corruption", "Migration 006 report B.")
    b_ids = [
        (await add_whistleblower_message(db, b, "Reporter")).id,
        (await add_admin_message(db, b, "Office")).id,
    ]
    await create_attachments(db, a, [("m.txt", "text/plain", b"x")])
    receipt = {
        r.id: await db.scalar(text(
            "SELECT id FROM report_messages WHERE report_id = :r ORDER BY sent_at, id LIMIT 1"
        ), {"r": r.id}) for r in (a, b)
    }
    exact = {
        receipt[a.id]: at(1, 9, 5, 7), a_ids[0]: at(1, 14), a_ids[1]: at(1, 16, 30),
        a_ids[2]: at(1, 17), receipt[b.id]: at(1, 11), b_ids[0]: at(2, 8),
        b_ids[1]: at(3, 10, 15),
    }
    for msg_id, stamp in exact.items():
        await db.execute(text("UPDATE report_messages SET sent_at = :t WHERE id = :i"),
                         {"t": stamp, "i": msg_id})
    await db.execute(text("UPDATE reports SET submitted_at = :t"), {"t": at(1, 9, 5, 7)})
    await db.execute(text("UPDATE attachments SET uploaded_at = :t"), {"t": at(1, 9, 5, 7)})
    await db.commit()  # release locks before the alembic subprocess

    async def snapshot() -> tuple[object, ...]:
        rows = (await db.execute(text(
            "SELECT id, sent_at FROM report_messages ORDER BY report_id, sent_at"
        ))).all()
        days = (await db.execute(text(
            "SELECT submitted_at FROM reports UNION ALL SELECT uploaded_at FROM attachments"
        ))).scalars().all()
        await db.commit()
        return dict(rows), sorted(days)

    _alembic("downgrade", "b2d7f1a5c302")
    _alembic("upgrade", "head")
    first = await snapshot()
    msgs, days = first
    assert days == [at(1, 0)] * 3
    assert msgs == {
        receipt[a.id]: at(1, 0), a_ids[0]: at(1, 14),  # the office keeps its time
        a_ids[1]: at(1, 14) + tick, a_ids[2]: at(1, 14) + 2 * tick,  # after it, in order
        receipt[b.id]: at(1, 0), b_ids[0]: at(2, 0), b_ids[1]: at(3, 10, 15),
    }

    _alembic("downgrade", "b2d7f1a5c302")  # a no-op on data: the rounding is lossy
    assert await snapshot() == first
    _alembic("upgrade", "head")
    assert await snapshot() == first  # idempotent


def test_migration_006_runs_offline() -> None:
    import subprocess

    run = subprocess.run(  # noqa: S603
        ["alembic", "upgrade", "b2d7f1a5c302:c3e8a2b6d403", "--sql"],  # noqa: S607
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "UPDATE report_messages" in run.stdout  # the receipt is rounded offline too


@pytest.mark.asyncio
async def test_case_page_and_pdf_show_whistleblower_times_as_the_day_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import text

    from app.services.report import add_admin_message, add_whistleblower_message

    user = await _login(client, db_session, AdminRole.case_manager)
    report, _ = await create_report(db_session, "corruption", "Date-only display test text.")
    report.assigned_to_id = user.id
    await db_session.commit()
    admin_msg = await add_admin_message(db_session, report, "Admin answer")
    # A distinct office minute on the submission day; the reply lands 1 µs after it.
    day = report.submitted_at.strftime("%Y-%m-%d")
    await db_session.execute(text(
        "UPDATE report_messages SET sent_at = :t WHERE id = :i"
    ), {"t": report.submitted_at.replace(hour=13, minute=37), "i": admin_msg.id})
    await db_session.commit()
    await add_whistleblower_message(db_session, report, "Whistleblower follow-up")

    page = (await client.get(f"/admin/reports/{report.id}")).text
    assert page.count("data-date-only>") == 3  # submitted, receipt, whistleblower reply
    assert page.count("13:37 UTC") == 1

    pdf = _pdf_text((await client.get(f"/admin/reports/{report.id}/export.pdf")).content)
    body = [line for line in pdf.splitlines() if not line.startswith("Generated")]
    stamped = [line for line in body if "·" in line]
    assert [line.split("·")[1].strip() for line in stamped] == [day, f"{day} 13:37 UTC", day]
    assert re.search(rf"Submitted:?\s*{day}\s*$", "\n".join(body), re.M)


@pytest.mark.asyncio
async def test_equal_submission_days_page_in_a_stable_id_order(db_session: AsyncSession) -> None:
    isolate_to = await _bare_admin(db_session)
    ids = []
    for i in range(6):
        report, _ = await create_report(db_session, "corruption", f"Tiebreak report {i}.")
        report.assigned_to_id = isolate_to.id
        ids.append(report.id)
    await db_session.commit()
    paged = [
        r.id for page in range(1, 7)
        for r in (await get_reports_paginated(
            db_session, page=page, per_page=1, assigned_to_id=isolate_to.id))[0]
    ]
    assert paged == sorted(ids, reverse=True)


@pytest.mark.asyncio
async def test_concurrent_whistleblower_replies_get_distinct_ordered_times(
    db_session: AsyncSession,
) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.services.report import add_whistleblower_message, get_report_by_id

    report, _ = await create_report(db_session, "corruption", "Concurrent replies test text.")
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async def post(text: str) -> datetime:
            async with sessions() as db:
                loaded = await get_report_by_id(db, report.id)
                assert loaded is not None
                return (await add_whistleblower_message(db, loaded, text)).sent_at

        times = await asyncio.gather(*(post(f"Reply {i}") for i in range(4)))
    finally:
        await engine.dispose()
    assert len(set(times)) == 4
    await db_session.refresh(report, ["messages"])
    stored = [m.sent_at for m in report.messages]
    assert stored == sorted(stored) and len(set(stored)) == len(stored)


@pytest.mark.asyncio
async def test_demo_seed_stores_reporter_times_as_the_day(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.orm import selectinload

    from app.models.report import ReportSender
    from app.services import demo_seed
    from app.services.demo_seed import DEMO_REPORTS, _seed

    # Whether earlier tests left a completed setup without a demo account is
    # not this test's concern: it must seed whatever ran before it.
    monkeypatch.setattr(demo_seed, "_is_foreign_database", AsyncMock(return_value=False))
    await _seed(db_session)
    reports = (await db_session.execute(
        select(Report).options(selectinload(Report.messages))
        .where(Report.case_number.in_([d["case_number"] for d in DEMO_REPORTS]))
    )).scalars().all()
    assert len(reports) == len(DEMO_REPORTS)
    for report in reports:
        assert _is_midnight(report.submitted_at.astimezone(UTC))
        if report.acknowledged_at:
            assert report.submitted_at < report.acknowledged_at
        times = [m.sent_at for m in report.messages]
        assert len(set(times)) == len(times)  # the receipt is first, deterministically
        assert report.messages[0].sent_at == report.submitted_at
        for msg in report.messages:
            if msg.sender == ReportSender.whistleblower:
                assert _is_midnight(msg.sent_at.astimezone(UTC))


def test_local_time_script_shows_date_only_values_as_the_utc_day() -> None:
    """The base.html formatter, run in Node west of UTC: a date-only value stays
    its UTC day (local midnight-5h would read as the day before); an ordinary
    value becomes local time. No browser needed."""
    import os
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        # CI sets up Node for this test; a skip there would hide the guard.
        assert not os.environ.get("CI"), "node is missing in CI (actions/setup-node)"
        pytest.skip("node is not installed")
    html = Path("app/templates/base.html").read_text()
    script = next(
        chunk.split("</script>")[0] for chunk in html.split("<script nonce=")[1:]
        if "time[data-utc]" in chunk
    ).split(">", 1)[1]
    harness = """
    function el(utc, dateOnly) {
      return {attrs: {'data-utc': utc}, textContent: '', title: '',
        getAttribute(n) { return this.attrs[n]; },
        hasAttribute(n) { return n === 'data-date-only' ? dateOnly : n in this.attrs; }};
    }
    const els = [el('2026-09-01T00:00:00+00:00', true), el('2026-09-01T00:00:00+00:00', false)];
    globalThis.document = {querySelectorAll: () => els};
    """ + script + """
    console.log(JSON.stringify(els.map(e => [e.textContent, e.title])));
    """
    run = subprocess.run(  # noqa: S603
        [node, "-e", harness], capture_output=True, text=True, check=True,
        env={**os.environ, "TZ": "America/New_York"},
    )
    import json

    (day_only, day_only_title), (local, _) = json.loads(run.stdout)
    assert day_only == "2026-09-01" and day_only_title == ""
    assert local.startswith("2026-08-31 20:00")


@pytest.mark.asyncio
async def test_content_search_stays_inside_the_callers_organisation(
    db_session: AsyncSession,
) -> None:
    """No report of another organisation is decrypted for the search, and none
    spends the CONTENT_SEARCH_LIMIT budget of this one."""
    from app.models.organisation import Organisation

    ours = Organisation(id=uuid.uuid4(), name="Ours", slug=f"o-{uuid.uuid4().hex[:6]}")
    theirs = Organisation(id=uuid.uuid4(), name="Theirs", slug=f"t-{uuid.uuid4().hex[:6]}")
    db_session.add_all([ours, theirs])
    await db_session.flush()
    word = f"Okapi{uuid.uuid4().hex[:6]}"
    mine, _ = await create_report(db_session, "corruption", f"Our report on {word}.")
    other, _ = await create_report(db_session, "corruption", f"Their report on {word}.")
    mine.org_id, other.org_id = ours.id, theirs.id
    await db_session.commit()

    hits = await content_match_ids(db_session, word, scope_org=True, org_id=ours.id)
    assert hits == [mine.id]
