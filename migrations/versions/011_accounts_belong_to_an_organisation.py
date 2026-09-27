"""Every account belongs to an organisation.

Revision ID: b8d3f7a1c908
Revises: a7c2e6f0b807
Create Date: 2026-09-27

Accounts made on /admin/users while multi-tenancy was off, and accounts LDAP
provisioned, had no organisation. Every report has one, so switching
multi-tenancy on showed those admins and case managers no case at all. They
join the default organisation (DEFAULT_ORG_SLUG, else the oldest one), as the
setup wizard's account always did.

Downgrade is a no-op: which accounts had none is not kept, and the older code
reads an organisation it would have set with multi-tenancy on.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d3f7a1c908"
down_revision: str | None = "a7c2e6f0b807"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # op.execute with a bound parameter: runs online and renders offline (--sql).
    op.execute(
        sa.text(
            "UPDATE admin_users SET org_id = COALESCE("
            "(SELECT id FROM organisations WHERE slug = :slug),"
            " (SELECT id FROM organisations ORDER BY created_at, id LIMIT 1))"
            " WHERE org_id IS NULL"
        ).bindparams(slug=os.environ.get("DEFAULT_ORG_SLUG", "default"))
    )


def downgrade() -> None:
    pass
