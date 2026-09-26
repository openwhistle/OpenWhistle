"""v1.6.0 final-review guards: one test per finding."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_ROOT = Path(__file__).resolve().parent.parent


# --- I7: database errors carry no bound parameters ---------------------------------------


async def test_db_error_log_line_has_no_bound_parameter(caplog: pytest.LogCaptureFixture) -> None:
    from app.database import engine

    case_number = "OW-SECRET-CASE-4711"
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("SELECT CAST(:v AS text), 1 / 0"), {"v": case_number})
        with caplog.at_level(logging.ERROR):
            logging.getLogger("uvicorn.error").error("request failed", exc_info=exc_info.value)
    finally:
        await engine.dispose()
    assert case_number not in str(exc_info.value)
    assert case_number not in caplog.text


def test_every_engine_hides_parameters() -> None:
    offenders = []
    sources = [*_ROOT.glob("app/**/*.py"), *_ROOT.glob("scripts/*.py"), _ROOT / "migrations/env.py"]
    for path in sources:
        source = path.read_text()
        for match in re.finditer(r"(create_async_engine|async_engine_from_config)\(", source):
            depth, i = 1, match.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(source[i], 0)
                i += 1
            if "hide_parameters=True" not in source[match.end():i]:
                line = source[:match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(_ROOT)}:{line}")
    assert offenders == []


# --- I6: the digest is no more precise than the stored day --------------------------------


def test_notification_digest_defaults_to_one_day() -> None:
    from app.config import Settings

    assert Settings.model_fields["notification_batch_minutes"].default == 1440
    compose = (_ROOT / "docker-compose.prod.yml").read_text()
    assert '"${NOTIFICATION_BATCH_MINUTES:-1440}"' in compose
    values = (_ROOT / "charts/openwhistle/values.yaml").read_text()
    assert 'notificationBatchMinutes: "1440"' in values


# --- I2: a key change that leaves existing data unreadable refuses to start ---------------

_KEY_A = "a" * 40
_KEY_B = "b" * 40


async def _seed_report_and_admin(db) -> None:  # type: ignore[no-untyped-def]
    import uuid

    import pyotp

    from app.models.user import AdminUser
    from app.services.report import create_report

    await create_report(db, "corruption", "Written under the key configured at the time.")
    db.add(AdminUser(
        id=uuid.uuid4(), username=f"key-{uuid.uuid4().hex[:8]}", totp_secret=pyotp.random_base32(),
    ))
    await db.commit()


async def test_setting_encryption_key_without_previous_is_detected(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from app.config import settings
    from app.services.encryption import configured_keys_read_existing_data

    monkeypatch.setattr(settings, "encryption_key", "")
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    await _seed_report_and_admin(throwaway_db)
    assert await configured_keys_read_existing_data()

    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    assert not await configured_keys_read_existing_data()
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    assert await configured_keys_read_existing_data()


async def test_removing_encryption_key_is_detected(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from app.config import settings
    from app.services.encryption import configured_keys_read_existing_data

    monkeypatch.setattr(settings, "encryption_key", _KEY_A)
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    await _seed_report_and_admin(throwaway_db)
    monkeypatch.setattr(settings, "encryption_key", "")
    assert not await configured_keys_read_existing_data()


async def test_an_unreadable_totp_secret_alone_is_detected(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """No report yet: the admins' second factor alone must still stop the start."""
    import uuid

    from app.config import settings
    from app.models.user import AdminUser
    from app.services.encryption import configured_keys_read_existing_data

    monkeypatch.setattr(settings, "encryption_key", _KEY_A)
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    throwaway_db.add(
        AdminUser(id=uuid.uuid4(), username="totp-only", totp_secret="JBSWY3DPEHPK3PXP")
    )
    await throwaway_db.commit()
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    assert not await configured_keys_read_existing_data()


async def test_a_database_without_tables_passes_the_key_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.engine import make_url

    from app.config import settings
    from app.services.encryption import configured_keys_read_existing_data

    empty = make_url(settings.database_url).set(database="postgres")
    monkeypatch.setattr(settings, "database_url", empty.render_as_string(hide_password=False))
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    assert await configured_keys_read_existing_data()


