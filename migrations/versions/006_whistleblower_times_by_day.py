"""Whistleblower-originated times are stored as the day.

Revision ID: c3e8a2b6d403
Revises: b2d7f1a5c302
Create Date: 2026-09-24

Report submission, the receipt message (a report's first), whistleblower
messages and attachment uploads keep only their UTC day. Three set-based
UPDATEs, so it also runs offline (``--sql``).

Messages keep their order. Per report, with n the 1-based position in the old
order and r the rounded (reporter) or unchanged (office) time, the new time is

    new(n) = max over k <= n of (r(k) + (n - k) µs)

- the least increasing sequence with new >= r: a rounded message that would
sort before its predecessor moves one microsecond after it. Running it again
changes nothing.

Downgrade is a no-op on data: the rounding is lossy and the exact times are not
kept anywhere, by design. The schema is unchanged, so the older code reads the
rounded values as they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8a2b6d403"
down_revision: str | None = "b2d7f1a5c302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DAY = "date_trunc('day', {col} AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"

_MESSAGES = f"""
WITH ranked AS (
    SELECT id, report_id, sender, sent_at,
           row_number() OVER (PARTITION BY report_id ORDER BY sent_at, id) AS n
    FROM report_messages
), rounded AS (
    SELECT id, report_id, n,
           CASE WHEN n = 1 OR sender = 'whistleblower'
                THEN {_DAY.format(col="sent_at")} ELSE sent_at END AS r
    FROM ranked
), retimed AS (
    SELECT id,
           max(r - n * interval '1 microsecond')
               OVER (PARTITION BY report_id ORDER BY n)
           + n * interval '1 microsecond' AS new
    FROM rounded
)
UPDATE report_messages m SET sent_at = retimed.new
FROM retimed
WHERE m.id = retimed.id AND m.sent_at <> retimed.new
"""  # noqa: S608 — fixed SQL, no input


def upgrade() -> None:
    for table, column in (("reports", "submitted_at"), ("attachments", "uploaded_at")):
        op.execute(sa.text(
            f"UPDATE {table} SET {column} = {_DAY.format(col=column)} "  # noqa: S608 — fixed names
            f"WHERE {column} <> {_DAY.format(col=column)}"
        ))
    op.execute(sa.text(_MESSAGES))


def downgrade() -> None:
    pass
