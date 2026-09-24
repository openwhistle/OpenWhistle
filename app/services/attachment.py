"""Attachment service — file validation, storage, and retrieval."""

from __future__ import annotations

import io
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.report import Report

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


def content_disposition_attachment(filename: str) -> str:
    """Build a Content-Disposition header value safe for any filename.

    Response headers are latin-1 encoded, so a raw non-Latin-1 filename (CJK,
    Cyrillic, emoji, …) raises UnicodeEncodeError and 500s the download. Emit an
    ASCII-only ``filename`` fallback plus an RFC 5987 ``filename*`` with the full
    UTF-8 name for modern clients.
    """
    ascii_name = filename.encode("ascii", "ignore").decode("ascii").replace('"', "").strip()
    if not ascii_name:
        ascii_name = "attachment"
    utf8_name = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


# Expected leading bytes (magic numbers) per extension, so the declared type /
# extension cannot lie about the actual content (e.g. HTML bytes named .png).
# Text formats (.txt/.csv) have no signature and are intentionally omitted.
_MAGIC_BY_EXT: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),  # RIFF container; the WEBP marker is checked separately
    ".docx": (b"PK\x03\x04",),  # OOXML = zip
    ".xlsx": (b"PK\x03\x04",),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # legacy OLE/CFB
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
}


def _content_matches_ext(ext: str, head: bytes) -> bool:
    """True if the file header matches the signature expected for the extension.

    Extensions with no registered signature (text formats) always pass.
    """
    sigs = _MAGIC_BY_EXT.get(ext)
    if sigs is None:
        return True
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return any(head.startswith(sig) for sig in sigs)


class MetadataError(ValueError):
    """A file whose metadata could not be removed is refused, never stored as-is."""


_OOXML_EMPTY_PARTS: dict[str, bytes] = {
    "docProps/core.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
        b'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        b'xmlns:dcterms="http://purl.org/dc/terms/" '
        b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
    ),
    "docProps/app.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'extended-properties"/>'
    ),
    "docProps/custom.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'custom-properties"/>'
    ),
}


def _strip_image(data: bytes) -> bytes:
    from PIL import Image, ImageOps  # noqa: PLC0415

    with Image.open(io.BytesIO(data)) as img:
        fmt = img.format
        out = io.BytesIO()
        if fmt == "GIF":
            # Keep animation; frames carry no EXIF, only an optional comment.
            img.info.pop("comment", None)
            img.save(out, format="GIF", save_all=True)
            return out.getvalue()
        # Bake the EXIF orientation into the pixels, then copy the pixels alone:
        # EXIF (GPS, camera serial), XMP, ICC and text chunks stay behind.
        upright = ImageOps.exif_transpose(img)
        clean = Image.new(upright.mode, upright.size)
        clean.paste(upright)
        if fmt == "JPEG":
            clean.save(out, format="JPEG", quality=95)
        elif fmt == "PNG":
            clean.save(out, format="PNG", optimize=True)
        elif fmt == "WEBP":
            clean.save(out, format="WEBP", quality=95)
        else:
            raise MetadataError(f"unsupported image format {fmt}")
    return out.getvalue()


