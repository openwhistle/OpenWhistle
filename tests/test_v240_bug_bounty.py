"""Defects found by the bug bounty after v2.3.0, each reproduced before it was fixed."""

import asyncio
import secrets

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ── The lockout holds against guesses sent together ─────────────────────────


@pytest.mark.asyncio
async def test_parallel_codes_get_no_more_guesses_than_the_lockout_allows(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count was read, the code checked, the failure counted after: a burst all read
    the same count. 50 codes sent together with the password known got 18 checked
    against a limit of 10 (measured), and the burst can be repeated every window."""
    from app.config import settings
    from app.redis_client import get_redis
    from app.services import auth as auth_service
    from tests.test_v210_bug_bounty import _totp_user

    monkeypatch.setattr(settings, "demo_mode", False)
    user = await _totp_user(db_session)
    redis = await get_redis()
    tokens = [secrets.token_urlsafe(32) for _ in range(50)]
    for token in tokens:
        await auth_service.store_totp_pending(redis, token, str(user.id))

    async def guess(token: str) -> int:
        resp = await client.post(
            "/admin/login/mfa",
            data={"temp_token": token, "totp_code": "000000"},
            follow_redirects=False,
        )
        return resp.status_code

    codes = await asyncio.gather(*(guess(t) for t in tokens))
    assert codes.count(200) == settings.max_login_attempts, codes


@pytest.mark.asyncio
async def test_a_right_password_does_not_count_as_a_failure(
    client: AsyncClient, db_session: AsyncSession, no_csrf
) -> None:
    """Counted before it is checked, a right password gives its attempt back."""
    from app.redis_client import get_redis
    from app.services import rate_limit as rl
    from tests.test_v210_bug_bounty import _totp_user

    user = await _totp_user(db_session)
    for _ in range(3):
        resp = await client.post(
            "/admin/login", data={"username": user.username, "password": "TestPassword123!"}
        )
        assert "temp_token" in resp.text
    assert await (await get_redis()).get(rl._admin_key(user.username)) in (None, b"0", "0")


@pytest.mark.asyncio
async def test_a_right_directory_password_does_not_count_as_a_failure(
    client: AsyncClient, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import rate_limit as rl
    from app.services.ldap_auth import LDAPUserInfo

    name = f"ldap_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "ldap_enabled", True)
    with patch(
        "app.services.ldap_auth.authenticate_ldap", AsyncMock(return_value=LDAPUserInfo(name))
    ):
        for _ in range(3):
            await client.post("/admin/login", data={"username": name, "password": "x"})
    assert await (await get_redis()).get(rl._admin_key(name)) in (None, b"0", "0")


@pytest.mark.asyncio
async def test_a_locked_sign_in_answers_429(
    client: AsyncClient, db_session: AsyncSession, no_csrf
) -> None:
    """The second-factor form answered a lockout with 429, the password form with 200."""
    from app.config import settings
    from tests.test_v210_bug_bounty import _totp_user

    user = await _totp_user(db_session)
    for _ in range(settings.max_login_attempts):
        await client.post("/admin/login", data={"username": user.username, "password": "wrong"})
    resp = await client.post(
        "/admin/login", data={"username": user.username, "password": "TestPassword123!"}
    )
    assert resp.status_code == 429


@pytest.mark.parametrize(
    "name",
    [
        "login_lockout_minutes",
        "max_login_attempts",
        "access_lockout_minutes",
        "max_access_attempts",
        "access_token_expire_minutes",
    ],
)
def test_a_lockout_or_session_of_zero_is_refused(name: str) -> None:
    """LOGIN_LOCKOUT_MINUTES=0 was accepted: EXPIRE 0 deletes the counter as it is
    written, so the lockout never locked. 0 attempts locked every account after one
    miss, a session of 0 minutes ended at once."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match=name):
        Settings(**{name: 0})  # type: ignore[arg-type]


# ── Three years of retention are three calendar years ───────────────────────


@pytest.mark.asyncio
async def test_retention_keeps_a_report_three_calendar_years_across_a_leap_day(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RETENTION_DAYS=1095 is "3 years" on the retention page, and the cutoff was
    1095 days: closed on 1 March 2027, a report was deleted on 28 February 2030,
    a day before HinSchG §11(5)'s three years were up (2028 has a 29 February)."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    import app.services.retention as retention
    from app.config import settings
    from app.models.report import Report, ReportStatus
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Kept three years.")
    report.status = ReportStatus.closed
    report.closed_at = datetime(2027, 3, 1, tzinfo=UTC)
    await db_session.commit()
    report_id = report.id

    class Now(datetime):
        moment = datetime(2030, 2, 28, 12, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def, override]
            return cls.moment

    monkeypatch.setattr(retention, "datetime", Now)
    monkeypatch.setattr(settings, "retention_enabled", True)
    monkeypatch.setattr(settings, "retention_days", 1095)
    await retention.run_retention_cleanup()
    assert await db_session.scalar(select(Report.id).where(Report.id == report_id))

    Now.moment = datetime(2030, 3, 1, 12, tzinfo=UTC)
    await retention.run_retention_cleanup()
    db_session.expire_all()
    assert await db_session.scalar(select(Report.id).where(Report.id == report_id)) is None


# ── Switching a category or location off stands with its audit entry ───────


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["categories", "locations"])
@pytest.mark.parametrize("action", ["deactivate", "reactivate"])
async def test_a_category_or_location_switch_is_not_kept_without_its_audit_row(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, kind: str, action: str
) -> None:
    """2.3.0 made creating them commit with the audit entry; switching them off or on
    committed first, so a failing audit write left the change in place, unaudited."""
    import uuid

    from sqlalchemy import select

    from app.models.category import ReportCategory
    from app.models.location import Location
    from app.models.user import AdminRole
    from app.services import audit as audit_service
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    admin = await _totp_user(db_session, AdminRole.admin)
    model = ReportCategory if kind == "categories" else Location
    tag = uuid.uuid4().hex[:8]
    row = (
        ReportCategory(slug=f"c_{tag}", label_en="X", label_de="X", org_id=admin.org_id)
        if kind == "categories"
        else Location(name="X", code=f"L{tag}".upper(), org_id=admin.org_id)
    )
    row.is_active = action == "deactivate"  # the switch has something to switch
    db_session.add(row)
    await db_session.commit()
    row_id = row.id

    async def broken_log(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(audit_service, "log", broken_log)
    act(admin)
    with pytest.raises(RuntimeError, match="audit write failed"):
        await client.post(f"/admin/{kind}/{row_id}/{action}")
    db_session.expire_all()
    is_active = await db_session.scalar(select(model.is_active).where(model.id == row_id))
    assert is_active == (action == "deactivate")  # unchanged


# ── The case of another organisation is labelled with its own category ──────


@pytest.mark.asyncio
async def test_a_superadmin_sees_each_case_under_its_own_organisations_label(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slug is unique per organisation only. A superadmin is not scoped, so one
    slug -> label map held both organisations' "custom" and one label won: the case
    page, the dashboard and the PDF export named the other organisation's category."""
    import io
    import uuid

    from pypdf import PdfReader

    from app.api.deps import get_current_admin
    from app.config import settings
    from app.main import app
    from app.models.category import ReportCategory
    from app.models.organisation import Organisation
    from app.models.user import AdminRole
    from app.services.report import create_report
    from tests.test_v210_bug_bounty import _totp_user

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    orgs = [Organisation(id=uuid.uuid4(), name=n, slug=f"{n}-{uuid.uuid4().hex[:6]}") for n in "AB"]
    db_session.add_all(orgs)
    await db_session.flush()
    reports = {}
    for org in orgs:
        db_session.add(
            ReportCategory(
                slug="custom", label_en=f"Label of {org.name}", label_de="x", org_id=org.id
            )
        )
        report, _ = await create_report(db_session, "custom", "Labelled by its own org.")
        report.org_id = org.id
        reports[org.name] = report
    boss = await _totp_user(db_session, AdminRole.superadmin)
    await db_session.commit()

    app.dependency_overrides[get_current_admin] = lambda: boss
    try:
        for name, other in (("A", "B"), ("B", "A")):
            page = (await client.get(f"/admin/reports/{reports[name].id}")).text
            assert f"Label of {name}" in page and f"Label of {other}" not in page
            pdf = (await client.get(f"/admin/reports/{reports[name].id}/export.pdf")).content
            text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
            assert f"Label of {name}" in text, name
        from app.csrf import validate_csrf

        app.dependency_overrides[validate_csrf] = lambda: None
        for name in "AB":
            case = reports[name].case_number
            dashboard = (await client.post("/admin/dashboard", data={"q": case})).text
            link = dashboard.index(f"/admin/reports/{reports[name].id}")
            row = dashboard[dashboard.rindex("<tr", 0, link) : link]
            assert f"Label of {name}" in row, name
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(validate_csrf, None)


# ── Migration 017 moves a case's audit trail with the case ──────────────────


@pytest.mark.asyncio
async def test_migration_017_moves_the_audit_rows_with_the_case(db_session: AsyncSession) -> None:
    """017 filed organisation-less cases under an organisation; their audit rows, which
    carry the case's organisation from when they were written, stayed without one. The
    audit log is filtered by organisation: that organisation's admins saw no trail of
    the case, its identity reveals included."""
    import importlib.util
    from pathlib import Path

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.report import Report
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Filed without an org.")
    report.org_id = None
    report_id = report.id
    await db_session.flush()
    db_session.add(
        AuditLog(admin_username="x", action="report.identity_revealed", report_id=report_id)
    )
    await db_session.commit()
    assert (
        await db_session.scalar(select(AuditLog.org_id).where(AuditLog.report_id == report_id))
        is None
    )

    path = next((Path(__file__).parents[1] / "migrations/versions").glob("017_*.py"))
    spec = importlib.util.spec_from_file_location("m017", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def upgrade(sync_conn) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(sync_conn)):
            module.upgrade()

    conn = await db_session.connection()
    await conn.run_sync(upgrade)
    await db_session.commit()
    db_session.expire_all()
    org = await db_session.scalar(select(Report.org_id).where(Report.id == report_id))
    assert org is not None
    trail = await db_session.scalar(select(AuditLog.org_id).where(AuditLog.report_id == report_id))
    assert trail == org


# ── Attachments: what the strip missed ──────────────────────────────────────


def _package(parts: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
            b'2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr(
            "word/document.xml",
            b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main"><w:body/></w:document>',
        )
        for name, body in parts.items():
            z.writestr(name, body)
    return out.getvalue()


def _unpacked(data: bytes) -> bytes:
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(data))
    return b"".join(z.read(n) for n in z.namelist())


@pytest.mark.parametrize(
    "part", ["docProps/Core.xml", "package/services/metadata/core-properties/1f2e.psmdcp"]
)
def test_core_properties_are_emptied_wherever_the_package_keeps_them(part: str) -> None:
    """Only a part named exactly docProps/core.xml was emptied. The package names its
    core properties in _rels/.rels, and part names are case-insensitive: System.IO.
    Packaging writes them under package/services/. The author's name stayed."""
    from app.services.attachment import strip_metadata

    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/'
        'package/2006/relationships/metadata/core-properties" Target="/' + part + '"/>'
        "</Relationships>"
    ).encode()
    core = (
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        b'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Jane Doe'
        b"</dc:creator></cp:coreProperties>"
    )
    out = strip_metadata("a.docx", _package({"_rels/.rels": rels, part: core}))
    assert b"Jane Doe" not in _unpacked(out)


@pytest.mark.parametrize("name", ["image1.jfif", "image1.jpe", "image1.bin"])
def test_a_photo_in_a_document_loses_its_exif_whatever_its_name(name: str) -> None:
    """Pictures were cleaned by their extension (.jpg, .png, …). Word keeps the one the
    picture came with: a .jfif from the browser's "Save image" kept its EXIF."""
    import io

    from PIL import Image

    from app.services.attachment import strip_metadata

    exif = Image.Exif()
    exif[0x010F] = "MakerOfJanesCamera"
    photo = io.BytesIO()
    Image.new("RGB", (8, 8)).save(photo, "JPEG", exif=exif)
    out = strip_metadata("a.docx", _package({f"word/media/{name}": photo.getvalue()}))
    assert b"MakerOfJanesCamera" not in _unpacked(out)


def test_a_drawing_in_a_document_loses_its_metadata_and_profile_paths() -> None:
    """An SVG (Office's icons, an Inkscape drawing) was copied as it was: its <metadata>
    names the author, inkscape:export-filename the Windows account."""
    from app.services.attachment import strip_metadata

    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/'
        b'namespaces/inkscape" inkscape:export-filename="C:\\Users\\jane.doe\\x.png">'
        b"<metadata><creator>Jane Doe</creator></metadata><rect/></svg>"
    )
    out = _unpacked(strip_metadata("a.docx", _package({"word/media/image1.svg": svg})))
    assert b"jane.doe" not in out and b"Jane Doe" not in out and b"<rect/>" in out


