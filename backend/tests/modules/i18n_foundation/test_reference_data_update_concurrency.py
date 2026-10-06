"""Separate PostgreSQL transactions must not overwrite edits or deliver a rate twice."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.data_repairs import DataRepairDelivery
from app.modules.i18n_foundation import reference_data_update as updater
from app.modules.i18n_foundation.models import TaxConfiguration
from tests._pg import isolated_engine
from tests.modules.i18n_foundation.test_reference_data_update import NEW_KEYS, _install_old

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory():
    async with isolated_engine() as engine:
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sessions() as setup:
            await _install_old(setup)
            await setup.commit()
        yield sessions


async def _wait_for_reference_lock(observer: AsyncSession, pid: int, task: asyncio.Task) -> None:
    async def waiting():
        while not task.done():
            blocked = await observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :pid AND NOT granted "
                    "AND locktype = 'relation' AND relation IN "
                    "('oe_i18n_country'::regclass, 'oe_i18n_work_calendar'::regclass, "
                    "'oe_i18n_tax_config'::regclass))"
                ),
                {"pid": pid},
            )
            if blocked:
                return
            await asyncio.sleep(0.01)
        pytest.fail("The writer finished without waiting for the reference-data lock")

    await asyncio.wait_for(waiting(), timeout=10)


async def test_two_apply_transactions_deliver_each_rate_once(factory, monkeypatch):
    reached, release = asyncio.Event(), asyncio.Event()
    original = updater.compute_reference_diff
    paused = False

    async with factory() as first, factory() as second, factory() as observer:

        async def pause_after_first_read(session):
            nonlocal paused
            diff = await original(session)
            if session is first and not paused:
                paused = True
                reached.set()
                await release.wait()
            return diff

        monkeypatch.setattr(updater, "compute_reference_diff", pause_after_first_read)

        async def apply(session):
            result = await updater.apply_reference_update(session, sorted(NEW_KEYS))
            await session.commit()
            return result

        pid = await second.scalar(text("SELECT pg_backend_pid()"))
        task_a = asyncio.create_task(apply(first))
        task_b = None
        try:
            await asyncio.wait_for(reached.wait(), timeout=10)
            task_b = asyncio.create_task(apply(second))
            await _wait_for_reference_lock(observer, pid, task_b)
        finally:
            release.set()
            tasks = [task_a] if task_b is None else [task_a, task_b]
            outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=20)

        assert all(not isinstance(value, BaseException) for value in outcomes), outcomes
        assert len(outcomes) == 2
        assert (outcomes[0].rows_added, outcomes[1].rows_added) == (4, 0)
        assert set(outcomes[1].skipped) == NEW_KEYS
        for key in NEW_KEYS:
            country, code = key.removeprefix("tax:").split("/")
            count = await observer.scalar(
                select(func.count())
                .select_from(TaxConfiguration)
                .where(
                    TaxConfiguration.country_code == country,
                    TaxConfiguration.tax_code == code,
                )
            )
            assert count == 1, key
        delivered = await observer.scalar(
            select(func.count())
            .select_from(DataRepairDelivery)
            .where(
                DataRepairDelivery.repair_id == updater.REPAIR_ID,
                DataRepairDelivery.delivery_key.in_(NEW_KEYS),
            )
        )
        assert delivered == 4


async def test_apply_waits_for_a_custom_rate_insert_then_rechecks_the_jurisdiction(factory):
    async with factory() as custom_writer, factory() as applying, factory() as observer:
        # This writer uses ordinary INSERT, not an updater-specific advisory
        # lock. The pending custom tier must be visible to Apply's fresh check.
        custom = TaxConfiguration(
            country_code="HU",
            tax_code="OUR_5",
            tax_name="Our reduced rate",
            rate_pct="5.0",
            tax_type="vat",
            combination="national",
            effective_from="2020-01-01",
            is_default=False,
        )
        custom_writer.add(custom)
        await custom_writer.flush()
        custom_id = custom.id
        pid = await applying.scalar(text("SELECT pg_backend_pid()"))

        async def apply():
            result = await updater.apply_reference_update(applying, ["tax:HU/AFA_5"])
            await applying.commit()
            return result

        task = asyncio.create_task(apply())
        try:
            await _wait_for_reference_lock(observer, pid, task)
        finally:
            await custom_writer.commit()
            result = await asyncio.wait_for(task, timeout=20)

        assert result.applied == []
        assert result.skipped == ["tax:HU/AFA_5"]
        refusal = next(change for change in result.after.changes if change.key == "tax:HU/AFA_5")
        assert (refusal.status, refusal.reason) == ("review", "jurisdiction")
        own = await observer.get(TaxConfiguration, custom_id)
        assert (own.tax_name, own.rate_pct, own.tax_code) == ("Our reduced rate", "5.0", "OUR_5")
        count = await observer.scalar(
            select(func.count())
            .select_from(TaxConfiguration)
            .where(
                TaxConfiguration.country_code == "HU",
                TaxConfiguration.tax_code == "AFA_5",
            )
        )
        assert count == 0
        delivered = await observer.scalar(
            select(func.count())
            .select_from(DataRepairDelivery)
            .where(
                DataRepairDelivery.repair_id == updater.REPAIR_ID,
                DataRepairDelivery.delivery_key == "tax:HU/AFA_5",
            )
        )
        assert delivered == 0
