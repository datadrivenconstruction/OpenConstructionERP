# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ISO-zero repair against the row it exists for and the row it must not touch.

The headline number is the one to read first. Saudi Arabia stored as
``[0, 1, 2, 3, 4]`` counts four working days in the week of 4 January 2026,
because ``isoweekday()`` returns 1..7 and the 0 matches nothing at all. Stored
as ``[7, 1, 2, 3, 4]`` it counts five. That is the defect: not a refusal, not an
error in a log, a working week quietly one day short for every schedule drawn in
the country.

The other half is the four-day Monday-to-Thursday week. It is unusual, it is
entirely legal on this axis, and a repair that could not tell it apart from a
week written on the wrong axis would be rewriting somebody's deliberate
configuration on every boot. That case is asserted here rather than reasoned
about, because it is the one that decides whether this repair is safe to ship.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.data_repairs import run_data_repairs
from app.modules.i18n_foundation.models import WorkCalendar
from app.modules.i18n_foundation.seed import load_work_calendar_seed_rows, work_calendar_from_seed_row
from app.modules.i18n_foundation.service import I18nFoundationService
from app.modules.i18n_foundation.work_calendar_iso_zero import REPAIR_ID

pytestmark = pytest.mark.asyncio

#: The week the Saudi row was shipped with, on the wrong axis.
_BROKEN = [0, 1, 2, 3, 4]

#: The same week written the way the column is read.
_REPAIRED = [7, 1, 2, 3, 4]

#: A Sunday to the Saturday after it. Saudi Arabia declares no January holiday,
#: so nothing but the working week itself moves this count.
_WEEK_START = "2026-01-04"
_WEEK_END = "2026-01-10"


@pytest_asyncio.fixture
async def repair_factory(pg_engine):
    """A session factory the runner can open many sessions from, rolled back after."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    conn = await pg_engine.connect()
    trans = await conn.begin()
    factory = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        if trans.is_active:
            await trans.rollback()
        await conn.close()


async def _install(factory, *, weeks: dict[str, list[int]] | None = None) -> None:
    """Seed from the shipped file, optionally overriding some countries' weeks."""
    overrides = weeks or {}
    async with factory() as session:
        await session.execute(WorkCalendar.__table__.delete())
        for row in load_work_calendar_seed_rows():
            calendar = work_calendar_from_seed_row(row)
            if calendar.country_code in overrides:
                calendar.work_days = list(overrides[calendar.country_code])
            session.add(calendar)
        await session.commit()


async def _weeks(factory) -> dict[str, list[int]]:
    async with factory() as session:
        rows = (await session.execute(select(WorkCalendar))).scalars().all()
    return {row.country_code: list(row.work_days) for row in rows}


async def _working_days(factory, country: str) -> int:
    async with factory() as session:
        answer = await I18nFoundationService(session).get_working_days(country, _WEEK_START, _WEEK_END)
    return answer.working_days


def _outcome(report, repair_id: str):
    return next(o for o in report.outcomes if o.repair_id == repair_id)


async def test_the_shipped_saudi_row_stops_counting_a_four_day_week(repair_factory) -> None:
    """The defect end to end, in the number a planner would actually see."""
    await _install(repair_factory, weeks={"SA": _BROKEN})

    before = await _working_days(repair_factory, "SA")
    assert before == 4, (
        f"Saudi Arabia counts {before} working days before the repair, not the four the defect "
        "produces, so this fixture is not the broken row and everything below measures nothing"
    )

    report = await run_data_repairs(repair_factory)
    outcome = _outcome(report, REPAIR_ID)

    assert outcome.status == "applied"
    assert outcome.rows_changed == 1
    assert (await _weeks(repair_factory))["SA"] == _REPAIRED
    assert await _working_days(repair_factory, "SA") == 5, "the Saudi week is still one day short"


async def test_a_deliberate_four_day_week_is_left_alone(repair_factory) -> None:
    """The case that separates "wrong axis" from "unusual but meant".

    Monday to Thursday is four days, which is the same length as the defect
    produces, and it is a perfectly legal week on this axis. Nothing here may be
    rewritten, and the repair must report having changed nothing at all rather
    than quietly counting it.
    """
    their_week = [1, 2, 3, 4]
    await _install(repair_factory, weeks={"DE": their_week})

    report = await run_data_repairs(repair_factory)

    assert (await _weeks(repair_factory))["DE"] == their_week, (
        "the repair rewrote a deliberate four-day Monday-to-Thursday week"
    )
    assert _outcome(report, REPAIR_ID).rows_changed == 0


async def test_only_the_impossible_row_is_touched(repair_factory) -> None:
    """One row changed, every other week byte for byte what it was.

    The count matters beyond this test. One is the expected number on an install
    carrying the shipped Saudi row; anything larger means something is writing 0
    into this column today and the repair would be treating a symptom.
    """
    await _install(repair_factory, weeks={"SA": _BROKEN})
    before = await _weeks(repair_factory)

    report = await run_data_repairs(repair_factory)
    after = await _weeks(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 1
    assert set(before) == set(after), "the repair added or removed a calendar"
    changed = {code for code in before if before[code] != after[code]}
    assert changed == {"SA"}, f"the repair touched rows it had no business touching: {sorted(changed - {'SA'})}"


async def test_a_clean_install_is_untouched(repair_factory) -> None:
    """The shipped file carries no such row, so a fresh install never meets this."""
    await _install(repair_factory)
    before = await _weeks(repair_factory)

    report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 0
    assert await _weeks(repair_factory) == before


async def test_a_second_boot_corrects_nothing(repair_factory) -> None:
    """Idempotent on the data rather than on a version marker."""
    await _install(repair_factory, weeks={"SA": _BROKEN})

    first = await run_data_repairs(repair_factory)
    assert _outcome(first, REPAIR_ID).rows_changed == 1
    after_first = await _weeks(repair_factory)

    second = await run_data_repairs(repair_factory)

    assert _outcome(second, REPAIR_ID).rows_changed == 0
    assert await _weeks(repair_factory) == after_first


async def test_a_second_country_with_the_same_error_is_covered_too(repair_factory) -> None:
    """The guard is the value, not the country, so a new offender needs no new repair."""
    await _install(repair_factory, weeks={"SA": _BROKEN, "QA": [0, 1, 2, 3, 4]})

    report = await run_data_repairs(repair_factory)
    weeks = await _weeks(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 2
    assert weeks["SA"] == _REPAIRED
    assert weeks["QA"] == _REPAIRED
