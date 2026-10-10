"""Turkey's public holidays reach the scheduler, and only for the years we sourced.

Before ``_holidays_tr`` existed, Turkey had a shipped 2026 calendar in the
work-calendar seed and nothing in ``_HOLIDAY_FUNCS``, so a Turkish project was
planned on a week with no public holidays at all: Republic Day and both feasts
counted as working days. The seed does not feed the scheduler, which is why the
2026 roster sitting in it changed nothing.

The religious feasts are pinned per year rather than converted, because Turkey
takes them from Diyanet's own calendar. A year Diyanet has not published yet
must come back as the fixed days plus a stated omission, never as a guess.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.calendar import _holidays_tr, is_working_day, resolve_holidays
from app.core.provenance import Source
from app.modules.schedule.service import get_work_calendar

_FIXED_2027 = {
    date(2027, 1, 1),
    date(2027, 4, 23),
    date(2027, 5, 1),
    date(2027, 5, 19),
    date(2027, 7, 15),
    date(2027, 8, 30),
    date(2027, 10, 29),
}
_RAMAZAN_2027 = {date(2027, 3, 9), date(2027, 3, 10), date(2027, 3, 11)}
_KURBAN_2027 = {date(2027, 5, 16), date(2027, 5, 17), date(2027, 5, 18), date(2027, 5, 19)}


def test_2027_is_the_fixed_days_plus_both_feasts_as_diyanet_published_them() -> None:
    assert _holidays_tr(2027) == _FIXED_2027 | _RAMAZAN_2027 | _KURBAN_2027


def test_the_arife_half_days_are_not_whole_holidays() -> None:
    # 8 March and 15 May 2027 are the feast eves; only their afternoons are off.
    assert date(2027, 3, 8) not in _holidays_tr(2027)
    assert date(2027, 5, 15) not in _holidays_tr(2027)


def test_a_holiday_on_a_weekend_is_not_moved() -> None:
    # 1 May 2027 is a Saturday. Law 2429 has no substitute day.
    assert date(2027, 5, 1).weekday() == 5
    assert is_working_day(date(2027, 5, 3), "TR")


def test_a_year_diyanet_has_not_published_returns_the_fixed_days_and_says_so() -> None:
    resolved = resolve_holidays("TR", 2028)
    assert set(resolved["dates"]) == {
        date(2028, m, d) for m, d in ((1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29))
    }
    assert resolved["omitted"] == ("Ramazan Bayrami", "Kurban Bayrami")
    assert resolved["effective_year"].source is Source.FALLBACK


@pytest.mark.parametrize("region", ["TR", "TR_ISTANBUL", "TR_NATIONAL"])
def test_a_turkish_project_is_scheduled_around_the_feasts(region: str) -> None:
    calendar = get_work_calendar(region)
    assert calendar["holiday_country"] == "TR"
    holidays = calendar["holidays"](2027)
    assert holidays >= _RAMAZAN_2027
    assert holidays >= _KURBAN_2027
    assert not is_working_day(date(2027, 3, 9), "TR")
