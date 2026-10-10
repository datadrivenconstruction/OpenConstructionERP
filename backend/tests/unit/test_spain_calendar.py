# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Spain has a national holiday list, and it is deliberately the short one.

Spanish holidays are set at three levels: the State, the autonomous community
and the municipality. A function keyed by country can only return what is the
same everywhere, which is the nine national days no community may replace
(Real Decreto 2001/1983, art. 45.1 (a) to (c)). These tests hold the engine to
exactly that set and to saying so, and they pin the days it leaves out by
name, so the short list is never read as the calendar of a Spanish site.

The expectation for 2025 and 2026 is copied from the labour calendar the
Dirección General de Trabajo publishes each year, where these days carry the
mark "Fiesta Nacional no sustituible". No resolution for 2027 existed when
this was written, so 2027 to 2030 are checked against the rule of art. 45 and
a published table of Easter Sundays.
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
from app.core.country_coverage import COVERED, country_coverage
from app.core.provenance import Source
from app.modules.schedule.service import WORK_CALENDARS, _get_work_week, calendar_holiday_dates

_SEED = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

#: Real Decreto 2001/1983, art. 45.1 (a), (b) and (c), the fixed days, read
#: 2026-10-10 at https://www.boe.es/buscar/act.php?id=BOE-A-1983-20906
_FIXED = [(1, 1), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)]

#: The rows marked "Fiesta Nacional no sustituible" in every community.
#: 2025: Resolución de 15 de octubre de 2024, BOE-A-2024-21316,
#: https://www.boe.es/diario_boe/txt.php?id=BOE-A-2024-21316
#: 2026: Resolución de 17 de octubre de 2025, BOE-A-2025-21667,
#: https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-21667
#: Both read 2026-10-10. A national day that falls on a Sunday has no row of
#: its own in the table: 12 October in 2025, 1 November and 6 December in 2026.
_BOE_NOT_REPLACEABLE = {
    2025: {
        date(2025, 1, 1),
        date(2025, 4, 18),  # Viernes Santo
        date(2025, 5, 1),
        date(2025, 8, 15),
        date(2025, 11, 1),
        date(2025, 12, 6),
        date(2025, 12, 8),
        date(2025, 12, 25),
    },
    2026: {
        date(2026, 1, 1),
        date(2026, 4, 3),  # Viernes Santo
        date(2026, 5, 1),
        date(2026, 8, 15),
        date(2026, 10, 12),
        date(2026, 12, 8),
        date(2026, 12, 25),
    },
}

#: Easter Sunday, from the United States Census Bureau table "Easter Dates from
#: 1600 to 2099", read 2026-10-10:
#: https://www.census.gov/data/software/x13as/genhol/easter-dates.html
_PUBLISHED_EASTER = {
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
    2027: date(2027, 3, 28),
    2028: date(2028, 4, 16),
    2029: date(2029, 4, 1),
    2030: date(2030, 4, 21),
}

