"""A report's Fernet tokens carry no time.

Revision ID: d4f1b7c3e010
Revises: c9e4a8b2d009
Create Date: 2026-10-11

A Fernet token holds the second it was made, unencrypted. Migration 006 kept
only the day of a submission, a whistleblower message and an upload, but every
token written with them still held the exact second: readable from a dump or a
backup, with no key. New tokens are made at time 0 (app.services.crypto.seal);
this re-seals a report's existing ones: its key wrapper, description,
confidential fields, messages, notes, and the names and bytes of attachments
held in the database.

Attachments in an S3 bucket are not rewritten: the bucket records each object's
upload time itself (LastModified), which no token can hide.

A token that does not decrypt under the configured keys is left as it is and
counted in the log; the application cannot read it either. Running it again
changes nothing. Downgrade is a no-op on data: the times are not kept anywhere,
by design. Online only: offline SQL (``--sql``) cannot re-encrypt.
"""

import base64
import logging
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

revision: str = "d4f1b7c3e010"
down_revision: str | None = "c9e4a8b2d009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

_TOKEN = b"gAAAA"  # a Fernet token's base64url start; anything else is legacy plaintext


def _resealer(
    fernet: Fernet | MultiFernet, unreadable: list[int]
) -> Callable[[bytes], bytes | None]:
    from app.services.crypto import seal

    def reseal(token: bytes) -> bytes | None:
        if not token.startswith(_TOKEN) or base64.urlsafe_b64decode(token)[1:9] == bytes(8):
            return None
        try:
            return seal(fernet, fernet.decrypt(token))
        except InvalidToken:
            unreadable[0] += 1
            return None

    return reseal


def _update(table: str, column: str, row_id: object, value: bytes, as_text: bool) -> None:
    op.get_bind().execute(
        sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),  # noqa: S608 — fixed names
        {"v": value.decode() if as_text else value, "i": row_id},
    )


def _reseal_text(table: str, column: str, where: str, params: dict[str, object], reseal) -> None:  # type: ignore[no-untyped-def]
    rows = op.get_bind().execute(
        sa.text(f"SELECT id, {column} FROM {table} WHERE {where}"),  # noqa: S608 — fixed names
        params,
    )
    for row_id, value in rows.all():
        if value is not None and (new := reseal(value.encode())) is not None:
            _update(table, column, row_id, new, as_text=True)


def upgrade() -> None:
    if context.is_offline_mode():
        msg = "Migration 013 must run online: offline SQL cannot re-encrypt the tokens"
        raise RuntimeError(msg)
    from app.services.crypto import _make_fernet
    from app.services.encryption import make_mek_fernet

    bind = op.get_bind()
    unreadable = [0]
    by_mek = _resealer(make_mek_fernet(), unreadable)
    by_root = _resealer(_make_fernet(), unreadable)
    reports = bind.execute(sa.text("SELECT id, encrypted_dek FROM reports")).all()
    for report_id, dek_token in reports:
        for column in ("confidential_name", "confidential_contact", "secure_email"):
            _reseal_text("reports", column, "id = :r", {"r": report_id}, by_root)
        try:
            dek = make_mek_fernet().decrypt(dek_token.encode())
        except InvalidToken:
            unreadable[0] += 1
            continue
        by_dek = _resealer(Fernet(base64.urlsafe_b64encode(dek)), unreadable)
        params = {"r": report_id}
        _reseal_text("reports", "description", "id = :r", params, by_dek)
        _reseal_text("report_messages", "content", "report_id = :r", params, by_dek)
        _reseal_text("admin_notes", "content", "report_id = :r", params, by_dek)
        _reseal_text("attachments", "filename", "report_id = :r AND encrypted", params, by_dek)
        ids = bind.execute(
            sa.text(
                "SELECT id FROM attachments WHERE report_id = :r AND encrypted AND data IS NOT NULL"
            ),
            params,
        ).scalars()
        for attachment_id in ids.all():
            data = bind.scalar(
                sa.text("SELECT data FROM attachments WHERE id = :i"), {"i": attachment_id}
            )
            if (new := by_dek(bytes(data))) is not None:
                _update("attachments", "data", attachment_id, new, as_text=False)
        if (new := by_mek(dek_token.encode())) is not None:
            _update("reports", "encrypted_dek", report_id, new, as_text=True)
    if unreadable[0]:
        log.warning(
            "Migration 013: %d token(s) do not decrypt under the configured keys and keep "
            "their time; see ENCRYPTION_KEY_PREVIOUS in the upgrade guide",
            unreadable[0],
        )


def downgrade() -> None:
    pass
