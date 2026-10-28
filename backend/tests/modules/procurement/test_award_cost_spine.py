# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A tender award is an order, and it has to land on the cost spine like one.

Wiring the money link into the order form and the requisition covered what a
buyer types. It did not cover the largest single commitment the system makes:
awarding a tender turns a whole package into a purchase order in an event
handler that builds its line items itself, and that handler was putting the
bid line's ``position_id`` into ``wbs_id`` as text while leaving the money link
null. The package therefore landed on the project total and nowhere in the
breakdown, which is the same defect the order form had, on a larger number.

The handler opens its own session through ``async_session_factory``. These
tests hand it the rolled-back test session instead, so the assertions run in
the gated module lane rather than in an integration lane that blocks nothing.

They drive ``_create_po_from_award`` rather than the subscriber that wraps it.
The subscriber launches the work as a detached task and returns at once, so an
await on it proves nothing and, sharing one connection with the test session,
runs the two concurrently until asyncpg refuses. Awaiting the coroutine itself
is both the assertion that can be made and the only one that is sound.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.models import CostLine
from app.modules.costmodel.repository import CostSpineRepository
from app.modules.procurement import events as procurement_events
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.tendering.models import TenderBid, TenderPackage
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

#: The status ``po_committed_by_cost_line`` counts as committed money. The
#: handler creates a draft, so the aggregate assertions walk it to this first.
COMMITTED_STATUS = "issued"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


class _BorrowedSession:
    """Hand the handler a session it must not close.

    The handler owns its session, opening and closing it around one award. A
    test that let it close the shared session would take the outer transaction
    with it and the rollback would have nothing left to undo.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture
def lend_session(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        procurement_events,
        "async_session_factory",
        lambda: _BorrowedSession(session),
    )


async def make_position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ordinal: str = "1.1",
    with_cost_line: bool = True,
) -> tuple[Position, CostLine | None]:
    """A bill position, optionally already on the cost spine."""
    boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()

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

    if not with_cost_line:
        return position, None

    cost_line = CostLine(
        project_id=project_id,
        code=f"CL-{ordinal}",
        description=position.description,
        unit=position.unit,
        source="boq",
        boq_position_id=position.id,
        boq_id=boq.id,
        estimate_quantity=position.quantity,
        estimate_unit_rate=position.unit_rate,
        estimate_amount=position.total,
        currency="EUR",
        status="active",
    )
    session.add(cost_line)
    await session.flush()

    position.cost_line_id = cost_line.id
    await session.flush()
    return position, cost_line


async def make_award(
    session: AsyncSession,
    project_id: uuid.UUID,
    lines: list[dict[str, Any]],
) -> Event:
    """A tender package with one winning bid, and the event that awards it."""
    package = TenderPackage(project_id=project_id, name="Substructure", description="")
    session.add(package)
    await session.flush()

    bid = TenderBid(
        package_id=package.id,
        company_name="Groundworks contractor",
        total_amount="21600.00",
        currency="EUR",
        line_items=lines,
    )
    session.add(bid)
    await session.flush()

    return Event(
        name="tender.awarded",
        data={"package_id": str(package.id), "bid_id": str(bid.id)},
    )


async def issued_items(session: AsyncSession, project_id: uuid.UUID) -> list[PurchaseOrderItem]:
    """The line items of the order the award created, in order."""
    po = (await session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id))).scalar_one()
    rows = (
        (
            await session.execute(
                select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id).order_by(PurchaseOrderItem.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def committed(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    """What the committed report says, which is the number anybody actually reads.

    Keyed by the cost line id as text, which is how the aggregate returns it and
    how every caller has to look it up.
    """
    return await CostSpineRepository(session).po_committed_by_cost_line(project_id)


@pytest.mark.usefixtures("lend_session")
async def test_an_awarded_bid_line_commits_against_its_cost_line(session: AsyncSession, project_id: uuid.UUID) -> None:
    position, cost_line = await make_position(session, project_id)
    assert cost_line is not None
    event = await make_award(
        session,
        project_id,
        [
            {
                "description": "Reinforced concrete, C30/37",
                "unit": "m3",
                "quantity": "120",
                "unit_rate": "180.00",
                "position_id": str(position.id),
            }
        ],
    )

    await procurement_events._create_po_from_award(event)

    items = await issued_items(session, project_id)
    assert [item.cost_line_id for item in items] == [cost_line.id]


@pytest.mark.usefixtures("lend_session")
async def test_the_award_reaches_the_committed_report(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The column is not the deliverable; the report reading it is."""
    position, cost_line = await make_position(session, project_id)
    assert cost_line is not None
    event = await make_award(
        session,
        project_id,
        [
            {
                "description": "Concrete",
                "unit": "m3",
                "quantity": "120",
                "unit_rate": "180.00",
                "position_id": str(position.id),
            }
        ],
    )

    await procurement_events._create_po_from_award(event)
    po = (await session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id))).scalar_one()
    po.status = COMMITTED_STATUS
    await session.flush()

    assert await committed(session, project_id) == {str(cost_line.id): Decimal("21600.00")}


