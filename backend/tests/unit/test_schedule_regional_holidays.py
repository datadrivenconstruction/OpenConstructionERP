"""Regional planning uses the country's holidays without borrowing a neighbour's."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.schedule.service import (
    ScheduleService,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [None, False, True])
async def test_generated_calendar_records_only_known_week_fallback(fallback):
    service = SimpleNamespace(_project_default_calendar=AsyncMock(return_value=None))
    schedule = SimpleNamespace(metadata_={}, project_id="own-fixture")
    known_fallback = {} if fallback is None else {"week_fallback": fallback}
    calendar, recorded = await ScheduleService._generation_calendar(
        service, schedule, {0, 1, 2, 3, 4}, "ZZ", **known_fallback
    )
    assert calendar is recorded
    if fallback is None:
        assert "week_fallback" not in recorded
    else:
        assert recorded["week_fallback"] is fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
async def test_explicit_calendar_does_not_inherit_a_regional_week_fallback(manual):
    explicit = {"work_days": [0, 2, 4], "exceptions": ["2026-10-16"]}
    default = AsyncMock(return_value=None if manual else explicit)
    service = SimpleNamespace(_project_default_calendar=default)
    schedule = SimpleNamespace(metadata_={"calendar": explicit} if manual else {}, project_id="own-fixture")
    calendar, recorded = await ScheduleService._generation_calendar(
        service, schedule, {0, 1, 2, 3, 4}, "ZZ", week_fallback=True
    )
    assert calendar == explicit
    assert "week_fallback" not in calendar
    assert recorded is None
    if manual:
        default.assert_not_awaited()
    else:
        default.assert_awaited_once_with(schedule.project_id)
