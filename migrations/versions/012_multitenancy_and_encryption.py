"""Add organisations table, org_id FKs, encrypted_dek, and superadmin role.

Revision ID: 012
Revises: 011
Create Date: 2026-04-27

Schema changes:
  - CREATE TABLE organisations (id, name, slug, is_active, branding, created_at)
  - INSERT default organisation (slug='default')
  - ALTER TYPE adminrole ADD VALUE 'superadmin'
  - ADD COLUMN org_id to reports, admin_users, report_categories, locations, audit_log
  - ADD COLUMN encrypted_dek to reports (envelope encryption)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Create organisations table ─────────────────────────────────────────────
    op.create_table(
        "organisations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("branding", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_organisations_slug", "organisations", ["slug"], unique=True)

    # Insert the default organisation
    op.execute(
        sa.text(
            "INSERT INTO organisations (id, name, slug, is_active, created_at) "
            "VALUES (gen_random_uuid(), 'Default Organisation', 'default', true, NOW())"
        )
    )

    # ── Add 'superadmin' value to adminrole enum ───────────────────────────────
    # PostgreSQL requires a transaction-level lock; ADD VALUE is DDL that cannot
    # be inside a transaction in older PG versions. Use IF NOT EXISTS for safety.
    op.execute(sa.text("ALTER TYPE adminrole ADD VALUE IF NOT EXISTS 'superadmin' BEFORE 'admin'"))

    # ── Add org_id FK column to data-bearing tables (nullable initially) ───────
    for table in ("reports", "admin_users", "report_categories", "locations", "audit_log"):
        op.add_column(
            table,
            sa.Column(
                "org_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organisations.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])

    # ── Add encrypted_dek column to reports ────────────────────────────────────
    op.add_column("reports", sa.Column("encrypted_dek", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "encrypted_dek")

    for table in ("audit_log", "locations", "report_categories", "admin_users", "reports"):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_column(table, "org_id")

    # Note: PostgreSQL does not support removing enum values — skip adminrole downgrade

    op.drop_index("ix_organisations_slug", table_name="organisations")
    op.drop_table("organisations")