def _strip_pdf(data: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415

    # An owner-password-only PDF opens without a password and is written back
    # unencrypted and cleaned; one that needs a user password cannot be read
    # and fails here, which strip_metadata turns into a refusal.
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.metadata = None  # document info: author, creator tool, dates
    writer._root_object.pop("/Metadata", None)  # XMP packet
    # Unlinking is not removing: the XMP stream would still be written as an
    # orphaned object that any forensic tool can read.
    writer.compress_identical_objects(remove_identicals=False, remove_orphans=True)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _strip_ooxml(data: bytes) -> bytes:
    import zipfile  # noqa: PLC0415

    src = zipfile.ZipFile(io.BytesIO(data))
    # Declared sizes bound what ZipExtFile will inflate; refuse zip bombs.
    if sum(i.file_size for i in src.infolist()) > 20 * MAX_SIZE_BYTES:
        raise MetadataError("archive expands too far")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = _OOXML_EMPTY_PARTS.get(info.filename) or src.read(info)
            dst.writestr(info, body)
    return out.getvalue()


_STRIPPERS = {
    ".jpg": _strip_image, ".jpeg": _strip_image, ".png": _strip_image,
    ".gif": _strip_image, ".webp": _strip_image,
    ".pdf": _strip_pdf,
    ".docx": _strip_ooxml, ".xlsx": _strip_ooxml,
}


def strip_metadata(filename: str, data: bytes) -> bytes:
    """Remove identifying metadata (EXIF/GPS, PDF author, Office properties).

    Plain text has none; legacy .doc/.xls cannot be cleaned and the upload page
    says so. Anything else that fails to clean raises MetadataError.
    """
    stripper = _STRIPPERS.get(Path(filename).suffix.lower())
    if stripper is None:
        return data
    try:
        return stripper(data)
    except MetadataError:
        raise
    except Exception as exc:  # noqa: BLE001 — any parser failure means "not cleaned"
        raise MetadataError(str(exc)) from exc


def validate_file(filename: str, content_type: str, size: int, head: bytes = b"") -> str | None:
    """Return an error string if the file is invalid, or None if it's acceptable.

    ``head`` is the first bytes of the file; when supplied, the content's magic
    number must match the extension (declared type/extension alone are
    attacker-controlled).
    """
    if size > MAX_SIZE_BYTES:
        mb = size / (1024 * 1024)
        return f"'{filename}' is too large ({mb:.1f} MB). Maximum 10 MB per file."

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return (
            f"'{filename}' has an unsupported file extension. "
            "Allowed: PDF, JPEG, PNG, GIF, WebP, TXT, CSV, DOCX, XLSX."
        )

    # Normalise declared MIME type (strip charset suffixes like text/plain; charset=utf-8)
    declared_type = content_type.split(";")[0].strip().lower()
    if declared_type not in ALLOWED_MIME_TYPES:
        return (
            f"'{filename}' has an unsupported file type ({declared_type}). "
            "Allowed: PDF, images, text, Word, Excel."
        )

    if head and not _content_matches_ext(ext, head):
        return (
            f"'{filename}' content does not match its '{ext}' type "
            "(the file may be corrupted or disguised)."
        )

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

        # Enforce the count limit before touching the next file's bytes, so a
        # flood of parts can't force us to read them all into memory first.
        if len(result) >= MAX_ATTACHMENTS:
            return [], f"Too many files. Maximum {MAX_ATTACHMENTS} attachments per report."

        # Bounded read: pull at most one byte past the limit so an oversized
        # file is rejected without buffering its entire (potentially huge) body.
        data = await upload.read(MAX_SIZE_BYTES + 1)
        if len(data) == 0:
            continue

        name = sanitize_filename(upload.filename)
        content_type = upload.content_type or "application/octet-stream"
        error = validate_file(name, content_type, len(data), head=data[:16])
        if error:
            return [], error

        try:
            data = strip_metadata(name, data)
        except MetadataError:
            return [], (
                f"'{name}' could not be checked for hidden metadata (author, location, "
                "device) and was not accepted. Save it again or export it as a PDF."
            )

        result.append((name, content_type, data))

    return result, None


async def create_attachments(
    db: AsyncSession,
    report: Report,
    file_tuples: list[tuple[str, str, bytes]],
) -> list[Attachment]:
    """Persist (filename, content_type, data) tuples as encrypted Attachment rows.

    The bytes are encrypted with the report's own data key before they leave
    the process, so neither the database nor the S3 bucket holds plaintext.
    With STORAGE_BACKEND=s3 the ciphertext goes to the bucket and the row keeps
    only the storage_key.
    """
    from app.config import settings  # noqa: PLC0415
    from app.services.encryption import make_report_fernet  # noqa: PLC0415
    from app.services.storage import generate_storage_key, get_storage_backend  # noqa: PLC0415

    backend = get_storage_backend()
    use_s3 = settings.storage_backend == "s3"
    fernet = make_report_fernet(report.encrypted_dek, settings.secret_key)

    attachments = []
    for filename, content_type, data in file_tuples:
        ciphertext = fernet.encrypt(data)
        storage_key: str | None = None
        db_data: bytes | None = ciphertext

        if use_s3:
            storage_key = generate_storage_key(filename)
            await backend.put(storage_key, ciphertext, "application/octet-stream")
            db_data = None

        att = Attachment(
            id=uuid.uuid4(),
            report_id=report.id,
            filename=filename,
            content_type=content_type,
            size=len(data),
            data=db_data,
            storage_key=storage_key,
            encrypted=True,
        )
        db.add(att)
        attachments.append(att)
    if attachments:
        await db.commit()
    return attachments


async def read_attachment(db: AsyncSession, attachment: Attachment) -> bytes:
    """Return an attachment's plaintext bytes from the DB or external storage.

    Raises LookupError when the bytes are gone (e.g. S3 object deleted).
    Rows written before encryption was introduced are returned as stored.
    """
    from app.config import settings  # noqa: PLC0415
    from app.services.encryption import make_report_fernet  # noqa: PLC0415
    from app.services.storage import (  # noqa: PLC0415
        StorageObjectNotFoundError,
        get_storage_backend,
    )

    if attachment.storage_key:
        try:
            data = await get_storage_backend().get(attachment.storage_key)
        except StorageObjectNotFoundError as exc:
            raise LookupError(attachment.storage_key) from exc
    elif attachment.data is None:
        raise LookupError(str(attachment.id))
    else:
        data = attachment.data

    if not attachment.encrypted:
        return data
    dek = await db.scalar(select(Report.encrypted_dek).where(Report.id == attachment.report_id))
    if dek is None:
        raise LookupError(str(attachment.report_id))
    return make_report_fernet(dek, settings.secret_key).decrypt(data)


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


async def stored_object_keys(db: AsyncSession, report_ids: list[uuid.UUID]) -> list[str]:
    """Return external-storage keys of all attachments belonging to the given reports."""
    result = await db.execute(
        select(Attachment.storage_key).where(
            Attachment.report_id.in_(report_ids), Attachment.storage_key.isnot(None)
        )
    )
    return [key for key in result.scalars() if key]


async def delete_stored_objects(keys: list[str]) -> None:
    """Remove attachment objects from external storage after their rows are gone.

    The DB cascade removes attachment rows but cannot reach an S3 bucket, so
    without this a deleted report's files would stay there indefinitely.
    Best-effort per key: one failure must not keep the others alive.
    """
    import logging  # noqa: PLC0415

    from app.services.storage import get_storage_backend  # noqa: PLC0415

    backend = get_storage_backend()
    for key in keys:
        try:
            await backend.delete(key)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Failed to delete stored object %s", key)
