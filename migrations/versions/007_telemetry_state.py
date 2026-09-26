"""Installation-count state.

Revision ID: d4f9b3c7e504
Revises: c3e8a2b6d403
Create Date: 2026-09-26

One row: whether an admin agreed to the daily installation count, the random
identifier it sends, and when a report last succeeded. No row is created here:
an installation upgrading to 2.0.0 was never asked, so it stays off until an
admin switches it on. Downgrade drops the table; nothing else refers to it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f9b3c7e504"
down_revision: str | None = "c3e8a2b6d403"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("installation_id", sa.String(32), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="telemetry_state_single_row"),
    )


def downgrade() -> None:
    op.drop_table("telemetry_state")
