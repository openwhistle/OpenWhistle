"""Tests for file attachment upload, validation, and download."""

from __future__ import annotations

import io
import re

import pytest

from app.services.attachment import (
    MAX_ATTACHMENTS,
    MAX_SIZE_BYTES,
    format_size,
    sanitize_filename,
    validate_file,
)

# ─── sanitize_filename ────────────────────────────────────────────────────────


def test_sanitize_plain_filename() -> None:
    assert sanitize_filename("report.pdf") == "report.pdf"


def test_sanitize_strips_directory_traversal() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("../secret.txt") == "secret.txt"


def test_sanitize_replaces_forbidden_chars() -> None:
    name = sanitize_filename('bad<>:"/\\|?*name.pdf')
    assert "<" not in name
    assert "/" not in name
    assert "\\" not in name


def test_sanitize_null_bytes() -> None:
    name = sanitize_filename("file\x00name.pdf")
    assert "\x00" not in name


def test_sanitize_empty_name_returns_fallback() -> None:
    assert sanitize_filename("") == "attachment"
    assert sanitize_filename("...") == "attachment"


def test_sanitize_preserves_extension() -> None:
    name = sanitize_filename("evidence.docx")
    assert name.endswith(".docx")


def test_sanitize_truncates_long_name() -> None:
    long_name = "a" * 300 + ".pdf"
    result = sanitize_filename(long_name)
    assert len(result) <= 255
    assert result.endswith(".pdf")


# ─── validate_file ────────────────────────────────────────────────────────────


def test_validate_valid_pdf() -> None:
    assert validate_file("report.pdf", "application/pdf", 1024) is None


def test_validate_valid_jpeg() -> None:
    assert validate_file("screenshot.jpg", "image/jpeg", 512 * 1024) is None


def test_validate_valid_png() -> None:
    assert validate_file("evidence.png", "image/png", 2 * 1024 * 1024) is None


def test_validate_valid_docx() -> None:
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert validate_file("notes.docx", mime, 100_000) is None


def test_validate_valid_txt() -> None:
    assert validate_file("log.txt", "text/plain", 4096) is None


def test_validate_file_too_large() -> None:
    error = validate_file("big.pdf", "application/pdf", MAX_SIZE_BYTES + 1)
    assert error is not None
    assert "too large" in error.lower()


def test_validate_file_at_exact_limit_is_valid() -> None:
    assert validate_file("ok.pdf", "application/pdf", MAX_SIZE_BYTES) is None


def test_validate_disallowed_extension() -> None:
    error = validate_file("script.exe", "application/octet-stream", 100)
    assert error is not None
    assert "unsupported file extension" in error.lower()


def test_validate_disallowed_mime_type() -> None:
    error = validate_file("shell.sh", "text/x-sh", 100)
    assert error is not None


def test_validate_mime_type_with_charset_suffix() -> None:
    # Browser may send 'text/plain; charset=utf-8'
    assert validate_file("notes.txt", "text/plain; charset=utf-8", 100) is None


def test_validate_svg_is_blocked() -> None:
    # SVG can contain scripts — must not be allowed
    error = validate_file("icon.svg", "image/svg+xml", 100)
    assert error is not None


# ─── format_size ──────────────────────────────────────────────────────────────


def test_format_size_bytes() -> None:
    assert format_size(512) == "512 B"


def test_format_size_kilobytes() -> None:
    assert "KB" in format_size(2048)


def test_format_size_megabytes() -> None:
    result = format_size(3 * 1024 * 1024)
    assert "MB" in result
    assert "3.0" in result


# ─── read_upload_files (integration — mocked UploadFile) ─────────────────────


@pytest.mark.asyncio
async def test_read_empty_files_list_returns_empty() -> None:
    from app.services.attachment import read_upload_files

    result, error = await read_upload_files([])
    assert result == []
    assert error is None


@pytest.mark.asyncio
async def test_read_skips_empty_filename_parts() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.attachment import read_upload_files

    empty_upload = MagicMock()
    empty_upload.filename = ""
    empty_upload.read = AsyncMock(return_value=b"")

    result, error = await read_upload_files([empty_upload])
    assert result == []
    assert error is None


