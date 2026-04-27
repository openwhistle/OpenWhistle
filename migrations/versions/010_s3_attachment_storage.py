"""Make attachments.data nullable; add storage_key for S3-compatible backends.

Revision ID: 010
Revises: 009
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Make data nullable — existing rows keep their data; S3-backed rows will have NULL
    op.alter_column("attachments", "data", existing_type=sa.LargeBinary(), nullable=True)

    # Add storage_key column for S3 object key (NULL for DB-backed attachments)
    op.add_column(
        "attachments",
        sa.Column("storage_key", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attachments", "storage_key")
    op.alter_column("attachments", "data", existing_type=sa.LargeBinary(), nullable=False)
