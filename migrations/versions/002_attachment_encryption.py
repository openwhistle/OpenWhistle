"""Attachments are encrypted with the report's data key.

Revision ID: 3c1f0a7e9b42
Revises: 26b6f459846b
Create Date: 2026-09-23

Existing rows keep encrypted = false and are served as stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c1f0a7e9b42"
down_revision: str | None = "26b6f459846b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("attachments", "encrypted")