@pytest.mark.asyncio
async def test_read_valid_file_returns_tuple() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.attachment import read_upload_files

    upload = MagicMock()
    upload.filename = "evidence.pdf"
    upload.content_type = "application/pdf"
    upload.read = AsyncMock(return_value=b"%PDF-1.4 fake content here")

    result, error = await read_upload_files([upload])
    assert error is None
    assert len(result) == 1
    name, ct, data = result[0]
    assert name == "evidence.pdf"
    assert ct == "application/pdf"
    assert data == b"%PDF-1.4 fake content here"


@pytest.mark.asyncio
async def test_read_too_many_files_returns_error() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.attachment import read_upload_files

    uploads = []
    for i in range(MAX_ATTACHMENTS + 1):
        u = MagicMock()
        u.filename = f"file{i}.pdf"
        u.content_type = "application/pdf"
        u.read = AsyncMock(return_value=b"X" * 100)
        uploads.append(u)

    result, error = await read_upload_files(uploads)
    assert error is not None
    assert "too many" in error.lower()


@pytest.mark.asyncio
async def test_read_oversized_file_returns_error() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.attachment import read_upload_files

    upload = MagicMock()
    upload.filename = "huge.pdf"
    upload.content_type = "application/pdf"
    upload.read = AsyncMock(return_value=b"X" * (MAX_SIZE_BYTES + 1))

    result, error = await read_upload_files([upload])
    assert error is not None
    assert "too large" in error.lower()


@pytest.mark.asyncio
async def test_read_disallowed_type_returns_error() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.services.attachment import read_upload_files

    upload = MagicMock()
    upload.filename = "malware.exe"
    upload.content_type = "application/octet-stream"
    upload.read = AsyncMock(return_value=b"MZ" + b"\x00" * 100)

    result, error = await read_upload_files([upload])
    assert error is not None


# ─── integration tests (require live DB) ──────────────────────────────────────


def _get_csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


def _detect_step(text: str) -> int:
    m = re.search(r'name="step" value="(\d+)"', text)
    return int(m.group(1)) if m else 1


async def _walk_to_step5(client: object, category: str = "financial_fraud") -> tuple[object, str]:
    """Walk the wizard through steps 1-(2)-3-4 and return (response_at_step5, csrf_for_step5).

    Handles both with-locations and without-locations flows.
    The returned response is the step-5 (attachments) page ready for file upload.
    """
    from httpx import AsyncClient

    ac: AsyncClient = client  # type: ignore[assignment]

    # Step 1: mode selection
    get_resp = await ac.get("/submit")
    csrf = _get_csrf(get_resp.text)
    resp = await ac.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": "anonymous",
    })

    # Step 2 (location — conditional): skip if present by posting with empty location_id
    if _detect_step(resp.text) == 2:
        csrf = _get_csrf(resp.text)
        resp = await ac.post("/submit", data={
            "csrf_token": csrf,
            "step": "2",
            "action": "next",
            "location_id": "",
        })

    # Step 3: category
    csrf = _get_csrf(resp.text)
    resp = await ac.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_detect_step(resp.text)),
        "action": "next",
        "category": category,
    })

    # Step 4: description
    csrf = _get_csrf(resp.text)
    resp = await ac.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_detect_step(resp.text)),
        "action": "next",
        "description": "Testing file upload feature with a PDF attachment.",
    })

    # Now on step 5 (attachments) — return ready for file upload
    csrf = _get_csrf(resp.text)
    return resp, csrf


