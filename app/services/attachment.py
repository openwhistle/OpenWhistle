"""Attachment service — file validation, storage, and retrieval."""

from __future__ import annotations

import io
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.report import Report

if TYPE_CHECKING:
    from app.services.storage import StorageBackend

MAX_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS: int = 5
# Hard cap on what one submission draft holds in Redis (before base64 and
# encryption, which add about 78 %).
MAX_DRAFT_ATTACHMENT_BYTES: int = MAX_ATTACHMENTS * MAX_SIZE_BYTES

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
})

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".jpg", ".jpeg",
    ".png", ".gif", ".webp",
    ".txt", ".csv",
    ".docx",
    ".xlsx",
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
        elif fmt == "TIFF":
            clean.save(out, format="TIFF", compression="tiff_lzw")
        else:
            raise MetadataError(f"unsupported image format {fmt}")
    return out.getvalue()


# JPEG markers that carry no metadata: APP0 (JFIF) and APP14 (Adobe colour transform).
_JPEG_KEEP_APP = {0xE0, 0xEE}


def _strip_jpeg_segments(data: bytes) -> bytes:
    """Drop the APPn (EXIF, XMP, IPTC, ICC) and COM segments of a JPEG, pixels untouched.

    A PDF embeds a JPEG as-is (/DCTDecode), so a photo keeps its GPS inside the PDF.
    Re-encoding would change the image; cutting the header segments does not.
    """
    if data[:2] != b"\xff\xd8":
        return data
    out, i = bytearray(data[:2]), 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: the rest is image data
            break
        end = i + 2 + int.from_bytes(data[i + 2:i + 4], "big")
        if not ((0xE0 <= marker <= 0xEF and marker not in _JPEG_KEEP_APP) or marker == 0xFE):
            out += data[i:end]
        i = end
    return bytes(out + data[i:])


def _strip_pdf(data: bytes) -> bytes:
    import os  # noqa: PLC0415

    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    from pypdf.generic import (  # noqa: PLC0415
        ArrayObject,
        ByteStringObject,
        NameObject,
        StreamObject,
        TextStringObject,
    )

    # An owner-password-only PDF opens without a password and is written back
    # unencrypted and cleaned; one that needs a user password cannot be read
    # and fails here, which strip_metadata turns into a refusal.
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.metadata = None  # document info: author, creator tool, dates
    writer._root_object.pop("/Metadata", None)  # XMP packet
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if "/T" in annot:  # the commenter's name
                annot[NameObject("/T")] = TextStringObject("Author")
            for key in ("/M", "/CreationDate"):  # when they commented
                annot.pop(key, None)
    for obj in writer._objects:
        # A JPEG alone in its stream is the file as-is; set the raw bytes (pypdf
        # cannot re-encode DCT). A JPEG behind a second filter is left alone.
        if isinstance(obj, StreamObject) and obj.get("/Filter") in ("/DCTDecode", ["/DCTDecode"]):
            obj._data = _strip_jpeg_segments(obj._data)
    # Unlinking is not removing: the XMP stream would still be written as an
    # orphaned object that any forensic tool can read.
    writer.compress_identical_objects(remove_duplicates=False, remove_unreferenced=True)
    # The file identifier is carried over from the original and links the two files.
    fresh_id = ByteStringObject(os.urandom(16))
    writer._ID = ArrayObject([fresh_id, fresh_id])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _neutral_attrs(xml: bytes, values: dict[bytes, bytes]) -> bytes:
    """Replace the value of every (optionally prefixed) attribute named in ``values``."""
    for name, value in values.items():
        xml = re.sub(
            rb"(\s(?:\w+:)?" + name + rb")=(?:\"[^\"]*\"|'[^']*')", rb'\1="' + value + b'"', xml
        )
    return xml


# Who wrote a comment or tracked change. Names are replaced, never removed, so
# every reference inside the package (threaded comments → person ids) still resolves.
_WORD_AUTHOR = {b"author": b"Author", b"initials": b"A", b"userId": b"", b"providerId": b"None"}
_XL_PERSON = {b"displayName": b"Author", b"userId": b"", b"providerId": b"None"}


