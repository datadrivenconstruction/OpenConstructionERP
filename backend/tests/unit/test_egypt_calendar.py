# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egypt works Sunday to Thursday and has a holiday calendar of its own.

Until this file an Egyptian project fell through to the Monday to Friday
default with no public holidays: Fridays were working days, Sundays rest days,
and no Egyptian holiday existed anywhere. The spec is
``docs/design/egypt/calendar.md``.

The holiday days are Ministerial Decree 294/2025. Sham el-Nessim is the Monday
after Orthodox Easter, so the expected Easter dates below are written out from
published tables and not from the library the engine computes with. The
Thursday moves are per-year decrees held as data in
``app/core/country_data/holiday_observances.json``; the sets below are what an
Egyptian private employer observed, written out by hand.

The Gulf is pinned in the same file because the Egyptian Islamic holidays are
computed next to the Gulf ones, and a refactor of the shared converter path is
exactly where a Gulf date could move without anybody looking.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.core import calendar as cal
from app.core import holiday_observances as obs
from app.core.calendar import (
    AXIS_EFFECTIVE_YEAR,
    AXIS_JURISDICTION,
    HolidayCalculationError,
    add_working_days,
    is_working_day,
    julian_christmas,
    orthodox_easter,
    resolve_holidays,
)
from app.core.provenance import Source
from app.modules.schedule.service import compute_duration, get_work_calendar

_SEED = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

#: Orthodox Easter Sunday in Gregorian dates, from the published Orthodox
#: Paschalion (the same dates the Greek and Romanian public-holiday calendars
#: print). 2024 and 2027 are five weeks after Western Easter, 2025 coincides
#: with it, 2026 is one week after: the three relationships a computus can get
#: wrong.
_PUBLISHED_ORTHODOX_EASTER = {
    2021: date(2021, 5, 2),
    2022: date(2022, 4, 24),
    2023: date(2023, 4, 16),
    2024: date(2024, 5, 5),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 12),
    2027: date(2027, 5, 2),
}

#: What an Egyptian private employer observed in 2026, by hand. Fifteen days.
_EG_2026 = {
    date(2026, 1, 7),  # Coptic Christmas (Wednesday, never moved)
    date(2026, 1, 29),  # 25 January moved to Thursday, PM Decree 199/2026
    date(2026, 3, 20),  # Eid al-Fitr, 1 Shawwal 1447
    date(2026, 3, 21),  # Eid al-Fitr, 2 Shawwal
    date(2026, 4, 13),  # Sham el-Nessim, Monday after Orthodox Easter 12 April
    date(2026, 4, 25),  # Sinai Liberation Day (Saturday)
    date(2026, 5, 1),  # Labour Day (Friday)
    date(2026, 5, 26),  # Arafat Day
    date(2026, 5, 27),  # Eid al-Adha day 1
    date(2026, 5, 28),  # Eid al-Adha day 2
    date(2026, 6, 18),  # Hijri New Year 1448, decreed for Thursday
    date(2026, 7, 2),  # 30 June moved to Thursday
    date(2026, 7, 23),  # 23 July Revolution (already a Thursday)
    date(2026, 8, 27),  # Prophet's Birthday, decreed for Thursday
    date(2026, 10, 8),  # 6 October moved to Thursday
}