@pytest.mark.parametrize(
    "target",
    [
        "https://contoso-my.sharepoint.com/personal/jane_doe_contoso_com/Documents/x.xlsx",
        "https://d.docs.live.net/4f2c9a1b7e3d5a60/Documents/x.xlsx",
    ],
)
def test_a_link_into_someones_onedrive_loses_the_account(target: str) -> None:
    """A workbook linked from OneDrive is addressed by the owner's account; home-share
    paths were scrubbed, these were not."""
    from app.services.attachment import strip_metadata

    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/externalLinkPath" Target="' + target + '" '
        'TargetMode="External"/></Relationships>'
    ).encode()
    out = _unpacked(strip_metadata("a.docx", _package({"word/_rels/settings.xml.rels": rels})))
    assert b"jane_doe" not in out and b"4f2c9a1b7e3d5a60" not in out


def test_a_pdf_page_thumbnail_is_removed() -> None:
    """A page's /Thumb is a picture of the page as it was when the thumbnail was made:
    blacked out since, the text is still in it. It was kept."""
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject

    from app.services.attachment import strip_metadata

    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    thumb = DecodedStreamObject()
    thumb.set_data(b"BEFORE-REDACTION" * 4)
    thumb[NameObject("/Width")] = NumberObject(4)
    thumb[NameObject("/Height")] = NumberObject(4)
    writer.pages[0][NameObject("/Thumb")] = writer._add_object(thumb)
    pdf = io.BytesIO()
    writer.write(pdf)
    out = strip_metadata("a.pdf", pdf.getvalue())
    assert b"/Thumb" not in out and b"BEFORE-REDACTION" not in out


