"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A calendar naming no working day must not silently zero the count.

``work_days`` is the weekly pattern, so a row with an empty one states no
working week at all. Counted with, it makes every date in every range a
non-working day, and the caller gets ``working_days: 0`` with a 200 and no
warning anywhere. That is the shape of failure this module keeps producing: not
an error, a plausible number.

The branch that made it dangerous is the out-of-range lookup. It builds a
mapping of year to week and then asks only whether the mapping is non-empty, so
a single empty week put a key in the mapping while putting nothing in the week.
The year then reported ``carried``, naming a real calendar as its source, and
counted nothing. A caller reading the disclosure would have been told the answer
came from a declared calendar, which was true, and would still have had a zero.

No shipped calendar has an empty week - all thirty seeded rows declare five
days - so nothing else will ever exercise this. These tests are the only thing
that will.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.provenance import Source
from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import make_calendar

# Monday to the second Sunday: fourteen calendar days, ten of them weekdays.
FROM_DATE = "2026-01-05"
TO_DATE = "2026-01-18"
WEEKDAYS_IN_RANGE = 10
DAYS_IN_RANGE = 14


async def test_an_empty_week_inside_the_range_is_not_counted_as_a_week(session: AsyncSession) -> None:
    """The year must fall through to Monday-Friday rather than to nothing."""
    await make_calendar(session, country_code="DE", year="2026", work_days=[])
    service = I18nFoundationService(session)

    answer = await service.get_working_days(country_code="DE", from_date=FROM_DATE, to_date=TO_DATE)

    assert answer.working_days == WEEKDAYS_IN_RANGE
    assert answer.working_days != 0
    assert answer.calendar_days == DAYS_IN_RANGE

    year = answer.years[0]
    assert year.work_week_source == "default"
    assert year.work_week_source != "declared"


async def test_an_empty_week_outside_the_range_is_not_carried(session: AsyncSession) -> None:
    """The branch the defect lived in, pinned on its own.

    The mapping is keyed by year, so an empty week still put a key in it. The
    emptiness check asked about the mapping and not about the week inside, which
    is how a year came to report a week carried from a real calendar and then
    count no working days at all.
    """
    await make_calendar(session, country_code="DE", year="2026", work_days=[])
    service = I18nFoundationService(session)

    answer = await service.get_working_days(country_code="DE", from_date="2027-01-04", to_date="2027-01-17")

    assert answer.working_days == WEEKDAYS_IN_RANGE
    assert answer.working_days != 0

    year = answer.years[0]
    assert year.work_week_source == "default"
    assert year.work_week_source != "carried"
    assert year.work_week_from_year is None


async def test_a_real_week_outside_the_range_is_still_carried(session: AsyncSession) -> None:
    """The negative control, without which the two tests above prove nothing.

    Both would pass against an implementation that had simply stopped carrying
    weeks between years. This is the case that must keep working, and it uses a
    week that is not Monday-Friday so that a fallback to the hardcoded week
    cannot be mistaken for a successful carry.
    """
    await make_calendar(session, country_code="SA", year="2026", work_days=[7, 1, 2, 3, 4])
    service = I18nFoundationService(session)

    answer = await service.get_working_days(country_code="SA", from_date="2027-01-04", to_date="2027-01-17")

    year = answer.years[0]
    assert year.work_week_source == "carried"
    assert year.work_week_from_year == 2026

    # Sunday to Thursday over the same fortnight is still ten days, which is
    # why the count alone could never have caught this: the totals match and
    # only the individual days differ. Asserted on a Friday and a Sunday.
    friday = await service.get_working_days(country_code="SA", from_date="2027-01-08", to_date="2027-01-08")
    sunday = await service.get_working_days(country_code="SA", from_date="2027-01-10", to_date="2027-01-10")
    assert friday.working_days == 0
    assert sunday.working_days == 1


async def test_a_country_whose_only_calendar_is_empty_reports_a_fallback(session: AsyncSession) -> None:
    """The jurisdiction axis has to agree with what actually answered.

    A row exists for this country, so a check that merely asked whether one
    existed would call it declared. Nothing in that row contributed to the
    answer, and the week used belongs to no country, so the honest verdict is
    the same as for a country with no row at all.
    """
    await make_calendar(session, country_code="DE", year="2026", work_days=[])
    service = I18nFoundationService(session)

    answer = await service.get_working_days(country_code="DE", from_date=FROM_DATE, to_date=TO_DATE)

    assert answer.jurisdiction.source is Source.FALLBACK
    assert answer.jurisdiction.answered is False
    assert answer.jurisdiction.used != "DE"


async def test_a_usable_calendar_still_reports_its_country(session: AsyncSession) -> None:
    """The control for the test above, so it cannot pass by always falling back."""
    await make_calendar(session, country_code="DE", year="2026", work_days=[1, 2, 3, 4, 5])
    service = I18nFoundationService(session)

    answer = await service.get_working_days(country_code="DE", from_date=FROM_DATE, to_date=TO_DATE)

    assert answer.jurisdiction.source is Source.DECLARED
    assert answer.jurisdiction.used == "DE"
