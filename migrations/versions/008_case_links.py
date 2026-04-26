"""Add case linking table for report de-duplication.

Revision ID: 008
Revises: 007
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE case_links (
            id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            report_id_a         UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            report_id_b         UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            linked_by_id        UUID REFERENCES admin_users(id) ON DELETE SET NULL,
            linked_by_username  VARCHAR(64) NOT NULL,
            linked_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (report_id_a, report_id_b),
            CHECK (report_id_a < report_id_b)
        )
    """)
    op.execute("CREATE INDEX ix_case_links_report_id_a ON case_links (report_id_a)")
    op.execute("CREATE INDEX ix_case_links_report_id_b ON case_links (report_id_b)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS case_links")
