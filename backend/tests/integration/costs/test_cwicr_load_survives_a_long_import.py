"""A regional cost base load must not leave its own session broken.

The onboarding job for a large base (55 719 items for Toronto) used to end as
``failed`` at 15% with "Can't reconnect until invalid transaction is rolled
back", while every item was in fact in the database. The mechanism is a
PostgreSQL session state, so these tests run on PostgreSQL and nothing else:

1. ``load_cwicr_region`` reads the item count through the caller's async
   session. That read opens a transaction.
2. The import itself runs for many minutes in a thread on its OWN sync
   connection and commits there, so the items land.
3. Meanwhile the async session sits "idle in transaction". The request engine
   carries ``idle_in_transaction_session_timeout`` (300 s by default), so the
   server terminates that connection.
4. The resource price sheet seed then runs on the dead session, fails, and is
   swallowed as "non-fatal". The session is now invalid, and the caller's
   ``commit`` raises the error the user saw. The price sheet is also missing,
   which nothing reported at all.

The test reproduces this with a one-second timeout and an import that takes a
few seconds, which is the same state in miniature. The assertion that matters is
the price sheet row, not the absence of an exception: a fix that only rolled the
session back would pass "no exception" and still lose the sheet.

The second test covers the other way one bad input used to fail a whole load:
one row PostgreSQL refuses (a NUL character in a description) sank its whole
flush, and with it the import. That row must be skipped and counted.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.costs import router
from app.modules.costs.models import CostItem, ResourcePrice
from tests._pg import isolated_database_url

REGION = "ZZ_LONG_IMPORT"
# The server-side idle budget the tests give the caller's session, and how much
# longer than that the simulated import takes. The gap is the experiment: an
# import shorter than the budget would pass on the unfixed code too.
_IDLE_MS = 1000
_IMPORT_S = 2.5


def _write_parquet(path: Path, descriptions: list[str]) -> None:
    """A minimal CWICR parquet: one work item per description, one labour resource each."""
    import pandas as pd

    pd.DataFrame(
        [
            {
                "rate_code": f"R{index:04d}",
                "rate_original_name": text,
                "rate_final_name": text,
                "rate_unit": "m3",
                "collection_name": "Works",
                "department_name": "Structural",
                "section_name": "Demolition",
                "resource_code": "L1",
                "resource_name": "Labour",
                "resource_unit": "hr",
                "resource_quantity": 1.0,
                "resource_price_per_unit_current": 10.0,
                "resource_cost": 10.0,
                "row_type": "Labour",
                "is_labor": True,
                "is_material": False,
                "is_machine": False,
            }
            for index, text in enumerate(descriptions)
        ]
    ).to_parquet(path, index=False)


def _sync_url(async_url: str) -> str:
    return make_url(async_url).set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


@pytest.fixture
def isolated_db():
    """A throwaway schema-loaded database the importer's sync engine also writes to."""
    with isolated_database_url() as url:
        # The bulk import reads its target from the live env, exactly as in
        # production; point it at the clone rather than the shared test database.
        # Restored by hand before the clone is dropped: the drop connects to the
        # database this variable names, and would find itself inside the clone.
        previous = os.environ["DATABASE_SYNC_URL"]
        os.environ["DATABASE_SYNC_URL"] = _sync_url(url)
        try:
            yield url
        finally:
            os.environ["DATABASE_SYNC_URL"] = previous


@pytest_asyncio.fixture
async def factory(isolated_db: str):
    """Sessions whose idle-in-transaction budget is short enough to cross in a test."""
    engine = create_async_engine(
        isolated_db,
        poolclass=NullPool,
        connect_args={"server_settings": {"idle_in_transaction_session_timeout": str(_IDLE_MS)}},
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        # Before the clone is dropped, or the drop finds it still open.
        await engine.dispose()


def _point_at(parquet: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _find(_db_id: str) -> Path:
        return parquet

    monkeypatch.setattr(router, "_find_cwicr_file", _find)


async def test_a_load_longer_than_the_idle_budget_commits_and_seeds_the_price_sheet(
    factory: async_sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet = tmp_path / "cwicr.parquet"
    _write_parquet(parquet, [f"Work item {i}" for i in range(5)])
    _point_at(parquet, monkeypatch)

    real_import = router._process_and_insert_cwicr

    def _slow_import(path: str, db_id: str, target: str) -> dict:
        # The real import, preceded by the wall time a large base spends in
        # pandas and COPY while the caller's session waits.
        time.sleep(_IMPORT_S)
        return real_import(path, db_id, target)

    monkeypatch.setattr(router, "_process_and_insert_cwicr", _slow_import)

    async with factory() as session:
        result = await router.load_cwicr_region(REGION, session)
        # This is the call that raised "Can't reconnect until invalid
        # transaction is rolled back" in the onboarding handler.
        await session.commit()

    assert result["imported"] == 5
    async with factory() as check:
        items = (await check.execute(select(func.count()).where(CostItem.region == REGION))).scalar_one()
        prices = (await check.execute(select(func.count()).where(ResourcePrice.region == REGION))).scalar_one()
    assert items == 5
    # The half nobody saw: the price sheet seed ran on the dead session.
    assert prices == 1, "the resource price sheet was not seeded"
    assert "resource_prices" in result


async def test_a_row_postgresql_refuses_is_skipped_and_counted_not_fatal(
    factory: async_sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptions = [f"Work item {i}" for i in range(6)]
    # PostgreSQL text cannot hold a NUL character; COPY rejects the whole chunk.
    descriptions[3] = "Work item\x00 three"
    parquet = tmp_path / "cwicr.parquet"
    _write_parquet(parquet, descriptions)
    _point_at(parquet, monkeypatch)

    async with factory() as session:
        result = await router.load_cwicr_region(REGION, session)
        await session.commit()

    assert result["imported"] == 5
    assert result["failed"] == 1
    assert result["failed_codes"] == ["R0003"]
    async with factory() as check:
        codes = (await check.execute(select(CostItem.code).where(CostItem.region == REGION))).scalars().all()
    assert sorted(codes) == ["R0000", "R0001", "R0002", "R0004", "R0005"]


async def test_loading_a_base_again_seeds_a_price_sheet_the_first_load_lost(
    factory: async_sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The estate the failure above left behind: items loaded, sheet empty.

    Every later load of the region takes the already-loaded early return, so
    without a seed there the sheet would stay empty for good while the job
    reported the base complete.
    """
    parquet = tmp_path / "cwicr.parquet"
    # More than the early return's threshold of ten items.
    _write_parquet(parquet, [f"Work item {i}" for i in range(12)])
    _point_at(parquet, monkeypatch)

    async with factory() as session:
        await router.load_cwicr_region(REGION, session)
        await session.commit()
    async with factory() as session:
        await session.execute(delete(ResourcePrice).where(ResourcePrice.region == REGION))
        await session.commit()

    async with factory() as session:
        result = await router.load_cwicr_region(REGION, session)
        await session.commit()

    assert result["status"] == "already_loaded"
    async with factory() as check:
        prices = (await check.execute(select(func.count()).where(ResourcePrice.region == REGION))).scalar_one()
    assert prices == 1
