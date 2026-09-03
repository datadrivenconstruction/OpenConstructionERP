# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Recurrence for delivery-board tasks.

Two rules that matter, both settled in the preview and mirrored here so
the server is the one place they are enforced:

1. "Monthly" means the same DAY OF THE MONTH (clamped for short months),
   never "+28 days" - a progress claim is due on the 25th, and 28-day
   stepping walks it backwards through the calendar. There is also a
   "last working day" rule because that is what claims actually run on.

2. The next occurrence is computed from the SCHEDULED date, never from
   when someone happened to tick the task. Closing Monday's toolbox talk
   on Wednesday still puts the next one on Monday; otherwise a series
   slides later every time someone is busy, which is exactly when it
   slides.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def last_working_day(year: int, month: int) -> date:
    """The last Mon-Fri of ``month`` (1-12) in ``year``."""
    day = date(year, month, calendar.monthrange(year, month)[1])
    while day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        day -= timedelta(days=1)
    return day


def next_occurrence(iso_day: str, rule: str) -> str | None:
    """The occurrence after ``iso_day`` under ``rule``, or None.

    Anchored on the schedule: callers pass the task's due date, not
    today. An unparseable day or unknown rule returns None rather than
    guessing - the caller decides whether that is an error.
    """
    if not iso_day or not rule:
        return None
    try:
        anchor = date.fromisoformat(iso_day)
    except ValueError:
        return None
    if rule == "weekly":
        return (anchor + timedelta(days=7)).isoformat()
    if rule == "fortnightly":
        return (anchor + timedelta(days=14)).isoformat()
    next_year = anchor.year + (1 if anchor.month == 12 else 0)
    next_month = 1 if anchor.month == 12 else anchor.month + 1
    if rule == "monthly-last":
        return last_working_day(next_year, next_month).isoformat()
    if rule == "monthly":
        # Clamp: the 31st becomes the 30th, or the 28th in February.
        last = calendar.monthrange(next_year, next_month)[1]
        return date(next_year, next_month, min(anchor.day, last)).isoformat()
    return None
