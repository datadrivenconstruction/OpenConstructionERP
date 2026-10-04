# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""A confirmed contingency drawdown survives every other writer of the row's metadata.

A drawdown is a key in ``ProjectBudget.metadata_``. Four code paths rewrite
that whole dict from a copy they read first: the budget PATCH, the budget sync
that runs after every invoice and order event, and the order-approved,
order-cancelled and goods-receipt subscribers (whose fallback row is the
project's oldest, which can be the contingency line). If the copy is read
before a manager's drawdown commits and written after, the drawdown is gone
with no trace and the risk falls back to pending.

Each test runs the real race with two connections: B confirms a drawdown and
holds its transaction open, A starts the competing write, then B commits. With
an unlocked read A works on the stale copy and wipes the drawdown; reading the
row under a lock makes A wait for B and build on B's write.

Runs on a throwaway database (``tests._pg.isolated_engine``), because the race
needs two committed transactions, which the rolled-back session cannot give.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import Event
from app.modules.finance import events as fin_events
from app.modules.finance.models import ProjectBudget
from app.modules.finance.schemas import BudgetCreate, BudgetUpdate
from app.modules.finance.service import CONTINGENCY_DRAWDOWN_PREFIX, FinanceService
from tests._pg import isolated_engine

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
RISK_ID = uuid.uuid4()
SOURCE = f"risk:{RISK_ID}"
DRAWDOWN_KEY = f"{CONTINGENCY_DRAWDOWN_PREFIX}{SOURCE}"
RECORD = {
    "amount": "9000.00",
    "currency": "EUR",
    "risk_id": str(RISK_ID),
    "risk_code": "R-001",
    "risk_title": "Ground water",
    "confirmed_by": "manager",
    "confirmed_at": "2026-10-04T08:00:00+00:00",
    "note": "",
}

Factory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def factory():
    async with isolated_engine() as engine:
        f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with f() as s:
            from app.modules.projects.models import Project
            from app.modules.users.models import User

            s.add(User(id=OWNER_ID, email=f"lock-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="L"))
            await s.flush()
            s.add(Project(id=PROJECT_ID, name="Lock", owner_id=OWNER_ID, currency="EUR"))
            await s.commit()
        yield f


async def _contingency_line(factory: Factory) -> uuid.UUID:
    async with factory() as s:
        line = await FinanceService(s).create_budget(
            BudgetCreate(project_id=PROJECT_ID, wbs_id="CT", category="contingency", original_budget="50000")
        )
        await s.commit()
        return line.id


async def _stored_metadata(factory: Factory, budget_id: uuid.UUID) -> dict:
    async with factory() as s:
        row = (await s.execute(select(ProjectBudget).where(ProjectBudget.id == budget_id))).scalar_one()
        return dict(row.metadata_ or {})


async def _race(factory: Factory, line_id: uuid.UUID, competing: Callable[[], Awaitable[None]]) -> None:
    """B confirms a drawdown and holds it uncommitted while ``competing`` starts; then B commits."""
    async with factory() as b:
        await FinanceService(b).set_contingency_drawdown(
            project_id=PROJECT_ID, source=SOURCE, budget_id=line_id, record=RECORD
        )
        task = asyncio.create_task(competing())
        # Long enough for the competing write to reach the row; it cannot
        # finish while B holds the lock on it, fixed or not.
        await asyncio.sleep(0.5)
        assert not task.done(), "the competing write did not wait for the drawdown in flight"
        await b.commit()
        await asyncio.wait_for(task, timeout=30)


@pytest.mark.asyncio
async def test_budget_patch_keeps_a_drawdown_confirmed_while_it_ran(factory):
    line_id = await _contingency_line(factory)

    async def patch() -> None:
        async with factory() as a:
            await FinanceService(a).update_budget(line_id, BudgetUpdate(metadata={"notes": "weather"}))
            await a.commit()

    await _race(factory, line_id, patch)
    md = await _stored_metadata(factory, line_id)
    assert md.get(DRAWDOWN_KEY) == RECORD
    assert md["notes"] == "weather"


@pytest.mark.asyncio
async def test_budget_sync_keeps_a_drawdown_confirmed_while_it_ran(factory):
    # A row the sync has never run on: it stamps ``budget_sync`` and so writes
    # the whole metadata back.
    async with factory() as s:
        legacy = ProjectBudget(
            project_id=PROJECT_ID,
            wbs_id="CT-OLD",
            category="contingency",
            currency_code="EUR",
            original_budget=Decimal("50000"),
            revised_budget=Decimal("50000"),
            metadata_={"notes": "legacy"},
        )
        s.add(legacy)
        await s.commit()
        line_id = legacy.id

    async def sync() -> None:
        async with factory() as a:
            await FinanceService(a).sync_project_budget(PROJECT_ID)
            await a.commit()

    await _race(factory, line_id, sync)
    md = await _stored_metadata(factory, line_id)
    assert md.get(DRAWDOWN_KEY) == RECORD
    assert md["budget_sync"] == "1"
    assert md["notes"] == "legacy"


@pytest.mark.asyncio
async def test_order_approval_on_the_oldest_row_keeps_a_drawdown(factory, monkeypatch):
    # The contingency line is the project's only, so oldest, budget row: the
    # row an order without a WBS hint commits against.
    line_id = await _contingency_line(factory)
    monkeypatch.setattr(fin_events, "async_session_factory", factory)
    po_id = uuid.uuid4()
    event = Event(
        name="procurement.po.approved",
        data={
            "po_id": str(po_id),
            "project_id": str(PROJECT_ID),
            "amount_subtotal": "1200.00",
            "currency_code": "EUR",
        },
        source_module="oe_procurement",
    )

    async def approve() -> None:
        await fin_events._on_po_approved(event)

    await _race(factory, line_id, approve)
    md = await _stored_metadata(factory, line_id)
    assert md.get(DRAWDOWN_KEY) == RECORD
    # The approval itself landed too: the wait did not turn into a skip.
    assert md[f"committed_from_po:{po_id}"] == "1200.00"


@pytest.mark.asyncio
async def test_a_locked_patch_still_answers_404_for_a_missing_row(factory):
    from fastapi import HTTPException

    async with factory() as s:
        with pytest.raises(HTTPException) as exc:
            await FinanceService(s).update_budget(uuid.uuid4(), BudgetUpdate(category="material"))
    assert exc.value.status_code == 404
