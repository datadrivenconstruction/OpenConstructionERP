"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The answer has to say which years it was actually informed about.

The seeded calendars cover one year, and a range reaching past it is answered
rather than refused because a schedule running past December is ordinary use.
That makes the disclosure the contract: a caller must be able to separate the
part of the answer built from a declared calendar from the part built from a
fallback.

Reported per year, never per range. A range that straddles the boundary is the
case that matters, and one flag across it would be true and useless: it would
say "something here was a fallback" without saying which half. So the assertions
below are on the shape of the per-year list, and
:func:`test_a_straddling_range_reports_each_year_differently` is the one that
would fail if this were ever collapsed into a single boolean.

Loaded from the shipped seed through the real seeder, for the same reason as the
sibling module: a fixture would prove the mechanism and certify nothing about
the data we ship.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.seed import _seed_work_calendars
from app.modules.i18n_foundation.service import I18nFoundationService

SEEDED_YEAR = 2026


async def _seeded_service(session: AsyncSession) -> I18nFoundationService:
    """Load the shipped seed and confirm it still covers exactly one year.

    If a second year is ever seeded, the expectations below stop describing the
    data and this says so rather than failing somewhere less obvious.
    """
    await _seed_work_calendars(session)
    service = I18nFoundationService(session)

    calendars = await service.work_calendar_repo.list(country_code="DE")
    assert calendars, "the shipped seed no longer carries a calendar for DE"
    assert {c.year for c in calendars} == {str(SEEDED_YEAR)}, (
        f"DE is now seeded for {sorted(c.year for c in calendars)}; this module assumes "
        f"the seed covers only {SEEDED_YEAR}"
    )
    return service


async def test_a_year_with_its_own_calendar_says_so(session: AsyncSession) -> None:
    """Inside the seeded year, the week is declared and holidays are applied."""
    service = await _seeded_service(session)

    result = await service.get_working_days("DE", "2026-03-02", "2026-03-06")

    assert [y.year for y in result.years] == [2026]
    year = result.years[0]
    assert year.work_week_source == "declared"
    assert year.work_week_from_year is None
    assert year.holidays_applied is True


async def test_a_year_past_the_seed_says_the_week_was_carried_and_holidays_were_not(
    session: AsyncSession,
) -> None:
    """Past the seeded year the week survives and the holidays do not.

    Both halves are asserted because they are separate facts. A year whose week
    was carried correctly still contributed no holidays, and that is exactly the
    gap a caller cannot see from the total.
    """
    service = await _seeded_service(session)

    result = await service.get_working_days("DE", "2027-03-01", "2027-03-05")

    assert [y.year for y in result.years] == [2027]
    year = result.years[0]
    assert year.work_week_source == "carried"
    assert year.work_week_from_year == SEEDED_YEAR
    assert year.holidays_applied is False


async def test_a_straddling_range_reports_each_year_differently(session: AsyncSession) -> None:
    """The case a single range-wide flag would answer uselessly.

    One boolean here could only say that some part of the range used a fallback.
    The caller needs to know which part, so the two years must disagree.
    """
    service = await _seeded_service(session)

    result = await service.get_working_days("DE", "2026-12-28", "2027-01-08")

    assert [y.year for y in result.years] == [2026, 2027]
    first, second = result.years

    assert first.work_week_source == "declared"
    assert first.holidays_applied is True
    assert second.work_week_source == "carried"
    assert second.holidays_applied is False

    # The disagreement is the point: collapsing this to one flag loses it.
    assert first.holidays_applied != second.holidays_applied


async def test_a_country_with_no_calendar_at_all_says_default(session: AsyncSession) -> None:
    """An unknown country is answered Mon-Fri, and says that is what happened."""
    service = await _seeded_service(session)

    result = await service.get_working_days("XX", "2027-03-01", "2027-03-05")

    assert [y.year for y in result.years] == [2027]
    year = result.years[0]
    assert year.work_week_source == "default"
    assert year.work_week_from_year is None
    assert year.holidays_applied is False


async def test_every_year_in_the_range_is_accounted_for(session: AsyncSession) -> None:
    """No year may be silently omitted, and the order follows the range."""
    service = await _seeded_service(session)

    result = await service.get_working_days("DE", "2026-12-31", "2029-01-01")

    assert [y.year for y in result.years] == [2026, 2027, 2028, 2029]
    assert [y.holidays_applied for y in result.years] == [True, False, False, False]
    # Every uninformed year names where its week came from rather than leaving
    # the caller to guess that it was the seeded one.
    assert [y.work_week_from_year for y in result.years] == [None, 2026, 2026, 2026]


async def test_the_disclosure_did_not_move_the_arithmetic(session: AsyncSession) -> None:
    """Reporting how the answer was built must not change the answer.

    2026-03-02 to 2026-03-06 is a full Monday-to-Friday week with no German
    public holiday in it, so the count is five regardless of the seed's contents.
    """
    service = await _seeded_service(session)

    result = await service.get_working_days("DE", "2026-03-02", "2026-03-06")

    assert result.working_days == 5
    assert result.calendar_days == 5