# ── Address headers of CloudFront and the geo headers of CDNs ───────────────


@pytest.mark.parametrize(
    "header",
    [
        "cloudfront-viewer-address",
        "cloudfront-viewer-latitude",
        "cloudfront-viewer-longitude",
        "cloudfront-viewer-city",
        "cloudfront-viewer-postal-code",
        "x-appengine-citylatlong",
        "x-appengine-city",
        "cf-ipcity",
        "cf-iplatitude",
        "x-client-geo-location",
    ],
)
def test_a_cdns_address_or_location_header_is_dropped(header: str) -> None:
    """CloudFront hands the origin the viewer's address and port, and with them the
    city and coordinates; App Engine and Cloudflare the city. None was dropped, though
    "no handler, error report or log line further down can ever see" the address."""
    from app.middleware import _IP_REVEAL_HEADERS

    assert header in _IP_REVEAL_HEADERS


# ── The receipt does not say which language the reporter's browser speaks ───


@pytest.mark.asyncio
async def test_the_receipt_is_stored_in_no_reporters_language(
    client: AsyncClient, db_session: AsyncSession, acting_as
) -> None:
    """The receipt was written in the language of the reporter's browser and kept in
    the case: a Portuguese browser at a German company showed up on the case page as
    "Sua denúncia foi recebida". Each reader now sees it in their own language."""
    from sqlalchemy import select

    from app.models.report import Report
    from app.models.user import AdminRole
    from app.services.report import decrypt_report_fields
    from tests.conftest import wizard_submit
    from tests.test_v210_bug_bounty import _totp_user

    _, act = acting_as
    client.headers["Accept-Language"] = "pt-BR"
    case_number, pin = await wizard_submit(client)
    report = await db_session.scalar(select(Report).where(Report.case_number == case_number))
    await db_session.refresh(report, ["messages"])
    _, stored = decrypt_report_fields(report)
    assert stored[0].startswith("Your report has been received")

    reporter_page = await client.post("/status", data={"case_number": case_number, "pin": pin})
    assert "Sua denúncia foi recebida" in reporter_page.text

    del client.headers["Accept-Language"]
    client.cookies.clear()
    act(await _totp_user(db_session, AdminRole.admin))
    page = (await client.get(f"/admin/reports/{report.id}")).text
    assert "Your report has been received" in page and "Sua denúncia" not in page


