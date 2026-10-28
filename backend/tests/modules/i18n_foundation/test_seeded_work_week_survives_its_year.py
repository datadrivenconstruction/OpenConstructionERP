"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The seeded work week must outlive the single year the seed file covers.

Every other test in this package builds its calendars with ``make_calendar``.
That proves the mechanism and certifies nothing about the data we ship, which is
how a seed file covering exactly one year sat behind a green cross-year test. So
this module loads the real ``work_calendars.json`` through the real seeder and
asks the service the same questions a caller would.

Everything here is asserted per day, never per year. Sunday-Thursday and
Monday-Friday are both five days a week, so an annual total is identical under
either and a count-based assertion passes while every individual day is wrong.
:func:`test_a_yearly_total_cannot_see_this` pins that blind spot rather than
leaving the next author to rediscover it.

Holidays are deliberately not asserted here. They are not carried across years
and that gap is open work, so a holiday assertion would either fail or quietly
record the gap as intended behaviour.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.seed import _seed_work_calendars
from app.modules.i18n_foundation.service import I18nFoundationService

# Saudi Arabia is the one seeded row whose week is not Monday-Friday.
SA_WORK_DAYS = {1, 2, 3, 4, 7}  # Mon-Thu plus Sun, ISO numbering

# 2027 is the first year the seed file does not cover. These two dates are the
# whole argument: one is a Friday, one is a Sunday, and the two countries below
# must disagree about both.
FRIDAY_2027 = "2027-01-01"
SUNDAY_2027 = "2027-01-03"


async def _seeded_service(session: AsyncSession) -> I18nFoundationService:
    """Load the shipped seed and confirm it still says what this module assumes.

    Guards against the silent-pass case: if the seeder skips because the table is
    already populated, or if Saudi Arabia's week is ever edited in the seed file,
    the precondition fails loudly instead of the assertions below testing nothing.
    """
    await _seed_work_calendars(session)
    service = I18nFoundationService(session)

    sa = await service.work_calendar_repo.get_for_country("SA", "2026")
    assert sa is not None, "the shipped seed no longer carries a 2026 calendar for SA"
    assert set(sa.work_days) == SA_WORK_DAYS, (
        f"the shipped SA week changed to {sorted(sa.work_days)}; this module assumes "
        f"{sorted(SA_WORK_DAYS)} and its assertions are meaningless otherwise"
    )
    return service


async def _is_working(service: I18nFoundationService, code: str, day: str) -> bool:
    """Ask the public calculation about a single day."""
    result = await service.get_working_days(code, day, day)
    assert result.calendar_days == 1
    return result.working_days == 1


async def test_saudi_arabia_keeps_its_own_week_past_the_seeded_year(session: AsyncSession) -> None:
    """A 2027 Friday is not a working day in Saudi Arabia, and a Sunday is.

    Before the fallback looked outside the requested range, both answers came
    back exactly inverted: the hardcoded Monday-Friday default was used for any
    range with no calendar in its own years, even though the country has one.
    """
    service = await _seeded_service(session)

    assert await _is_working(service, "SA", FRIDAY_2027) is False
    assert await _is_working(service, "SA", SUNDAY_2027) is True


async def test_a_monday_to_friday_country_is_unchanged_past_the_seeded_year(session: AsyncSession) -> None:
    """Germany still reads Friday as working and Sunday as not.

    This is the control that a fallback which simply stopped resolving cannot
    pass: an empty work week would make the Friday assertion fail here while
    still satisfying the Saudi Friday above.
    """
    service = await _seeded_service(session)

    assert await _is_working(service, "DE", FRIDAY_2027) is True
    assert await _is_working(service, "DE", SUNDAY_2027) is False


async def test_the_two_countries_disagree_about_the_same_two_days(session: AsyncSession) -> None:
    """The disagreement is the point, so assert it directly.

    If the fallback ever reverts to a single hardcoded week, every country
    answers alike and this goes red even if one country's answers look right.
    """
    service = await _seeded_service(session)

    for day in (FRIDAY_2027, SUNDAY_2027):
        sa = await _is_working(service, "SA", day)
        de = await _is_working(service, "DE", day)
        assert sa != de, f"SA and DE gave the same answer for {day}; the declared week is being ignored"


async def test_a_country_with_no_calendar_at_all_still_falls_back_to_monday_friday(
    session: AsyncSession,
) -> None:
    """The last rung survives: an unknown country is still counted Mon-Fri."""
    service = await _seeded_service(session)

    assert await _is_working(service, "XX", FRIDAY_2027) is True
    assert await _is_working(service, "XX", SUNDAY_2027) is False


async def test_a_yearly_total_cannot_see_this(session: AsyncSession) -> None:
    """Why every assertion above counts days rather than years.

    2029 begins on a Monday, which gives Sunday-Thursday and Monday-Friday the
    same number of days across the year. A test asserting an annual total would
    pass here with the calendar inverted, so the totals are asserted EQUAL and
    the disagreement is shown one day at a time.
    """
    service = await _seeded_service(session)

    sa_year = (await service.get_working_days("SA", "2029-01-01", "2029-12-31")).working_days
    xx_year = (await service.get_working_days("XX", "2029-01-01", "2029-12-31")).working_days
    assert sa_year == xx_year, (
        "2029 was chosen because the two work weeks total the same across it; if that "
        "is no longer true this test has lost its point rather than found a defect"
    )

    # Identical totals, opposite answers. 2029-01-05 is a Friday, 2029-01-07 a Sunday.
    assert await _is_working(service, "SA", "2029-01-05") is False
    assert await _is_working(service, "XX", "2029-01-05") is True
    assert await _is_working(service, "SA", "2029-01-07") is True
    assert await _is_working(service, "XX", "2029-01-07") is False
