# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Türkiye has a holiday calendar of its own, on the dates offices close.

Until this file the engine had no Turkish table at all, so a Turkish project
was planned on a Monday to Friday week with no public holidays, while the
shipped 2026 calendar beside it listed fourteen. The two now have to agree.

The fixed days are Law 2429, Art. 1 and 2. The two feasts move by ten or
eleven days a year and are copied from the calendar the Diyanet İşleri
Başkanlığı publishes, so the checks here are of two kinds: dates written out
again from the source for the years most likely to be planned in, and
properties every row has to satisfy, which catch a mistyped row without
needing the source.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core import calendar as cal
from app.core.calendar import AXIS_EFFECTIVE_YEAR, AXIS_JURISDICTION, is_working_day, resolve_holidays
from app.core.provenance import Source

_SEED = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

_FIXED = [(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)]

#: First day of Ramazan Bayramı and of Kurban Bayramı, written out a second
#: time from the Diyanet "Resmi Tatiller" pages rather than read back from the
#: table under test.
_PUBLISHED_FIRST_DAYS = {
    2025: (date(2025, 3, 30), date(2025, 6, 6)),
    2026: (date(2026, 3, 20), date(2026, 5, 27)),
    2027: (date(2027, 3, 9), date(2027, 5, 16)),
    2028: (date(2028, 2, 26), date(2028, 5, 5)),
    2029: (date(2029, 2, 14), date(2029, 4, 24)),
    2030: (date(2030, 2, 4), date(2030, 4, 13)),
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cal._holiday_cache.clear()
    yield
    cal._holiday_cache.clear()


def _holidays(year: int) -> set[date]:
    return set(resolve_holidays("TR", year)["dates"])


# ── The fixed days ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("year", [2025, 2026, 2030, 2033, 2040])
def test_the_seven_fixed_days_of_law_2429_are_holidays_every_year(year: int) -> None:
    holidays = _holidays(year)
    for month, day in _FIXED:
        assert date(year, month, day) in holidays, f"{day}.{month}.{year}"


def test_15_july_is_a_holiday_and_an_ordinary_summer_day_is_not() -> None:
    assert not is_working_day(date(2026, 7, 15), "TR")  # a Wednesday
    assert is_working_day(date(2026, 7, 16), "TR")


def test_the_half_days_are_not_counted_as_whole_holidays() -> None:
    """28 October and the eve of each feast are holidays from 13:00 only."""
    holidays = _holidays(2026)
    assert date(2026, 10, 28) not in holidays
    assert date(2026, 3, 19) not in holidays  # eve of Ramazan Bayramı
    assert date(2026, 5, 26) not in holidays  # eve of Kurban Bayramı


# ── The feasts ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("year", sorted(_PUBLISHED_FIRST_DAYS))
def test_the_feasts_fall_on_the_published_dates(year: int) -> None:
    ramazan, kurban = _PUBLISHED_FIRST_DAYS[year]
    expected = {date(year, month, day) for month, day in _FIXED}
    expected |= {ramazan + timedelta(days=offset) for offset in range(3)}
    expected |= {kurban + timedelta(days=offset) for offset in range(4)}
    assert _holidays(year) == expected


def test_the_table_reaches_at_least_from_2025_to_2030_without_a_gap() -> None:
    assert set(range(2025, 2031)) <= set(cal._TR_BAYRAMS)
    assert sorted(cal._TR_BAYRAMS) == list(range(min(cal._TR_BAYRAMS), max(cal._TR_BAYRAMS) + 1))


def test_every_row_keeps_the_distance_the_lunar_calendar_fixes() -> None:
    """Kurban Bayramı begins 10 Zilhicce, Ramazan Bayramı 1 Şevval: 68 to 70 days apart.

    A mistyped month or day breaks this; a whole table shifted the same way
    would not, which is what the written-out dates above are for.
    """
    for year, row in cal._TR_BAYRAMS.items():
        first_ramazan = date(year, *row["ramazan"][0])
        kurban = date(year, *row["kurban"][0])
        assert 68 <= (kurban - first_ramazan).days <= 70, year


def test_each_feast_moves_ten_to_twelve_days_earlier_every_year() -> None:
    years = sorted(cal._TR_BAYRAMS)
    for earlier, later in zip(years, years[1:], strict=False):
        for feast in ("ramazan", "kurban"):
            before = date(earlier, *cal._TR_BAYRAMS[earlier][feast][0])
            after = date(later, *cal._TR_BAYRAMS[later][feast][0])
            assert 353 <= (after - before).days <= 356, (feast, earlier, later)


def test_a_year_the_lunar_calendar_fits_twice_carries_both_feasts() -> None:
    """In 2033 Ramazan Bayramı falls in January and again in December."""
    assert len(cal._TR_BAYRAMS[2033]["ramazan"]) == 2
    holidays = _holidays(2033)
    assert {date(2033, 1, 2), date(2033, 1, 3), date(2033, 1, 4)} <= holidays
    assert {date(2033, 12, 23), date(2033, 12, 24), date(2033, 12, 25)} <= holidays


def test_a_year_has_fourteen_whole_days_unless_a_feast_meets_a_fixed_day() -> None:
    """Seven fixed days, three of Ramazan Bayramı and four of Kurban Bayramı."""
    for year in range(2025, 2033):
        count = len(_holidays(year))
        assert 12 <= count <= 14, (year, count)
    assert len(_holidays(2026)) == 14


# ── Agreement with the shipped calendar ──────────────────────────────────────


def test_the_engine_and_the_shipped_2026_calendar_name_the_same_days() -> None:
    row = next(c for c in json.loads(_SEED.read_text(encoding="utf-8")) if c["country_code"] == "TR")
    assert row["year"] == "2026"
    seeded = {date.fromisoformat(entry["date"]) for entry in row["exceptions"]}
    assert seeded == _holidays(2026)
    assert len(seeded) == 14


def test_the_shipped_calendar_writes_the_feast_names_in_turkish_letters() -> None:
    row = next(c for c in json.loads(_SEED.read_text(encoding="utf-8")) if c["country_code"] == "TR")
    names = {entry["name"]["tr"] for entry in row["exceptions"]}
    assert "Ramazan Bayramı 1. gün" in names
    assert "Kurban Bayramı 4. gün" in names
    assert "Yılbaşı" in names


# ── Provenance ───────────────────────────────────────────────────────────────


def test_a_covered_year_is_answered_by_turkeys_own_table() -> None:
    result = resolve_holidays("TR", 2027)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED
    assert result["omitted"] == ()


def test_a_year_past_the_table_says_which_feasts_it_left_out() -> None:
    year = max(cal._TR_BAYRAMS) + 5
    result = resolve_holidays("TR", year)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.FALLBACK
    assert result[AXIS_EFFECTIVE_YEAR].used == cal.GREGORIAN_ONLY
    assert result["omitted"] == ("Ramazan Bayramı", "Kurban Bayramı")
    assert len(result["dates"]) == len(_FIXED)


def test_turkey_does_not_inherit_the_hijri_converters_window() -> None:
    """The dates are copied from the published calendar, not converted."""
    assert "TR" not in cal._HIJRI_DEPENDENT
    assert "TR" not in cal._PLACEHOLDER_SPANS


# ── The working week ─────────────────────────────────────────────────────────


def test_the_week_is_monday_to_friday() -> None:
    assert cal._WORKING_WEEK["TR"] == frozenset({0, 1, 2, 3, 4})
    assert is_working_day(date(2026, 10, 9), "TR")  # Friday
    assert not is_working_day(date(2026, 10, 10), "TR")  # Saturday
    assert not is_working_day(date(2026, 10, 11), "TR")  # Sunday


def test_a_feast_week_loses_its_working_days() -> None:
    """Kurban Bayramı 2026 runs Wednesday 27 to Saturday 30 May."""
    worked = [d for d in (date(2026, 5, 25) + timedelta(days=i) for i in range(7)) if is_working_day(d, "TR")]
    assert worked == [date(2026, 5, 25), date(2026, 5, 26)]
