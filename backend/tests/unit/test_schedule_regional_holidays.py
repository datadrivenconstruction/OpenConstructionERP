"""Regional planning uses the country's holidays without borrowing a neighbour's."""

from datetime import date

import pytest

from app.modules.schedule.service import (
    calendar_holiday_coverage,
    calendar_region_for,
    compute_duration,
    get_work_calendar,
)


@pytest.mark.parametrize("region", ["DE_BERLIN", "CA_TORONTO", "GB_LONDON", "US", "BR_SAOPAULO"])
def test_christmas_is_not_a_working_day(region):
    assert compute_duration("2026-12-25", "2026-12-25", region) == 0


def test_year_boundary_loads_both_holiday_years():
    assert compute_duration("2026-12-31", "2027-01-04", "DE_BERLIN") == 2


def test_macro_region_uses_explicit_country_without_german_holiday_fallback():
    assert calendar_region_for("DACH", "CH") == "CH"
    assert date(2026, 10, 3) not in get_work_calendar("CH")["holidays"](2026)
    assert "holidays" not in get_work_calendar("DACH")
    assert calendar_holiday_coverage(None, 2026)["applied"] is False


def test_foreign_table_is_reported_but_not_applied():
    # core.calendar currently serves AT from the German function; do not
    # newly schedule Austria's German Unity Day while integrating holidays.
    assert get_work_calendar("AT")["holidays"](2026) == frozenset()
    assert calendar_holiday_coverage("AT", 2026)["applied"] is False


def test_unknown_country_exposes_missing_coverage():
    calendar = get_work_calendar("unknown-market")
    assert calendar["week_fallback"] is True
    assert calendar["holiday_country"] is None
    assert calendar_holiday_coverage(None, 2026)["jurisdiction"]["source"] == "fallback"
