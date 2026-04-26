"""Add immutable audit log table.

Revision ID: 004
Revises: 003
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_log (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            admin_id        UUID REFERENCES admin_users(id) ON DELETE SET NULL,
            admin_username  VARCHAR(64) NOT NULL,
            action          VARCHAR(64) NOT NULL,
            report_id       UUID REFERENCES reports(id) ON DELETE CASCADE,
            detail          TEXT
        )
    """)
    op.execute("CREATE INDEX ix_audit_log_created_at ON audit_log (created_at DESC)")
    op.execute("CREATE INDEX ix_audit_log_report_id  ON audit_log (report_id)")
    op.execute("CREATE INDEX ix_audit_log_action     ON audit_log (action)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
