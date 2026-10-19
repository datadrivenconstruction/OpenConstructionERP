# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Counting a period of days on a stated basis. Pure functions, standard library only.

A contractual or statutory period is either a run of calendar days or a run of
working days, and which one it is changes the answer by several days. This
module owns that arithmetic for the whole platform so that a deadline computed
by one engine equals the same deadline computed by another.

It was extracted verbatim from :mod:`app.modules.payment_clock.clock`, which
still re-exports both names and remains the place where the payment sequence is
argued. It lives in ``app.core`` rather than in that module because the notice
and time-bar engine in ``oe_change_intelligence`` needs the same arithmetic, and
``oe_payment_clock`` is a *regional* module whose manifest states that a
deployment outside a security-of-payment jurisdiction should be able to switch
it off. A controls module must not stop counting deadlines because a regional
one was removed.

**Business days are Monday to Friday minus a calendar the deployment supplies.**
Public holidays are deliberately not shipped here: they differ by jurisdiction
and change every year, and a wrong holiday list is worse than an honest
weekends-only count because it produces a date nobody can reproduce. Callers
with a holiday calendar pass it as ``holidays``. A country whose week is not
Monday to Friday passes its working weekdays as ``working_week`` (Monday is
0), which :func:`working_week_for` reads from the country table in
:mod:`app.core.calendar`, so the two modules never disagree on the week.

That decision is what separates this module from :mod:`app.core.calendar`, which
does ship per-country holiday tables and counts on a *scheduling* convention: it
rolls a start date that is not a working day forward before counting, and its
result is inclusive of the start. Here, day one is the day after the start date,
which is how the statutes and contracts these periods come from are counted and
how a court reads them. The two conventions give different answers whenever a
period starts on a weekend, so they are not interchangeable and neither is
wrong - they answer different questions. Use this module for a deadline and
``app.core.calendar`` for a schedule.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

#: Monday to Friday, Monday being 0.
MONDAY_TO_FRIDAY: frozenset[int] = frozenset({0, 1, 2, 3, 4})

#: The two bases a period can be counted on.
CALENDAR = "calendar"
BUSINESS = "business"


def working_week_for(country_code: str | None) -> frozenset[int]:
    """The working weekdays of a country (Monday is 0), Monday to Friday when it has none on file.

    Read from the working-week table of :mod:`app.core.calendar`, the one
    place the platform states a country's week. Only the week is read, never
    the holidays: this module ships no holiday list.
    """
    from app.core.calendar import _DEFAULT_WORKING_WEEK, _WORKING_WEEK  # noqa: PLC0415

    code = (country_code or "").strip().upper().split("-", 1)[0]
    return frozenset(_WORKING_WEEK.get(code, _DEFAULT_WORKING_WEEK))


def is_business_day(
    day: date,
    holidays: Iterable[date] = (),
    working_week: frozenset[int] = MONDAY_TO_FRIDAY,
) -> bool:
    """Whether ``day`` counts as a business (working) day."""
    return day.weekday() in working_week and day not in set(holidays)


def add_days(
    start: date,
    days: int,
    basis: str = CALENDAR,
    holidays: Iterable[date] = (),
    working_week: frozenset[int] = MONDAY_TO_FRIDAY,
) -> date:
    """``start`` plus ``days``, counted on ``basis``.

    ``days`` may be negative, which counts backwards on the same basis. Zero
    returns ``start`` untouched on either basis - a statute that makes the sum
    due on the day the claim is served means that day, weekend or not.

    Args:
        start: The date the period runs from.
        days: How many days, positive forwards and negative backwards.
        basis: ``"calendar"`` or ``"business"``.
        holidays: Days that are not business days beyond the weekend.
        working_week: The weekdays that are business days, Monday being 0.

    Returns:
        The end of the period.

    Raises:
        ValueError: If ``basis`` is not one of the two known bases.
    """
    if basis == CALENDAR:
        return start + timedelta(days=days)
    if basis != BUSINESS:
        raise ValueError(f"Unknown day basis {basis!r}; expected 'calendar' or 'business'.")
    if days == 0:
        return start
    holiday_set = set(holidays)
    step = 1 if days > 0 else -1
    remaining = abs(days)
    current = start
    while remaining:
        current = current + timedelta(days=step)
        if is_business_day(current, holiday_set, working_week):
            remaining -= 1
    return current


__all__ = ["BUSINESS", "CALENDAR", "MONDAY_TO_FRIDAY", "add_days", "is_business_day", "working_week_for"]
