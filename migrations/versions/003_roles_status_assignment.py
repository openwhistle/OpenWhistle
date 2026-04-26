"""Add admin roles, new report statuses, and case assignment.

Revision ID: 003
Revises: 002
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Admin roles
    op.execute("CREATE TYPE adminrole AS ENUM ('admin', 'case_manager')")
    op.execute("""
        ALTER TABLE admin_users
        ADD COLUMN role adminrole NOT NULL DEFAULT 'admin',
        ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE
    """)

    # New report statuses (PostgreSQL allows ADD VALUE but not DROP VALUE)
    op.execute("ALTER TYPE reportstatus ADD VALUE IF NOT EXISTS 'in_review'")
    op.execute("ALTER TYPE reportstatus ADD VALUE IF NOT EXISTS 'pending_feedback'")

    # Migrate old statuses to new workflow
    op.execute("""
        UPDATE reports
        SET status = 'in_review'
        WHERE status IN ('acknowledged', 'in_progress')
    """)

    # Case assignment
    op.execute("""
        ALTER TABLE reports
        ADD COLUMN assigned_to_id UUID REFERENCES admin_users(id) ON DELETE SET NULL
    """)
    op.execute(
        "CREATE INDEX ix_reports_assigned_to_id ON reports (assigned_to_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_reports_assigned_to_id")
    op.execute("ALTER TABLE reports DROP COLUMN IF EXISTS assigned_to_id")
    op.execute("ALTER TABLE admin_users DROP COLUMN IF EXISTS role")
    op.execute("ALTER TABLE admin_users DROP COLUMN IF EXISTS is_active")
    op.execute("DROP TYPE IF EXISTS adminrole")
