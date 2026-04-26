"""Add internal admin notes per report.

Revision ID: 005
Revises: 004
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE admin_notes (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            report_id       UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            author_id       UUID REFERENCES admin_users(id) ON DELETE SET NULL,
            author_username VARCHAR(64) NOT NULL,
            content         TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_admin_notes_report_id ON admin_notes (report_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_notes")
