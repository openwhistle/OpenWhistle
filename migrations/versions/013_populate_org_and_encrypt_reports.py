"""Populate org_id for all existing rows; encrypt existing report content.

Revision ID: 013
Revises: 012
Create Date: 2026-04-27

Data migrations:
  1. Set org_id = default org for all existing rows in data-bearing tables.
  2. Make org_id NOT NULL after backfill.
  3. Encrypt existing report descriptions and message bodies using envelope
     encryption (per-report DEK wrapped with MEK derived from SECRET_KEY).
  4. Make encrypted_dek NOT NULL after backfill.

SECRET_KEY is read from the environment at migration time. If SECRET_KEY is
not set the migration fails loudly rather than leaving data unencrypted.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _derive_mek(secret_key: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openwhistle-mek-v1",
        info=b"report-encryption",
    ).derive(secret_key.encode("utf-8"))


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Backfill org_id for all existing rows ───────────────────────────────
    default_org = conn.execute(
        sa.text("SELECT id FROM organisations WHERE slug = 'default' LIMIT 1")
    ).fetchone()
    if default_org is None:
        msg = "Default organisation not found — run migration 012 first."
        raise RuntimeError(msg)

    default_org_id = str(default_org[0])

    for table in ("reports", "admin_users", "report_categories", "locations", "audit_log"):
        conn.execute(
            sa.text(f"UPDATE {table} SET org_id = :oid WHERE org_id IS NULL"),  # noqa: S608
            {"oid": default_org_id},
        )

    # ── 2. Make org_id NOT NULL ────────────────────────────────────────────────
    for table in ("reports", "admin_users", "report_categories", "locations"):
        op.alter_column(table, "org_id", nullable=False)
    # audit_log stays nullable so system-generated entries need no org

    # ── 3. Encrypt existing report content ────────────────────────────────────
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key:
        msg = "SECRET_KEY environment variable is not set — cannot encrypt reports."
        raise RuntimeError(msg)

    from cryptography.fernet import Fernet

    raw_mek = _derive_mek(secret_key)
    mek_fernet = Fernet(base64.urlsafe_b64encode(raw_mek))

    reports = conn.execute(
        sa.text("SELECT id, description FROM reports WHERE encrypted_dek IS NULL")
    ).fetchall()

    for row in reports:
        dek_raw = os.urandom(32)
        dek_key = base64.urlsafe_b64encode(dek_raw)
        encrypted_dek = mek_fernet.encrypt(dek_raw).decode("utf-8")
        report_fernet = Fernet(dek_key)

        enc_desc = report_fernet.encrypt(row[1].encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text(
                "UPDATE reports SET description = :d, encrypted_dek = :k WHERE id = :id"
            ),
            {"d": enc_desc, "k": encrypted_dek, "id": row[0]},
        )

        # Encrypt all messages for this report using the same DEK
        messages = conn.execute(
            sa.text("SELECT id, content FROM report_messages WHERE report_id = :rid"),
            {"rid": row[0]},
        ).fetchall()
        for msg in messages:
            enc_content = report_fernet.encrypt(msg[1].encode("utf-8")).decode("utf-8")
            conn.execute(
                sa.text("UPDATE report_messages SET content = :c WHERE id = :id"),
                {"c": enc_content, "id": msg[0]},
            )

    # ── 4. Make encrypted_dek NOT NULL ────────────────────────────────────────
    op.alter_column("reports", "encrypted_dek", nullable=False)


def downgrade() -> None:
    # Reverse: make columns nullable again; we cannot reverse encryption
    op.alter_column("reports", "encrypted_dek", nullable=True)

    for table in ("reports", "admin_users", "report_categories", "locations"):
        op.alter_column(table, "org_id", nullable=True)

    for table in ("reports", "admin_users", "report_categories", "locations", "audit_log"):
        conn = op.get_bind()
        conn.execute(sa.text(f"UPDATE {table} SET org_id = NULL"))  # noqa: S608
