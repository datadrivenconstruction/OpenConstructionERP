# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A purchase order has to read back the position it was ordered against.

``POItemCreate`` accepts a ``boq_position_id``, the buyer picks one, and the
order stores only the cost line it resolved to, because a money row carries no
position column. That is the right storage decision and it left a hole on the
read side: the response returned the cost line and nothing else, so an edit
form reopening the order had no way to put the buyer's own choice back into
the picker. The control renders empty, empty looks like "never coded", and the
next save writes it back over a real attribution.

So the response now carries the position too, derived rather than stored.
These tests cover both halves of that: the query that resolves it, and the
stamping that puts it on the response.

The negative cases are the point. A line with no cost link, and a cost line
generated from no position, both have to come back as ``None`` rather than as
somebody else's position, because the map is keyed by cost line and a wrong
key silently reads as a missing one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.models import CostLine
from app.modules.procurement.cost_spine import positions_for_cost_lines
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.router import _po_to_response
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


async def make_cost_line(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ordinal: str = "1.1",
    with_position: bool = True,
) -> tuple[CostLine, Position | None]:
    """A cost line, optionally generated from a bill position."""
    position: Position | None = None
    boq_id: uuid.UUID | None = None

    if with_position:
        boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
        session.add(boq)
        await session.flush()
        boq_id = boq.id

        position = Position(
            boq_id=boq.id,
            ordinal=ordinal,
            description="Reinforced concrete, C30/37, foundation slab",
            unit="m3",
            quantity="120",
            unit_rate="180.00",
            total="21600.00",
        )
        session.add(position)
        await session.flush()

    cost_line = CostLine(
        project_id=project_id,
        code=f"CL-{ordinal}",
        description="Reinforced concrete, C30/37, foundation slab",
        unit="m3",
        source="boq" if with_position else "manual",
        boq_position_id=position.id if position else None,
        boq_id=boq_id,
        estimate_quantity="120",
        estimate_unit_rate="180.00",
        estimate_amount="21600.00",
        currency="EUR",
        status="active",
    )
    session.add(cost_line)
    await session.flush()

    if position is not None:
        position.cost_line_id = cost_line.id
        await session.flush()

    return cost_line, position


async def make_po(
    session: AsyncSession,
    project_id: uuid.UUID,
    cost_line_ids: list[uuid.UUID | None],
) -> PurchaseOrder:
    """An issued order with one line per entry, linked or not as given."""
    po = PurchaseOrder(
        project_id=project_id,
        po_number="PO-0042",
        status="issued",
        currency_code="EUR",
        amount_subtotal="21600.00",
        amount_total="21600.00",
    )
    session.add(po)
    await session.flush()

    for index, cost_line_id in enumerate(cost_line_ids):
        session.add(
            PurchaseOrderItem(
                po_id=po.id,
                description=f"Line {index + 1}",
                quantity="1",
                unit="m3",
                unit_rate="180.00",
                amount="180.00",
                cost_line_id=cost_line_id,
                sort_order=index,
            )
        )
    await session.flush()
    await session.refresh(po)
    return po


# ── The query ────────────────────────────────────────────────────────────────


async def test_a_cost_line_names_the_position_it_came_from(session: AsyncSession, project_id: uuid.UUID) -> None:
    cost_line, position = await make_cost_line(session, project_id)
    assert position is not None

    assert await positions_for_cost_lines(session, [cost_line.id]) == {str(cost_line.id): position.id}


async def test_a_cost_line_with_no_position_is_absent_rather_than_null(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """Absent and None mean the same thing to the caller, and absent is cheaper.

    A manually added cost line belongs to no bill position. Returning a null
    for it would make the caller distinguish "asked and got nothing" from
    "never asked", which nothing downstream needs.
    """
    cost_line, _ = await make_cost_line(session, project_id, with_position=False)

    assert await positions_for_cost_lines(session, [cost_line.id]) == {}


async def test_each_line_keeps_its_own_position(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The map is keyed by cost line, so a mix must not cross the keys over."""
    first, first_pos = await make_cost_line(session, project_id, ordinal="1.1")
    second, second_pos = await make_cost_line(session, project_id, ordinal="1.2")
    assert first_pos is not None and second_pos is not None

    assert await positions_for_cost_lines(session, [first.id, second.id]) == {
        str(first.id): first_pos.id,
        str(second.id): second_pos.id,
    }


async def test_nothing_to_resolve_costs_no_query(session: AsyncSession, project_id: uuid.UUID) -> None:
    """An order whose lines are all unlinked is the ordinary case, not an edge."""
    assert await positions_for_cost_lines(session, []) == {}
    assert await positions_for_cost_lines(session, [None, None]) == {}


async def test_an_unknown_cost_line_resolves_to_nothing(session: AsyncSession, project_id: uuid.UUID) -> None:
    assert await positions_for_cost_lines(session, [uuid.uuid4()]) == {}


# ── The response ─────────────────────────────────────────────────────────────


async def test_the_response_carries_the_position_of_a_linked_line(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The whole point: an edit form can put the buyer's choice back on screen."""
    cost_line, position = await make_cost_line(session, project_id)
    assert position is not None
    po = await make_po(session, project_id, [cost_line.id])

    resp = _po_to_response(po, {}, await positions_for_cost_lines(session, [cost_line.id]))

    assert [item.cost_line_id for item in resp.items] == [cost_line.id]
    assert [item.boq_position_id for item in resp.items] == [position.id]


async def test_an_unlinked_line_reads_back_with_no_position(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The control. Without it the test above passes on a field nobody cleared."""
    po = await make_po(session, project_id, [None])

    resp = _po_to_response(po, {}, {})

    assert [item.cost_line_id for item in resp.items] == [None]
    assert [item.boq_position_id for item in resp.items] == [None]


async def test_one_linked_line_does_not_lend_its_position_to_the_others(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """A mixed order is the normal shape, and the failure would be invisible.

    Site welfare and a one-off hire belong to no bill position. If the stamping
    read anything other than each line's own cost line, they would inherit the
    concrete position sitting next to them and the cost report would say the
    scaffolding was foundation work.
    """
    cost_line, position = await make_cost_line(session, project_id)
    assert position is not None
    po = await make_po(session, project_id, [None, cost_line.id, None])

    resp = _po_to_response(po, {}, await positions_for_cost_lines(session, [cost_line.id]))

    ordered = sorted(resp.items, key=lambda i: i.sort_order)
    assert [item.boq_position_id for item in ordered] == [None, position.id, None]


async def test_a_line_linked_to_a_cost_line_off_the_bill_reads_back_bare(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """A real link to a cost line that answers to no position is not an error.

    The order committed against something; it simply did not come from the
    bill. The response says exactly that: a cost line and no position.
    """
    cost_line, _ = await make_cost_line(session, project_id, with_position=False)
    po = await make_po(session, project_id, [cost_line.id])

    resp = _po_to_response(po, {}, await positions_for_cost_lines(session, [cost_line.id]))

    assert [item.cost_line_id for item in resp.items] == [cost_line.id]
    assert [item.boq_position_id for item in resp.items] == [None]
