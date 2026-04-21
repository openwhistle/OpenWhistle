"""Initial schema: reports, messages, admin users, setup status.

Revision ID: 001
Revises:
Create Date: 2026-04-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE reportcategory AS ENUM (
                'financial_fraud', 'workplace_safety', 'environmental',
                'corruption', 'data_protection', 'discrimination', 'other'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE reportstatus AS ENUM (
                'received', 'acknowledged', 'in_progress', 'closed'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE reportsender AS ENUM ('whistleblower', 'admin');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_number", sa.String(20), unique=True, nullable=False),
        sa.Column("pin_hash", sa.String(72), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "financial_fraud",
                "workplace_safety",
                "environmental",
                "corruption",
                "data_protection",
                "discrimination",
                "other",
                name="reportcategory",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "acknowledged",
                "in_progress",
                "closed",
                name="reportstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="received",
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reports_case_number", "reports", ["case_number"])

    op.create_table(
        "report_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender",
            sa.Enum("whistleblower", "admin", name="reportsender", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_report_messages_report_id", "report_messages", ["report_id"])

    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(72), nullable=False),
        sa.Column("totp_secret", sa.String(32), nullable=False),
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("oidc_sub", sa.String(255), unique=True, nullable=True),
        sa.Column("oidc_issuer", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_users_username", "admin_users", ["username"])

    op.create_table(
        "setup_status",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("completed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("INSERT INTO setup_status (id, completed) VALUES (1, false) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.drop_table("setup_status")
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_table("admin_users")
    op.drop_index("ix_report_messages_report_id", table_name="report_messages")
    op.drop_table("report_messages")
    op.drop_index("ix_reports_case_number", table_name="reports")
    op.drop_table("reports")
    op.execute("DROP TYPE IF EXISTS reportsender")
    op.execute("DROP TYPE IF EXISTS reportstatus")
    op.execute("DROP TYPE IF EXISTS reportcategory")
