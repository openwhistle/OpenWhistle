"""Defects found by the v2.2.1 bug bounty, each reproduced before it was fixed."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_v210_bug_bounty import _totp_user, acting_as, no_csrf  # noqa: F401

# ── Four eyes: a reset password is a chosen password ────────────────────────


@pytest.mark.asyncio
async def test_a_superadmin_who_reset_an_account_is_not_its_second_pair_of_eyes(
    acting_as,  # noqa: F811
    db_session: AsyncSession,
) -> None:
    """reset-totp shows the superadmin the account's new temporary password, so they can
    sign in as it before its holder does, enrol their own authenticator and confirm their
    own deletion request. Only creating an account counted as choosing its password."""
    from app.models.user import AdminRole
    from app.services.report import create_report

    client, act = acting_as
    superadmin = await _totp_user(db_session, AdminRole.superadmin)
    other = await _totp_user(db_session, AdminRole.admin)
    report, _ = await create_report(db_session, "financial_fraud", "Delete with one pair of eyes.")

    act(superadmin)
    reset = await client.post(f"/admin/users/{other.id}/reset-totp")
    assert reset.status_code == 200
    await client.post(f"/admin/reports/{report.id}/request-delete")
    act(other)
    resp = await client.post(f"/admin/reports/{report.id}/confirm-delete", follow_redirects=False)
    assert resp.status_code == 409


# ── Retention: a period that deletes everything is not a period ─────────────


@pytest.mark.parametrize("days", [0, -1])
def test_a_retention_period_below_one_day_is_refused(days: int) -> None:
    """RETENTION_DAYS=-1 put the cutoff in the future: the 03:00 job deleted every
    closed report, and the setting validated."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(retention_days=days)


# ── Proxy headers that carry the whistleblower's address ─────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    [
        "X-Original-Forwarded-For",  # ingress-nginx, in front of the Helm chart
        "Fastly-Client-IP",
        "X-Envoy-External-Address",
        "X-Azure-ClientIP",
        "X-Azure-SocketIP",
        "CF-Connecting-IPv6",
        "X-Appengine-User-IP",
    ],
)
async def test_every_known_address_header_is_noted_and_stripped(client, header: str) -> None:  # type: ignore[no-untyped-def]
    """Seven names were stripped; a proxy that writes another one passed the
    address to every handler, and the operator's warning never fired."""
    from fastapi import Request

    from app.main import app
    from app.middleware import check_ip_warning, clear_ip_warning

    seen: dict[str, str | None] = {}

    @app.get("/__probe_headers")
    async def probe(request: Request) -> dict[str, str]:
        seen["value"] = request.headers.get(header)
        return {}

    try:
        await clear_ip_warning()
        await client.get("/__probe_headers", headers={header: "203.0.113.7"})
    finally:
        app.router.routes.pop()
    assert seen["value"] is None
    assert await check_ip_warning()


# ── An unhandled error keeps the security headers ────────────────────────────


