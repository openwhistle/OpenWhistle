"""Attachments stored before v1.4.0 are encrypted with their report's data key.

Revision ID: a7c4e0f6b113
Revises: f6b3d9e5a012
Create Date: 2026-10-13

Migration 002 left existing rows as they were (encrypted = false), and nothing
encrypted them later: a photo uploaded to v1.3 stayed readable to anyone holding
a database dump. Bytes in the database are encrypted here; objects in S3 by the
startup job (app.services.attachment.rekey_legacy_objects).

A row whose report key cannot be unwrapped (encryption key changed) keeps its
bytes and is logged by id; the application still reads it.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import InvalidToken

revision: str = "a7c4e0f6b113"
down_revision: str | None = "f6b3d9e5a012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    if context.is_offline_mode():
        msg = "Migration 016 must run online: offline SQL cannot encrypt the attachments"
        raise RuntimeError(msg)
    from app.services.crypto import seal
    from app.services.encryption import make_report_fernet

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT a.id, r.encrypted_dek FROM attachments a JOIN reports r ON r.id = a.report_id "
            "WHERE NOT a.encrypted AND a.data IS NOT NULL"
        )
    ).all()
    for att_id, dek in rows:  # one row in memory at a time: attachments are up to 10 MB
        try:
            fernet = make_report_fernet(dek)
        except (InvalidToken, ValueError):
            log.warning("Attachment %s: report key unavailable, left as stored", att_id)
            continue
        data = bind.execute(
            sa.text("SELECT data FROM attachments WHERE id = :i"), {"i": att_id}
        ).scalar_one()
        bind.execute(
            sa.text("UPDATE attachments SET data = :d, encrypted = true WHERE id = :i"),
            {"d": seal(fernet, bytes(data)), "i": att_id},
        )


def downgrade() -> None:
    pass  # decrypting stored evidence back to plaintext is never wanted