@pytest.mark.asyncio
@pytest.mark.integration
async def test_submit_with_pdf_attachment(client: object) -> None:
    """Submit form with a PDF attachment; success page shows the filename."""
    from httpx import AsyncClient

    ac: AsyncClient = client  # type: ignore[assignment]

    # Walk steps 1-4, arrive at step 5 (attachments)
    resp5, csrf = await _walk_to_step5(ac)
    step5_num = _detect_step(resp5.text)  # type: ignore[attr-defined]

    pdf_content = b"%PDF-1.4 minimal fake pdf content for testing"
    resp = await ac.post(
        "/submit",
        data={"csrf_token": csrf, "step": str(step5_num), "action": "next"},
        files={"files": ("evidence.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert resp.status_code == 200

    # Now on step 6 (review) — submit final
    csrf6 = _get_csrf(resp.text)
    step6_num = _detect_step(resp.text)
    final_resp = await ac.post("/submit", data={
        "csrf_token": csrf6,
        "step": str(step6_num),
        "action": "next",
    })
    assert final_resp.status_code == 200
    assert "evidence.pdf" in final_resp.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_submit_without_attachment_still_works(client: object) -> None:
    """Submitting without any file must still succeed."""
    from conftest import wizard_submit
    from httpx import AsyncClient

    ac: AsyncClient = client  # type: ignore[assignment]

    case_number, pin = await wizard_submit(
        ac,
        category="financial_fraud",
        description="No attachment is attached to this test report.",
    )
    assert case_number.startswith("OW-") or case_number != ""


@pytest.mark.asyncio
@pytest.mark.integration
async def test_submit_oversized_file_returns_error(client: object) -> None:
    """Uploading a file over 10 MB must show a validation error."""
    from httpx import AsyncClient

    ac: AsyncClient = client  # type: ignore[assignment]

    # Walk steps 1-4, arrive at step 5 (attachments)
    resp5, csrf = await _walk_to_step5(ac)
    step5_num = _detect_step(resp5.text)  # type: ignore[attr-defined]

    oversized = b"X" * (MAX_SIZE_BYTES + 1)
    resp = await ac.post(
        "/submit",
        data={"csrf_token": csrf, "step": str(step5_num), "action": "next"},
        files={"files": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
    )
    assert resp.status_code == 200
    assert "too large" in resp.text.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_can_download_attachment(client: object, db_session: object) -> None:
    """Admin must be able to download an attachment from a report."""
    import uuid

    import pyotp
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.attachment import Attachment
    from app.models.report import Report, ReportStatus
    from app.models.user import AdminUser
    from app.services.auth import hash_password, hash_pin

    ac: AsyncClient = client  # type: ignore[assignment]
    db: AsyncSession = db_session  # type: ignore[assignment]

    # Create a dedicated admin user for this test
    totp_secret = "JBSWY3DPEHPK3PXP"
    admin = AdminUser(
        id=uuid.uuid4(),
        username=f"dl_admin_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("dl_test_pass_123"),
        totp_secret=totp_secret,
        totp_enabled=True,
    )
    db.add(admin)

    report = Report(
        id=uuid.uuid4(),
        case_number=f"OW-TEST-{uuid.uuid4().hex[:6].upper()}",
        pin_hash=hash_pin("test-pin-value"),
        category="other",
        description="Test report for attachment download.",
        status=ReportStatus.received,
    )
    db.add(report)

    attachment = Attachment(
        id=uuid.uuid4(),
        report_id=report.id,
        filename="test_evidence.pdf",
        content_type="application/pdf",
        size=4,
        data=b"TEST",
    )
    db.add(attachment)
    await db.commit()

    # Step 1: GET /admin/login for CSRF cookie
    get_resp = await ac.get("/admin/login")
    csrf_token = get_resp.cookies.get("ow_csrf")

    # Step 2: POST credentials
    login_resp = await ac.post(
        "/admin/login",
        data={"username": admin.username, "password": "dl_test_pass_123", "csrf_token": csrf_token},
    )

    # Step 3: Extract temp_token and CSRF from MFA form
    temp_m = re.search(r'name="temp_token" value="([^"]+)"', login_resp.text)
    temp_token = temp_m.group(1) if temp_m else ""
    csrf_m = re.search(r'name="csrf_token" value="([^"]+)"', login_resp.text)
    mfa_csrf = csrf_m.group(1) if csrf_m else ""

    # Step 4: POST MFA with real TOTP code
    totp_code = pyotp.TOTP(totp_secret).now()
    await ac.post(
        "/admin/login/mfa",
        data={"csrf_token": mfa_csrf, "temp_token": temp_token, "totp_code": totp_code},
    )

    dl_resp = await ac.get(f"/admin/reports/{report.id}/attachments/{attachment.id}")
    assert dl_resp.status_code == 200
    assert dl_resp.content == b"TEST"
    assert "attachment" in dl_resp.headers.get("content-disposition", "").lower()
