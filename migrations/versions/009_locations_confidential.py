"""Add locations table, submission_mode, confidential fields, secure_email to reports.

Revision ID: 009
Revises: 008
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE locations (
            id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name         VARCHAR(128) NOT NULL,
            code         VARCHAR(32) NOT NULL UNIQUE,
            description  TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_locations_code ON locations (code)")
    op.execute("CREATE INDEX ix_locations_is_active ON locations (is_active)")

    op.execute("""
        CREATE TYPE submissionmode AS ENUM ('anonymous', 'confidential')
    """)

    op.execute("""
        ALTER TABLE reports
            ADD COLUMN location_id       UUID REFERENCES locations(id) ON DELETE SET NULL,
            ADD COLUMN submission_mode   submissionmode NOT NULL DEFAULT 'anonymous',
            ADD COLUMN confidential_name TEXT,
            ADD COLUMN confidential_contact TEXT,
            ADD COLUMN secure_email      TEXT
    """)
    op.execute("CREATE INDEX ix_reports_location_id ON reports (location_id)")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE reports
            DROP COLUMN IF EXISTS location_id,
            DROP COLUMN IF EXISTS submission_mode,
            DROP COLUMN IF EXISTS confidential_name,
            DROP COLUMN IF EXISTS confidential_contact,
            DROP COLUMN IF EXISTS secure_email
    """)
    op.execute("DROP TYPE IF EXISTS submissionmode")
    op.execute("DROP TABLE IF EXISTS locations")
