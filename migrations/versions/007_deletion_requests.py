"""Add 4-eyes deletion request table.

Revision ID: 007
Revises: 006
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE deletion_requests (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            report_id               UUID NOT NULL UNIQUE REFERENCES reports(id) ON DELETE CASCADE,
            requested_by_id         UUID REFERENCES admin_users(id) ON DELETE SET NULL,
            requested_by_username   VARCHAR(64) NOT NULL,
            requested_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            confirmed_by_id         UUID REFERENCES admin_users(id) ON DELETE SET NULL,
            confirmed_by_username   VARCHAR(64),
            confirmed_at            TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX ix_deletion_requests_report_id ON deletion_requests (report_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deletion_requests")
