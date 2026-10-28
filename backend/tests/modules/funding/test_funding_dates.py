# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The date arithmetic every funding deadline is derived from.

These three functions decide when a report is due, how long money may sit
unspent, and when vouchers may be destroyed. Each of those dates is told to a
person who then plans around it, so an off-by-one here is not a rounding
error, it is a missed deadline with money attached.
"""

from __future__ import annotations

import pytest

from app.modules.funding.service import _plus_days, _plus_years, iso_day


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-03-01", "2026-03-01"),
        # Anything that has been through a timestamp still names a calendar
        # day, and that day is the one a deadline is about.
        ("2026-03-01T09:30:00+01:00", "2026-03-01"),
        ("2026-03-01 09:30:00", "2026-03-01"),
        ("  2026-03-01  ", "2026-03-01"),
        ("2024-02-29", "2024-02-29"),
    ],
)
def test_a_calendar_day_is_read_out_of_whatever_carried_it(value: str, expected: str) -> None:
    assert iso_day(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "2026-03",
        "not a date",
        "0000-00-00",
        # A day that does not exist is absent, not the nearest real one. A
        # rule that silently rounds 31 June to 30 June states a deadline the
        # source document never gave.
        "2026-06-31",
        "2026-13-01",
        "2025-02-29",
    ],
)
def test_anything_that_is_not_a_real_day_reads_as_absent(value: object) -> None:
    assert iso_day(value) == ""


def test_days_are_added_as_calendar_days() -> None:
    assert _plus_days("2026-03-01", 30) == "2026-03-31"
    assert _plus_days("2026-12-20", 30) == "2027-01-19"


def test_a_leap_day_counts_when_days_are_added_across_it() -> None:
    """2028 is a leap year, so the end of February has a twenty-ninth."""
    assert _plus_days("2028-02-27", 3) == "2028-03-01"
    assert _plus_days("2027-02-27", 3) == "2027-03-02"


@pytest.mark.parametrize(("day", "days"), [("", 30), ("nonsense", 30), ("2026-03-01", 0), ("2026-03-01", -1)])
def test_no_offset_and_no_day_both_produce_no_deadline(day: str, days: int) -> None:
    """An empty result is how the service decides not to invent an obligation."""
    assert _plus_days(day, days) == ""


def test_whole_years_keep_the_same_day_of_the_month() -> None:
    assert _plus_years("2026-03-01", 10) == "2036-03-01"
    assert _plus_years("2026-12-31", 5) == "2031-12-31"


def test_the_twenty_ninth_of_february_plus_a_year_is_the_twenty_eighth() -> None:
    """What every retention rule means, and what timedelta cannot express.

    Ten years of record keeping counted from a leap day has to land on a day
    that exists. Falling back to the twenty-eighth is the reading that never
    moves the deadline later than the terms allow.
    """
    assert _plus_years("2024-02-29", 1) == "2025-02-28"
    assert _plus_years("2024-02-29", 10) == "2034-02-28"
    # Four years later February has a twenty-ninth again, and then the
    # original day survives untouched.
    assert _plus_years("2024-02-29", 4) == "2028-02-29"


@pytest.mark.parametrize(("day", "years"), [("", 10), ("nonsense", 10), ("2026-03-01", 0), ("2026-03-01", -1)])
def test_no_retention_period_and_no_day_both_produce_no_deadline(day: str, years: int) -> None:
    assert _plus_years(day, years) == ""
