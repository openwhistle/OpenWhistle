"""Organisations lose the branding column.

Revision ID: e5a2c8d4f011
Revises: d4f1b7c3e010
Create Date: 2026-10-11

Declared in 001 as "optional JSON branding overrides", it was never read or
written: every page takes its colour and logo from BRAND_PRIMARY_COLOR and
BRAND_LOGO_URL. Downgrade adds it back, empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a2c8d4f011"
down_revision: str | None = "d4f1b7c3e010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("organisations", "branding")


def downgrade() -> None:
    op.add_column("organisations", sa.Column("branding", sa.JSON(), nullable=True))