@pytest.mark.asyncio
async def test_a_receipt_stored_in_the_reporters_language_reads_in_the_readers(
    db_session: AsyncSession,
) -> None:
    """Cases from before keep the reporter's language in the database; it is not shown."""
    from app.services.encryption import encrypt_field, make_report_fernet
    from app.services.report import create_report, decrypt_report_fields

    report, _ = await create_report(db_session, "financial_fraud", "An older case.")
    await db_session.refresh(report, ["messages"])
    from app.i18n import _load

    pt = _load("pt-br")["system.receipt_message"]
    report.messages[0].content = encrypt_field(make_report_fernet(report.encrypted_dek), pt)
    _, shown = decrypt_report_fields(report, "de")
    assert shown[0] == _load("de")["system.receipt_message"]


# ── Opening the form stores nothing ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_opening_the_form_stores_no_draft(client: AsyncClient) -> None:
    """Every GET of /submit without a cookie stored an empty draft for two hours: 20
    visits, 20 keys (measured). Nothing limits the visits, and Redis refuses every
    write when full: sessions and drafts of real reporters included."""
    from app.redis_client import get_redis

    redis = await get_redis()

    async def drafts() -> int:
        return len([k async for k in redis.scan_iter("submission-session:*")])

    before = await drafts()
    for _ in range(20):
        client.cookies.clear()
        assert (await client.get("/submit")).status_code == 200
    assert await drafts() == before


