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

A deadline is the end of its last day (§§ 187 Abs. 1, 188 BGB): the day of
receipt or acknowledgement does not count, and the period ends with the last
day, not at its start. Receipt is stored as its UTC day (migration 006), which
is all the count needs. The deadlines used to start at midnight of the last
day, so an acknowledgement on the seventh day read "late" in the PDF export,
and the seven days were added before the three months: received 24 November,
the feedback was due 1 March, not 3 March.
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


def _end_of_day(dt: datetime) -> datetime:
    return _aware(dt).replace(hour=23, minute=59, second=59, microsecond=999999)


def ack_due(submitted_at: datetime) -> datetime:
    return _end_of_day(_aware(submitted_at) + timedelta(days=ACK_DAYS))


def feedback_due(submitted_at: datetime, acknowledged_at: datetime | None = None) -> datetime:
    """The feedback deadline. An acknowledgement never moves it later.

    Three months from a late acknowledgement would run past the receipt-based
    deadline; the earlier of the two holds.
    """
    receipt = _aware(submitted_at)
    without_ack = _end_of_day(add_months(receipt, FEEDBACK_MONTHS) + timedelta(days=ACK_DAYS))
    if acknowledged_at is None:
        return without_ack
    return min(_end_of_day(add_months(_aware(acknowledged_at), FEEDBACK_MONTHS)), without_ack)


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


def feedback_status(
    due: datetime | None, feedback_sent_at: datetime | None, now: datetime
) -> Deadline | None:
    """Done once the office wrote to the reporter after the acknowledgement
    (``Report.feedback_sent_at``). It used to be done once the case was closed: a
    case closed without a word read "Delivered", and an answered one "Overdue"."""
    if due is None:
        return None
    due = _aware(due)
    left = (due - _aware(now)).days
    if feedback_sent_at is not None:
        return Deadline("done", due, left)
    if _aware(now) > due:
        return Deadline("overdue", due, left)
    return Deadline("warning" if left <= FEEDBACK_WARN_DAYS else "ok", due, left)
