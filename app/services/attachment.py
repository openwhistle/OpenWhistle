"""Attachment service — file validation, storage, and retrieval."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment

MAX_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS: int = 5

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/msword",
    "application/vnd.ms-excel",
})

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".jpg", ".jpeg",
    ".png", ".gif", ".webp",
    ".txt", ".csv",
    ".docx", ".doc",
    ".xlsx", ".xls",
})


def sanitize_filename(filename: str) -> str:
    """Return a safe basename with dangerous characters replaced."""
    name = Path(filename).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    if not name:
        return "attachment"
    suffix = Path(name).suffix.lower()
    stem = name[: len(name) - len(suffix)]
    max_stem = 240 - len(suffix)
    if len(stem) > max_stem:
        name = stem[:max_stem] + suffix
    return name


def validate_file(filename: str, content_type: str, size: int) -> str | None:
    """Return an error string if the file is invalid, or None if it's acceptable."""
    if size > MAX_SIZE_BYTES:
        mb = size / (1024 * 1024)
        return f"'{filename}' is too large ({mb:.1f} MB). Maximum 10 MB per file."

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"'{filename}' has an unsupported file extension. Allowed: PDF, JPEG, PNG, GIF, WebP, TXT, CSV, DOCX, XLSX."

    # Normalise declared MIME type (strip charset suffixes like text/plain; charset=utf-8)
    declared_type = content_type.split(";")[0].strip().lower()
    if declared_type not in ALLOWED_MIME_TYPES:
        return f"'{filename}' has an unsupported file type ({declared_type}). Allowed: PDF, images, text, Word, Excel."

    return None


async def read_upload_files(
    files: list[UploadFile],
) -> tuple[list[tuple[str, str, bytes]], str | None]:
    """Read and validate uploaded files.

    Returns ([(filename, content_type, data), ...], error_message_or_None).
    Silently skips empty file parts (browser sends empty part when no file selected).
    """
    result: list[tuple[str, str, bytes]] = []

    for upload in files:
        if not upload.filename or upload.filename.strip() == "":
            continue

        data = await upload.read()
        if len(data) == 0:
            continue

        name = sanitize_filename(upload.filename)
        content_type = upload.content_type or "application/octet-stream"
        error = validate_file(name, content_type, len(data))
        if error:
            return [], error

        result.append((name, content_type, data))

    if len(result) > MAX_ATTACHMENTS:
        return [], f"Too many files. Maximum {MAX_ATTACHMENTS} attachments per report."

    return result, None


async def create_attachments(
    db: AsyncSession,
    report_id: uuid.UUID,
    file_tuples: list[tuple[str, str, bytes]],
) -> list[Attachment]:
    """Persist a list of (filename, content_type, data) tuples as Attachment rows."""
    attachments = []
    for filename, content_type, data in file_tuples:
        att = Attachment(
            id=uuid.uuid4(),
            report_id=report_id,
            filename=filename,
            content_type=content_type,
            size=len(data),
            data=data,
        )
        db.add(att)
        attachments.append(att)
    if attachments:
        await db.commit()
    return attachments


async def get_attachment_by_id(
    db: AsyncSession, attachment_id: uuid.UUID
) -> Attachment | None:
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    return result.scalar_one_or_none()


def format_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"
