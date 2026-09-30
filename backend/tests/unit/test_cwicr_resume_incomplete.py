# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A cost base whose import was cut off is finished on request, not called loaded.

``load_cwicr_region`` treats a region with more than ten rows as loaded. The
import commits every 5 000 rows on its own, so an import cut by a proxy timeout
or a restart leaves a fraction of the base, and every later load, the pack
installer's Retry included, reported that fraction as "already loaded".

``resume_incomplete`` (passed by the pack installer only) carries on importing
a region well short of the base's published count. A short region that was
repriced into another market is not topped up with home-currency rows. Without
the flag nothing changes, which is what keeps the market switch and the
``/load-cwicr`` route as they were.

The parquet lookup and the import itself are stubbed; the count, the currency
check and the decision run against a real per-test PostgreSQL database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.costs import router as costs_router
from app.modules.costs.models import CostItem
from tests._pg import isolated_engine

_REGION = "DE_BERLIN"  # published with about 55 700 work items, priced in EUR


@pytest_asyncio.fixture
async def session_factory():
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed(factory: async_sessionmaker[AsyncSession], count: int, currency: str) -> None:
    async with factory() as s:
        for i in range(count):
            s.add(
                CostItem(
                    code=f"CUT-{i:04d}",
                    description="Work item from the interrupted import",
                    unit="m3",
                    rate="10.00",
                    currency=currency,
                    region=_REGION,
                )
            )
        await s.commit()


@pytest.fixture
def imports(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the parquet lookup and the import; record each import run."""
    calls: list[str] = []

    async def _find(db_id: str) -> Path:
        return Path(f"{db_id}.parquet")

    def _import(_path: str, db_id: str, _target: str) -> dict[str, Any]:
        calls.append(db_id)
        # Everything was already in: the per-flush ON CONFLICT added nothing.
        return {"imported": 0, "skipped": 0, "database": db_id}

    monkeypatch.setattr(costs_router, "_find_cwicr_file", _find)
    monkeypatch.setattr(costs_router, "_process_and_insert_cwicr", _import)
    return calls


@pytest.mark.asyncio
async def test_a_cut_off_base_is_resumed_when_asked(
    session_factory: async_sessionmaker[AsyncSession], imports: list[str]
) -> None:
    await _seed(session_factory, 50, "EUR")

    async with session_factory() as s:
        res = await costs_router.load_cwicr_region(_REGION, s, resume_incomplete=True)

    assert imports == [_REGION]
    assert res.get("status") != "already_loaded"
    assert res["resumed"] is True
    # The size of the base, not only what this run added.
    assert res["total_items"] == 50


@pytest.mark.asyncio
async def test_without_the_flag_a_cut_off_base_still_reads_loaded(
    session_factory: async_sessionmaker[AsyncSession], imports: list[str]
) -> None:
    """The route and the market switch keep their behaviour."""
    await _seed(session_factory, 50, "EUR")

    async with session_factory() as s:
        res = await costs_router.load_cwicr_region(_REGION, s)

    assert imports == []
    assert res["status"] == "already_loaded"


@pytest.mark.asyncio
async def test_a_complete_base_is_not_imported_again(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession], imports: list[str]
) -> None:
    await _seed(session_factory, 50, "EUR")
    # Fifty rows stand in for a full base: lower the bar instead of seeding 55 000.
    monkeypatch.setattr(costs_router, "_COMPLETE_BASE_SHARE", 50 / 55719 / 2)

    async with session_factory() as s:
        res = await costs_router.load_cwicr_region(_REGION, s, resume_incomplete=True)

    assert imports == []
    assert res["status"] == "already_loaded"


@pytest.mark.asyncio
async def test_a_cut_off_base_repriced_elsewhere_is_reported_not_topped_up(
    session_factory: async_sessionmaker[AsyncSession], imports: list[str]
) -> None:
    """Home-currency rows added to a USD region would mix two currencies."""
    await _seed(session_factory, 50, "USD")

    async with session_factory() as s:
        res = await costs_router.load_cwicr_region(_REGION, s, resume_incomplete=True)

    assert imports == []
    assert res["status"] == "incomplete"
    assert res["total_items"] == 50
    assert res["expected_items"] > 50
    assert res["currency"] == "USD"
