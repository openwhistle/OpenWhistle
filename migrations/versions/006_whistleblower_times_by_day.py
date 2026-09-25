"""Whistleblower-originated times are stored as the day.

Revision ID: c3e8a2b6d403
Revises: b2d7f1a5c302
Create Date: 2026-09-24

Report submission, the receipt message, whistleblower messages and attachment
uploads keep only their UTC day. Messages stay in their original order: a
rounded time is moved just after the previous message when needed. Running it
again changes nothing.

Downgrade is a no-op on data: the rounding is lossy and the exact times are not
kept anywhere, by design. The schema is unchanged, so the older code reads the
rounded values as they are.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import context, op

revision: str = "c3e8a2b6d403"
down_revision: str | None = "b2d7f1a5c302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TICK = timedelta(microseconds=1)
log = logging.getLogger("alembic.runtime.migration")


def _day(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def retime(
    rows: list[tuple[object, str, datetime]], first_id: object
) -> list[tuple[object, datetime]]:
    """New ``sent_at`` per message; rows are ``(id, sender, sent_at)`` in thread
    order and ``first_id`` is the receipt, whose time is the submission's."""
    out: list[tuple[object, datetime]] = []
    prev: datetime | None = None
    for msg_id, sender, sent_at in rows:
        new = _day(sent_at) if sender == "whistleblower" or msg_id == first_id else sent_at
        if prev is not None and new <= prev:
            new = prev + _TICK
        out.append((msg_id, new))
        prev = new
    return out


def upgrade() -> None:
    for table, column in (("reports", "submitted_at"), ("attachments", "uploaded_at")):
        op.execute(sa.text(
            f"UPDATE {table} SET {column} = "  # noqa: S608 — fixed identifiers, no input
            f"date_trunc('day', {column} AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        ))
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    report_ids = [r for (r,) in bind.execute(sa.text("SELECT id FROM reports")).tuples()]
    for report_id in report_ids:
        try:
            with bind.begin_nested():
                rows = list(bind.execute(sa.text(
                    "SELECT id, sender::text, sent_at FROM report_messages "
                    "WHERE report_id = :r ORDER BY sent_at, id"
                ), {"r": report_id}).tuples())
                if not rows:
                    continue
                for (msg_id, new), (_, _, old) in zip(
                    retime(rows, first_id=rows[0][0]), rows, strict=True
                ):
                    if new != old:
                        bind.execute(
                            sa.text("UPDATE report_messages SET sent_at = :t WHERE id = :i"),
                            {"t": new, "i": msg_id},
                        )
        except sa.exc.SQLAlchemyError:
            log.exception("Migration 006: messages of report %s left as they were", report_id)


def downgrade() -> None:
    pass