#: Good Friday written out by hand, two days before each Easter Sunday above.
_PUBLISHED_GOOD_FRIDAY = {
    2025: date(2025, 4, 18),
    2026: date(2026, 4, 3),
    2027: date(2027, 3, 26),
    2028: date(2028, 4, 14),
    2029: date(2029, 3, 30),
    2030: date(2030, 4, 19),
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cal._holiday_cache.clear()
    yield
    cal._holiday_cache.clear()


def _holidays(year: int) -> set[date]:
    return set(resolve_holidays("ES", year)["dates"])


# ── Against the published labour calendar ────────────────────────────────────


@pytest.mark.parametrize("year", sorted(_BOE_NOT_REPLACEABLE))
def test_the_days_off_sunday_are_the_ones_the_labour_calendar_marks_not_replaceable(year: int) -> None:
    off_sunday = {d for d in _holidays(year) if d.weekday() != 6}
    assert off_sunday == _BOE_NOT_REPLACEABLE[year]


@pytest.mark.parametrize("year", sorted(_BOE_NOT_REPLACEABLE))
def test_the_labour_calendar_and_the_easter_table_agree_on_good_friday(year: int) -> None:
    """Two sources that do not know of each other, so neither is trusted alone."""
    assert _PUBLISHED_GOOD_FRIDAY[year] in _BOE_NOT_REPLACEABLE[year]
    assert _PUBLISHED_GOOD_FRIDAY[year] == _PUBLISHED_EASTER[year] - timedelta(days=2)


# ── Against the rule, for the years with no resolution yet ───────────────────


@pytest.mark.parametrize("year", sorted(_PUBLISHED_GOOD_FRIDAY))
def test_the_holidays_are_the_nine_days_of_article_45(year: int) -> None:
    expected = {date(year, month, day) for month, day in _FIXED} | {_PUBLISHED_GOOD_FRIDAY[year]}
    assert _holidays(year) == expected
    assert len(expected) == 9
    assert _PUBLISHED_GOOD_FRIDAY[year].weekday() == 4


# ── What a national list cannot hold ─────────────────────────────────────────


def test_the_days_a_community_may_replace_are_left_out() -> None:
    """Art. 45.1 (d): Holy Thursday, Epiphany, and Saint Joseph or Saint James."""
    holidays = _holidays(2026)
    for left_out in (date(2026, 4, 2), date(2026, 1, 6), date(2026, 3, 19), date(2026, 7, 25)):
        assert left_out not in holidays, left_out
    assert is_working_day(date(2026, 1, 6), "ES")  # a Tuesday, and a holiday in most of Spain


def test_a_sunday_holiday_stays_on_its_date_and_the_monday_is_not_added() -> None:
    """Art. 45.2 moves the rest to Monday, art. 45.3 lets a community replace it.

    1 November and 6 December 2026 are Sundays. The 2026 labour calendar lists
    2 November and 7 December as national days kept only where a community
    did not replace them, so they are not days common to all of Spain.
    """
    holidays = _holidays(2026)
    assert {date(2026, 11, 1), date(2026, 12, 6)} <= holidays
    for monday in (date(2026, 11, 2), date(2026, 12, 7)):
        assert monday not in holidays
        assert is_working_day(monday, "ES")


def test_community_and_local_days_are_left_out() -> None:
    """Named in the 2026 labour calendar as days of single communities."""
    holidays = _holidays(2026)
    for community_day in (date(2026, 2, 28), date(2026, 5, 2), date(2026, 9, 11), date(2026, 10, 9)):
        assert community_day not in holidays, community_day


def test_the_function_says_it_is_not_the_calendar_of_any_place() -> None:
    doc = cal._holidays_es.__doc__ or ""
    assert "NOT the calendar of any place in Spain" in doc
    for needle in ("community", "local days", "art. 45"):
        assert needle in doc, needle


# ── The working week ─────────────────────────────────────────────────────────


def test_the_week_is_monday_to_friday() -> None:
    assert cal._WORKING_WEEK["ES"] == frozenset({0, 1, 2, 3, 4})
    assert is_working_day(date(2026, 10, 9), "ES")  # Friday
    assert not is_working_day(date(2026, 10, 10), "ES")  # Saturday
    assert not is_working_day(date(2026, 10, 11), "ES")  # Sunday
    assert not is_working_day(date(2026, 10, 12), "ES")  # Monday, Fiesta Nacional de España


def test_the_planning_week_and_the_statutory_week_now_name_the_same_days() -> None:
    """Both registries resolve for Spain, so this agreement is a measured one."""
    planning = _get_work_week("ES")
    assert planning is WORK_CALENDARS["SPAIN"]
    assert frozenset(planning["work_days"]) == cal._WORKING_WEEK["ES"]


def test_a_spanish_programme_is_now_planned_around_the_national_holidays() -> None:
    """The planner takes its holidays from this engine, which had none for Spain."""
    assert calendar_holiday_dates("ES", 2026) == frozenset(_holidays(2026))
    assert date(2026, 12, 8) in calendar_holiday_dates("ES", 2026)


# ── Provenance ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("year", [2025, 2030, 2045])
def test_every_year_is_answered_by_spains_own_table(year: int) -> None:
    result = resolve_holidays("ES", year)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED
    assert result[AXIS_HOLIDAY_EXTENT].source is Source.DECLARED
    assert result["omitted"] == ()


def test_spain_is_served_by_its_own_function() -> None:
    assert cal._canonical_holiday_country("ES") == "ES"
    assert "ES" not in cal._CURATED_TABLES


# ── Against the shipped calendar ─────────────────────────────────────────────


def test_the_shipped_2026_calendar_holds_the_national_days_and_two_replaceable_ones() -> None:
    row = next(c for c in json.loads(_SEED.read_text(encoding="utf-8")) if c["country_code"] == "ES")
    assert row["year"] == "2026"
    seeded = {date.fromisoformat(entry["date"]) for entry in row["exceptions"]}
    assert _holidays(2026) <= seeded
    assert seeded - _holidays(2026) == {date(2026, 1, 6), date(2026, 4, 2)}  # Epiphany, Holy Thursday


# ── Coverage ─────────────────────────────────────────────────────────────────


def test_the_country_report_shows_what_spain_now_has() -> None:
    report = {d.dimension: d.verdict for d in country_coverage("ES").dimensions}
    for dimension in (
        "calendar.holiday_functions",
        "calendar.working_week",
        "calendar.schedule_regions",
        "calendar.seeded_rows",
        "payment.prompt_payment_regime",
        "tax.vat_rate_table",
        "tax.rates",
    ):
        assert report[dimension] == COVERED, dimension
