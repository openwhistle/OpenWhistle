"""Operator branding: one row per organisation and one default, images by hash.

Revision ID: c3e9a2d5f417
Revises: b8d5f1a7c214
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e9a2d5f417"
down_revision: str | None = "b8d5f1a7c214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]

_IMAGES = ("logo_light", "logo_dark", "favicon_32", "favicon_180")


def upgrade() -> None:
    op.create_table(
        "brand_images",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("png", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "branding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("primary_color", sa.String(7), nullable=True),
        *(
            sa.Column(name, sa.String(64), sa.ForeignKey("brand_images.sha256"), nullable=True)
            for name in _IMAGES
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_branding_default",
        "branding",
        [sa.text("(org_id IS NULL)")],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_branding_default", table_name="branding")
    op.drop_table("branding")
    op.drop_table("brand_images")
