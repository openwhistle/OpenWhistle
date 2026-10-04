"""The two deadlines of §17 HinSchG, computed in one place.

- Acknowledgement: at the latest seven days after receipt (Abs. 1 Nr. 1).
- Feedback: within three months of the acknowledgement or, without one,
  three months and seven days after receipt (Abs. 2).

Months are calendar months (§188 BGB): 31 January + 1 month is 28 or 29
February, not 3 March. The feedback deadline used to be ``+ 90 days`` from
the acknowledgement, which is a day *later* than the statute for an
acknowledgement on 31 January or 1 February, and existed only once an
acknowledgement was sent — a case moved to "in review" without one had no
feedback deadline and no reminder at all. The dashboard, the case page, the
status page, the PDF and the statistics each computed "on time" and
"overdue" in their own way, and disagreed at the edges.

Receipt is stored as its UTC day (migration 006), so both deadlines run from
the start of that day: up to a day early, never late.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

ACK_DAYS = 7
FEEDBACK_MONTHS = 3
ACK_WARN_FROM_DAY = 5
FEEDBACK_WARN_DAYS = 14

State = Literal["done", "ok", "warning", "overdue"]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def add_months(dt: datetime, months: int) -> datetime:
    """``dt`` plus calendar months; a day the month lacks becomes its last."""
    month_index = dt.month - 1 + months
    year, month = dt.year + month_index // 12, month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def ack_due(submitted_at: datetime) -> datetime:
    return _aware(submitted_at) + timedelta(days=ACK_DAYS)


def feedback_due(submitted_at: datetime, acknowledged_at: datetime | None = None) -> datetime:
    """The feedback deadline. An acknowledgement never moves it later.

    Three months from a late acknowledgement would run past the receipt-based
    deadline; the earlier of the two holds.
    """
    without_ack = add_months(ack_due(submitted_at), FEEDBACK_MONTHS)
    if acknowledged_at is None:
        return without_ack
    return min(add_months(_aware(acknowledged_at), FEEDBACK_MONTHS), without_ack)


def ack_on_time(submitted_at: datetime, acknowledged_at: datetime | None) -> bool:
    return acknowledged_at is not None and _aware(acknowledged_at) <= ack_due(submitted_at)


@dataclass(frozen=True)
class Deadline:
    state: State
    due: datetime
    # Acknowledgement: the day since receipt ("Day 3/7"). Feedback: whole days
    # left, 0 on the last day. Meaningless once done.
    days: int


def ack_status(submitted_at: datetime, acknowledged_at: datetime | None, now: datetime) -> Deadline:
    due = ack_due(submitted_at)
    day = (_aware(now) - _aware(submitted_at)).days
    if acknowledged_at is not None:
        return Deadline("done", due, day)
    if _aware(now) > due:
        return Deadline("overdue", due, day)
    return Deadline("warning" if day >= ACK_WARN_FROM_DAY else "ok", due, day)


def feedback_status(due: datetime | None, closed: bool, now: datetime) -> Deadline | None:
    if due is None:
        return None
    due = _aware(due)
    left = (due - _aware(now)).days
    if closed:
        return Deadline("done", due, left)
    if _aware(now) > due:
        return Deadline("overdue", due, left)
    return Deadline("warning" if left <= FEEDBACK_WARN_DAYS else "ok", due, left)
