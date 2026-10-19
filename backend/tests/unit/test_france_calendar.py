"""A French project is planned on France's holidays for every year, and Alsace-Moselle on its own.

France had a seeded 2026 roster and no rule, so a programme running into 2027
lost every French public holiday after 31 December 2026. The three departments
of Alsace-Moselle (57, 67, 68) keep two more days under local law (Code du
travail L3134-13): Good Friday and 26 December.
"""

from datetime import date

import pytest

from app.core.calendar import has_subdivision_holidays, is_working_day, resolve_holidays
from app.modules.schedule.service import get_work_calendar

_NATIONAL_2027 = {
    date(2027, 1, 1),
    date(2027, 3, 29),  # Easter Monday (Easter 28 March 2027)
    date(2027, 5, 1),
    date(2027, 5, 6),  # Ascension
    date(2027, 5, 8),
    date(2027, 5, 17),  # Whit Monday
    date(2027, 7, 14),
    date(2027, 8, 15),
    date(2027, 11, 1),
    date(2027, 11, 11),
    date(2027, 12, 25),
}


def test_france_is_answered_by_rule_for_years_after_the_seed() -> None:
    answer = resolve_holidays("FR", 2027)
    assert answer["jurisdiction"].answered
    assert set(answer["dates"]) == _NATIONAL_2027


def test_the_rule_agrees_with_the_shipped_2026_roster() -> None:
    dates = set(resolve_holidays("FR", 2026)["dates"])
    assert len(dates) == 11
    assert {date(2026, 4, 6), date(2026, 5, 14), date(2026, 5, 25)} <= dates


def test_national_france_has_no_good_friday_and_no_saint_stephen() -> None:
    dates = set(resolve_holidays("FR", 2027)["dates"])
    assert date(2027, 3, 26) not in dates
    assert date(2027, 12, 26) not in dates


@pytest.mark.parametrize("code", ["FR-57", "FR-67", "FR-68", "FR-6AE"])
def test_alsace_moselle_adds_good_friday_and_saint_stephen(code: str) -> None:
    assert has_subdivision_holidays(code)
    answer = resolve_holidays(code, 2027)
    assert answer["jurisdiction"].answered
    assert set(answer["dates"]) == _NATIONAL_2027 | {date(2027, 3, 26), date(2027, 12, 26)}


def test_another_department_falls_back_to_the_national_list() -> None:
    assert not has_subdivision_holidays("FR-75")
    assert set(resolve_holidays("FR-75", 2027)["dates"]) == _NATIONAL_2027


def test_the_french_week_is_monday_to_friday() -> None:
    assert is_working_day(date(2027, 3, 26), "FR") is True  # Good Friday, national
    assert is_working_day(date(2027, 3, 29), "FR") is False  # Easter Monday
    assert is_working_day(date(2027, 3, 27), "FR") is False  # Saturday


def test_a_french_project_gets_the_french_schedule_calendar() -> None:
    cal = get_work_calendar("FR")
    assert cal["week_fallback"] is False
    assert cal["holiday_country"] == "FR"
