"""Poland's public holidays, working week and Saturday-holiday rule.

The rosters below are the ones Polish secondary sources publish for 2026 and
2027 (infor.pl, forsal.pl, gazetaprawna.pl, read 2026-10-19), written out by
hand rather than derived from the function under test, so a wrong Easter
offset or a missing rule fails here instead of agreeing with itself.

The distinguishing cases are the two rule changes: Christmas Eve is a holiday
from 2025 and not before, Epiphany from 2011 and not before.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.core import calendar as cal
from app.modules.schedule.service import WORK_CALENDARS, _get_work_week

SEED_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

PL_2026 = {
    date(2026, 1, 1),  # Thu, Nowy Rok
    date(2026, 1, 6),  # Tue, Trzech Króli
    date(2026, 4, 5),  # Sun, Wielkanoc
    date(2026, 4, 6),  # Mon, Poniedziałek Wielkanocny
    date(2026, 5, 1),  # Fri
    date(2026, 5, 3),  # Sun
    date(2026, 5, 24),  # Sun, Zielone Świątki
    date(2026, 6, 4),  # Thu, Boże Ciało
    date(2026, 8, 15),  # Sat
    date(2026, 11, 1),  # Sun
    date(2026, 11, 11),  # Wed
    date(2026, 12, 24),  # Thu, Wigilia
    date(2026, 12, 25),  # Fri
    date(2026, 12, 26),  # Sat
}

PL_2027 = {
    date(2027, 1, 1),  # Fri
    date(2027, 1, 6),  # Wed
    date(2027, 3, 28),  # Sun, Wielkanoc
    date(2027, 3, 29),  # Mon
    date(2027, 5, 1),  # Sat
    date(2027, 5, 3),  # Mon
    date(2027, 5, 16),  # Sun, Zielone Świątki
    date(2027, 5, 27),  # Thu, Boże Ciało
    date(2027, 8, 15),  # Sun
    date(2027, 11, 1),  # Mon
    date(2027, 11, 11),  # Thu
    date(2027, 12, 24),  # Fri, Wigilia
    date(2027, 12, 25),  # Sat
    date(2027, 12, 26),  # Sun
}


@pytest.mark.parametrize(("year", "expected"), [(2026, PL_2026), (2027, PL_2027)])
def test_the_roster_equals_the_published_one(year: int, expected: set[date]) -> None:
    assert cal._holidays_pl(year) == expected


def test_christmas_eve_is_a_holiday_from_2025_and_not_before() -> None:
    assert date(2024, 12, 24) not in cal._holidays_pl(2024)
    assert date(2025, 12, 24) in cal._holidays_pl(2025)
    assert date(2026, 12, 24) in cal._holidays_pl(2026)


def test_epiphany_is_a_holiday_from_2011_and_not_before() -> None:
    assert date(2010, 1, 6) not in cal._holidays_pl(2010)
    assert date(2011, 1, 6) in cal._holidays_pl(2011)


@pytest.mark.parametrize(("year", "corpus_christi"), [(2026, date(2026, 6, 4)), (2027, date(2027, 5, 27))])
def test_corpus_christi_is_sixty_days_after_easter(year: int, corpus_christi: date) -> None:
    assert corpus_christi in cal._holidays_pl(year)
    assert corpus_christi.weekday() == 3  # always a Thursday


def test_christmas_eve_is_worked_in_2024_and_not_in_2026() -> None:
    # Both are weekdays (Tuesday and Thursday), so only the holiday rule decides.
    assert date(2024, 12, 24).weekday() == 1
    assert date(2026, 12, 24).weekday() == 3
    assert cal.is_working_day(date(2024, 12, 24), "PL") is True
    assert cal.is_working_day(date(2026, 12, 24), "PL") is False


def test_the_working_week_is_monday_to_friday() -> None:
    assert cal._WORKING_WEEK["PL"] == frozenset({0, 1, 2, 3, 4})
    assert cal.is_working_day(date(2026, 10, 17), "PL") is False  # Saturday
    assert cal.is_working_day(date(2026, 10, 19), "PL") is True  # Monday


@pytest.mark.parametrize(
    ("year", "owed"),
    [
        (2026, [date(2026, 8, 15), date(2026, 12, 26)]),
        (2027, [date(2027, 5, 1), date(2027, 12, 25)]),
    ],
)
def test_saturday_holidays_owe_a_day_off(year: int, owed: list[date]) -> None:
    assert cal.holidays_owing_a_day_off("PL", year) == owed


def test_the_owed_day_is_not_taken_out_of_the_working_week() -> None:
    # The employer picks the replacement day, so no weekday becomes a holiday:
    # the Monday after 15 August 2026 is still worked.
    assert cal.is_working_day(date(2026, 8, 17), "PL") is True
    assert len(cal._holidays_pl(2026)) == len(PL_2026)


def test_a_sunday_holiday_owes_nothing() -> None:
    owed = cal.holidays_owing_a_day_off("PL", 2026)
    assert date(2026, 11, 1) not in owed  # Sunday
    assert date(2026, 5, 3) not in owed  # Sunday


def test_a_country_without_the_rule_owes_nothing() -> None:
    # Germany has Saturday holidays in 2026 (Boxing Day) and no such rule.
    assert any(d.weekday() == 5 for d in cal._holidays_de(2026))
    assert cal.holidays_owing_a_day_off("DE", 2026) == []
    assert cal.saturday_holiday_compensation_rule("DE") is None
    rule = cal.saturday_holiday_compensation_rule("pl")
    assert rule is not None
    assert "130" in rule["statute"]


def test_the_schedule_resolver_gives_poland_its_own_calendar() -> None:
    for region in ("PL", "PL_WARSAW", "Poland"):
        calendar = _get_work_week(region)
        assert calendar is WORK_CALENDARS["POLAND"], region
        assert calendar is not WORK_CALENDARS["DEFAULT"]
    assert WORK_CALENDARS["POLAND"]["work_days"] == {0, 1, 2, 3, 4}
    assert WORK_CALENDARS["POLAND"]["hours_per_day"] == 8


def test_the_shipped_2026_calendar_agrees_with_the_engine() -> None:
    rows = [r for r in json.loads(SEED_PATH.read_text(encoding="utf-8")) if r["country_code"] == "PL"]
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == "2026"
    assert row["work_days"] == [1, 2, 3, 4, 5]
    assert {date.fromisoformat(e["date"]) for e in row["exceptions"]} == PL_2026
