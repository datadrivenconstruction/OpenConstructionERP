# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The committed-by-position rollup answers with a page, and says how big it is.

This rollup is a register keyed to the bill, not a fixed taxonomy: one row
appears for every position the project has raised an order against, so the
set grows whenever a buyer orders against a position nothing had been ordered
against before. That is why it carries an envelope rather than an exemption.

``total`` is the number the envelope exists for, and it is the one a shape
assertion cannot check: on any project small enough to fit in one page a
``total`` that merely echoes ``len(items)`` is indistinguishable from a
correct one. So every test here builds more positions than the page it asks
for, and checks the total against a number it knows independently.

The count is also not the number of rows the database returns. The collapse
from cost line to bill position happens in Python, and several cost lines can
name one position, so a total taken from the ``GROUP BY`` would be larger than
the list the caller receives. ``test_two_cost_lines_on_one_position_...``
is the case that separates those two numbers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.models import CostLine
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.router import committed_by_position
from app.modules.procurement.service import ProcurementService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

#: Positions built, and the page asked for. Longer than the page on purpose.
POSITIONS = 5
PAGE = 2

#: A status the rollup counts. It filters out ``cancelled`` and nothing else.
COMMITTED_STATUS = "issued"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def make_owner_and_project(session: AsyncSession) -> tuple[str, uuid.UUID]:
    """A real project and its owner, because the route verifies access first."""
    user = User(
        email=f"procurement-page-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Procurement",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Procurement {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return str(user.id), project.id


async def make_boq(session: AsyncSession, project_id: uuid.UUID) -> BOQ:
    boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()
    return boq


async def make_position(session: AsyncSession, boq: BOQ, ordinal: str) -> Position:
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
    return position


async def make_cost_line(
    session: AsyncSession,
    project_id: uuid.UUID,
    boq: BOQ,
    position: Position,
    code: str,
) -> CostLine:
    cost_line = CostLine(
        project_id=project_id,
        code=code,
        description=position.description,
        unit=position.unit,
        source="boq",
        boq_position_id=position.id,
        boq_id=boq.id,
        estimate_quantity=position.quantity,
        estimate_unit_rate=position.unit_rate,
        estimate_amount=position.total,
        currency="",
        status="active",
    )
    session.add(cost_line)
    await session.flush()
    position.cost_line_id = cost_line.id
    await session.flush()
    return cost_line


async def make_po(
    session: AsyncSession,
    project_id: uuid.UUID,
    cost_line_ids: list[uuid.UUID],
    *,
    status: str = COMMITTED_STATUS,
    quantity: str = "10",
    unit_rate: str = "180.00",
    amount: str = "1800.00",
) -> PurchaseOrder:
    """One purchase order with a line against each cost line given."""
    po = PurchaseOrder(
        project_id=project_id,
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
        status=status,
        currency_code="EUR",
    )
    session.add(po)
    await session.flush()
    for n, cost_line_id in enumerate(cost_line_ids):
        session.add(
            PurchaseOrderItem(
                po_id=po.id,
                description="Reinforced concrete, C30/37",
                quantity=quantity,
                unit="m3",
                unit_rate=unit_rate,
                amount=amount,
                cost_line_id=cost_line_id,
                sort_order=n,
            )
        )
    await session.flush()
    return po


async def one_position_each(
    session: AsyncSession,
    project_id: uuid.UUID,
    count: int,
) -> list[Position]:
    """``count`` positions, each on the spine and each with an order against it."""
    boq = await make_boq(session, project_id)
    positions = []
    cost_line_ids = []
    for n in range(count):
        position = await make_position(session, boq, f"1.{n + 1}")
        cost_line = await make_cost_line(session, project_id, boq, position, f"CL-{n + 1}")
        positions.append(position)
        cost_line_ids.append(cost_line.id)
    await make_po(session, project_id, cost_line_ids)
    return positions


def expected_order(positions: list[Position]) -> list[str]:
    """The order the route sorts by, worked out independently of the route."""
    return sorted(str(position.id) for position in positions)


# ── The page and its total ─────────────────────────────────────────────────


async def test_a_page_of_the_rollup_reports_how_many_positions_there_are(session: AsyncSession) -> None:
    user_id, project_id = await make_owner_and_project(session)
    positions = await one_position_each(session, project_id, POSITIONS)
    service = ProcurementService(session)

    page = await committed_by_position(project_id, user_id, session, offset=0, limit=PAGE, service=service)

    assert len(page.items) == PAGE
    # Asserted against POSITIONS, not against len(page.items): the latter
    # would hold against a total that simply echoed the page.
    assert page.total == POSITIONS
    assert page.total > len(page.items)
    assert page.offset == 0
    assert page.limit == PAGE
    assert [row.boq_position_id for row in page.items] == expected_order(positions)[:PAGE]


async def test_the_pages_together_are_the_whole_rollup_with_nothing_repeated(session: AsyncSession) -> None:
    """A GROUP BY with no ORDER BY may come back differently on each request.

    Slicing that is how a position lands on two pages while another lands on
    none, and the reader deciding what still has to be bought never finds out.
    """
    user_id, project_id = await make_owner_and_project(session)
    positions = await one_position_each(session, project_id, POSITIONS)
    service = ProcurementService(session)

    seen: list[str] = []
    for offset in range(0, POSITIONS, PAGE):
        page = await committed_by_position(project_id, user_id, session, offset=offset, limit=PAGE, service=service)
        assert page.total == POSITIONS
        seen.extend(row.boq_position_id for row in page.items)

    assert seen == expected_order(positions)
    assert len(seen) == len(set(seen))


async def test_two_cost_lines_on_one_position_are_one_row_counted_once(session: AsyncSession) -> None:
    """The total counts what the caller receives, not what the query returned.

    The database groups by cost line; the route folds those onto positions.
    A total taken before the fold would be 2 here and the caller would page
    for a row that does not exist.
    """
    user_id, project_id = await make_owner_and_project(session)
    boq = await make_boq(session, project_id)
    position = await make_position(session, boq, "1.1")
    first = await make_cost_line(session, project_id, boq, position, "CL-A")
    second = await make_cost_line(session, project_id, boq, position, "CL-B")
    await make_po(session, project_id, [first.id, second.id])
    service = ProcurementService(session)

    page = await committed_by_position(project_id, user_id, session, offset=0, limit=100, service=service)

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].boq_position_id == str(position.id)
    # Both orders rolled onto the one position rather than one of them winning.
    assert Decimal(page.items[0].committed_qty) == Decimal("20")
    assert Decimal(page.items[0].committed_value) == Decimal("3600.00")


async def test_a_rollup_that_fits_in_one_page_reports_its_own_length(session: AsyncSession) -> None:
    """The other direction: a total permanently larger than the set is equally wrong."""
    user_id, project_id = await make_owner_and_project(session)
    await one_position_each(session, project_id, 2)
    service = ProcurementService(session)

    page = await committed_by_position(project_id, user_id, session, offset=0, limit=100, service=service)

    assert page.total == len(page.items) == 2


async def test_a_project_with_no_orders_answers_with_an_empty_page(session: AsyncSession) -> None:
    user_id, project_id = await make_owner_and_project(session)
    service = ProcurementService(session)

    page = await committed_by_position(project_id, user_id, session, offset=0, limit=PAGE, service=service)

    assert page.items == []
    assert page.total == 0


async def test_a_cancelled_order_commits_nothing_and_is_not_counted(session: AsyncSession) -> None:
    """The one filter this rollup applies, guarded because the total now depends on it."""
    user_id, project_id = await make_owner_and_project(session)
    boq = await make_boq(session, project_id)
    live = await make_position(session, boq, "1.1")
    dead = await make_position(session, boq, "1.2")
    live_line = await make_cost_line(session, project_id, boq, live, "CL-LIVE")
    dead_line = await make_cost_line(session, project_id, boq, dead, "CL-DEAD")
    await make_po(session, project_id, [live_line.id])
    await make_po(session, project_id, [dead_line.id], status="cancelled")
    service = ProcurementService(session)

    page = await committed_by_position(project_id, user_id, session, offset=0, limit=100, service=service)

    assert page.total == 1
    assert [row.boq_position_id for row in page.items] == [str(live.id)]


async def test_an_order_against_a_line_off_the_bill_is_still_in_the_rollup(session: AsyncSession) -> None:
    """The fallback the schema describes, asserted rather than only written down.

    ``positions_for_cost_lines`` answers with nothing for a cost line that
    names no position, which is the ordinary state of a spine generated
    before the bill was finished. Such an order is real money and dropping it
    would understate what the project has committed, so the row survives
    under the cost line's own id and ``boq_position_id`` carries an id of one
    kind or the other. That is why the field is text rather than a UUID, and
    why a reader joining it against the bill has to expect a miss.

    It is pinned here because the alternative failure is silent both ways: a
    dropped row leaves a smaller number that still looks like a number, and a
    row merged onto a real position inflates that position instead.
    """
    user_id, project_id = await make_owner_and_project(session)
    boq = await make_boq(session, project_id)
    on_bill = await make_position(session, boq, "1.1")
    mapped = await make_cost_line(session, project_id, boq, on_bill, "CL-ON")
    orphan = CostLine(
        project_id=project_id,
        code="CL-OFF",
        description="Temporary works, not yet on the bill",
        unit="m3",
        source="manual",
        boq_position_id=None,
        boq_id=boq.id,
        estimate_quantity="10",
        estimate_unit_rate="180.00",
        estimate_amount="1800.00",
        currency="",
        status="active",
    )
    session.add(orphan)
    await session.flush()
    await make_po(session, project_id, [mapped.id, orphan.id])
    service = ProcurementService(session)

    page = await committed_by_position(project_id, user_id, session, offset=0, limit=100, service=service)

    assert page.total == 2, "an order against a line off the bill was dropped from the rollup"
    by_id = {row.boq_position_id: row for row in page.items}
    assert str(orphan.id) in by_id, "the unmapped row is not under the cost line's own id"
    assert str(on_bill.id) in by_id
    # Separate rows, so neither line's money moved onto the other.
    assert Decimal(by_id[str(orphan.id)].committed_value) == Decimal("1800.00")
    assert Decimal(by_id[str(on_bill.id)].committed_value) == Decimal("1800.00")