#: 2025, by hand. The 30 June and 6 October moves are recorded; the July 23
#: move the press anticipated is not, because no decree was found for it.
_EG_2025 = {
    date(2025, 1, 7),
    date(2025, 1, 25),  # Saturday, not moved
    date(2025, 3, 30),  # Eid al-Fitr
    date(2025, 3, 31),
    date(2025, 4, 21),  # Sham el-Nessim, Orthodox Easter 20 April
    date(2025, 4, 25),
    date(2025, 5, 1),
    date(2025, 6, 5),  # Arafat Day
    date(2025, 6, 6),  # Eid al-Adha
    date(2025, 6, 7),
    date(2025, 6, 26),  # Hijri New Year 1447 (a Thursday)
    date(2025, 7, 3),  # 30 June moved to Thursday, PM Decree 2130/2025
    date(2025, 7, 23),
    date(2025, 9, 4),  # Prophet's Birthday (a Thursday)
    date(2025, 10, 9),  # 6 October moved to Thursday
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    loader = obs.load_observances  # held, so a test's monkeypatch cannot hide it
    cal._holiday_cache.clear()
    loader.cache_clear()
    yield
    cal._holiday_cache.clear()
    loader.cache_clear()


# ── Country-neutral computations ──────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(("year", "expected"), sorted(_PUBLISHED_ORTHODOX_EASTER.items()))
def test_orthodox_easter_matches_the_published_paschalion(year: int, expected: date) -> None:
    assert orthodox_easter(year) == expected
    assert orthodox_easter(year).weekday() == 6


@pytest.mark.unit
def test_julian_christmas_drifts_a_day_after_2100() -> None:
    """7 January only while the calendars are thirteen days apart."""
    assert julian_christmas(2026) == date(2026, 1, 7)
    assert julian_christmas(2100) == date(2100, 1, 7)
    assert julian_christmas(2101) == date(2101, 1, 8)


# ── The Egyptian week ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_egypt_works_sunday_to_thursday() -> None:
    assert cal._WORKING_WEEK["EG"] == frozenset({6, 0, 1, 2, 3})
    # Friday 16 and Saturday 17 October 2026 are rest days, Sunday 18 works.
    assert is_working_day(date(2026, 10, 16), "EG") is False
    assert is_working_day(date(2026, 10, 17), "EG") is False
    assert is_working_day(date(2026, 10, 18), "EG") is True


@pytest.mark.unit
@pytest.mark.parametrize("region", ["EG", "EG_CAIRO", "Egypt", "egypt"])
def test_every_spelling_of_egypt_reaches_the_egyptian_week(region: str) -> None:
    calendar = get_work_calendar(region)
    assert calendar["work_days"] == {6, 0, 1, 2, 3}
    assert calendar["hours_per_day"] == 8
    assert calendar["week_fallback"] is False
    assert "Gulf" not in calendar["label"]


@pytest.mark.unit
@pytest.mark.parametrize("region", ["EG", "EG_CAIRO"])
def test_a_coded_egyptian_region_gets_egyptian_holidays(region: str) -> None:
    """Holidays follow the ISO code. A typed country name ("Egypt", like
    "Qatar") reaches the week but not the holidays, because the region
    registry resolves no country names at all; that gap is platform-wide and
    a project's country column closes it (``calendar_region_for``)."""
    assert get_work_calendar(region)["holiday_country"] == "EG"


@pytest.mark.unit
def test_a_schedule_across_a_weekend_and_sham_el_nessim() -> None:
    """Thursday 9 to Wednesday 15 April 2026.

    Egypt: Thu 9 works, Fri 10 and Sat 11 rest, Sun 12 works, Mon 13 is Sham
    el-Nessim, Tue 14 and Wed 15 work: four days. The old fallback counted
    Monday to Friday with no holidays, which is five, so this case fails on
    the defect and passes only on the fix.
    """
    assert compute_duration("2026-04-09", "2026-04-15", "EG") == 4
    assert compute_duration("2026-04-09", "2026-04-15", None) == 5
    assert add_working_days(date(2026, 4, 9), 2, "EG") == date(2026, 4, 14)


# ── The Egyptian holidays ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_the_2026_holidays() -> None:
    answer = resolve_holidays("EG", 2026)
    assert set(answer["dates"]) == _EG_2026
    assert answer[AXIS_JURISDICTION].source is Source.DECLARED
    assert answer[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED


@pytest.mark.unit
def test_the_2025_holidays_and_that_the_roster_postdates_january() -> None:
    answer = resolve_holidays("EG", 2025)
    assert set(answer["dates"]) == _EG_2025
    # Decree 294/2025 took effect on 2025-09-01, so the first eight months of
    # 2025 are answered with a roster that was not yet law.
    assert answer[AXIS_EFFECTIVE_YEAR].source is Source.FALLBACK
    assert answer[AXIS_EFFECTIVE_YEAR].used == cal.ROSTER_FROM_LATER_DECREE


@pytest.mark.unit
def test_a_year_with_no_announced_moves_answers_the_statutory_days() -> None:
    """2027: nothing announced yet, so 25 January stays on Monday 25 January."""
    days = resolve_holidays("EG", 2027)["dates"]
    assert date(2027, 1, 25) in days
    assert date(2027, 5, 3) in days  # Sham el-Nessim, Orthodox Easter 2 May
    assert len(days) == 15


@pytest.mark.unit
def test_a_move_whose_statutory_date_no_longer_matches_the_engine_raises(monkeypatch) -> None:
    """A move must name the day it moves. Applied blind, it would delete the wrong one."""
    stale = obs.Observance(
        country="EG",
        year=2026,
        holiday="revolution_25_january",
        statutory=(date(2026, 1, 26),),
        observed=(date(2026, 1, 29),),
        authority="test",
        source_url="https://example.org/",
        private_sector="stated",
    )
    monkeypatch.setattr(obs, "load_observances", lambda: (stale,))
    with pytest.raises(HolidayCalculationError):
        resolve_holidays("EG", 2026)


@pytest.mark.unit
def test_every_shipped_observance_validates_and_names_a_computed_holiday() -> None:
    rows = obs.load_observances()
    assert rows, "no observance rows shipped; this test is checking nothing"
    named_2025 = cal._holidays_eg_statutory(2025)
    named_2026 = cal._holidays_eg_statutory(2026)
    for row in rows:
        assert row.source_url.startswith("https://")
        assert row.private_sector in {"stated", "not_stated"}
        if row.country == "EG":
            named = {2025: named_2025, 2026: named_2026}[row.year]
        else:
            named = cal._eid_days(row.country, row.year)
        assert row.holiday in named
        assert tuple(sorted(named[row.holiday])) == row.statutory


@pytest.mark.unit
def test_the_validator_refuses_a_malformed_row() -> None:
    good = {
        "country": "EG",
        "year": 2026,
        "holiday": "armed_forces_day",
        "statutory": ["2026-10-06"],
        "observed": ["2026-10-08"],
        "authority": "x",
        "source_url": "https://example.org/",
        "private_sector": "stated",
    }
    assert obs.parse_observances([good])
    for broken in (
        {**good, "source_url": "http://insecure.example/"},
        {**good, "observed": ["2027-10-08"]},
        {**good, "statutory": []},
        {**good, "private_sector": "maybe"},
        {k: v for k, v in good.items() if k != "authority"},
    ):
        with pytest.raises(ValueError):
            obs.parse_observances([broken])
    with pytest.raises(ValueError):
        obs.parse_observances([good, good])


# ── The seeded calendar row ───────────────────────────────────────────────────


@pytest.mark.unit
def test_the_seeded_2026_row_is_the_engine_answer_on_a_sunday_week() -> None:
    rows = json.loads(_SEED.read_text(encoding="utf-8"))
    (row,) = [r for r in rows if r["country_code"] == "EG"]
    assert row["year"] == "2026"
    assert row["work_days"] == [7, 1, 2, 3, 4]  # ISO: Sunday is 7
    seeded = {date.fromisoformat(e["date"]) for e in row["exceptions"]}
    assert seeded == _EG_2026
    for exc in row["exceptions"]:
        assert exc["name"]["en"] and exc["name"]["ar"]


# ── Saudi Arabia: its own sourced Eid spans ───────────────────────────────────


@pytest.mark.unit
def test_saudi_eids_are_four_days_and_adha_starts_on_arafah() -> None:
    """Eid al-Fitr four days from 1 Shawwal, Eid al-Adha four from 9 Dhu al-Hijjah.

    The shared Gulf placeholder gave three days of Fitr and started Adha on the
    10th. 2025 has no announced row, so it is the computed span; 2026 carries
    the HRSD announcement that Eid al-Fitr ran from Thursday 19 March, which
    makes the engine equal the shipped 2026 calendar row.
    """
    assert set(resolve_holidays("SA", 2025)["dates"]) == {
        date(2025, 2, 22),
        date(2025, 3, 30), date(2025, 3, 31), date(2025, 4, 1), date(2025, 4, 2),
        date(2025, 6, 5), date(2025, 6, 6), date(2025, 6, 7), date(2025, 6, 8),
        date(2025, 9, 23),
    }  # fmt: skip
    assert set(resolve_holidays("SA", 2026)["dates"]) == {
        date(2026, 2, 22),
        date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 21), date(2026, 3, 22),
        date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29),
        date(2026, 9, 23),
    }  # fmt: skip