async def test_startup_refuses_before_migrating_when_data_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI

    from app.main import lifespan

    with (
        patch("app.services.encryption.configured_keys_read_existing_data",
              new_callable=AsyncMock, return_value=False),
        patch("app.main._run_alembic_upgrade") as upgrade,
        pytest.raises(RuntimeError, match="ENCRYPTION_KEY_PREVIOUS"),
    ):
        async with lifespan(FastAPI()):
            pass
    upgrade.assert_not_called()


async def test_rotation_script_names_the_key_mismatch(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    import importlib.util

    from app.config import settings
    from app.services.encryption import UNREADABLE_DATA_MESSAGE

    await _seed_report_and_admin(throwaway_db)
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    monkeypatch.setattr(settings, "encryption_key_previous", _KEY_A)  # the wrong old key
    spec = importlib.util.spec_from_file_location("rot", _ROOT / "scripts/rotate_encryption_key.py")
    assert spec and spec.loader
    rot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rot)
    assert await rot.main() == 1
    assert UNREADABLE_DATA_MESSAGE in capsys.readouterr().out


# --- I8: content search is POST-only and audited -----------------------------------------


def _csrf_of(client) -> str:  # type: ignore[no-untyped-def]
    return client.cookies.get("ow_csrf") or ""


async def _content_search_rows(db, admin_id):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.services.audit import AuditAction

    return list((await db.execute(select(AuditLog).where(
        AuditLog.admin_id == admin_id, AuditLog.action == AuditAction.CONTENT_SEARCHED,
    ))).scalars())


async def test_content_search_is_audited_with_the_term_encrypted(client, db_session) -> None:  # type: ignore[no-untyped-def]
    import json
    import uuid

    from app.models.user import AdminRole
    from app.services.crypto import decrypt
    from app.services.report import create_report
    from tests.test_v160_privacy import _login

    admin = await _login(client, db_session, AdminRole.admin)
    word = f"Tapir{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, "corruption", f"The ledger names {word}.")
    resp = await client.post("/admin/dashboard", data={"q": word, "csrf_token": _csrf_of(client)})
    assert report.case_number in resp.text
    rows = await _content_search_rows(db_session, admin.id)
    assert len(rows) == 1
    assert word not in (rows[0].detail or "")
    detail = json.loads(rows[0].detail or "{}")
    assert decrypt(detail["term"]) == word and detail["hits"] == 1
    log = await client.get("/admin/audit-log")
    assert word in log.text  # the audit log shows the term to whoever may read it


async def test_a_search_term_in_the_url_is_ignored(client, db_session) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from app.models.user import AdminRole
    from app.services.report import create_report
    from tests.test_v160_privacy import _login

    admin = await _login(client, db_session, AdminRole.admin)
    word = f"Quokka{uuid.uuid4().hex[:6]}"
    await create_report(db_session, "corruption", f"Nothing but {word}.")
    resp = await client.get("/admin/dashboard", params={"q": word})
    assert resp.status_code == 200 and f'value="{word}"' not in resp.text
    assert await _content_search_rows(db_session, admin.id) == []
    refused = await client.post("/admin/dashboard", data={"q": word, "csrf_token": "forged"})
    assert refused.status_code == 403


async def test_search_pagination_posts_the_term_and_never_links_it(client, db_session) -> None:  # type: ignore[no-untyped-def]
    import re
    import uuid

    from app.models.user import AdminRole
    from app.services.report import create_report
    from tests.test_v160_privacy import _login

    await _login(client, db_session, AdminRole.admin)
    word = f"Numbat{uuid.uuid4().hex[:6]}"
    cases = [(await create_report(db_session, "corruption", f"{word} no. {i}"))[0].case_number
             for i in range(12)]
    form = {"q": word, "per_page": "10", "csrf_token": _csrf_of(client)}
    first = await client.post("/admin/dashboard", data=form)
    second = await client.post("/admin/dashboard", data={**form, "page": "2"})
    shown = [c for c in cases if c in first.text] + [c for c in cases if c in second.text]
    assert sorted(shown) == sorted(cases)
    assert not re.search(r'href="[^"]*[?&]q=', first.text)
    nav_form = r'<form method="post"[^>]*class="dash-nav-form">(.*?)</form>'
    forms = re.findall(nav_form, first.text, re.S)
    assert any(f'name="q" value="{word}"' in f and 'name="page" value="2"' in f for f in forms)


