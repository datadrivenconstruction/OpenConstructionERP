# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rent schedule arithmetic. Pure: no database, no FastAPI.

A lease bills ``rent_amount`` per period of its ``frequency`` (monthly,
quarterly, semiannual, annual), in advance, from ``start`` to ``end``. Periods
are anchored on the start date and step in calendar months: a lease starting on
31 January has periods starting 28/29 February, 31 March, 30 April. A start on
the last day of a month keeps every period on the last day.

Escalation compounds every ``escalation_every_months`` counted from the start:

* ``none``: the rent never changes.
* ``fixed``: each review raises the rent by ``escalation_rate`` percent.
* ``index``: each review raises it by the rate recorded for that review (a
  review event names the index movement). A review with no recorded rate does
  not move the rent; it is never guessed.

A last period cut short by the end date is prorated by days. Money is
:class:`~decimal.Decimal` throughout and each line is rounded half up to cents.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

FREQUENCY_MONTHS: dict[str, int] = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}
ESCALATION_KINDS = ("none", "fixed", "index")

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class ScheduleLineSpec:
    """One rent period as the schedule wants it."""

    seq: int
    period_start: date
    period_end: date
    due_date: date
    amount: Decimal
    tax_amount: Decimal
    review_number: int


def _is_month_end(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def add_months(anchor: date, months: int) -> date:
    """``anchor`` moved by whole calendar months, clamped to the month end.

    When ``anchor`` is itself the last day of its month the result is the last
    day of the target month, so a lease from 30 April runs 30 April, 31 May,
    30 June rather than drifting to the 30th.
    """
    total = anchor.month - 1 + months
    year, month = anchor.year + total // 12, total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    if _is_month_end(anchor):
        return date(year, month, last)
    return date(year, month, min(anchor.day, last))


def term_months(start: date, end: date) -> int:
    """Whole months from ``start`` to the day after ``end`` (an end on 31 Dec of a 1 Jan lease is 12)."""
    after = end + timedelta(days=1)
    months = (after.year - start.year) * 12 + (after.month - start.month)
    if add_months(start, months) > after:
        months -= 1
    return max(months, 0)


def q2(value: Decimal) -> Decimal:
    """Round half up to cents."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def escalation_factor(
    review_number: int,
    *,
    kind: str,
    rate: Decimal | None,
    index_rates: Mapping[int, Decimal] | None = None,
) -> Decimal:
    """Compound factor after ``review_number`` reviews (0 = the starting rent)."""
    factor = Decimal("1")
    if kind == "none" or review_number <= 0:
        return factor
    for n in range(1, review_number + 1):
        if kind == "fixed":
            step = rate or Decimal("0")
        else:
            step = (index_rates or {}).get(n, Decimal("0"))
        factor *= Decimal("1") + step / _HUNDRED
    return factor


def build_schedule(
    *,
    start: date,
    end: date,
    rent_amount: Decimal,
    frequency: str,
    escalation_kind: str = "none",
    escalation_rate: Decimal | None = None,
    escalation_every_months: int = 12,
    index_rates: Mapping[int, Decimal] | None = None,
    tax_rate: Decimal | None = None,
) -> list[ScheduleLineSpec]:
    """Every rent period of the lease, in order.

    Raises:
        ValueError: on an unknown frequency or escalation kind, or end before start.
    """
    if frequency not in FREQUENCY_MONTHS:
        raise ValueError(f"unknown frequency: {frequency}")
    if escalation_kind not in ESCALATION_KINDS:
        raise ValueError(f"unknown escalation kind: {escalation_kind}")
    if end < start:
        raise ValueError("end is before start")
    step = FREQUENCY_MONTHS[frequency]
    every = max(int(escalation_every_months or 12), 1)
    tax = tax_rate or Decimal("0")
    lines: list[ScheduleLineSpec] = []
    i = 0
    while True:
        p_start = add_months(start, i * step)
        if p_start > end:
            break
        full_end = add_months(start, (i + 1) * step) - timedelta(days=1)
        p_end = min(full_end, end)
        months_from_start = i * step
        review = months_from_start // every
        base = rent_amount * escalation_factor(
            review, kind=escalation_kind, rate=escalation_rate, index_rates=index_rates
        )
        if p_end < full_end:
            full_days = (full_end - p_start).days + 1
            base = base * Decimal((p_end - p_start).days + 1) / Decimal(full_days)
        amount = q2(base)
        lines.append(
            ScheduleLineSpec(
                seq=i + 1,
                period_start=p_start,
                period_end=p_end,
                due_date=p_start,
                amount=amount,
                tax_amount=q2(amount * tax / _HUNDRED),
                review_number=review,
            )
        )
        i += 1
    return lines