@pytest.mark.unit
def test_saudi_arabia_no_longer_reports_a_placeholder_span() -> None:
    answer = resolve_holidays("SA", 2026)
    assert answer["placeholder_spans"] == ()
    assert answer[cal.AXIS_HOLIDAY_EXTENT].source is Source.DECLARED
    assert cal._EID_SPANS["SA"].sourced and cal._EID_SPANS["EG"].sourced


@pytest.mark.unit
def test_an_eid_that_starts_in_december_counts_its_january_days() -> None:
    """Arafah 1483 falls on 30 December 2071 in the converter.

    Measured over the converter's whole window this is the only year boundary
    an Eid span crosses after 2006. The old Gulf expansion filed 1 and 2
    January 2072 under 2071, where no lookup by year ever reads them, and left
    2072 without them, so they counted as working days. A sourced or
    placeholder span now files each day under its own year.
    """
    sa_2071 = resolve_holidays("SA", 2071)["dates"]
    sa_2072 = resolve_holidays("SA", 2072)["dates"]
    assert {date(2071, 12, 30), date(2071, 12, 31)} <= sa_2071
    assert all(day.year == 2071 for day in sa_2071)
    assert {date(2072, 1, 1), date(2072, 1, 2)} <= sa_2072
    assert is_working_day(date(2072, 1, 1), "SA") is False
    # The UAE placeholder starts a day later and runs to 3 January.
    assert {date(2072, 1, 1), date(2072, 1, 2), date(2072, 1, 3)} <= resolve_holidays("AE", 2072)["dates"]


