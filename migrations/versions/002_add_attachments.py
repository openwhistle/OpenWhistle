"""Add attachments table for file evidence uploads.

Revision ID: 002
Revises: 001
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE attachments (
            id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            report_id    UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            filename     VARCHAR(255) NOT NULL,
            content_type VARCHAR(128) NOT NULL,
            size         INTEGER NOT NULL,
            data         BYTEA NOT NULL,
            uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX ix_attachments_report_id ON attachments (report_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attachments")
