"""An account whose password someone else set must change it first.

Revision ID: f6b1d5e9a706
Revises: e5a0c4d8f605
Create Date: 2026-09-27

Whoever sets a password for someone else (an admin creating the account, a
superadmin resetting it, the host operator's reset script) knows it. The
flag makes the holder replace it before the admin area opens. Existing
accounts get ``false``: nothing records who set their password.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6b1d5e9a706"
down_revision: str | None = "e5a0c4d8f605"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("admin_users", "must_change_password")
