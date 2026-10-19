# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Offline issuing and the deadline for sending the invoice to KSeF afterwards.

The modes and their periods are rows in :data:`facts.OFFLINE_MODES`, read from
https://github.com/CIRFMF/ksef-docs/blob/main/tryby-offline.md (10.07.2025):

* offline24: the next business day after the issue date (P_1);
* offline (announced unavailability): the next business day after it ends;
* awaria (announced failure): 7 business days after it ends;
* awaria calkowita (total failure): no upload obligation, no QR codes.

A failure announced while an offline24 or offline invoice is still waiting moves
its deadline to 7 business days after the end of that failure.

Business days come from :func:`app.core.calendar.add_working_days` for ``PL``.
That table has no Polish public holidays yet, so a computed deadline can land on
a holiday. That makes it earlier than the statutory one, never later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.calendar import add_working_days, resolve_holidays
from app.modules.einvoice_ksef.facts import (
    FAILURE_DURING_WAIT_BUSINESS_DAYS,
    OFFLINE24,
    OFFLINE_FAILURE,
    OFFLINE_MODES,
    OFFLINE_TOTAL_FAILURE,
    OfflineMode,
)

COUNTRY = "PL"


class OfflineError(ValueError):
    """The mode or the dates do not describe an offline issue the law knows."""


@dataclass(frozen=True)
class UploadDeadline:
    mode: str
    # ``None`` for total failure: there is nothing to send.
    due: date | None
    counted_from: date | None
    business_days: int | None
    # Whether the calendar knew Polish public holidays when it counted.
    holidays_known: bool
    explanation: str


def mode(key: str) -> OfflineMode:
    """The offline mode named ``key``."""
    found = OFFLINE_MODES.get((key or "").strip().lower())
    if found is None:
        raise OfflineError(f"{key!r} is not a KSeF offline mode; use one of {', '.join(OFFLINE_MODES)}")
    return found


def _holidays_known(year: int) -> bool:
    try:
        resolved = resolve_holidays(COUNTRY, year)
    except Exception:  # noqa: BLE001 - a broken calendar is "not known", and the deadline still errs early
        return False
    return bool(resolved.get("dates"))


def upload_deadline(
    key: str,
    *,
    issue_date: date,
    event_end: date | None = None,
    failure_end: date | None = None,
) -> UploadDeadline:
    """When an invoice issued in offline mode ``key`` must be in KSeF.

    Args:
        key: One of the offline mode keys.
        issue_date: P_1 of the invoice.
        event_end: For ``offline`` and ``awaria``, the day the announced
            unavailability or failure ended. Required for those modes.
        failure_end: The end of a failure announced while the invoice waited.
            Moves the deadline to 7 business days after it.
    """
    chosen = mode(key)
    if chosen.key == OFFLINE_TOTAL_FAILURE:
        return UploadDeadline(
            chosen.key,
            None,
            None,
            None,
            _holidays_known(issue_date.year),
            "Total failure: the invoice is delivered the agreed way and is not sent to KSeF afterwards.",
        )
    if failure_end is not None:
        start, days = failure_end, FAILURE_DURING_WAIT_BUSINESS_DAYS
        why = f"a failure ended on {failure_end.isoformat()}, which restarts the count at {days} business days"
    elif chosen.counted_from == "issue":
        start, days = issue_date, int(chosen.upload_business_days or 0)
        why = f"{chosen.label}: {days} business day(s) after the issue date"
    else:
        if event_end is None:
            raise OfflineError(f"{chosen.label} is counted from the end of the announced event; give its end date")
        if event_end < issue_date and chosen.key == OFFLINE_FAILURE:
            raise OfflineError("the failure ended before the invoice was issued, so it was not issued in that failure")
        start, days = event_end, int(chosen.upload_business_days or 0)
        why = f"{chosen.label}: {days} business day(s) after the event ended on {event_end.isoformat()}"
    # ``add_working_days`` counts from the first working day at or after its
    # start; the period runs from the day AFTER the start, so step past it.
    due = add_working_days(start, days, COUNTRY) if _is_working(start) else add_working_days(start, days - 1, COUNTRY)
    return UploadDeadline(chosen.key, due, start, days, _holidays_known(due.year), why)


def _is_working(day: date) -> bool:
    from app.core.calendar import is_working_day

    return is_working_day(day, COUNTRY)


def is_overdue(deadline: UploadDeadline, today: date) -> bool:
    """Whether the upload deadline has passed on ``today``."""
    return deadline.due is not None and today > deadline.due


def default_mode() -> str:
    """The mode a taxpayer can choose on its own: offline24."""
    return OFFLINE24


__all__ = [
    "COUNTRY",
    "OfflineError",
    "UploadDeadline",
    "default_mode",
    "is_overdue",
    "mode",
    "upload_deadline",
]
