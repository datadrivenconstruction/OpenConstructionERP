"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Working-day counting: work weeks, holidays and the edges around them.

Both ends of a range are inclusive here, which every count below assumes. That
convention is worth stating loudly because the platform's other working-day
implementation disagrees: ``schedule/progress_math.WorkCalendar`` documents
``working_days_between`` as "exclusive of the start date, inclusive of the end".
The two are unrelated pieces of code with the same name, and a caller moving a
number between them is off by one working day.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import make_calendar

# ── The default work week ────────────────────────────────────────────────────


async def test_no_calendar_falls_back_to_monday_to_friday(session: AsyncSession) -> None:
    """A country with no calendar is counted Mon-Fri, not refused.

    The service docstring used to promise a 404 here. It never raised one, and
    the router documents the Mon-Fri fallback, so the behaviour is the contract
    and the docstring was the error.
    """
    service = I18nFoundationService(session)

    # 2026-01-05 is a Monday; the range covers exactly two full weeks.
    result = await service.get_working_days("XX", "2026-01-05", "2026-01-18")

    assert result.working_days == 10
    assert result.calendar_days == 14
    assert result.country_code == "XX"


async def test_calendar_work_days_replace_the_default(session: AsyncSession) -> None:
    """A Sunday-to-Thursday week is counted on its own days, not Mon-Fri."""
    await make_calendar(session, country_code="AE", year="2026", work_days=[7, 1, 2, 3, 4])
    service = I18nFoundationService(session)

    result = await service.get_working_days("AE", "2026-01-05", "2026-01-18")

    # Sun-Thu is still five days a week, but they are different days: the two
    # Fridays are off and the two Sundays are on.
    assert result.working_days == 10
    assert result.calendar_days == 14


async def test_a_four_day_week_is_counted_as_four_days(session: AsyncSession) -> None:
    """The work week is whatever the calendar declares, not always five days."""
    await make_calendar(session, country_code="IS", year="2026", work_days=[1, 2, 3, 4])
    service = I18nFoundationService(session)

    result = await service.get_working_days("IS", "2026-01-05", "2026-01-18")

    assert result.working_days == 8


async def test_country_code_is_matched_case_insensitively(session: AsyncSession) -> None:
    """Lower-case input finds the upper-case stored calendar."""
    await make_calendar(session, country_code="DE", year="2026", work_days=[1, 2, 3])
    service = I18nFoundationService(session)

    result = await service.get_working_days("de", "2026-01-05", "2026-01-18")

    assert result.working_days == 6
    assert result.country_code == "DE"


# ── Holidays ─────────────────────────────────────────────────────────────────


async def test_a_holiday_on_a_work_day_is_deducted(session: AsyncSession) -> None:
    """A declared holiday removes exactly one working day."""
    await make_calendar(
        session,
        country_code="DE",
        year="2026",
        exceptions=[{"date": "2026-01-06", "name": "Epiphany"}],
    )
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-18")

    assert result.working_days == 9
    assert result.calendar_days == 14


async def test_a_holiday_falling_on_a_weekend_costs_nothing(session: AsyncSession) -> None:
    """A holiday on a non-working day must not be double-counted."""
    await make_calendar(
        session,
        country_code="DE",
        year="2026",
        # 2026-01-10 is a Saturday, already outside the Mon-Fri work week.
        exceptions=[{"date": "2026-01-10", "name": "Saturday holiday"}],
    )
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-18")

    assert result.working_days == 10


async def test_a_holiday_outside_the_range_is_ignored(session: AsyncSession) -> None:
    """Only holidays inside the queried range change the count."""
    await make_calendar(
        session,
        country_code="DE",
        year="2026",
        exceptions=[{"date": "2026-05-01", "name": "Labour Day"}],
    )
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-18")

    assert result.working_days == 10


async def test_a_malformed_holiday_date_is_skipped_not_fatal(session: AsyncSession) -> None:
    """One unparseable exception entry must not take the whole calculation down."""
    await make_calendar(
        session,
        country_code="DE",
        year="2026",
        exceptions=[
            {"date": "not-a-date", "name": "Broken"},
            {"name": "No date field at all"},
            {"date": "", "name": "Empty"},
            {"date": "2026-01-06", "name": "Epiphany"},
        ],
    )
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-18")

    # The three broken entries are dropped; the one good holiday still counts.
    assert result.working_days == 9