@pytest.mark.usefixtures("lend_session")
async def test_a_bid_line_naming_no_position_stays_unlinked(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The negative case, asserted on the report and not only on the column.

    A resolver that runs and returns nothing leaves the column exactly as a
    resolver that never ran, so the column alone cannot tell the two apart.
    """
    await make_position(session, project_id)
    event = await make_award(
        session,
        project_id,
        [{"description": "Site setup, lump sum", "unit": "item", "quantity": "1", "unit_rate": "4000.00"}],
    )

    await procurement_events._create_po_from_award(event)
    po = (await session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id))).scalar_one()
    po.status = COMMITTED_STATUS
    await session.flush()

    items = await issued_items(session, project_id)
    assert [item.cost_line_id for item in items] == [None]
    assert await committed(session, project_id) == {}


@pytest.mark.usefixtures("lend_session")
async def test_a_position_off_the_spine_links_nothing_and_mints_nothing(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """A project that never generated a spine still gets its order."""
    position, cost_line = await make_position(session, project_id, with_cost_line=False)
    assert cost_line is None
    event = await make_award(
        session,
        project_id,
        [
            {
                "description": "Concrete",
                "unit": "m3",
                "quantity": "120",
                "unit_rate": "180.00",
                "position_id": str(position.id),
            }
        ],
    )

    await procurement_events._create_po_from_award(event)

    items = await issued_items(session, project_id)
    assert [item.cost_line_id for item in items] == [None]
    assert (await session.execute(select(CostLine).where(CostLine.project_id == project_id))).scalars().all() == []


@pytest.mark.usefixtures("lend_session")
async def test_each_line_resolves_on_its_own(session: AsyncSession, project_id: uuid.UUID) -> None:
    """A mixed package must not attribute one line's money to another line."""
    first, first_line = await make_position(session, project_id, ordinal="1.1")
    second, second_line = await make_position(session, project_id, ordinal="1.2")
    assert first_line is not None and second_line is not None
    event = await make_award(
        session,
        project_id,
        [
            {"description": "A", "unit": "m3", "quantity": "1", "unit_rate": "10.00", "position_id": str(first.id)},
            {"description": "B", "unit": "m3", "quantity": "1", "unit_rate": "20.00"},
            {"description": "C", "unit": "m3", "quantity": "1", "unit_rate": "30.00", "position_id": str(second.id)},
        ],
    )

    await procurement_events._create_po_from_award(event)

    items = await issued_items(session, project_id)
    assert [item.cost_line_id for item in items] == [first_line.id, None, second_line.id]


@pytest.mark.usefixtures("lend_session")
async def test_the_position_is_still_recorded_as_the_wbs(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Adding the money link must not take away what the handler already wrote.

    The position id has been landing in ``wbs_id`` since this handler was
    written, and ``check_line_cost_coded`` counts that as a coded line. Dropping
    it while adding the cost line would trade one gap for another on any project
    whose spine has not been generated.
    """
    position, _ = await make_position(session, project_id)
    event = await make_award(
        session,
        project_id,
        [
            {
                "description": "Concrete",
                "unit": "m3",
                "quantity": "1",
                "unit_rate": "10.00",
                "position_id": str(position.id),
            }
        ],
    )

    await procurement_events._create_po_from_award(event)

    items = await issued_items(session, project_id)
    assert items[0].wbs_id == str(position.id)


@pytest.mark.usefixtures("lend_session")
async def test_a_stale_position_still_records_the_award(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Losing the attribution is bad; losing the commitment is worse.

    A bid line pointing at a position that has moved out of the project makes
    resolution raise. The order still has to be recorded, because an award that
    silently fails to become a purchase order is a missing commitment nobody
    will notice until the money is spent.
    """
    other_project = uuid.uuid4()
    stranger, _ = await make_position(session, other_project)
    event = await make_award(
        session,
        project_id,
        [
            {
                "description": "Concrete",
                "unit": "m3",
                "quantity": "1",
                "unit_rate": "10.00",
                "position_id": str(stranger.id),
            }
        ],
    )

    await procurement_events._create_po_from_award(event)

    items = await issued_items(session, project_id)
    assert [item.cost_line_id for item in items] == [None]
