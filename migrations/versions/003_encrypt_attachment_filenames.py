"""Attachment filenames are encrypted with the report's data key.

Revision ID: 7d4e2b9c1a05
Revises: 3c1f0a7e9b42
Create Date: 2026-09-24

A filename such as "Max_Mustermann_evidence.pdf" identifies the whistleblower
as well as the content does. The column becomes Text (a Fernet token is longer
than the name) and existing plaintext names are encrypted in place.

Idempotent: a name that already decrypts with its report key is left alone.
A row whose report key cannot be unwrapped (SECRET_KEY changed) keeps its
plaintext name and is logged by id; the application still reads it.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import Fernet, InvalidToken

revision: str = "7d4e2b9c1a05"
down_revision: str | None = "3c1f0a7e9b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def _rows() -> list[tuple[object, str, str]]:
    return list(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT a.id, a.filename, r.encrypted_dek FROM attachments a "
                "JOIN reports r ON r.id = a.report_id WHERE r.encrypted_dek IS NOT NULL"
            )
        )
        .tuples()
    )


def _fernet(dek: str) -> Fernet | None:
    from app.config import settings
    from app.services.encryption import make_report_fernet

    try:
        return make_report_fernet(dek, settings.secret_key)
    except InvalidToken, ValueError:
        return None


def _set(att_id: object, filename: str) -> None:
    op.get_bind().execute(
        sa.text("UPDATE attachments SET filename = :f WHERE id = :i"), {"f": filename, "i": att_id}
    )


def _is_token(fernet: Fernet, value: str) -> bool:
    try:
        fernet.decrypt(value.encode())
    except InvalidToken:
        return False
    return True


def upgrade() -> None:
    op.alter_column("attachments", "filename", type_=sa.Text(), existing_nullable=False)
    if context.is_offline_mode():
        return
    for att_id, filename, dek in _rows():
        fernet = _fernet(dek)
        if fernet is None:
            log.warning("Attachment %s: report key unavailable, name left as stored", att_id)
        elif not _is_token(fernet, filename):
            _set(att_id, fernet.encrypt(filename.encode()).decode())


def downgrade() -> None:
    if not context.is_offline_mode():
        for att_id, filename, dek in _rows():
            fernet = _fernet(dek)
            if fernet is not None and _is_token(fernet, filename):
                _set(att_id, fernet.decrypt(filename.encode()).decode())
    op.alter_column("attachments", "filename", type_=sa.String(255), existing_nullable=False)
