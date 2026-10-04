"""Every report's feedback deadline follows §17 Abs. 2 HinSchG.

Revision ID: a7c2e6f0b807
Revises: f6b1d5e9a706
Create Date: 2026-09-27

Three calendar months from the acknowledgement or, without one, three months
and seven days from receipt; an acknowledgement never moves it later (see
app/services/deadlines.py). It used to be ``acknowledged_at + 90 days`` and
unset for a report never acknowledged. PostgreSQL's ``interval '3 months'``
clamps to the month's last day, as ``add_months`` does.

Downgrade restores the old rule; nothing else depended on it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c2e6f0b807"
down_revision: str | None = "f6b1d5e9a706"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE reports SET feedback_due_at = LEAST("
        "acknowledged_at + interval '3 months',"
        " (submitted_at + interval '7 days') + interval '3 months')"
        " WHERE acknowledged_at IS NOT NULL"
    )
    op.execute(
        "UPDATE reports SET feedback_due_at ="
        " (submitted_at + interval '7 days') + interval '3 months'"
        " WHERE acknowledged_at IS NULL"
    )


def downgrade() -> None:
    op.execute("UPDATE reports SET feedback_due_at = acknowledged_at + interval '90 days'")