# ── The rest of the Gulf is unchanged ─────────────────────────────────────────

_GCC_EXPECTED: dict[tuple[str, int], tuple[str, ...]] = {
    ("AE", 2025): (
        "01-01", "03-30", "03-31", "04-01", "06-06", "06-07", "06-08", "06-09", "06-26", "09-04",
        "12-01", "12-02", "12-03",
    ),
    ("AE", 2026): (
        "01-01", "03-20", "03-21", "03-22", "05-27", "05-28", "05-29", "05-30", "06-16", "08-25",
        "12-01", "12-02", "12-03",
    ),
    ("QA", 2025): ("02-11", "03-30", "03-31", "04-01", "06-06", "06-07", "06-08", "06-09", "12-18"),
    ("QA", 2026): ("02-10", "03-20", "03-21", "03-22", "05-27", "05-28", "05-29", "05-30", "12-18"),
    ("KW", 2025): (
        "01-01", "02-25", "02-26", "03-30", "03-31", "04-01", "06-06", "06-07", "06-08", "06-09",
        "06-26", "09-04",
    ),
    ("KW", 2026): (
        "01-01", "02-25", "02-26", "03-20", "03-21", "03-22", "05-27", "05-28", "05-29", "05-30",
        "06-16", "08-25",
    ),
    ("BH", 2025): (
        "01-01", "03-30", "03-31", "04-01", "05-01", "06-06", "06-07", "06-08", "06-09", "06-26",
        "09-04", "12-16", "12-17",
    ),
    ("BH", 2026): (
        "01-01", "03-20", "03-21", "03-22", "05-01", "05-27", "05-28", "05-29", "05-30", "06-16",
        "08-25", "12-16", "12-17",
    ),
    ("OM", 2025): (
        "01-01", "03-30", "03-31", "04-01", "06-06", "06-07", "06-08", "06-09", "06-26", "09-04", "11-18",
    ),
    ("OM", 2026): (
        "01-01", "03-20", "03-21", "03-22", "05-27", "05-28", "05-29", "05-30", "06-16", "08-25", "11-18",
    ),
}  # fmt: skip


@pytest.mark.unit
@pytest.mark.parametrize(("country", "year"), sorted(_GCC_EXPECTED))
def test_gulf_holidays_are_unchanged(country: str, year: int) -> None:
    expected = {date.fromisoformat(f"{year}-{md}") for md in _GCC_EXPECTED[(country, year)]}
    assert set(resolve_holidays(country, year)["dates"]) == expected


@pytest.mark.unit
def test_gulf_weeks_and_unsourced_spans_are_unchanged() -> None:
    for country in ("AE", "QA", "KW", "BH", "OM"):
        assert cal._EID_SPANS[country] is cal._UNSOURCED_GULF_SPAN
        assert resolve_holidays(country, 2026)["placeholder_spans"] == ("Eid al-Fitr", "Eid al-Adha")
    assert cal._WORKING_WEEK["AE"] == frozenset({0, 1, 2, 3, 4})
    for country in ("SA", "QA", "KW", "BH", "OM"):
        assert cal._WORKING_WEEK[country] == frozenset({6, 0, 1, 2, 3})
        assert get_work_calendar(country)["label"] == "Gulf (Sun-Thu, 8h)"
