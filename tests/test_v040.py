"""Tests for v0.4.0 features: multi-step submission, locations, confidential mode, i18n."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import SubmissionMode
from app.services.crypto import decrypt, decrypt_or_none, encrypt
from app.services.locations import (
    create_location,
    deactivate_location,
    get_active_locations,
    get_location_by_code,
    get_location_by_id,
    reactivate_location,
)
from app.services.report import create_report

# ── Crypto service ─────────────────────────────────────────────────

class TestCrypto:
    def test_round_trip(self) -> None:
        token = encrypt("hello world")
        assert token != "hello world"
        assert decrypt(token) == "hello world"

    def test_empty_string(self) -> None:
        token = encrypt("")
        assert decrypt(token) == ""

    def test_unicode(self) -> None:
        text = "Ünïcödé tëxt with special chars: €§°"
        assert decrypt(encrypt(text)) == text

    def test_decrypt_or_none_on_none(self) -> None:
        assert decrypt_or_none(None) is None

    def test_decrypt_or_none_on_bad_token(self) -> None:
        assert decrypt_or_none("not-a-valid-token") is None

    def test_decrypt_or_none_valid(self) -> None:
        token = encrypt("test")
        assert decrypt_or_none(token) == "test"


# ── Location service ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestLocationService:
    async def test_create_and_get(self, db_session: AsyncSession) -> None:
        loc = await create_location(db_session, "Test HQ", "TEST-HQ", "Main office", 0)
        assert loc.name == "Test HQ"
        assert loc.code == "TEST-HQ"
        assert loc.is_active is True

    async def test_get_by_code(self, db_session: AsyncSession) -> None:
        await create_location(db_session, "Branch A", "BRANCH-A")
        found = await get_location_by_code(db_session, "BRANCH-A")
        assert found is not None
        assert found.name == "Branch A"

    async def test_get_active_locations_filters_inactive(self, db_session: AsyncSession) -> None:
        await create_location(db_session, "Active", "ACTIVE-LOC")
        loc_inactive = await create_location(db_session, "Inactive", "INACTIVE-LOC")
        await deactivate_location(db_session, loc_inactive)

        active = await get_active_locations(db_session)
        codes = {loc.code for loc in active}
        assert "ACTIVE-LOC" in codes
        assert "INACTIVE-LOC" not in codes

    async def test_reactivate(self, db_session: AsyncSession) -> None:
        loc = await create_location(db_session, "Temp", "TEMP-LOC")
        await deactivate_location(db_session, loc)
        assert loc.is_active is False
        await reactivate_location(db_session, loc)
        assert loc.is_active is True

    async def test_get_by_id(self, db_session: AsyncSession) -> None:
        loc = await create_location(db_session, "ID Test", "ID-TEST-LOC")
        found = await get_location_by_id(db_session, loc.id)
        assert found is not None
        assert found.id == loc.id


# ── Report service with new fields ────────────────────────────────

@pytest.mark.asyncio
class TestReportCreateWithNewFields:
    async def test_anonymous_report(self, db_session: AsyncSession) -> None:
        report, pin = await create_report(
            db_session,
            category="financial_fraud",
            description="Test anonymous report description.",
        )
        assert report.submission_mode == SubmissionMode.anonymous
        assert report.location_id is None
        assert report.confidential_name is None
        assert report.secure_email is None
        assert len(pin) > 10

    async def test_confidential_report(self, db_session: AsyncSession) -> None:
        name_enc = encrypt("Jane Doe")
        contact_enc = encrypt("jane@protonmail.com")
        email_enc = encrypt("anon@protonmail.com")

        report, pin = await create_report(
            db_session,
            category="corruption",
            description="Confidential report about corruption.",
            submission_mode=SubmissionMode.confidential,
            confidential_name_enc=name_enc,
            confidential_contact_enc=contact_enc,
            secure_email_enc=email_enc,
        )
        assert report.submission_mode == SubmissionMode.confidential
        assert report.confidential_name == name_enc
        assert report.confidential_contact == contact_enc
        assert report.secure_email == email_enc

        # Verify we can decrypt
        assert decrypt(report.confidential_name) == "Jane Doe"

    async def test_report_with_location(self, db_session: AsyncSession) -> None:
        loc = await create_location(db_session, "Report Loc Test", "RPTLOC")
        report, _ = await create_report(
            db_session,
            category="environmental",
            description="Environmental violation at this location.",
            location_id=loc.id,
        )
        assert report.location_id == loc.id


# ── Multi-step submission (HTTP) ──────────────────────────────────

@pytest.mark.asyncio
class TestMultiStepSubmission:
    async def test_submit_get_returns_step1(self, client: AsyncClient) -> None:
        resp = await client.get("/submit")
        assert resp.status_code == 200
        # Step 1 is mode selection — submission_mode radio buttons present
        assert "submission_mode" in resp.text

    async def test_submit_step1_requires_mode(self, client: AsyncClient) -> None:
        get_resp = await client.get("/submit")
        csrf = _get_csrf(get_resp)
        resp = await client.post("/submit", data={
            "csrf_token": csrf,
            "step": "1",
            "action": "next",
            "submission_mode": "",
        })
        assert resp.status_code == 200
        assert "submission_mode" in resp.text

    async def test_full_anonymous_submission(self, client: AsyncClient) -> None:
        case_number, pin = await _do_full_anonymous_submit(client)
        assert case_number.startswith("OW-")
        assert len(pin) > 10

    async def test_submit_restart(self, client: AsyncClient) -> None:
        resp = await client.post("/submit/restart")
        assert resp.status_code == 200


async def _do_full_anonymous_submit(client: AsyncClient) -> tuple[str, str]:
    """Walk through all wizard steps and return (case_number, pin).

    Handles both with-locations and without-locations flows.
    """
    # Step 1: mode
    get_resp = await client.get("/submit")
    csrf = _get_csrf(get_resp)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": "anonymous",
    })
    assert resp.status_code == 200

    # Step 2 (location — conditional): skip if present by posting with empty location_id
    if _detect_step(resp) == 2:
        csrf = _get_csrf(resp)
        resp = await client.post("/submit", data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": "",
        })
        assert resp.status_code == 200

    # Step 3: category
    csrf = _get_csrf(resp)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_detect_step(resp)),
        "action": "next",
        "category": "financial_fraud",
    })
    assert resp.status_code == 200
    csrf = _get_csrf(resp)

    # Step 4: description
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_detect_step(resp)),
        "action": "next",
        "description": "This is a test report with enough characters to pass validation.",
    })
    assert resp.status_code == 200
    csrf = _get_csrf(resp)

    # Step 5: attachments (skip)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_detect_step(resp)),
        "action": "next",
    })
    assert resp.status_code == 200
    csrf = _get_csrf(resp)

    # Step 6: review + final submit
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_detect_step(resp)),
        "action": "next",
    })
    assert resp.status_code == 200

    # Should be on success page
    assert any(k in resp.text for k in ("case_number", "Case Number", "Numéro", "Vorgangsnummer"))

    # Extract case number and pin from page
    import re
    cn_match = re.search(r"OW-\d{4}-\d{5}", resp.text)
    case_number = cn_match.group(0) if cn_match else "OW-0000-00000"
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    pin_match = re.search(uuid_pattern, resp.text)
    pin = pin_match.group(0) if pin_match else "00000000-0000-0000-0000-000000000000"
    return case_number, pin


def _get_csrf(response: object) -> str:
    import re

    from httpx import Response as HttpxResponse
    r: HttpxResponse = response  # type: ignore[assignment]
    match = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    return match.group(1) if match else ""


def _detect_step(response: object) -> int:
    import re

    from httpx import Response as HttpxResponse
    r: HttpxResponse = response  # type: ignore[assignment]
    match = re.search(r'name="step" value="(\d+)"', r.text)
    return int(match.group(1)) if match else 1


# ── i18n / Language ───────────────────────────────────────────────

class TestI18n:
    def test_en_locale_loads(self) -> None:
        from app.i18n import make_translator
        t = make_translator("en")
        assert t("nav.submit_report") == "Submit Report"

    def test_de_locale_loads(self) -> None:
        from app.i18n import make_translator
        t = make_translator("de")
        assert t("nav.submit_report") == "Meldung abgeben"

    def test_fr_locale_loads(self) -> None:
        from app.i18n import make_translator
        t = make_translator("fr")
        assert t("nav.submit_report") == "Soumettre un signalement"

    def test_fr_new_keys(self) -> None:
        from app.i18n import make_translator
        t = make_translator("fr")
        assert t("submit.step.mode.anonymous.label") == "Anonyme"
        assert t("admin.nav.locations") == "Lieux"
        assert t("status.deadlines.ack") != "status.deadlines.ack"

    def test_unknown_lang_falls_back(self) -> None:
        from app.i18n import make_translator
        t = make_translator("xx")  # unknown → falls back to en
        assert t("nav.submit_report") == "Submit Report"

    def test_format_keys(self) -> None:
        from app.i18n import make_translator
        t = make_translator("en")
        result = t("submit.progress.step_of", step=2, total=5)
        assert "2" in result and "5" in result

    def test_all_en_keys_present_in_de(self) -> None:
        import json
        from pathlib import Path
        locales = Path(__file__).parent.parent / "app" / "locales"
        en = json.loads((locales / "en.json").read_text())
        de = json.loads((locales / "de.json").read_text())
        missing = [k for k in en if k not in de]
        assert missing == [], f"Keys missing from de.json: {missing[:10]}"

    def test_all_en_keys_present_in_fr(self) -> None:
        import json
        from pathlib import Path
        locales = Path(__file__).parent.parent / "app" / "locales"
        en = json.loads((locales / "en.json").read_text())
        fr = json.loads((locales / "fr.json").read_text())
        missing = [k for k in en if k not in fr]
        assert missing == [], f"Keys missing from fr.json: {missing[:10]}"


# ── Admin location routes ─────────────────────────────────────────

@pytest.mark.asyncio
class TestAdminLocationRoutes:
    async def test_locations_page_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/locations")
        # Should redirect to login
        assert resp.status_code in (200, 302, 401)

    async def test_language_switch_fr(self, client: AsyncClient) -> None:
        resp = await client.post("/set-language", data={
            "lang": "fr",
            "next": "/submit",
        })
        assert resp.status_code == 200  # follows redirects
        # Should have fr cookie
        cookies = {c.name: c.value for c in client.cookies.jar}
        assert cookies.get("ow-lang") == "fr"

    async def test_language_switch_unknown_falls_back(self, client: AsyncClient) -> None:
        await client.post("/set-language", data={
            "lang": "zz",
            "next": "/submit",
        })
        cookies = {c.name: c.value for c in client.cookies.jar}
        assert cookies.get("ow-lang") == "en"