async def test_rotation_script_rotates_content_search_terms(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    import importlib.util
    import json
    import uuid

    from cryptography.fernet import InvalidToken
    from sqlalchemy import text as sql

    from app.config import settings
    from app.models.audit import AuditLog
    from app.services import crypto
    from app.services.audit import AuditAction

    row = AuditLog(
        id=uuid.uuid4(), admin_username="x", action=AuditAction.CONTENT_SEARCHED,
        detail=json.dumps({"term": crypto.encrypt("Müller"), "hits": 2}),
    )
    throwaway_db.add(row)
    await throwaway_db.commit()
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    spec = importlib.util.spec_from_file_location("rot", _ROOT / "scripts/rotate_encryption_key.py")
    assert spec and spec.loader
    rot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rot)
    assert await rot.main() == 0
    detail = json.loads(await throwaway_db.scalar(
        sql("SELECT detail FROM audit_log WHERE id = :i"), {"i": row.id}
    ))
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    assert crypto.decrypt(detail["term"]) == "Müller" and detail["hits"] == 2
    monkeypatch.setattr(settings, "encryption_key", settings.secret_key)
    with pytest.raises(InvalidToken):
        crypto.decrypt(detail["term"])


# --- I10: metadata inside Office packages and PDFs ---------------------------------------

_CAMERA = "SecretCamMaker-4711"


def _exif_jpeg() -> bytes:
    import io

    from PIL import Image

    exif = Image.Exif()
    exif[0x010F] = _CAMERA  # Make; GPS sits in the same EXIF block
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, "JPEG", exif=exif.tobytes())
    assert _CAMERA.encode() in out.getvalue()
    return out.getvalue()


@pytest.mark.parametrize(("name", "media"), [("a.docx", "word/media/image1.jpeg"),
                                             ("a.xlsx", "xl/media/image1.JPG")])
def test_photos_inside_office_files_lose_their_exif(name: str, media: str) -> None:
    import io
    import zipfile

    from PIL import Image

    from app.services.attachment import strip_metadata

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(media, _exif_jpeg())
    clean = zipfile.ZipFile(io.BytesIO(strip_metadata(name, buf.getvalue())))
    photo = clean.read(media)
    assert _CAMERA.encode() not in photo
    assert Image.open(io.BytesIO(photo)).size == (8, 8)


def test_pdf_loses_annotation_authors_photo_exif_and_its_file_id() -> None:
    import io

    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        ByteStringObject,
        DictionaryObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    from app.services.attachment import strip_metadata

    base = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(base, "PDF")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(base.getvalue())))
    page = writer.pages[0]
    image = next(iter(page["/Resources"]["/XObject"].values())).get_object()
    image._data = _exif_jpeg()  # a JPEG is embedded as-is, EXIF included
    note = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/Rect"): ArrayObject([NumberObject(0)] * 4),
        NameObject("/T"): TextStringObject("Jane Whistle"),
        NameObject("/M"): TextStringObject("D:20260926101500Z"),
    })
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(note)])
    original_id = ByteStringObject(b"ORIGINAL-FILE-ID")
    writer._ID = ArrayObject([original_id, original_id])
    out = io.BytesIO()
    writer.write(out)
    assert b"Jane Whistle" in out.getvalue() and _CAMERA.encode() in out.getvalue()

    clean = strip_metadata("a.pdf", out.getvalue())
    for leak in (b"Jane Whistle", _CAMERA.encode(), b"D:20260926", b"ORIGINAL-FILE-ID"):
        assert leak not in clean, leak
    reader = PdfReader(io.BytesIO(clean))
    assert reader.trailer["/ID"][0] != original_id
    assert list(reader.pages[0].images)[0].image.size == (8, 8)


# --- M11: setup-token guesses are rate-limited ---------------------------------------------


