# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hungary has a holiday calendar of its own, and says what it leaves out.

Until this file the engine had no Hungarian table and the seed had no
Hungarian row, so a project in Hungary was planned on a Monday to Friday week
with no public holidays at all.

The days are Labour Code (2012. évi I. törvény) 102. § (1), read on
2026-10-10 at https://njt.jog.gov.hu/jogszabaly/2012-1-00-00 in the text
consolidated to 2026-10-01. Three of them move with Easter, so the expected
dates below are written out from a published table of Easter Sundays and not
from the library the engine computes with.

What the engine does not hold is the yearly decree that swaps working days
around the holidays. The tests at the end pin that gap by its real dates, so
nobody reads the green suite as covering it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core import calendar as cal
from app.core.calendar import (
    AXIS_EFFECTIVE_YEAR,
    AXIS_HOLIDAY_EXTENT,
    AXIS_JURISDICTION,
    is_working_day,
    resolve_holidays,
)
from app.core.country_coverage import COVERED, FALLBACK, country_coverage
from app.core.provenance import Source

_SEED = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

#: The fixed days of 102. § (1), as (month, day).
_FIXED = [(1, 1), (3, 15), (5, 1), (8, 20), (10, 23), (11, 1), (12, 25), (12, 26)]

#: Easter Sunday, from the United States Census Bureau table "Easter Dates from
#: 1600 to 2099", read 2026-10-10:
#: https://www.census.gov/data/software/x13as/genhol/easter-dates.html
#: The 2025 and 2026 rows agree with the Good Fridays the Spanish labour
#: calendar resolutions print for those years (18 April 2025, 3 April 2026).
_PUBLISHED_EASTER = {
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
    2027: date(2027, 3, 28),
    2028: date(2028, 4, 16),
    2029: date(2029, 4, 1),
    2030: date(2030, 4, 21),
}

#: Good Friday, Easter Monday and Whit Monday written out by hand from the
#: Easter Sundays above (two days before, the day after, fifty days after), so
#: a wrong offset in the engine cannot agree with a wrong offset here.
_PUBLISHED_MOVABLE = {
    2025: (date(2025, 4, 18), date(2025, 4, 21), date(2025, 6, 9)),
    2026: (date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 25)),
    2027: (date(2027, 3, 26), date(2027, 3, 29), date(2027, 5, 17)),
    2028: (date(2028, 4, 14), date(2028, 4, 17), date(2028, 6, 5)),
    2029: (date(2029, 3, 30), date(2029, 4, 2), date(2029, 5, 21)),
    2030: (date(2030, 4, 19), date(2030, 4, 22), date(2030, 6, 10)),
}

