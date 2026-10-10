"""The answer has to say whether it knew the country, not only the years.

The sibling module pins the time axes: which year's working week was used, where
it was carried from, and whether that year contributed holidays. All three are
about time, and all three were already honest. The axis missing from the
response was the country itself.

``country_code`` on the response is the code that was asked about. On its own it
read as a claim that this country's calendar produced the answer, which is
exactly what it does not mean for a country with no calendar at all - there the
week is a hardcoded Monday-Friday belonging to nobody. ``jurisdiction`` is that
claim made properly.

The distinction was derivable before this: every entry in ``years`` reads
``default`` exactly when no calendar exists. Derivable is not stated. A caller
should not have to reconstruct a fact about a country from a list about years,
and a single-year range gives it nothing to compare against.

The test that carries the most weight here is
:func:`test_a_known_country_is_still_known_outside_its_seeded_year`, because it
is the case where the two axes disagree: the country is known, the year is not,
and one flag across both would have to pick a side and be wrong about the other.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.provenance import Source
from app.modules.i18n_foundation.seed import _seed_work_calendars
from app.modules.i18n_foundation.service import I18nFoundationService

SEEDED_YEAR = 2026

#: A real country the shipped seed does not carry. Asserted rather than assumed
#: below, because the finding is about coverage and a test that quietly stopped
#: describing an uncovered country would still pass.
UNSEEDED = "MN"


async def _seeded_service(session: AsyncSession) -> I18nFoundationService:
    await _seed_work_calendars(session)
    service = I18nFoundationService(session)

    assert await service.work_calendar_repo.list(country_code="DE"), (
        "the shipped seed no longer carries a calendar for DE"
    )
    assert not await service.work_calendar_repo.list(country_code=UNSEEDED), (
        f"{UNSEEDED} is now seeded; this module needs a country the seed does not carry"
    )
    return service


async def test_a_seeded_country_reports_its_own_calendar_as_declared(session: AsyncSession) -> None:
    """Declared, not merely non-fallback.

    An implementation that reported a fallback for nothing, or for everything,
    would pass a test that only asked whether this was not a fallback.
    """
    service = await _seeded_service(session)

    answer = await service.get_working_days(
        country_code="DE",
        from_date=f"{SEEDED_YEAR}-01-05",
        to_date=f"{SEEDED_YEAR}-01-18",
    )

    assert answer.jurisdiction.source is Source.DECLARED
    assert answer.jurisdiction.answered is True
    assert answer.jurisdiction.requested == "DE"
    assert answer.jurisdiction.used == "DE"


async def test_a_country_with_no_calendar_says_the_week_belongs_to_nobody(session: AsyncSession) -> None:
    """Fallback, naming the generic week rather than echoing the request."""
    service = await _seeded_service(session)

    answer = await service.get_working_days(
        country_code=UNSEEDED,
        from_date=f"{SEEDED_YEAR}-01-05",
        to_date=f"{SEEDED_YEAR}-01-18",
    )

    assert answer.jurisdiction.source is Source.FALLBACK
    assert answer.jurisdiction.answered is False
    assert answer.jurisdiction.requested == UNSEEDED
    assert answer.jurisdiction.used != UNSEEDED
    # country_code keeps meaning what it always meant: what was asked about.
    assert answer.country_code == UNSEEDED


async def test_the_two_countries_do_not_get_the_same_verdict(session: AsyncSession) -> None:
    """The control for a constant answer, as one comparison between the cases."""
    service = await _seeded_service(session)

    known = await service.get_working_days(
        country_code="DE", from_date=f"{SEEDED_YEAR}-01-05", to_date=f"{SEEDED_YEAR}-01-18"
    )
    unknown = await service.get_working_days(
        country_code=UNSEEDED, from_date=f"{SEEDED_YEAR}-01-05", to_date=f"{SEEDED_YEAR}-01-18"
    )

    assert known.jurisdiction.source is not unknown.jurisdiction.source


async def test_a_known_country_is_still_known_outside_its_seeded_year(session: AsyncSession) -> None:
    """The case the two axes answer differently, which is why there are two.

    Past the seeded year the working week is carried, so the time axis reports
    a fallback of its own. The country is not in question at all - its calendar
    exists, just not for that year - and a single flag would have to call this
    either fully declared or fully fallen back, and would be wrong either way.
    """
    service = await _seeded_service(session)

    answer = await service.get_working_days(
        country_code="DE",
        from_date=f"{SEEDED_YEAR + 1}-01-05",
        to_date=f"{SEEDED_YEAR + 1}-01-18",
    )

    assert answer.jurisdiction.source is Source.DECLARED

    year = next(y for y in answer.years if y.year == SEEDED_YEAR + 1)
    assert year.work_week_source == "carried"
    assert year.work_week_from_year == SEEDED_YEAR
    assert year.holidays_applied is False


async def test_an_unknown_country_falls_back_on_both_axes_at_once(session: AsyncSession) -> None:
    """The converse, so the pair above cannot pass by reporting a fixed pattern."""
    service = await _seeded_service(session)

    answer = await service.get_working_days(
        country_code=UNSEEDED,
        from_date=f"{SEEDED_YEAR}-01-05",
        to_date=f"{SEEDED_YEAR}-01-18",
    )

    assert answer.jurisdiction.source is Source.FALLBACK
    assert [y.work_week_source for y in answer.years] == ["default"]


async def test_saying_so_did_not_move_the_arithmetic(session: AsyncSession) -> None:
    """Reporting how the answer was built must not change the answer.

    Monday to Sunday across two weeks is ten working days under a Monday-Friday
    week, and the same range is counted the same way whether or not the country
    is known - what differs is only what the answer admits about itself.
    """
    service = await _seeded_service(session)

    unknown = await service.get_working_days(
        country_code=UNSEEDED,
        from_date=f"{SEEDED_YEAR}-01-05",
        to_date=f"{SEEDED_YEAR}-01-18",
    )

    assert unknown.working_days == 10
    assert unknown.calendar_days == 14
