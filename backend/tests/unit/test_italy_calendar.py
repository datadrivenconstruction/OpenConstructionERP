"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An Italian project is planned on Italy's week and Italy's holidays.

Italy had a seeded 2026 roster but no runtime binding, so every Italian
project fell back to the default week and reported no public holidays for
any year, which the schedule page showed as two warnings.
"""

from datetime import date

from app.core.calendar import resolve_holidays
from app.modules.schedule.service import WORK_CALENDARS, get_work_calendar


def test_an_italian_project_gets_the_italian_week_not_the_fallback() -> None:
    for region in ("IT", "Italy", "IT_ROME"):
        cal = get_work_calendar(region)
        assert cal["week_fallback"] is False, region
        assert cal["label"] == WORK_CALENDARS["ITALY"]["label"], region
        assert cal["holiday_country"] == "IT", region


def test_italian_holidays_are_answered_for_the_years_a_plan_spans() -> None:
    for year in (2026, 2027, 2030):
        answer = resolve_holidays("IT", year)
        assert answer["jurisdiction"].answered, year
        assert date(year, 4, 25) in answer["dates"]
        assert date(year, 12, 26) in answer["dates"]
    assert date(2027, 3, 29) in resolve_holidays("IT", 2027)["dates"]  # Easter Monday


def test_saint_francis_is_a_national_holiday_from_2026_only() -> None:
    """Legge 8 ottobre 2025, n. 151 (GU n. 236, 10.10.2025), in force 1 January 2026.

    It amends art. 2 of Law 260/1949, so 4 October is a full public holiday
    from 2026 and an ordinary day in 2025, the year the act was published.
    """
    assert date(2026, 10, 4) in resolve_holidays("IT", 2026)["dates"]
    assert date(2025, 10, 4) not in resolve_holidays("IT", 2025)["dates"]
    assert date(2027, 10, 4) in resolve_holidays("IT", 2027)["dates"]