#: The yearly rearrangement, as (working Saturday, rest day).
#: 2025: 11/2024. (IV. 8.) NGM rendelet, https://njt.jog.gov.hu/jogszabaly/2024-11-20-2X
#: 2026: 10/2025. (IV. 30.) NGM rendelet, https://njt.jog.gov.hu/jogszabaly/2025-10-20-2X
#: Both read 2026-10-10. No decree for 2027 was found on that date.
_DECREED_SWAPS = {
    2025: (
        (date(2025, 5, 17), date(2025, 5, 2)),
        (date(2025, 10, 18), date(2025, 10, 24)),
        (date(2025, 12, 13), date(2025, 12, 24)),
    ),
    2026: (
        (date(2026, 1, 10), date(2026, 1, 2)),
        (date(2026, 8, 8), date(2026, 8, 21)),
        (date(2026, 12, 12), date(2026, 12, 24)),
    ),
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cal._holiday_cache.clear()
    yield
    cal._holiday_cache.clear()


def _holidays(year: int) -> set[date]:
    return set(resolve_holidays("HU", year)["dates"])


# ── The published tables are consistent with themselves ──────────────────────


@pytest.mark.parametrize("year", sorted(_PUBLISHED_EASTER))
def test_the_written_out_movable_days_follow_the_published_easter(year: int) -> None:
    easter_sunday = _PUBLISHED_EASTER[year]
    good_friday, easter_monday, whit_monday = _PUBLISHED_MOVABLE[year]
    assert easter_sunday.weekday() == 6
    assert good_friday == easter_sunday - timedelta(days=2) and good_friday.weekday() == 4
    assert easter_monday == easter_sunday + timedelta(days=1) and easter_monday.weekday() == 0
    assert whit_monday == easter_sunday + timedelta(days=50) and whit_monday.weekday() == 0


# ── The days of 102. § (1) ───────────────────────────────────────────────────


@pytest.mark.parametrize("year", sorted(_PUBLISHED_MOVABLE))
def test_the_holidays_are_the_eleven_days_the_labour_code_names(year: int) -> None:
    expected = {date(year, month, day) for month, day in _FIXED} | set(_PUBLISHED_MOVABLE[year])
    assert _holidays(year) == expected
    assert len(expected) == 11


def test_good_friday_is_a_holiday_only_from_the_year_it_was_added() -> None:
    """2017. évi XIII. törvény added it, in force from 24 March 2017.

    These two years are outside the published table above, so the Friday is
    taken from the engine's own Easter: the test is of the year gate, not of
    the date.
    """
    for year, expected in ((2016, False), (2017, True), (2018, True)):
        easter_sunday = cal.easter(year)
        assert ((easter_sunday - timedelta(days=2)) in _holidays(year)) is expected, year
        assert easter_sunday + timedelta(days=1) in _holidays(year)  # Easter Monday always was one


def test_easter_sunday_and_whit_sunday_are_not_in_the_set() -> None:
    """102. § (4) rosters them like a holiday; they are Sundays either way."""
    holidays = _holidays(2026)
    assert date(2026, 4, 5) not in holidays
    assert date(2026, 5, 24) not in holidays


def test_a_holiday_on_a_weekend_is_not_moved_to_a_weekday() -> None:
    """15 March and 1 November 2026 are Sundays, 26 December a Saturday."""
    holidays = _holidays(2026)
    assert {date(2026, 3, 15), date(2026, 11, 1), date(2026, 12, 26)} <= holidays
    for monday in (date(2026, 3, 16), date(2026, 11, 2), date(2026, 12, 28)):
        assert monday not in holidays
        assert is_working_day(monday, "HU")


def test_a_holiday_week_loses_its_working_days() -> None:
    """20 August 2026 is a Thursday, 23 October 2026 a Friday."""
    assert not is_working_day(date(2026, 8, 20), "HU")
    assert is_working_day(date(2026, 8, 19), "HU")
    assert not is_working_day(date(2026, 10, 23), "HU")
    assert not is_working_day(date(2026, 4, 6), "HU")  # Easter Monday


# ── The working week ─────────────────────────────────────────────────────────


def test_the_week_is_monday_to_friday() -> None:
    """Labour Code 97. § (2): five days a week, Monday to Friday."""
    assert cal._WORKING_WEEK["HU"] == frozenset({0, 1, 2, 3, 4})
    assert is_working_day(date(2026, 10, 9), "HU")  # Friday
    assert not is_working_day(date(2026, 10, 10), "HU")  # Saturday
    assert not is_working_day(date(2026, 10, 11), "HU")  # Sunday


# ── Provenance ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("year", [2025, 2030, 2045])
def test_every_year_is_answered_by_hungarys_own_table(year: int) -> None:
    result = resolve_holidays("HU", year)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED
    assert result[AXIS_HOLIDAY_EXTENT].source is Source.DECLARED
    assert result["omitted"] == ()


def test_hungary_is_served_by_its_own_function() -> None:
    assert cal._canonical_holiday_country("HU") == "HU"
    assert "HU" not in cal._CURATED_TABLES
    assert "HU" not in cal._HIJRI_DEPENDENT


# ── Agreement with the shipped calendar ──────────────────────────────────────


def test_the_engine_and_the_shipped_2026_calendar_name_the_same_days() -> None:
    row = next(c for c in json.loads(_SEED.read_text(encoding="utf-8")) if c["country_code"] == "HU")
    assert row["year"] == "2026"
    assert row["work_days"] == [1, 2, 3, 4, 5]
    seeded = {date.fromisoformat(entry["date"]) for entry in row["exceptions"]}
    assert seeded == _holidays(2026)
    assert len(seeded) == 11


def test_the_shipped_calendar_writes_the_names_in_hungarian_letters() -> None:
    row = next(c for c in json.loads(_SEED.read_text(encoding="utf-8")) if c["country_code"] == "HU")
    names = {entry["name"]["hu"] for entry in row["exceptions"]}
    assert {"Újév", "Nagypéntek", "Húsvéthétfő", "Pünkösdhétfő", "Az államalapítás ünnepe"} <= names


# ── The gap: the yearly rearrangement of working days ────────────────────────


@pytest.mark.parametrize("year", sorted(_DECREED_SWAPS))
def test_a_decreed_swap_stays_inside_one_month_and_never_uses_a_sunday(year: int) -> None:
    """The two limits 102. § (5) puts on the decree, checked on the copied dates."""
    for working_saturday, rest_day in _DECREED_SWAPS[year]:
        assert working_saturday.weekday() == 5
        assert rest_day.weekday() < 5
        assert (working_saturday.year, working_saturday.month) == (rest_day.year, rest_day.month)


@pytest.mark.parametrize("year", sorted(_DECREED_SWAPS))
def test_the_decreed_swaps_are_not_modelled(year: int) -> None:
    """The engine counts the rest day as worked and the working Saturday as not.

    This is the documented limitation of ``_holidays_hu``, asserted so that it
    is a known wrong answer on named dates. A day is worked when its weekday
    is in the week and it is not a holiday, so a Saturday cannot be made a
    working day, and adding the rest day alone would be one half of a swap.
    When the engine learns to express a working Saturday, this test fails and
    both halves go in together.
    """
    for working_saturday, rest_day in _DECREED_SWAPS[year]:
        assert not is_working_day(working_saturday, "HU"), working_saturday
        assert is_working_day(rest_day, "HU"), rest_day
        assert rest_day not in _holidays(year)


def test_over_a_whole_month_the_missing_swap_changes_no_count() -> None:
    """Both halves fall in one month, so a month's working days still add up.

    January 2026 has 22 weekdays. The engine takes off 1 January and counts
    21. The decree takes off 2 January as well and adds Saturday the 10th,
    which is 21 again, on different days.
    """
    january = [date(2026, 1, 1) + timedelta(days=i) for i in range(31)]
    engine_days = {d for d in january if is_working_day(d, "HU")}
    working_saturday, rest_day = _DECREED_SWAPS[2026][0]
    decreed_days = (engine_days - {rest_day}) | {working_saturday}
    assert len(engine_days) == len(decreed_days) == 21
    assert engine_days != decreed_days


# ── Coverage ─────────────────────────────────────────────────────────────────


def test_the_country_report_shows_what_hungary_now_has_and_what_it_still_lacks() -> None:
    report = {d.dimension: d.verdict for d in country_coverage("HU").dimensions}
    for dimension in (
        "calendar.holiday_functions",
        "calendar.working_week",
        "calendar.seeded_rows",
        "payment.prompt_payment_regime",
        "tax.vat_rate_table",
        "tax.rates",
    ):
        assert report[dimension] == COVERED, dimension
    # The planning table has no Hungarian calendar, so the week a programme is
    # drawn on is still the default one. It names the same five days.
    assert report["calendar.schedule_regions"] == FALLBACK
