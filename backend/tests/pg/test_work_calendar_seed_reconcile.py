# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The work calendar reconciler, against the cohorts it has to tell apart.

The repair delivers calendars an install was seeded too early to receive, and
the whole of its safety is in one distinction: a country with no calendar
because ours never arrived, against a country with no calendar because somebody
removed it. Those two databases look identical row for row. What separates them
is when the table was seeded, so every cohort here carries an explicit
``created_at`` and the tests are built around what that date licenses.

The cohorts are reconstructed as exclusions from today's seed file rather than
vendored, so they cannot drift away from what the product actually ships, and
each reconstruction asserts its own shape before it is used - a cohort that
silently stopped being the broken one would make every assertion below pass
while measuring nothing.

The end-to-end assertion is the one worth reading first. Sunday 4 January 2026
is a working day in Doha and is not one in Berlin, and Qatar declares no holiday
in January, so ``get_working_days`` over that single date answers 1 with the
calendar and 0 without it. That is the defect in one number: before the repair
the platform does not refuse to answer for Qatar, it answers confidently and
wrongly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.data_repairs import DataRepairDelivery, run_data_repairs
from app.core.provenance import Source
from app.modules.i18n_foundation.models import WorkCalendar
from app.modules.i18n_foundation.seed import load_work_calendar_seed_rows, work_calendar_from_seed_row
from app.modules.i18n_foundation.service import I18nFoundationService
from app.modules.i18n_foundation.work_calendar_seed_reconcile import (
    CALENDAR_FIRST_SHIPPED,
    REPAIR_ID,
)

pytestmark = pytest.mark.asyncio

#: A Sunday. A working day under a Sunday-to-Thursday week and a weekend day
#: under Monday-to-Friday, which is what makes it the discriminator. Qatar
#: declares no January holiday, so nothing else moves this count.
_A_SUNDAY = "2026-01-04"

#: The Gulf four, whose absence changes a date. Bulgaria and Nigeria are
#: delivered by the same repair but are Monday to Friday, which is what the
#: fallback already answers, so their arrival moves no schedule.
_GULF = ("BH", "KW", "OM", "QA")

#: Sunday through Thursday in ISO numbering.
_GULF_WEEK = [7, 1, 2, 3, 4]

#: The reconciler's own logger. Named so the warning assertions below read only
#: what this repair said: ``run_data_repairs`` runs every registered repair, and
#: a neighbour's warning must not be able to satisfy or break them.
_LOGGER = "app.modules.i18n_foundation.work_calendar_seed_reconcile"


def _warnings(caplog) -> list[str]:
    """What the reconciler warned about, in order."""
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING]


def _shipped() -> list[dict]:
    return load_work_calendar_seed_rows()


def _cohort_without_the_dated_rows() -> list[dict]:
    """The seed file as it stood before any of the six late calendars shipped."""
    dated = {country for country, _ in CALENDAR_FIRST_SHIPPED}
    rows = [row for row in _shipped() if row["country_code"] not in dated]
    assert len(rows) >= 25, f"cohort reconstruction left only {len(rows)} calendars; the seed file has changed shape"
    for country in _GULF:
        assert not any(r["country_code"] == country for r in rows), (
            f"{country} survived the exclusion, so this cohort is not the one missing the Gulf calendars"
        )
    return rows


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


async def _install(factory, cohort: list[dict], seeded_on: str) -> None:
    """Seed a database from *cohort*, as the seeder would, on a given date.

    One instant for every row, because that is what the seeder does: it writes
    the whole file in one transaction over an empty table, and the reconciler
    reads that fact back to date the seed.
    """
    seeded_at = datetime.fromisoformat(seeded_on).replace(tzinfo=UTC)
    async with factory() as session:
        await session.execute(WorkCalendar.__table__.delete())
        for row in cohort:
            calendar = work_calendar_from_seed_row(row)
            calendar.created_at = seeded_at
            calendar.updated_at = seeded_at
            session.add(calendar)
        await session.commit()


async def _countries(factory) -> set[str]:
    async with factory() as session:
        rows = (await session.execute(select(WorkCalendar.country_code))).all()
    return {row[0] for row in rows}


