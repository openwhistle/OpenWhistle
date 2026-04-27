"""Make admin_users.org_id nullable to support superadmin accounts and test fixtures.

Revision ID: 015
Revises: 014
Create Date: 2026-04-27

Design rationale:
  - Superadmin accounts are not scoped to a single org; they manage all orgs.
    Forcing org_id=NOT NULL on admin_users prevented superadmins from being
    created without a default-org lookup.
  - Tests and external admin provisioning tools create AdminUser objects
    directly without running the full HTTP wizard, so they cannot always
    resolve the default org at construction time.
  - The wizard.py still sets org_id = default org for all admins created
    via the web setup flow.  Downstream code that needs to scope admin
    access to an org should treat org_id IS NULL as "cross-org" (superadmin).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("admin_users", "org_id", nullable=True)


def downgrade() -> None:
    # Set any NULLs to the default org before making NOT NULL again
    conn = op.get_bind()
    default_org = conn.execute(
        sa.text("SELECT id FROM organisations WHERE slug = 'default' LIMIT 1")
    ).fetchone()
    if default_org:
        conn.execute(
            sa.text("UPDATE admin_users SET org_id = :oid WHERE org_id IS NULL"),
            {"oid": str(default_org[0])},
        )
    op.alter_column("admin_users", "org_id", nullable=False)
