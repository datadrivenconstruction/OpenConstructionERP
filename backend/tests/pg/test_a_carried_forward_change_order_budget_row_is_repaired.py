# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Budget delta rows written by 17.7.0 and 17.7.1 are put back into delta shape.

Those two releases wrote a change order's budget row with the project budget
carried forward as ``original`` and ``revised`` as that plus the effect, and
the dashboard aggregate sums every row, so each such row added the whole
project budget a second time. The create path is fixed; this is the other half,
the rows already on file. The boot-path repair rewrites a row only when it
carries the exact 17.7.x signature:

* it is linked to a change order through ``metadata.change_order_id``,
* that change order went through approval (``approved`` or ``executed``),
* ``original`` is not zero,
* ``revised - original`` is exactly the change order's ``cost_impact``.

Everything else is somebody's data and is left alone, which is why most of this
file is rows that must come out byte for byte as they went in: a correct delta
row, a baseline row whose numbers happen to look the same, a change order row
whose difference does not match, and a row pointing at a change order that was
never approved.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.data_repairs import run_data_repairs
from app.modules.changeorders.budget_delta_repair import repair_carried_forward_budget_deltas
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.repairs import CHANGEORDER_BUDGET_DELTA_ORIGINAL
from app.modules.finance.models import ProjectBudget
from app.modules.finance.repository import BudgetRepository
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory(pg_engine):
    """A session factory over one rolled-back transaction, the shape the repair runner takes."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    conn = await pg_engine.connect()
    trans = await conn.begin()
    session_factory = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session_factory
    finally:
        if trans.is_active:
            await trans.rollback()
        await conn.close()


async def _order(session, project_id: uuid.UUID, code: str, cost: str, status: str = "approved") -> ChangeOrder:
    order = ChangeOrder(
        project_id=project_id,
        code=code,
        title=f"Change {code}",
        description="",
        status=status,
        cost_impact=Decimal(cost),
        currency="USD",
    )
    session.add(order)
    await session.flush()
    return order


def _row(
    project_id: uuid.UUID,
    label: str,
    original: str,
    revised: str,
    order: ChangeOrder | None,
) -> ProjectBudget:
    metadata: dict = {}
    if order is not None:
        metadata = {"change_order_id": str(order.id), "change_order_code": order.code, "origin": "change_order"}
    return ProjectBudget(
        project_id=project_id,
        wbs_id=str(order.id) if order is not None else label,
        category=f"Change Order {order.code}" if order is not None else label,
        currency_code="USD",
        original_budget=Decimal(original),
        revised_budget=Decimal(revised),
        metadata_=metadata,
    )


async def _seed(factory) -> uuid.UUID:
    """One project as an install that approved change orders on 17.7.x holds it.

    Budget 100 000 before any change order, one baseline row, two change orders
    of 10 000 and 5 000 written in the carried-forward shape. Then the rows the
    repair must not touch.
    """
    async with factory() as session:
        owner = User(email=f"repair-{uuid.uuid4().hex[:10]}@test.com", hashed_password="x")
        session.add(owner)
        await session.flush()
        project = Project(name="Repair project", owner_id=owner.id, currency="USD", budget_estimate="122000")
        session.add(project)
        await session.flush()
        pid = project.id

        co1 = await _order(session, pid, "CO-001", "10000")
        co2 = await _order(session, pid, "CO-002", "5000", status="executed")
        correct = await _order(session, pid, "CO-003", "7000")
        mismatched = await _order(session, pid, "CO-004", "12000")
        unapproved = await _order(session, pid, "CO-005", "3000", status="submitted")

        session.add_all(
            [
                # Baseline, and a second baseline whose numbers look exactly like
                # a carried-forward row. Neither is linked to a change order.
                _row(pid, "Base", "100000", "100000", None),
                _row(pid, "Lookalike", "100000", "110000", None),
                # The two 17.7.x rows.
                _row(pid, "", "100000", "110000", co1),
                _row(pid, "", "110000", "115000", co2),
                # Already a delta row.
                _row(pid, "", "0", "7000", correct),
                # Linked, non-zero original, but the difference is not the
                # change order's amount: an edit somebody made, not the 17.7.x shape.
                _row(pid, "", "50000", "60000", mismatched),
                # Linked to a change order that was never approved.
                _row(pid, "", "20000", "23000", unapproved),
            ]
        )
        await session.commit()
    return pid


async def _rows(factory, project_id: uuid.UUID) -> dict[str, tuple[Decimal, Decimal]]:
    async with factory() as session:
        rows = (
            (await session.execute(select(ProjectBudget).where(ProjectBudget.project_id == project_id))).scalars().all()
        )
        return {str(r.category): (Decimal(str(r.original_budget)), Decimal(str(r.revised_budget))) for r in rows}


_UNTOUCHED = {
    "Base": (Decimal("100000"), Decimal("100000")),
    "Lookalike": (Decimal("100000"), Decimal("110000")),
    "Change Order CO-003": (Decimal("0"), Decimal("7000")),
    "Change Order CO-004": (Decimal("50000"), Decimal("60000")),
    "Change Order CO-005": (Decimal("20000"), Decimal("23000")),
}


async def test_the_seeded_rows_are_really_in_the_17_7_shape(factory) -> None:
    """Negative control: without it the assertions below could pass over rows that were never broken."""
    pid = await _seed(factory)
    rows = await _rows(factory, pid)
    assert rows["Change Order CO-001"] == (Decimal("100000"), Decimal("110000"))
    assert rows["Change Order CO-002"] == (Decimal("110000"), Decimal("115000"))


async def test_a_carried_forward_row_is_put_back_into_delta_shape(factory) -> None:
    pid = await _seed(factory)

    async with factory() as session:
        changed = await repair_carried_forward_budget_deltas(session)
        await session.commit()

    assert changed == 2
    rows = await _rows(factory, pid)
    assert rows["Change Order CO-001"] == (Decimal("0"), Decimal("10000"))
    assert rows["Change Order CO-002"] == (Decimal("0"), Decimal("5000"))
    for category, expected in _UNTOUCHED.items():
        assert rows[category] == expected, f"{category} was rewritten"


async def test_a_second_pass_changes_nothing(factory) -> None:
    pid = await _seed(factory)

    async with factory() as session:
        await repair_carried_forward_budget_deltas(session)
        await session.commit()
    after_first = await _rows(factory, pid)

    async with factory() as session:
        changed = await repair_carried_forward_budget_deltas(session)
        await session.commit()

    assert changed == 0
    assert await _rows(factory, pid) == after_first


async def test_the_repair_runs_on_the_boot_path_and_the_totals_come_out_right(factory) -> None:
    """Through the registry runner, as a boot runs it, then read back as the dashboard reads it."""
    pid = await _seed(factory)

    report = await run_data_repairs(factory, repairs=(CHANGEORDER_BUDGET_DELTA_ORIGINAL,), app_version="test")

    outcome = next(o for o in report.outcomes if o.repair_id == CHANGEORDER_BUDGET_DELTA_ORIGINAL.repair_id)
    assert outcome.status == "applied"
    assert outcome.rows_changed == 2

    # Only the repaired rows are counted here, so the lookalike and the
    # untouched rows are removed from the project before reading the totals.
    async with factory() as session:
        for row in (
            (await session.execute(select(ProjectBudget).where(ProjectBudget.project_id == pid))).scalars().all()
        ):
            if row.category in _UNTOUCHED and row.category != "Base":
                await session.delete(row)
        await session.commit()

    async with factory() as session:
        agg = await BudgetRepository(session).aggregate_for_dashboard(project_id=pid)
    assert agg["original_by_currency"] == {"USD": 100000.0}
    assert agg["revised_by_currency"] == {"USD": 115000.0}