async def _week(factory, country: str) -> list[int] | None:
    async with factory() as session:
        row = (
            await session.execute(select(WorkCalendar).where(WorkCalendar.country_code == country))
        ).scalar_one_or_none()
    return None if row is None else row.work_days


async def _count(factory) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(WorkCalendar))).scalar_one()


async def _deliveries(factory) -> set[str]:
    async with factory() as session:
        rows = await session.execute(
            select(DataRepairDelivery.delivery_key).where(DataRepairDelivery.repair_id == REPAIR_ID)
        )
    return {row[0] for row in rows}


async def _working_days_on_the_sunday(factory, country: str):
    async with factory() as session:
        return await I18nFoundationService(session).get_working_days(country, _A_SUNDAY, _A_SUNDAY)


def _outcome(report, repair_id: str):
    return next(o for o in report.outcomes if o.repair_id == repair_id)


async def test_a_pre_gulf_install_is_given_the_calendars_it_never_received(repair_factory) -> None:
    """The defect, measured on the cohort that has it, end to end."""
    cohort = _cohort_without_the_dated_rows()
    await _install(repair_factory, cohort, "2026-06-01")

    before = await _working_days_on_the_sunday(repair_factory, "QA")
    assert before.working_days == 0, (
        "Qatar already counts the Sunday as a working day before any repair ran, so this fixture is "
        "not the broken cohort and everything below it would be measuring nothing"
    )
    assert before.jurisdiction.source == Source.FALLBACK

    report = await run_data_repairs(repair_factory)
    outcome = _outcome(report, REPAIR_ID)

    assert outcome.status == "applied"
    assert outcome.rows_changed == len(CALENDAR_FIRST_SHIPPED), (
        f"expected {len(CALENDAR_FIRST_SHIPPED)} calendars delivered, got {outcome.rows_changed}"
    )
    assert await _deliveries(repair_factory) == {f"{c}/{y}" for c, y in CALENDAR_FIRST_SHIPPED}
    assert await _count(repair_factory) == len(cohort) + len(CALENDAR_FIRST_SHIPPED)

    for country in _GULF:
        assert await _week(repair_factory, country) == _GULF_WEEK, f"{country} did not get a Sunday-Thursday week"

    after = await _working_days_on_the_sunday(repair_factory, "QA")
    assert after.working_days == 1, "Qatar still does not count Sunday as a working day"
    assert after.jurisdiction.source == Source.DECLARED


async def test_a_country_that_already_has_a_calendar_is_left_alone(repair_factory) -> None:
    """The promise the whole repair rests on.

    Somebody may have edited their Qatar week, and a reconciler that overwrites
    it is worse than the gap it closes. Their row stands exactly as written -
    and the three countries beside it are still delivered, so declining one is
    not an excuse to decline the rest.
    """
    cohort = _cohort_without_the_dated_rows()
    await _install(repair_factory, cohort, "2026-06-01")

    their_week = [1, 2, 3, 4, 5]
    async with repair_factory() as session:
        session.add(
            WorkCalendar(
                country_code="QA",
                name="Our own Qatar week",
                year="2026",
                work_hours_per_day="9",
                work_days=their_week,
                exceptions=[],
                metadata_={},
            )
        )
        await session.commit()

    report = await run_data_repairs(repair_factory)
    outcome = _outcome(report, REPAIR_ID)

    assert await _week(repair_factory, "QA") == their_week, "the reconciler overwrote a hand-edited Qatar calendar"
    async with repair_factory() as session:
        row = (await session.execute(select(WorkCalendar).where(WorkCalendar.country_code == "QA"))).scalar_one()
    assert row.name == "Our own Qatar week"
    assert row.work_hours_per_day == "9"

    assert outcome.rows_changed == len(CALENDAR_FIRST_SHIPPED) - 1
    assert "QA/2026" not in await _deliveries(repair_factory)
    for country in ("BH", "KW", "OM"):
        assert await _week(repair_factory, country) == _GULF_WEEK, f"{country} was declined along with Qatar"


async def test_a_deleted_calendar_is_not_resurrected(repair_factory) -> None:
    """An install seeded after the calendars shipped removed them on purpose."""
    cohort = _cohort_without_the_dated_rows()
    await _install(repair_factory, cohort, "2026-08-30")

    report = await run_data_repairs(repair_factory)
    outcome = _outcome(report, REPAIR_ID)

    assert outcome.rows_changed == 0, "calendars a customer deleted were put back"
    assert await _deliveries(repair_factory) == set()
    assert await _countries(repair_factory) & set(_GULF) == set()