@pytest.mark.asyncio
async def test_an_unhandled_error_is_answered_with_the_security_headers() -> None:
    """Starlette's ServerErrorMiddleware sits outside every added middleware: a 500
    went out without no-store, the CSP and X-Frame-Options."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    @app.get("/__probe_boom")
    async def boom() -> None:
        raise RuntimeError("probe")

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/__probe_boom")
    finally:
        app.router.routes.pop()
    assert resp.status_code == 500
    assert resp.headers.get("cache-control") == "no-store"
    assert "default-src" in resp.headers.get("content-security-policy", "")
    assert resp.headers.get("x-frame-options") == "DENY"


# ── An Office file inside an Office file ─────────────────────────────────────


def _zip(parts: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return buf.getvalue()


_CORE = (
    b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
    b'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    b"<dc:creator>Jane Doe</dc:creator></cp:coreProperties>"
)


def test_an_embedded_workbook_is_cleaned_too() -> None:
    """A chart in a Word file is an .xlsx in word/embeddings/; it was copied as it
    was, with its author."""
    import io
    import zipfile

    from app.services.attachment import strip_metadata

    inner = _zip({"[Content_Types].xml": b"<Types/>", "docProps/core.xml": _CORE})
    outer = _zip(
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<w:document/>",
            "word/embeddings/Microsoft_Excel_Worksheet.xlsx": inner,
        }
    )
    clean = zipfile.ZipFile(io.BytesIO(strip_metadata("a.docx", outer)))
    embedded = clean.read("word/embeddings/Microsoft_Excel_Worksheet.xlsx")
    assert b"Jane Doe" not in zipfile.ZipFile(io.BytesIO(embedded)).read("docProps/core.xml")


@pytest.mark.parametrize("name", ["oleObject1.bin", "Presentation1.pptx", "Drawing1.vsdx"])
def test_an_embedded_object_nothing_here_can_clean_is_refused(name: str) -> None:
    from app.services.attachment import MetadataError, strip_metadata

    outer = _zip({"word/document.xml": b"<w:document/>", f"word/embeddings/{name}": b"x"})
    with pytest.raises(MetadataError):
        strip_metadata("a.docx", outer)


# ── The file type comes from the name, not from the browser ──────────────────


@pytest.mark.parametrize(
    "declared", ["application/vnd.ms-excel", "application/octet-stream", "text/x-csv"]
)
@pytest.mark.asyncio
async def test_a_csv_is_accepted_whatever_type_the_browser_declares(declared: str) -> None:
    """Windows with Excel installed sends a .csv as application/vnd.ms-excel; the
    upload page said CSV was allowed and the upload was refused."""
    import io

    from fastapi import UploadFile
    from starlette.datastructures import Headers

    from app.services.attachment import read_upload_files

    upload = UploadFile(
        io.BytesIO(b"a,b\n1,2\n"), filename="a.csv", headers=Headers({"content-type": declared})
    )
    files, error = await read_upload_files([upload])
    assert error is None
    assert files == [("a.csv", "text/csv", b"a,b\n1,2\n")]


def test_the_stored_type_is_the_extensions_not_the_declared_one() -> None:
    from app.services.attachment import content_type_for

    assert content_type_for("notes.txt") == "text/plain"
    assert content_type_for("scan.PDF") == "application/pdf"


def test_a_package_inside_an_embedded_package_is_refused() -> None:
    """One level only: a zip that contains itself would recurse until it ran out of stack."""
    from app.services.attachment import MetadataError, strip_metadata

    inner = _zip({"word/embeddings/deeper.docx": _zip({"word/document.xml": b"<w:document/>"})})
    outer = _zip({"word/document.xml": b"<w:document/>", "word/embeddings/inner.docx": inner})
    with pytest.raises(MetadataError):
        strip_metadata("a.docx", outer)


# ── A wrong PIN costs the same whether the case exists or not ────────────────


@pytest.mark.asyncio
async def test_a_wrong_pin_reads_no_message_and_no_attachment(db_session: AsyncSession) -> None:
    """Messages and attachments, bytes included, were loaded before the PIN was
    checked: 276 ms against 207 ms for an unknown case number, with 5 x 10 MB."""
    from sqlalchemy import event

    from app.services.report import create_report, get_report_by_credentials

    report, pin = await create_report(db_session, "financial_fraud", "Timing probe report text.")
    await db_session.commit()
    statements: list[str] = []
    engine = db_session.bind.sync_engine  # type: ignore[union-attr]

    def record(conn, cursor, statement, *args) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert await get_report_by_credentials(db_session, report.case_number, "wrong") is None
        wrong = list(statements)
        found = await get_report_by_credentials(db_session, report.case_number, pin)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert found is not None and found.id == report.id
    assert not any("attachments" in s or "report_messages" in s for s in wrong), wrong


# ── A Fernet token carries no time ───────────────────────────────────────────


def _token_time(token: str | bytes) -> int:
    import base64
    import struct

    raw = base64.urlsafe_b64decode(token if isinstance(token, bytes) else token.encode())
    return int(struct.unpack(">Q", raw[1:9])[0])


@pytest.mark.asyncio
async def test_no_token_written_for_a_report_carries_its_time(db_session: AsyncSession) -> None:
    """The submission was stored as its day, and every Fernet token written with it
    held the exact second, readable from a dump without any key."""
    from sqlalchemy import text

    from app.services.attachment import create_attachments
    from app.services.crypto import encrypt
    from app.services.report import add_whistleblower_message, create_report

    report, _ = await create_report(
        db_session, "financial_fraud", "Token time probe.", confidential_name_enc=encrypt("J")
    )
    await add_whistleblower_message(db_session, report, "A later message.")
    await create_attachments(db_session, report, [("a.txt", "text/plain", b"evidence")])
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT r.encrypted_dek, r.description, r.confidential_name, m.content,"
                " a.filename, a.data FROM reports r JOIN report_messages m ON m.report_id = r.id"
                " JOIN attachments a ON a.report_id = r.id WHERE r.id = :i"
            ),
            {"i": report.id},
        )
    ).all()
    assert rows
    times = {_token_time(value) for row in rows for value in row}
    assert times == {0}


def test_no_code_makes_a_fernet_token_but_seal() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).parents[1] / "app"
    calls = [
        f"{p.relative_to(root)}:{n}"
        for p in root.rglob("*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"\.(encrypt|rotate)\(", line)
    ]
    assert not calls, calls


@pytest.mark.asyncio
async def test_migration_013_reseals_the_tokens_of_existing_reports(throwaway_db: AsyncSession) -> None:
    """Reports written before 2.2.1 hold tokens with their second; the upgrade takes it out
    and every value still decrypts to what it was."""
    import os
    import subprocess

    from sqlalchemy import text

    from app.config import settings
    from app.services import crypto
    from app.services.attachment import create_attachments
    from app.services.encryption import decrypt_field, make_mek_fernet, make_report_fernet
    from app.services.report import add_whistleblower_message, create_report

    def alembic(*args: str) -> None:
        run = subprocess.run(  # noqa: S603
            ["alembic", *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "DATABASE_URL": settings.database_url},
        )
        assert run.returncode == 0, run.stderr

    report, _ = await create_report(
        throwaway_db, "financial_fraud", "Old report.", confidential_name_enc=crypto.encrypt("J")
    )
    await add_whistleblower_message(throwaway_db, report, "Old message.")
    await create_attachments(throwaway_db, report, [("a.txt", "text/plain", b"evidence")])
    await throwaway_db.commit()
    # Make them what 2.2.0 wrote: tokens that carry the time they were made.
    mek, root = make_mek_fernet(), crypto._make_fernet()
    dek = mek.decrypt(report.encrypted_dek.encode())
    fernet = make_report_fernet(report.encrypted_dek)
    old = {
        "dek": mek.encrypt(dek).decode(),
        "description": fernet.encrypt(b"Old report.").decode(),
        "name": root.encrypt(b"J").decode(),
        "message": fernet.encrypt(b"Old message.").decode(),
        "filename": fernet.encrypt(b"a.txt").decode(),
        "data": fernet.encrypt(b"evidence"),
    }
    for sql in (
        "UPDATE reports SET encrypted_dek = :dek, description = :description,"
        " confidential_name = :name WHERE id = :r",
        "UPDATE report_messages SET content = :message WHERE report_id = :r",
        "UPDATE attachments SET filename = :filename, data = :data WHERE report_id = :r",
    ):
        await throwaway_db.execute(text(sql), {**old, "r": report.id})
    await throwaway_db.commit()

    alembic("downgrade", "c9e4a8b2d009")
    alembic("upgrade", "head")

    row = (
        await throwaway_db.execute(
            text(
                "SELECT r.encrypted_dek, r.description, r.confidential_name, a.filename, a.data"
                " FROM reports r JOIN attachments a ON a.report_id = r.id WHERE r.id = :r"
            ),
            {"r": report.id},
        )
    ).one()
    messages = (
        await throwaway_db.execute(
            text("SELECT content FROM report_messages WHERE report_id = :r"), {"r": report.id}
        )
    ).scalars().all()
    assert {_token_time(v) for v in (*row, *messages)} == {0}
    fernet = make_report_fernet(row.encrypted_dek)
    assert decrypt_field(fernet, row.description) == "Old report."
    assert crypto.decrypt(row.confidential_name) == "J"
    assert "Old message." in {decrypt_field(fernet, m) for m in messages}
    assert fernet.decrypt(bytes(row.data)) == b"evidence"
