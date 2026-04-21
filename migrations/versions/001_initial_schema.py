"""Initial schema: reports, messages, admin users, setup status.

Revision ID: 001
Revises:
Create Date: 2026-04-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.execute("""
        CREATE TYPE reportcategory AS ENUM (
            'financial_fraud', 'workplace_safety', 'environmental',
            'corruption', 'data_protection', 'discrimination', 'other'
        )
    """)

    op.execute("""
        CREATE TYPE reportstatus AS ENUM (
            'received', 'acknowledged', 'in_progress', 'closed'
        )
    """)

    op.execute("""
        CREATE TYPE reportsender AS ENUM ('whistleblower', 'admin')
    """)

    op.execute("""
        CREATE TABLE reports (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            case_number VARCHAR(20) NOT NULL UNIQUE,
            pin_hash    VARCHAR(72) NOT NULL,
            category    reportcategory NOT NULL,
            description TEXT NOT NULL,
            status      reportstatus NOT NULL DEFAULT 'received',
            submitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acknowledged_at   TIMESTAMPTZ,
            feedback_due_at   TIMESTAMPTZ,
            closed_at         TIMESTAMPTZ
        )
    """)

    op.execute("CREATE INDEX ix_reports_case_number ON reports (case_number)")

    op.execute("""
        CREATE TABLE report_messages (
            id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            sender    reportsender NOT NULL,
            content   TEXT NOT NULL,
            sent_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX ix_report_messages_report_id ON report_messages (report_id)")

    op.execute("""
        CREATE TABLE admin_users (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            username      VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(72) NOT NULL,
            totp_secret   VARCHAR(32) NOT NULL,
            totp_enabled  BOOLEAN NOT NULL DEFAULT false,
            oidc_sub      VARCHAR(255) UNIQUE,
            oidc_issuer   VARCHAR(255),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ
        )
    """)

    op.execute("CREATE INDEX ix_admin_users_username ON admin_users (username)")

    op.execute("""
        CREATE TABLE setup_status (
            id           INTEGER PRIMARY KEY,
            completed    BOOLEAN NOT NULL DEFAULT false,
            completed_at TIMESTAMPTZ
        )
    """)

    op.execute("INSERT INTO setup_status (id, completed) VALUES (1, false)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS setup_status")
    op.execute("DROP TABLE IF EXISTS admin_users")
    op.execute("DROP TABLE IF EXISTS report_messages")
    op.execute("DROP TABLE IF EXISTS reports")
    op.execute("DROP TYPE IF EXISTS reportsender")
    op.execute("DROP TYPE IF EXISTS reportstatus")
    op.execute("DROP TYPE IF EXISTS reportcategory")