def _anonymise_ooxml_part(name: str, body: bytes) -> bytes:
    if name.startswith("word/") and name.endswith(".xml"):
        # comments, w:ins/w:del/…Change in every story part, people.xml
        return _neutral_attrs(body, _WORD_AUTHOR)
    if re.fullmatch(r"xl/comments\d*\.xml", name):
        # "tc={person id}" links a legacy comment to its thread: not a name, kept.
        authors = set(re.findall(rb"<author>(?!tc=)([^<]+)</author>", body))
        for author in authors:
            # Excel's own "Name:" label opens the first run of each comment; the
            # rest of the comment (including any mentions of the author) is what
            # the whistleblower wrote and stays untouched.
            # Only replace in the first <t> inside each <comment>…<text> block.
            body = re.sub(
                rb"(<comment\b[^>]*>\s*<text>\s*<r>(?:\s*<rPr>.*?</rPr>)?\s*<t(?:\s[^>]*)?>)"
                + re.escape(author)
                + rb":",
                rb"\1Author:",
                body,
                flags=re.DOTALL,
            )
        return re.sub(rb"<author>(?!tc=)[^<]*</author>", b"<author>Author</author>", body)
    if name.startswith("xl/persons/"):
        return _neutral_attrs(body, _XL_PERSON)
    if name.startswith("xl/revisions/"):
        values = {b"userName": b"Author"}
        if name.endswith("userNames.xml"):
            values[b"name"] = b"Author"
        return _neutral_attrs(body, values)
    if name == "_rels/.rels":
        return re.sub(rb"<Relationship\b[^>]*docProps/thumbnail[^>]*/>", b"", body)
    if name == "[Content_Types].xml":
        return re.sub(rb"<Override\b[^>]*docProps/thumbnail[^>]*/>", b"", body)
    return body


_OOXML_MEDIA = re.compile(r"(?:word|xl|ppt)/media/[^/]+\.(?:jpe?g|png|gif|webp|tiff?)", re.I)


def _strip_ooxml(data: bytes) -> bytes:
    import zipfile  # noqa: PLC0415

    src = zipfile.ZipFile(io.BytesIO(data))
    # Declared sizes bound what ZipExtFile will inflate; refuse zip bombs.
    if sum(i.file_size for i in src.infolist()) > 20 * MAX_SIZE_BYTES:
        raise MetadataError("archive expands too far")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            # The thumbnail is a picture of the first page, names included.
            if info.filename.startswith("docProps/thumbnail."):
                continue
            body = _OOXML_EMPTY_PARTS.get(info.filename) or src.read(info)
            # A photo pasted into a document keeps its EXIF (GPS, camera) inside the package.
            if _OOXML_MEDIA.fullmatch(info.filename):
                body = _strip_image(body)
            # A fresh entry: no original timestamps, no extra fields (Unix
            # uid/gid, NTFS times) from the whistleblower's machine.
            clean = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            dst.writestr(clean, _anonymise_ooxml_part(info.filename, body), zipfile.ZIP_DEFLATED)
    return out.getvalue()


_STRIPPERS = {
    ".jpg": _strip_image, ".jpeg": _strip_image, ".png": _strip_image,
    ".gif": _strip_image, ".webp": _strip_image,
    ".pdf": _strip_pdf,
    ".docx": _strip_ooxml, ".xlsx": _strip_ooxml,
}