async def test_setup_token_guesses_lock_setup(  # type: ignore[no-untyped-def]
    client, db_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import select

    from app.config import settings
    from app.models.user import AdminUser
    from app.redis_client import get_redis
    from app.services.rate_limit import _SETUP_TOKEN_FAILURES
    from tests.conftest import setup_token
    from tests.test_v160_security import _csrf, _reset_setup, _restore_setup, _setup_form

    monkeypatch.setattr(settings, "max_login_attempts", 3)
    redis = await get_redis()
    await redis.delete(_SETUP_TOKEN_FAILURES)
    await _reset_setup(db_session)
    try:
        csrf = await _csrf(client, "/setup")
        for _ in range(3):
            wrong = await client.post("/setup", data=_setup_form(csrf, "x" * 40))
            assert wrong.status_code == 403
        form = _setup_form(csrf, await setup_token())
        locked = await client.post("/setup", data=form, follow_redirects=False)
        assert locked.status_code == 429
        assert "Too many wrong setup tokens" in locked.text
        created = await db_session.scalar(
            select(AdminUser).where(AdminUser.username == form["username"])
        )
        assert created is None
    finally:
        await redis.delete(_SETUP_TOKEN_FAILURES)
        await _restore_setup(db_session)


# --- M12: /set-language is CSRF-protected -------------------------------------------------


async def test_set_language_without_csrf_is_refused(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/set-language", data={"lang": "de", "next": "/submit", "csrf_token": "forged"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    page = (await client.get("/submit")).text
    form = page[page.index('action="/set-language"'):]
    assert 'name="csrf_token"' in form[:form.index("</form>")]


# --- M13: the status session and the attempt counter reveal nothing ----------------------


async def test_status_view_does_not_extend_the_session(client, db_session) -> None:  # type: ignore[no-untyped-def]
    from app.redis_client import get_redis
    from app.services.report import create_report

    report, pin = await create_report(db_session, "corruption", "Status session TTL test.")
    await client.get("/status")
    login = await client.post("/status", data={
        "case_number": report.case_number, "pin": pin,
        "csrf_token": client.cookies.get("ow_csrf")}, follow_redirects=False)
    assert login.status_code == 303
    key = f"status-session:{client.cookies.get('ow-status-session')}"
    redis = await get_redis()
    await redis.expire(key, 100)
    assert (await client.get("/status")).status_code == 200
    assert 0 < await redis.ttl(key) <= 100


async def test_attempt_counter_key_holds_no_case_number(client) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from app.redis_client import get_redis

    case = f"OW-2026-{uuid.uuid4().int % 100000:05d}"
    await client.get("/status")
    await client.post("/status", data={
        "case_number": case, "pin": str(uuid.uuid4()), "csrf_token": client.cookies.get("ow_csrf")})
    redis = await get_redis()
    keys = [k.decode() if isinstance(k, bytes) else k
            async for k in redis.scan_iter("openwhistle:wb_ratelimit:*")]
    assert keys and not any(case in k for k in keys)


async def test_reply_rotates_the_session_without_extending_it(client, db_session) -> None:  # type: ignore[no-untyped-def]
    from app.redis_client import get_redis
    from app.services.report import create_report

    report, pin = await create_report(db_session, "corruption", "Reply TTL test.")
    await client.get("/status")
    await client.post("/status", data={
        "case_number": report.case_number, "pin": pin,
        "csrf_token": client.cookies.get("ow_csrf")}, follow_redirects=False)
    old = client.cookies.get("ow-status-session")
    redis = await get_redis()
    await redis.expire(f"status-session:{old}", 100)
    reply = await client.post("/reply", data={
        "content": "One more detail.", "csrf_token": client.cookies.get("ow_csrf")},
        follow_redirects=False)
    assert reply.status_code == 303
    new = client.cookies.get("ow-status-session")
    assert new != old
    assert 0 < await redis.ttl(f"status-session:{new}") <= 100


# --- M25: one fallback for a category without a label ------------------------------------


async def test_an_unlabelled_category_reads_the_same_on_stats_case_page_and_pdf(  # type: ignore[no-untyped-def]
    client, db_session,
) -> None:
    import io
    import uuid

    from pypdf import PdfReader

    from app.models.user import AdminRole
    from app.services.pdf import generate_report_pdf
    from app.services.report import create_report, get_report_by_id
    from tests.test_v160_privacy import _login

    await _login(client, db_session, AdminRole.admin)
    slug = f"gone_{uuid.uuid4().hex[:6]}"
    report, _ = await create_report(db_session, slug, "A report whose category was deleted.")
    expected = slug.replace("_", " ").title()
    assert expected in (await client.get("/admin/stats")).text
    assert expected in (await client.get(f"/admin/reports/{report.id}")).text
    full = await get_report_by_id(db_session, report.id)
    assert full is not None
    text = PdfReader(io.BytesIO(generate_report_pdf(full))).pages[0].extract_text()
    assert expected in text
