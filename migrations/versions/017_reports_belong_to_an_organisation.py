"""Every report belongs to an organisation, as every account does since migration 011.

Revision ID: b8d5f1a7c214
Revises: a7c4e0f6b113
Create Date: 2026-10-13

A report filed while DEFAULT_ORG_SLUG named no organisation kept no organisation.
With multi-tenancy on, every organisation's admin could open it while their case
lists hid it. It goes to the default organisation, or the oldest one, and its
audit rows with it.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d5f1a7c214"
down_revision: str | None = "a7c4e0f6b113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE reports SET org_id = COALESCE("
            "(SELECT id FROM organisations WHERE slug = :slug),"
            " (SELECT id FROM organisations ORDER BY created_at, id LIMIT 1))"
            " WHERE org_id IS NULL"
        ).bindparams(slug=os.environ.get("DEFAULT_ORG_SLUG", "default"))
    )
    # The case's audit trail goes with it: the audit log is read by organisation,
    # and rows written while the case had none would stay out of every one's view.
    op.execute(
        "UPDATE audit_log SET org_id = reports.org_id FROM reports"
        " WHERE audit_log.report_id = reports.id AND audit_log.org_id IS NULL"
    )


def downgrade() -> None:
    pass