def strip_metadata(filename: str, data: bytes) -> bytes:
    """Remove identifying metadata (EXIF/GPS, PDF author, Office properties).

    Plain text has none. Anything else that fails to clean raises MetadataError.
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


class UploadError(str):
    """Why an upload was refused.

    The string value is the English message (logs, tests); ``key`` and
    ``params`` let the page show it in the whistleblower's language. The
    English text comes from en.json, so there is one source for it.
    """

    key: str
    params: dict[str, object]

    def __new__(cls, key: str, **params: object) -> UploadError:
        from app.i18n import make_translator  # noqa: PLC0415

        obj = super().__new__(cls, make_translator("en")(key, **params))
        obj.key = key
        obj.params = params
        return obj


def validate_file(filename: str, content_type: str, size: int, head: bytes = b"") -> str | None:
    """Return an error string if the file is invalid, or None if it's acceptable.

    ``head`` is the first bytes of the file; when supplied, the content's magic
    number must match the extension (declared type/extension alone are
    attacker-controlled).
    """
    ext = Path(filename).suffix.lower()
    if ext in {".doc", ".xls"}:
        # Legacy OLE files keep the author in places no parser here can clean.
        return UploadError("upload.error.legacy_office", name=filename)

    if size > MAX_SIZE_BYTES:
        return UploadError("upload.error.too_large", name=filename, size=format_size(size))

    if ext not in ALLOWED_EXTENSIONS:
        return UploadError("upload.error.bad_extension", name=filename)

    # Normalise declared MIME type (strip charset suffixes like text/plain; charset=utf-8)
    declared_type = content_type.split(";")[0].strip().lower()
    if declared_type not in ALLOWED_MIME_TYPES:
        return UploadError("upload.error.bad_type", name=filename, type=declared_type)

    if head and not _content_matches_ext(ext, head):
        return UploadError("upload.error.content_mismatch", name=filename, ext=ext)

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
            return [], UploadError("upload.error.too_many", max=MAX_ATTACHMENTS)

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

        from app.services.virus_scan import ScanUnavailableError, scan_bytes  # noqa: PLC0415

        try:
            # str | None: only None means clean. Never `if await scan_bytes(...)`
            # — an (unexpected) empty-string signature would be falsy and read
            # as clean, storing an infected file unscanned in all but name.
            if (await scan_bytes(data)) is not None:
                return [], UploadError("upload.error.malware", name=name)
        except ScanUnavailableError:
            return [], UploadError("upload.error.scan_unavailable", name=name)

        try:
            data = strip_metadata(name, data)
        except MetadataError:
            return [], UploadError("upload.error.metadata", name=name)

        result.append((name, content_type, data))

    return result, None


async def create_attachments(
    db: AsyncSession,
    report: Report,
    file_tuples: list[tuple[str, str, bytes]],
    *,
    commit: bool = True,
) -> list[Attachment]:
    """Persist (filename, content_type, data) tuples as encrypted Attachment rows.

    The bytes are encrypted with the report's own data key before they leave
    the process, so neither the database nor the S3 bucket holds plaintext.
    With STORAGE_BACKEND=s3 the ciphertext goes to the bucket and the row keeps
    only the storage_key.
    """
    from app.config import settings  # noqa: PLC0415
    from app.services.encryption import encrypt_field, make_report_fernet  # noqa: PLC0415
    from app.services.storage import generate_storage_key, get_storage_backend  # noqa: PLC0415

    backend = get_storage_backend()
    use_s3 = settings.storage_backend == "s3"
    from app.services.report import day_floor  # noqa: PLC0415

    fernet = make_report_fernet(report.encrypted_dek)
    today = day_floor(datetime.now(UTC))

    attachments = []
    for filename, content_type, data in file_tuples:
        ciphertext = fernet.encrypt(data)
        storage_key: str | None = None
        db_data: bytes | None = ciphertext

        if use_s3:
            storage_key = generate_storage_key()
            await backend.put(storage_key, ciphertext, "application/octet-stream")
            db_data = None

        att = Attachment(
            id=uuid.uuid4(),
            report_id=report.id,
            # "Max_Mustermann_evidence.pdf" identifies as well as the content.
            filename=encrypt_field(fernet, filename),
            content_type=content_type,
            size=len(data),
            data=db_data,
            storage_key=storage_key,
            encrypted=True,
            uploaded_at=today,  # the day only: the exact time could name the uploader
        )
        db.add(att)
        attachments.append(att)
    if attachments and commit:
        await db.commit()
    return attachments


async def read_attachment(db: AsyncSession, attachment: Attachment) -> bytes:
    """Return an attachment's plaintext bytes from the DB or external storage.

    Raises LookupError when the bytes are gone (e.g. S3 object deleted).
    Rows written before encryption was introduced are returned as stored.
    """
    from app.services.encryption import make_report_fernet  # noqa: PLC0415
    from app.services.storage import (  # noqa: PLC0415
        StorageObjectNotFoundError,
        get_storage_backend,
    )

    if attachment.storage_key:
        try:
            data = await get_storage_backend().get(attachment.storage_key)
        except StorageObjectNotFoundError as exc:
            # The attachment id, never storage_key: a not-yet-rekeyed legacy
            # row's storage_key is the original filename (task 17).
            raise LookupError(str(attachment.id)) from exc
    elif attachment.data is None:
        raise LookupError(str(attachment.id))
    else:
        data = attachment.data

    if not attachment.encrypted:
        return data
    dek = await db.scalar(select(Report.encrypted_dek).where(Report.id == attachment.report_id))
    if dek is None:
        raise LookupError(str(attachment.report_id))
    return make_report_fernet(dek).decrypt(data)


async def attachment_filename(db: AsyncSession, attachment: Attachment) -> str:
    """Return the attachment's plaintext name; names stored before v1.5.0 as stored."""
    from app.services.encryption import decrypt_field_safe, make_report_fernet  # noqa: PLC0415

    dek = await db.scalar(select(Report.encrypted_dek).where(Report.id == attachment.report_id))
    if dek is None:
        return attachment.filename
    fernet = make_report_fernet(dek)
    return decrypt_field_safe(fernet, attachment.filename) or attachment.filename


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
            # No key in the log line: a not-yet-rekeyed legacy row's key is
            # the original filename (task 17).
            logging.getLogger(__name__).exception("Failed to delete a stored object")


