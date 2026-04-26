"""Make admin_users.password_hash nullable; add ldap_username for LDAP-authenticated admins.

Revision ID: 011
Revises: 010
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "admin_users", "password_hash",
        existing_type=sa.String(72),
        nullable=True,
    )
    op.add_column(
        "admin_users",
        sa.Column("ldap_username", sa.String(255), nullable=True, unique=True),
    )
    op.create_unique_constraint("uq_admin_users_ldap_username", "admin_users", ["ldap_username"])


def downgrade() -> None:
    op.drop_constraint("uq_admin_users_ldap_username", "admin_users", type_="unique")
    op.drop_column("admin_users", "ldap_username")
    op.alter_column(
        "admin_users", "password_hash",
        existing_type=sa.String(72),
        nullable=False,
    )
