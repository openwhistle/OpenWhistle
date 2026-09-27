"""The account the setup wizard created becomes superadmin.

Revision ID: e5a0c4d8f605
Revises: d4f9b3c7e504
Create Date: 2026-09-27

Up to v2.0.0 the wizard created the first account as ``admin``, and only a
superadmin may grant superadmin, so no installation had one: organisations
and every superadmin-only page were unreachable. On an installation with no
superadmin, the earliest active admin (the one the wizard created, unless
it was deactivated) is promoted.
One that already has a superadmin is left alone. Downgrade keeps the role:
the account needs it, and a downgrade cannot tell it was granted here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a0c4d8f605"
down_revision: str | None = "d4f9b3c7e504"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE admin_users SET role = 'superadmin' "
        "WHERE id = (SELECT id FROM admin_users WHERE role = 'admin' AND is_active "
        "ORDER BY created_at, id LIMIT 1) "
        "AND NOT EXISTS (SELECT 1 FROM admin_users WHERE role = 'superadmin')"
    ))


def downgrade() -> None:
    pass
