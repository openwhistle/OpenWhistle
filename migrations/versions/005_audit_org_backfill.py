"""Audit rows get the organisation they belong to.

Revision ID: b2d7f1a5c302
Revises: a1c6e0f4b201
Create Date: 2026-09-24

Before v2.0.0 only retention rows carried org_id, so organisation-scoped audit
pages showed nothing. Rows about a report take the report's organisation, other
rows the acting admin's. Downgrade keeps the values (they are correct).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d7f1a5c302"
down_revision: str | None = "a1c6e0f4b201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE audit_log a SET org_id = r.org_id FROM reports r "
        "WHERE a.report_id = r.id AND a.org_id IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE audit_log a SET org_id = u.org_id FROM admin_users u "
        "WHERE a.admin_id = u.id AND a.report_id IS NULL AND a.org_id IS NULL"
    ))


def downgrade() -> None:
    pass
