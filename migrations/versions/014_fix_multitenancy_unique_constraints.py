"""Replace global unique constraints with per-org composite unique constraints.

Revision ID: 014
Revises: 013
Create Date: 2026-04-27

Fixes:
  - report_categories.slug: was globally unique, now unique per (slug, org_id)
  - locations.code:          was globally unique, now unique per (code, org_id)

This is required for multi-tenancy: two organisations must be able to use
the same category slug or location code without conflicting.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- report_categories: drop global unique on slug, add composite ---
    # The index name created by SQLAlchemy for unique=True on slug is
    # ix_report_categories_slug (index) + a unique constraint.
    # We drop both the constraint and the old index, then create the new ones.
    conn.execute(sa.text(
        "ALTER TABLE report_categories DROP CONSTRAINT IF EXISTS report_categories_slug_key"
    ))
    # Drop the index that SQLAlchemy created for the old unique column
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_report_categories_slug"))
    # Create composite unique constraint
    op.create_unique_constraint(
        "uq_report_categories_slug_org",
        "report_categories",
        ["slug", "org_id"],
    )
    # Recreate non-unique index for fast single-column lookups
    op.create_index("ix_report_categories_slug", "report_categories", ["slug"])

    # --- locations: drop global unique on code, add composite ---
    conn.execute(sa.text(
        "ALTER TABLE locations DROP CONSTRAINT IF EXISTS locations_code_key"
    ))
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_locations_code"))
    op.create_unique_constraint(
        "uq_locations_code_org",
        "locations",
        ["code", "org_id"],
    )
    op.create_index("ix_locations_code", "locations", ["code"])


def downgrade() -> None:
    conn = op.get_bind()

    # --- locations ---
    op.drop_index("ix_locations_code", table_name="locations")
    op.drop_constraint("uq_locations_code_org", "locations", type_="unique")
    conn.execute(sa.text(
        "ALTER TABLE locations ADD CONSTRAINT locations_code_key UNIQUE (code)"
    ))
    op.create_index("ix_locations_code", "locations", ["code"], unique=True)

    # --- report_categories ---
    op.drop_index("ix_report_categories_slug", table_name="report_categories")
    op.drop_constraint("uq_report_categories_slug_org", "report_categories", type_="unique")
    conn.execute(sa.text(
        "ALTER TABLE report_categories "
        "ADD CONSTRAINT report_categories_slug_key UNIQUE (slug)"
    ))
    op.create_index("ix_report_categories_slug", "report_categories", ["slug"], unique=True)
