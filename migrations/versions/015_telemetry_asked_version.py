"""Admins remember the release that last asked them to count the installation.

Revision ID: f6b3d9e5a012
Revises: e5a2c8d4f011
Create Date: 2026-10-12

After an update the dashboard asks once, per admin who may switch the count, while
it is off: the column holds the version that asked. Empty means never asked, so
the first dashboard after this migration asks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6b3d9e5a012"
down_revision: str | None = "e5a2c8d4f011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("telemetry_asked_version", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_users", "telemetry_asked_version")