async def test_an_empty_exception_list_is_fine(session: AsyncSession) -> None:
    """A calendar with no holidays at all behaves like a plain work week."""
    await make_calendar(session, country_code="DE", year="2026", exceptions=[])
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-18")

    assert result.working_days == 10


# ── Year boundaries ──────────────────────────────────────────────────────────


async def test_each_year_is_judged_by_its_own_work_week(session: AsyncSession) -> None:
    """DEFECT: the last year loaded used to set the work week for the whole range.

    ``work_day_numbers`` was reassigned inside the per-year loop, so with both
    2026 and 2027 present the 2027 week was applied to the 2026 dates as well.
    A country that changed its working week at the turn of the year - the Gulf
    move from Sunday-Thursday to Monday-Friday is the real case - had every day
    of the old year counted under the new week.

    The range below is picked so the two answers actually differ. Both weeks
    are five days long, so most spans give the same total either way and would
    pass with the bug in place; this one starts on a Sunday, which the 2026
    week works and the 2027 week does not.
    """
    await make_calendar(session, country_code="AE", year="2026", work_days=[7, 1, 2, 3, 4])
    await make_calendar(session, country_code="AE", year="2027", work_days=[1, 2, 3, 4, 5])
    service = I18nFoundationService(session)

    # 2026-12-27 (Sun) .. 2027-01-02 (Sat). Per year: Sun 27 through Thu 31
    # under Sun-Thu = 5, plus Fri 1 under Mon-Fri = 1, so 6. Applying the 2027
    # week to everything drops Sunday the 27th and gives 5.
    result = await service.get_working_days("AE", "2026-12-27", "2027-01-02")

    assert result.calendar_days == 7
    assert result.working_days == 6


async def test_holidays_from_both_years_are_applied(session: AsyncSession) -> None:
    """A range crossing a boundary honours each year's own holiday list."""
    await make_calendar(
        session,
        country_code="DE",
        year="2026",
        exceptions=[{"date": "2026-12-31", "name": "New Year's Eve"}],
    )
    await make_calendar(
        session,
        country_code="DE",
        year="2027",
        exceptions=[{"date": "2027-01-01", "name": "New Year's Day"}],
    )
    service = I18nFoundationService(session)

    # Sun 27 .. Sat 2 under Mon-Fri: five weekdays, two of them removed as
    # holidays, one from each year's own exception list.
    result = await service.get_working_days("DE", "2026-12-27", "2027-01-02")

    assert result.working_days == 3


async def test_a_year_without_a_calendar_carries_the_neighbour_forward(session: AsyncSession) -> None:
    """A gap year uses the nearest declared work week, not a snap back to Mon-Fri.

    Calendars are seeded per year and the following year's is often not loaded
    yet. Falling back to Mon-Fri for the undeclared year would silently change
    a Sunday-Thursday country's answer the moment a range crossed New Year.

    This is a characterization test, not a defect fix: the original code also
    carried the single loaded calendar across the whole range, and it is
    asserted here so the per-year rewrite is pinned to preserve that. The
    Mon-Fri fallback stays reserved for a country with no calendar at all.
    """
    await make_calendar(session, country_code="AE", year="2026", work_days=[7, 1, 2, 3, 4])
    service = I18nFoundationService(session)

    # Thu 2026-12-31 .. Fri 2027-01-08, nine calendar days with only 2026
    # declared. Carrying Sun-Thu forward gives 6; snapping 2027 to Mon-Fri
    # would give 7.
    result = await service.get_working_days("AE", "2026-12-31", "2027-01-08")

    assert result.calendar_days == 9
    assert result.working_days == 6