# ── Deployment and configuration ────────────────────────────────────────────


def test_the_quick_start_stack_mounts_no_code_into_the_app() -> None:
    """docker-compose.yml bind-mounted ./app/static over the image's root-owned copy.
    The app runs as uid 1000, usually the owner of the checkout: it could rewrite the
    JavaScript every reporter loads, for good (measured: appended to site.js from inside
    a read-only, cap-dropped container)."""
    from pathlib import Path

    import yaml

    compose = yaml.safe_load((Path(__file__).parents[1] / "docker-compose.yml").read_text())
    mounts = [str(v) for v in compose["services"]["app"].get("volumes", [])]
    assert not [m for m in mounts if ":/app" in m], mounts


def test_settings_load_from_a_copy_of_the_example_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cp .env.example .env` (Quick Start) and nothing outside a container could read
    the settings: the file also holds Compose's own variables (POSTGRES_USER, …) and
    the settings refused every key they do not know."""
    from pathlib import Path

    from app.config import Settings

    example = (Path(__file__).parents[1] / ".env.example").read_text()
    (tmp_path / ".env").write_text(example + "\nSECRET_KEY=" + "k" * 40 + "\n")
    monkeypatch.delenv("SECRET_KEY")
    Settings(_env_file=tmp_path / ".env")  # type: ignore[call-arg]


def test_the_reset_script_sets_no_key_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """The script put a placeholder SECRET_KEY into its environment, which outranks
    .env: run on the host, --reset-totp sealed the new authenticator secret with the
    placeholder, and the app could not read it."""
    import importlib.util
    import os
    from pathlib import Path

    monkeypatch.delenv("SECRET_KEY")
    path = Path(__file__).parents[1] / "scripts/reset_admin_password.py"
    spec = importlib.util.spec_from_file_location("reset_admin_password", path)
    assert spec and spec.loader
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert "SECRET_KEY" not in os.environ


def test_migrations_use_the_database_the_app_uses(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """migrations/env.py read DATABASE_URL from the environment only. Set in .env, the
    app used it and its start-up `alembic upgrade head` migrated alembic.ini's
    localhost/openwhistle instead."""
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).parents[1]
    shutil.copy(root / "alembic.ini", tmp_path / "alembic.ini")
    (tmp_path / "migrations").symlink_to(root / "migrations")
    (tmp_path / ".env").write_text(f"DATABASE_URL={os.environ['DATABASE_URL']}\n")
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["PYTHONPATH"] = str(root)
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "current"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and "(head)" in result.stdout, result.stderr[-500:]


def test_without_tls_the_role_serves_cookies_a_browser_keeps() -> None:
    """openwhistle_tls_enabled: false serves plain HTTP, and the role left SECURE_COOKIES
    at true: a browser drops a Secure cookie from http://, so no admin stayed signed in
    and no draft survived its first step. APP_PUBLIC_URL said https:// too."""
    from tests.test_ansible_env import _render

    off = _render(openwhistle_tls_enabled=False)
    assert "\nSECURE_COOKIES='false'\n" in off
    assert "\nAPP_PUBLIC_URL='http://ow.example.com'\n" in off
    on = _render()
    assert "\nSECURE_COOKIES='true'\n" in on
    assert "\nAPP_PUBLIC_URL='https://ow.example.com'\n" in on


def test_helm_liveness_does_not_restart_the_app_for_a_dependency() -> None:
    """The liveness probe was /health, which answers 503 while PostgreSQL or Redis is
    down: an outage of either restarted every pod, and each restart sat in back-off
    after the dependency came back."""
    import re
    from pathlib import Path

    deployment = Path(__file__).parents[1] / "charts/openwhistle/templates/deployment.yaml"
    liveness = re.search(r"livenessProbe:\n((?:\s{12,}.*\n)+)", deployment.read_text())
    assert liveness and "/health" not in liveness[1] and "tcpSocket" in liveness[1]


# ── Texts that said more than the code does ─────────────────────────────────


@pytest.mark.asyncio
async def test_an_unbatched_notice_does_not_say_it_is_batched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With NOTIFICATION_BATCH_MINUTES=0 every notice goes out as it happens, and each
    still said "notifications are batched, so their timing does not reveal when a
    report was sent"."""
    from unittest.mock import AsyncMock, patch

    from app.config import settings
    from app.services.notifications import _send_email

    async def body(minutes: int) -> str:
        sent = AsyncMock()
        cfg = settings.model_copy(
            update={"notify_email_to": "c@example.com", "notification_batch_minutes": minutes}
        )
        with patch("aiosmtplib.send", sent):
            await _send_email(["OW-2026-00001"], [], cfg)
        return str(sent.await_args.args[0].get_payload(decode=True).decode())

    assert "batched" not in await body(0)
    assert "batched" in await body(60)


@pytest.mark.asyncio
@pytest.mark.parametrize(("days", "said"), [(1095, True), (30, False)])
async def test_the_retention_page_says_nothing_was_deleted_early_only_when_true(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, days: int, said: bool
) -> None:
    """ "Nothing has been deleted early, and the first deletions are years away" was
    printed for any RETENTION_DAYS; with 30, reports had been deleted for years."""
    from app.config import settings
    from app.models.user import AdminRole
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    monkeypatch.setattr(settings, "retention_enabled", True)
    monkeypatch.setattr(settings, "retention_days", days)
    act(await _totp_user(db_session, AdminRole.admin))
    page = (await client.get("/admin/retention")).text
    assert ("nothing has been deleted early" in page) is said


# ── An enrolled authenticator is not shown again ─────────────────────────────


@pytest.mark.asyncio
async def test_a_second_setup_link_shows_nothing_once_the_authenticator_is_enrolled(
    client: AsyncClient, db_session: AsyncSession, no_csrf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sign-ins before enrolment give two setup links. After enrolling with the
    first, the second still showed the secret now in use, for its ten minutes, and
    could start a session of its own with a fresh code."""
    import pyotp

    from app.config import settings
    from app.redis_client import get_redis
    from app.services import auth as auth_service
    from app.services.users import create_user

    monkeypatch.setattr(settings, "demo_mode", False)
    user, _ = await create_user(db_session, f"enrol-{secrets.token_hex(3)}", "TestPassword123!")
    user.must_change_password = False
    await db_session.commit()
    redis = await get_redis()
    first, second = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    for token in (first, second):
        await auth_service.store_totp_setup_pending(redis, token, str(user.id))

    code = pyotp.TOTP(user.totp_secret).now()
    resp = await client.post(
        "/admin/mfa/setup", data={"temp_token": first, "totp_code": code}, follow_redirects=False
    )
    assert resp.status_code in (302, 303)
    client.cookies.clear()

    client.cookies.set("ow-mfa-setup", second)
    page = await client.get("/admin/mfa/setup", follow_redirects=False)
    assert user.totp_secret not in page.text and page.status_code in (302, 303)

    import time

    later = pyotp.TOTP(user.totp_secret).at(int(time.time()) + 30)
    resp = await client.post(
        "/admin/mfa/setup", data={"temp_token": second, "totp_code": later}, follow_redirects=False
    )
    assert "ow_session" not in resp.cookies


# ── The server checks what the category and location forms check ────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "form"),
    [
        ("categories", {"slug": "blank_en", "label_en": "   ", "label_de": "Etwas"}),
        ("categories", {"slug": "blank_de", "label_en": "Something", "label_de": "  "}),
        ("categories", {"slug": "Not A/Slug!", "label_en": "Something", "label_de": "Etwas"}),
        ("locations", {"name": "   ", "code": "BLANKNAME"}),
        ("locations", {"name": "Somewhere", "code": "NOT A CODE"}),
    ],
)
async def test_a_category_or_location_without_a_name_is_refused(
    acting_as, db_session: AsyncSession, kind: str, form: dict[str, str]
) -> None:
    """The forms require a name and a slug or code of letters, digits and _; the browser
    checked, the server stripped and stored: a name of spaces became an empty option
    in the reporting form."""
    from sqlalchemy import func, select

    from app.models.category import ReportCategory
    from app.models.location import Location
    from app.models.user import AdminRole
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    model = ReportCategory if kind == "categories" else Location
    before = await db_session.scalar(select(func.count()).select_from(model))
    resp = await client.post(f"/admin/{kind}", data=form, follow_redirects=False)
    assert resp.status_code in (400, 422)
    assert await db_session.scalar(select(func.count()).select_from(model)) == before


@pytest.mark.asyncio
async def test_a_category_without_a_german_label_shows_the_english_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The reporting form read label_de directly; label_for falls back to English."""
    from app.models.category import ReportCategory
    from app.services.report import default_org_id

    tag = secrets.token_hex(3)
    db_session.add(
        ReportCategory(
            slug=f"no_de_{tag}",
            label_en=f"Only English {tag}",
            label_de="",
            org_id=await default_org_id(db_session),
        )
    )
    await db_session.commit()
    client.cookies.set("ow-lang", "de")
    from tests.conftest import _wizard_get_csrf, _wizard_skip_location_if_needed

    page = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(page.text),
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    text, _ = await _wizard_skip_location_if_needed(client, resp.text)
    assert f"Only English {tag}" in text


@pytest.mark.asyncio
async def test_the_room_check_counts_what_a_draft_takes_in_redis(client: AsyncClient) -> None:
    """The check before storing attachments counted one base64 (4/3 of the files), the
    draft holds two (the files in the JSON, the sealed draft again): measured 14.0 MB
    counted, 18.6 MB stored for a 10 MB file."""
    import base64
    import os

    from app.api.reports import _draft_bytes, _new_draft_id, _save_submission, _submission_key
    from app.redis_client import get_redis

    redis = await get_redis()
    raw = os.urandom(10 * 1024 * 1024)
    data = base64.b64encode(raw).decode()
    state = {"file_data": [{"filename": "a.pdf", "content_type": "application/pdf", "data": data}]}
    draft = _new_draft_id()
    await _save_submission(redis, draft, state)
    stored = await redis.strlen(_submission_key(draft))
    await redis.delete(_submission_key(draft))
    assert _draft_bytes(len(raw)) >= stored * 0.99, (len(raw), stored)


@pytest.mark.asyncio
async def test_the_retention_period_reads_in_the_admins_number_format(
    acting_as, db_session: AsyncSession
) -> None:
    """German read "(3.0 Jahre)": the one number on the page not written the locale's way."""
    from app.models.user import AdminRole
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    client.cookies.set("ow-lang", "de")
    assert "(3,0 Jahre)" in (await client.get("/admin/retention")).text


def test_no_template_groups_digits_the_english_way() -> None:
    """The capped-search notice wrote its limit with Python's "," grouping: "5,000" in a
    German page, where format_count writes 5.000."""
    from pathlib import Path

    templates = Path(__file__).parents[1] / "app/templates"
    offenders = [p.name for p in templates.rglob("*.html") if "'{:,}'" in p.read_text()]
    assert not offenders


@pytest.mark.parametrize(
    ("lang", "term"),
    [
        ("en", "acknowledgement"),
        ("de", "eingangsbestätigung"),
        ("fr", "accusé de réception"),
        ("es", "acuse de recibo"),
        ("pt-br", "confirmação"),
    ],
)
def test_the_success_page_counts_the_three_months_from_the_acknowledgement(
    lang: str, term: str
) -> None:
    """docs-tech/i18n-review.md: "3 months counted from the acknowledgement, not from
    submission". German and French said "within 3 months" and nothing more."""
    from app.i18n import _load

    assert _load(lang)["success.next.body.html"].casefold().count(term) == 2


@pytest.mark.asyncio
async def test_a_french_reporter_reads_the_built_in_categories_in_french(
    client: AsyncClient,
) -> None:
    """Only label_en and label_de are stored; the French, Spanish and Portuguese labels
    of the built-in categories sat in the locales, read by nothing: the form said
    "Financial Fraud" to a French reporter."""
    from tests.conftest import _wizard_get_csrf, _wizard_skip_location_if_needed

    client.cookies.set("ow-lang", "fr")
    page = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={
            "csrf_token": _wizard_get_csrf(page.text),
            "step": "1",
            "action": "next",
            "submission_mode": "anonymous",
        },
    )
    text, _ = await _wizard_skip_location_if_needed(client, resp.text)
    assert "Fraude financière" in text and "Financial Fraud" not in text
