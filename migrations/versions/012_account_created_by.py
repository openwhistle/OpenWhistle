"""Record who made an account.

Revision ID: c9e4a8b2d009
Revises: b8d3f7a1c908
Create Date: 2026-09-27

Whoever makes an account on /admin/users chooses its first password and can
sign in with it before the holder does. The four-eyes deletion now refuses a
confirmation between an account and one it made, directly or through others.
Existing accounts get their creator from the audit log (``admin.created``
names the new username in its detail).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c9e4a8b2d009"
down_revision: str | None = "b8d3f7a1c908"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE admin_users u SET created_by_id = a.admin_id FROM audit_log a"
        " WHERE a.action = 'admin.created' AND a.admin_id IS NOT NULL"
        " AND a.admin_id <> u.id"
        " AND lower(a.detail::json->>'username') = lower(u.username)"
    )


def downgrade() -> None:
    op.drop_column("admin_users", "created_by_id")