async def test_a_range_spanning_three_years_counts_each_one(session: AsyncSession) -> None:
    """The loader walks every spanned year, not just the two endpoints."""
    await make_calendar(session, country_code="DE", year="2026", work_days=[1, 2, 3, 4, 5])
    await make_calendar(
        session,
        country_code="DE",
        year="2027",
        work_days=[1, 2, 3, 4, 5],
        exceptions=[{"date": "2027-06-01", "name": "Mid-year holiday"}],
    )
    await make_calendar(session, country_code="DE", year="2028", work_days=[1, 2, 3, 4, 5])
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-12-31", "2028-01-01")

    # The middle year's holiday is a Tuesday, so it must be deducted.
    assert result.calendar_days == 367
    assert result.working_days == 261


# ── Range edges ──────────────────────────────────────────────────────────────


async def test_a_single_day_range_is_one_calendar_day(session: AsyncSession) -> None:
    """Both ends are inclusive: from == to is one day, not zero."""
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-05")

    assert result.calendar_days == 1
    assert result.working_days == 1


async def test_a_single_non_working_day_range_is_zero_working_days(session: AsyncSession) -> None:
    """A one-day range on a Sunday still counts one calendar day."""
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-11", "2026-01-11")

    assert result.calendar_days == 1
    assert result.working_days == 0


async def test_a_reversed_range_is_a_400(session: AsyncSession) -> None:
    """An end before the start is rejected rather than silently counted as zero."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.get_working_days("DE", "2026-01-18", "2026-01-05")

    assert excinfo.value.status_code == 400


@pytest.mark.parametrize(
    ("from_date", "to_date"),
    [
        ("not-a-date", "2026-01-18"),
        ("2026-01-05", "not-a-date"),
        ("2026-13-01", "2026-12-31"),
        ("2026-02-30", "2026-03-01"),
        ("", "2026-01-18"),
    ],
)
async def test_an_unparseable_date_is_a_400(session: AsyncSession, from_date: str, to_date: str) -> None:
    """Garbage dates are a clean client error, never a 500."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.get_working_days("DE", from_date, to_date)

    assert excinfo.value.status_code == 400


async def test_a_leap_day_is_counted(session: AsyncSession) -> None:
    """29 February exists in a leap year and is a normal working day."""
    service = I18nFoundationService(session)

    # 2028-02-28 is a Monday and 2028-02-29 a Tuesday, so both count.
    leap = await service.get_working_days("DE", "2028-02-28", "2028-02-29")
    # The same two calendar dates in a non-leap year end a day earlier.
    non_leap = await service.get_working_days("DE", "2027-02-28", "2027-03-01")

    assert leap.calendar_days == 2
    assert leap.working_days == 2
    assert non_leap.calendar_days == 2


async def test_work_days_outside_the_iso_range_yield_no_working_days(session: AsyncSession) -> None:
    """A calendar declaring weekday 0 matches nothing - ``isoweekday`` is 1..7.

    ``WorkCalendarCreate`` and ``WorkCalendarUpdate`` now refuse a weekday
    outside 1..7, so a zero-based week (Sunday = 0, as JavaScript and cron
    count) can no longer be authored through the API. The arithmetic below is
    kept rather than deleted because that guard is on the door and this value
    reaches the column two other ways: a row already in a database from before
    the guard existed, and any writer that skips the schemas - ``seed.py``
    constructs ``WorkCalendar(...)`` straight on the ORM, which is how the
    seeded Saudi Arabia calendar shipped as ``[0, 1, 2, 3, 4]`` and counted
    that country as a four-day week until ``v3303`` repaired it. This test
    writes through the ORM for the same reason.

    DE is a stand-in here, not the country this ever happened to. What is
    pinned is the shape of the failure, and it is why the guard exists: no
    error, no log line, just a working week one day shorter than the one that
    was asked for. ``tests/unit/test_work_calendar_weekdays_are_iso.py``
    checks the seed file itself, which is what would have caught the Saudi row.
    """
    await make_calendar(session, country_code="DE", year="2026", work_days=[0, 1, 2, 3, 4])
    service = I18nFoundationService(session)

    result = await service.get_working_days("DE", "2026-01-05", "2026-01-18")

    # Weekday 0 never matches, so this five-day week counts as four.
    assert result.working_days == 8