_UUID_KEY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _storage() -> StorageBackend:
    from app.services.storage import get_storage_backend  # noqa: PLC0415

    return get_storage_backend()


async def rekey_legacy_objects(db: AsyncSession) -> int:
    """Move objects stored before v1.5.0 (keys carrying the filename) to bare UUIDs.

    Copy first, then point the row at the copy, then delete the old object, so
    no step can lose a file. A failure leaves that row as it was for the next run.
    """
    import logging  # noqa: PLC0415

    from app.services.storage import generate_storage_key  # noqa: PLC0415

    log = logging.getLogger(__name__)
    backend = _storage()
    rows = await db.execute(select(Attachment).where(Attachment.storage_key.isnot(None)))
    moved = 0
    for att in rows.scalars().all():
        old = att.storage_key or ""
        if _UUID_KEY.fullmatch(old):
            continue
        new = generate_storage_key()
        try:
            await backend.copy(old, new)
        except Exception:  # noqa: BLE001
            log.warning("Could not re-key attachment %s; retried at next start", att.id)
            continue
        att.storage_key = new
        await db.commit()
        try:
            await backend.delete(old)
        except Exception:  # noqa: BLE001
            log.warning("Re-keyed attachment %s; its old object could not be deleted", att.id)
        moved += 1
    return moved


async def run_s3_rekey() -> None:
    """Startup job: once across replicas (Redis lock), own DB session.

    The lock's 1h TTL is only a crash safety-net, not a correctness
    requirement: rekey_legacy_objects() is idempotent (it skips rows already
    holding a UUID key), so a replica that starts after the lock has expired
    just finds nothing left to move.
    """
    from app.database import AsyncSessionLocal  # noqa: PLC0415
    from app.redis_client import get_redis  # noqa: PLC0415

    redis = await get_redis()
    if not await redis.set("openwhistle:job_lock:s3_rekey", "1", nx=True, ex=3600):
        return
    async with AsyncSessionLocal() as db:
        await rekey_legacy_objects(db)
