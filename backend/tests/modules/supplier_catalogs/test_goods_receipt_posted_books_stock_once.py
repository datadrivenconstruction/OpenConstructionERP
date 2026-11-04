# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A posted procurement goods receipt advances warehouse stock exactly once.

``procurement.goods_receipt.posted`` carries an idempotency key; the stock
subscriber claims it before booking, so a replayed event moves nothing, and a
line with no warehouse is skipped without failing the receipt.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_effects import EventEffect, claim_effect
from app.database import Base
from app.modules.supplier_catalogs.events import apply_goods_receipt_posted
from app.modules.supplier_catalogs.models import CatalogItem, StockBalance, StockMovement, Warehouse

pytestmark = pytest.mark.asyncio

_TABLES = [
    EventEffect.__table__,
    CatalogItem.__table__,
    Warehouse.__table__,
    StockBalance.__table__,
    StockMovement.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """The few tables the subscriber touches, in a throwaway schema of the test cluster."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    from app.modules.supplier_catalogs.models import ItemCategory

    url = make_url(os.environ["DATABASE_URL"])
    schema = f"t_{uuid.uuid4().hex[:10]}"
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[ItemCategory.__table__, *_TABLES]))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    async with async_sessionmaker(scoped, expire_on_commit=False)() as s:
        yield s
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def _stock(session: AsyncSession, item: uuid.UUID) -> Decimal:
    q = select(func.coalesce(func.sum(StockBalance.quantity_on_hand), 0)).where(StockBalance.catalog_item_id == item)
    return Decimal(str((await session.execute(q)).scalar_one()))


async def _fixture(session: AsyncSession, *, project: uuid.UUID, with_warehouse: bool = True):
    item = CatalogItem(sku=f"S-{uuid.uuid4().hex[:6]}", name="Rebar", unit_of_measure="t")
    session.add(item)
    wh = None
    if with_warehouse:
        wh = Warehouse(code=f"W-{uuid.uuid4().hex[:4]}", name="Yard", project_id=project)
        session.add(wh)
    await session.flush()
    return item, wh


def _payload(gr_id: uuid.UUID, project: uuid.UUID, item: uuid.UUID, **line) -> dict:
    return {
        "gr_id": str(gr_id),
        "po_id": str(uuid.uuid4()),
        "project_id": str(project),
        "currency_code": "EUR",
        "idempotency_key": f"gr:{gr_id}:posted",
        "lines": [
            {
                "po_line_id": str(uuid.uuid4()),
                "catalog_item_id": str(item),
                "warehouse_id": None,
                "qty": "5",
                "unit": "t",
                "unit_rate": "800",
                **line,
            }
        ],
    }


async def test_claim_effect_is_a_unique_insert(session: AsyncSession) -> None:
    assert await claim_effect(session, "k1", "x")
    assert await claim_effect(session, "k1", "x") is None
    assert await claim_effect(session, "k2", "x")


async def test_replayed_event_moves_stock_once(session: AsyncSession) -> None:
    project = uuid.uuid4()
    item, wh = await _fixture(session, project=project)
    data = _payload(uuid.uuid4(), project, item.id)

    assert await apply_goods_receipt_posted(session, data) == 1
    assert await apply_goods_receipt_posted(session, data) == 0

    assert await _stock(session, item.id) == Decimal("5")
    moves = (await session.execute(select(func.count()).select_from(StockMovement))).scalar_one()
    assert moves == 1
    row = (await session.execute(select(StockMovement))).scalar_one()
    assert row.warehouse_id == wh.id
    assert row.reference_type == "gr"


async def test_line_warehouse_beats_the_project_default(session: AsyncSession) -> None:
    project = uuid.uuid4()
    item, _default = await _fixture(session, project=project)
    other = Warehouse(code="W-OTHER", name="Other", project_id=project)
    session.add(other)
    await session.flush()
    data = _payload(uuid.uuid4(), project, item.id, warehouse_id=str(other.id))

    await apply_goods_receipt_posted(session, data)

    assert (await session.execute(select(StockBalance.warehouse_id))).scalar_one() == other.id


async def test_no_warehouse_skips_without_failing(session: AsyncSession) -> None:
    project = uuid.uuid4()
    item, _ = await _fixture(session, project=project, with_warehouse=False)

    assert await apply_goods_receipt_posted(session, _payload(uuid.uuid4(), project, item.id)) == 0
    assert await _stock(session, item.id) == Decimal("0")


async def test_line_without_catalogue_item_or_quantity_moves_nothing(session: AsyncSession) -> None:
    project = uuid.uuid4()
    item, _ = await _fixture(session, project=project)
    data = _payload(uuid.uuid4(), project, item.id, qty="0")
    data["lines"].append({**data["lines"][0], "catalog_item_id": None, "qty": "3"})

    assert await apply_goods_receipt_posted(session, data) == 0
