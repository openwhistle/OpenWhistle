"""§ 17 feedback is the office's first message after the acknowledgement; deadlines end
with their last day.

``reports.feedback_sent_at`` records when feedback was given; "Delivered" used to mean
"closed". ``feedback_due_at`` is recomputed: it began at midnight of its last day, and
without an acknowledgement the seven days were added before the three months
(§§ 187, 188 BGB).

Revision ID: e7a2c9f4b310
Revises: d4f1b8c6e203
Create Date: 2026-10-28
"""

import calendar
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "e7a2c9f4b310"
down_revision: str | None = "d4f1b8c6e203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]


# The formula as of this revision, copied so a later change to the app cannot rewrite it.
def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year, month = dt.year + month_index // 12, month_index % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def _end_of_day(dt: datetime) -> datetime:
    return _aware(dt).replace(hour=23, minute=59, second=59, microsecond=999999)


def _feedback_due(submitted_at: datetime, acknowledged_at: datetime | None) -> datetime:
    without_ack = _end_of_day(_add_months(_aware(submitted_at), 3) + timedelta(days=7))
    if acknowledged_at is None:
        return without_ack
    return min(_end_of_day(_add_months(_aware(acknowledged_at), 3)), without_ack)


def upgrade() -> None:
    op.add_column(
        "reports", sa.Column("feedback_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE reports r SET feedback_sent_at = ("
            " SELECT min(m.sent_at) FROM report_messages m"
            " WHERE m.report_id = r.id AND m.sender = 'admin' AND m.sent_at > r.acknowledged_at"
            ") WHERE r.acknowledged_at IS NOT NULL"
        )
    )
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, submitted_at, acknowledged_at FROM reports")).all()
    for row in rows:
        conn.execute(
            sa.text("UPDATE reports SET feedback_due_at = :due WHERE id = :id"),
            {"due": _feedback_due(row.submitted_at, row.acknowledged_at), "id": row.id},
        )


def downgrade() -> None:
    op.drop_column("reports", "feedback_sent_at")