async def test_an_install_whose_seed_cannot_be_dated_is_given_nothing(repair_factory, caplog) -> None:
    """No anchoring calendar left means no evidence either way, so nothing moves.

    The warning is asserted rather than merely allowed. This is the one
    population the sentence about adding calendars by hand is true of - the
    table holds rows, so the seeder will not fill it, and nothing else is coming
    to close the gap. A change that silenced it here would take away the only
    notice this install ever gets.
    """
    late = {country for country, _ in CALENDAR_FIRST_SHIPPED}
    only_late = [row for row in _shipped() if row["country_code"] in late and row["country_code"] != "QA"]
    await _install(repair_factory, only_late, "2026-06-01")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 0
    assert "QA" not in await _countries(repair_factory)
    assert len(_warnings(caplog)) == 1, "the install that really has to be told by hand was not told"
    assert "by hand" in _warnings(caplog)[0]


async def test_an_unseeded_database_is_left_to_the_seeder_without_a_warning(repair_factory, caplog) -> None:
    """The first boot, where this repair runs before the data it reconciles exists.

    ``run_data_repairs`` is called from ``app.main`` well before
    ``seed_i18n_data``, so on a fresh data directory the reconciler meets an
    empty table. Read as a database whose seed cannot be dated, that produced a
    warning telling the user to add the calendars by hand, and roughly seven
    minutes later the seeder wrote all of them. The sentence was not early, it
    was false.

    An empty table is what tells the two apart, and it is a sound signal rather
    than a convenient one: ``_seed_work_calendars`` fills this table whenever it
    is empty, so an empty table always means the rows are on their way.
    """
    async with repair_factory() as session:
        await session.execute(WorkCalendar.__table__.delete())
        await session.commit()
    assert await _count(repair_factory) == 0, "this fixture is not the unseeded install it claims to be"

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        report = await run_data_repairs(repair_factory)

    assert _warnings(caplog) == [], "a fresh install was told to add by hand what the seeder is about to write"
    assert _outcome(report, REPAIR_ID).rows_changed == 0, "the reconciler wrote calendars the seeder will write"
    assert await _deliveries(repair_factory) == set(), (
        "deliveries were recorded against a database that has not been seeded, which would make the "
        "reconciler skip those calendars for the life of the install"
    )
    assert await _count(repair_factory) == 0


async def test_a_current_install_is_given_nothing(repair_factory) -> None:
    """A fresh install was seeded from today's file, so there is nothing to add."""
    await _install(repair_factory, _shipped(), "2026-08-30")

    report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 0
    assert await _count(repair_factory) == len(_shipped())


async def test_a_second_boot_delivers_nothing(repair_factory) -> None:
    """Idempotent on the data, and remembered in the ledger rather than inferred."""
    await _install(repair_factory, _cohort_without_the_dated_rows(), "2026-06-01")

    first = await run_data_repairs(repair_factory)
    assert _outcome(first, REPAIR_ID).rows_changed == len(CALENDAR_FIRST_SHIPPED)
    count_after_first = await _count(repair_factory)

    second = await run_data_repairs(repair_factory)
    assert _outcome(second, REPAIR_ID).rows_changed == 0
    assert await _count(repair_factory) == count_after_first


async def test_a_calendar_deleted_after_delivery_stays_deleted(repair_factory) -> None:
    """The ledger, not the table, is what says a delivery already happened.

    Without it the repair would read the empty slot on the next boot, date the
    seed to before the calendar shipped exactly as it did the first time, and
    hand the row back - which turns a customer deleting a calendar into a
    calendar that reappears at every restart.
    """
    await _install(repair_factory, _cohort_without_the_dated_rows(), "2026-06-01")
    await run_data_repairs(repair_factory)
    assert await _week(repair_factory, "QA") == _GULF_WEEK

    async with repair_factory() as session:
        await session.execute(WorkCalendar.__table__.delete().where(WorkCalendar.country_code == "QA"))
        await session.commit()

    report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 0
    assert "QA" not in await _countries(repair_factory), "a deleted calendar came back on the next boot"
