# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A purchase-order line's link to the cost spine, written and read back.

The committed-against-budget report has been complete and dead since it was
written: ``CostSpineRepository.po_committed_by_cost_line`` filters
``cost_line_id IS NOT NULL`` and nothing ever set that column, so every project
reported zero committed. A test that only asserted the happy path would have
passed against that writer, because a writer that does nothing still leaves a
column null and a report empty.

So the negative cases are first-class here. Each one reads the committed
aggregate itself rather than only inspecting the column, because a column
assertion cannot tell a link that is absent from a link the report declines to
follow.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.models import CostLine
from app.modules.costmodel.repository import CostSpineRepository
from app.modules.procurement.models import PurchaseOrder
from app.modules.procurement.schemas import POCreate, POItemCreate, POUpdate
from app.modules.procurement.service import MaterialRequisitionService, ProcurementService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

#: The statuses ``po_committed_by_cost_line`` counts as committed money. A PO
#: is walked to one of these directly rather than through approve/issue: the
#: read side filters on the column's value and knows nothing about how it got
#: there, and routing the fixture through the approval workflow would couple
#: these assertions to the vendor and validation gates instead.
COMMITTED_STATUS = "issued"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session with FK triggers off (synthetic project ids)."""
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


async def make_position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ordinal: str = "1.1",
    with_cost_line: bool = True,
) -> tuple[Position, CostLine | None]:
    """A bill position, optionally already on the cost spine.

    ``with_cost_line=False`` is the ordinary state of a project whose spine has
    never been generated, not a broken one.
    """
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
        currency="",
        status="active",
    )
    session.add(cost_line)
    await session.flush()

    position.cost_line_id = cost_line.id
    await session.flush()
    return position, cost_line


def po_payload(project_id: uuid.UUID, **item_fields: object) -> POCreate:
    """A one-line draft PO for 10 m3 at 180.00, worth 1800.00."""
    return POCreate(
        project_id=project_id,
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
        items=[
            POItemCreate(
                description="Reinforced concrete, C30/37",
                quantity="10",
                unit="m3",
                unit_rate="180.00",
                **item_fields,  # type: ignore[arg-type]
            )
        ],
    )


async def commit_po(session: AsyncSession, po: PurchaseOrder) -> None:
    """Advance a PO to a status the committed aggregate counts."""
    po.status = COMMITTED_STATUS
    await session.flush()


async def committed(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    return await CostSpineRepository(session).po_committed_by_cost_line(project_id)


# ── The link that was never written ──────────────────────────────────────────


async def test_a_line_bought_against_a_bill_position_commits_against_its_cost_line(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The whole point: pick a position, and the money link is derived for you.

    The buyer supplies a ``boq_position_id`` and never sees a cost line. What
    lands on the row is the cost line, and what the committed report returns is
    the order's value against it.
    """
    position, cost_line = await make_position(session, project_id)
    assert cost_line is not None

    service = ProcurementService(session)
    po = await service.create_po(po_payload(project_id, boq_position_id=str(position.id)))

    assert len(po.items) == 1
    assert po.items[0].cost_line_id == cost_line.id, (
        "the order line was raised against a spine-linked position and still carries no cost "
        "line, which is the state that made the committed report read zero on every project"
    )

    await commit_po(session, po)
    totals = await committed(session, project_id)
    assert totals == {str(cost_line.id): Decimal("1800.00")}


async def test_a_line_raised_without_a_position_stays_unlinked_and_commits_nothing(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The negative case, and the reason the positive one proves anything.

    Plenty of purchase-order lines belong to no bill position: site welfare, a
    one-off hire, a consumable. Those must leave the column null and must not
    appear in the committed aggregate under some placeholder key. A writer that
    invented a link here would be worse than the writer that wrote none, and a
    positive-only test cannot tell the two apart.
    """
    await make_position(session, project_id)

    service = ProcurementService(session)
    po = await service.create_po(po_payload(project_id))

    assert po.items[0].cost_line_id is None, (
        "an order line naming no bill position was linked to a cost line anyway; the resolver is "
        "guessing rather than resolving"
    )

    await commit_po(session, po)
    totals = await committed(session, project_id)
    assert totals == {}, (
        f"the committed aggregate returned {totals} for a project whose only order line names no "
        f"position. Committed money must be attributable to a cost line or absent, never both."
    )


async def test_a_position_that_is_not_on_the_spine_leaves_the_line_unlinked(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """A project whose cost spine has not been generated still takes orders.

    This is the case that tempts a writer into minting a cost line on the spot.
    It must not: the spine generator derives a control account from the
    position's classification standard and skips section headers, and a line
    minted outside it would be missing from the account rollups that give a
    cost line its purpose. The order is valid, it simply commits against
    nothing yet.
    """
    position, cost_line = await make_position(session, project_id, with_cost_line=False)
    assert cost_line is None

    service = ProcurementService(session)
    po = await service.create_po(po_payload(project_id, boq_position_id=str(position.id)))

    assert po.items[0].cost_line_id is None
    await commit_po(session, po)
    assert await committed(session, project_id) == {}

    # And nothing was invented on the spine to make the link possible.
    assert (await session.execute(CostLine.__table__.select())).first() is None, (
        "raising a purchase order created a cost line. Procurement reads the spine, it does not write it."
    )


async def test_the_link_is_frozen_when_the_order_is_written(session: AsyncSession, project_id: uuid.UUID) -> None:
    """An order commits against the scope as it stood on the day it was raised.

    Re-pointing the position at a different cost line afterwards must not
    rewrite what last month's order committed against, which is the difference
    between resolving on write and deriving on read.
    """
    position, original = await make_position(session, project_id)
    assert original is not None
    original_id = original.id

    service = ProcurementService(session)
    po = await service.create_po(po_payload(project_id, boq_position_id=str(position.id)))
    await commit_po(session, po)

    replacement = CostLine(
        project_id=project_id,
        code="CL-REPLACEMENT",
        description="Re-pointed after the order was raised",
        source="manual",
        currency="",
        status="active",
    )
    session.add(replacement)
    await session.flush()
    position.cost_line_id = replacement.id
    await session.flush()

    totals = await committed(session, project_id)
    assert totals == {str(original_id): Decimal("1800.00")}, (
        f"the committed aggregate returned {totals}. Re-pointing the position moved money that was "
        f"committed before the change, so the link is being derived on read rather than frozen on "
        f"write."
    )


async def test_correcting_a_quantity_does_not_strip_the_link(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The edit path rebuilds the rows, so it has to re-derive the link.

    ``update_po`` replaces the line items outright rather than patching them,
    which means a rebuild that forgot the cost line would silently unlink the
    whole order the first time somebody corrected a quantity. That order would
    then be missing from the committed report for good, and the header totals
    would still look right, so nothing on screen would say what had happened.

    Reading the committed aggregate rather than only the column is what makes
    this test discriminating: a resolver that runs on the edit path and returns
    null would leave the column exactly as an absent resolver does.

    The correction is made while the order is still a draft and the order is
    committed afterwards. A committed order's lines are frozen, so the draft is
    the only place this edit path runs on its own.
    """
    position, cost_line = await make_position(session, project_id)
    assert cost_line is not None
    cost_line_id = cost_line.id

    service = ProcurementService(session)
    po = await service.create_po(po_payload(project_id, boq_position_id=str(position.id)))

    corrected = await service.update_po(
        po.id,
        POUpdate(
            items=[
                POItemCreate(
                    description="Reinforced concrete, C30/37",
                    quantity="12",
                    unit="m3",
                    unit_rate="180.00",
                    boq_position_id=str(position.id),
                )
            ]
        ),
    )

    assert corrected.items[0].cost_line_id == cost_line_id, (
        "correcting the quantity rebuilt the line without its cost line, so the order has silently "
        "left the committed report"
    )
    await commit_po(session, corrected)
    assert await committed(session, project_id) == {str(cost_line_id): Decimal("2160.00")}


# ── Ownership ────────────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
async def test_another_projects_position_cannot_be_bought_against(session: AsyncSession, project_id: uuid.UUID) -> None:
    """A position carries no project of its own; ownership lives on its BOQ.

    Without the join through the BOQ the endpoint accepts a neighbouring
    project's position id and commits this project's money against it.
    """
    foreign_project = uuid.uuid4()
    foreign_position, _ = await make_position(session, foreign_project, ordinal="9.9")

    service = ProcurementService(session)
    with pytest.raises(HTTPException) as excinfo:
        await service.create_po(po_payload(project_id, boq_position_id=str(foreign_position.id)))

    assert excinfo.value.status_code == 404
    assert "not found in this project" in str(excinfo.value.detail)


async def test_a_refused_line_leaves_no_purchase_order_behind(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The refusal happens before the PO row exists.

    A 404 with a numbered purchase order already persisted behind it would burn
    a number from the project's sequence and leave a header nobody asked for.
    """
    foreign_position, _ = await make_position(session, uuid.uuid4(), ordinal="9.9")

    service = ProcurementService(session)
    with pytest.raises(HTTPException):
        await service.create_po(po_payload(project_id, boq_position_id=str(foreign_position.id)))

    rows = await session.execute(PurchaseOrder.__table__.select())
    assert rows.first() is None


@pytest.mark.tenant_isolation
async def test_an_explicit_cost_line_from_another_project_is_refused(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The explicit id is the direct path, so it needs the same check."""
    _, foreign_line = await make_position(session, uuid.uuid4(), ordinal="9.9")
    assert foreign_line is not None

    service = ProcurementService(session)
    with pytest.raises(HTTPException) as excinfo:
        await service.create_po(po_payload(project_id, cost_line_id=str(foreign_line.id)))

    assert excinfo.value.status_code == 404
    assert "Cost line not found in this project" in str(excinfo.value.detail)


async def test_an_unparseable_id_is_refused_rather_than_dropped(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Dropping it would leave the caller believing the line was linked."""
    service = ProcurementService(session)
    with pytest.raises(HTTPException) as excinfo:
        await service.create_po(po_payload(project_id, boq_position_id="not-a-uuid"))

    assert excinfo.value.status_code == 400


async def test_an_explicit_cost_line_outranks_the_position(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Both may be supplied; the explicit one is the caller being specific."""
    position, derived = await make_position(session, project_id)
    assert derived is not None
    chosen = CostLine(
        project_id=project_id,
        code="CL-CHOSEN",
        description="Picked explicitly",
        source="manual",
        currency="",
        status="active",
    )
    session.add(chosen)
    await session.flush()

    service = ProcurementService(session)
    po = await service.create_po(po_payload(project_id, boq_position_id=str(position.id), cost_line_id=str(chosen.id)))
    assert po.items[0].cost_line_id == chosen.id


async def test_lines_resolve_independently_within_one_order(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The resolver returns one answer per line, in order.

    A batched resolver that returned its answers misaligned would attribute
    money to the wrong scope item while every individual assertion above still
    passed, so the order is checked against a mixed set of lines.
    """
    first, first_line = await make_position(session, project_id, ordinal="1.1")
    second, second_line = await make_position(session, project_id, ordinal="2.1")
    assert first_line is not None and second_line is not None

    payload = POCreate(
        project_id=project_id,
        po_number="PO-MIXED",
        items=[
            POItemCreate(description="Unlinked scaffold hire", quantity="1", unit_rate="500.00"),
            POItemCreate(
                description="Second position",
                quantity="2",
                unit_rate="100.00",
                boq_position_id=str(second.id),
            ),
            POItemCreate(
                description="First position",
                quantity="3",
                unit_rate="100.00",
                boq_position_id=str(first.id),
            ),
        ],
    )
    po = await ProcurementService(session).create_po(payload)
    by_description = {item.description: item.cost_line_id for item in po.items}
    assert by_description == {
        "Unlinked scaffold hire": None,
        "Second position": second_line.id,
        "First position": first_line.id,
    }


# ── Requisitions take the same route ─────────────────────────────────────────


async def test_a_requisition_line_resolves_the_same_way(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Requisition items arrive as dicts, not as a schema.

    The module exposes no requisition endpoint, so there is no create schema to
    carry the field. The resolution is wired anyway so the link is correct on
    the day that endpoint lands rather than being a second omission to find
    then.
    """
    position, cost_line = await make_position(session, project_id)
    assert cost_line is not None

    service = MaterialRequisitionService(session)
    req = await service.create_requisition(
        project_id,
        title="Concrete for the foundation slab",
        items=[
            {
                "description": "Reinforced concrete, C30/37",
                "quantity_requested": "10",
                "unit_cost": "180.00",
                "boq_position_id": str(position.id),
            },
            {"description": "Site welfare consumables", "quantity_requested": "1", "unit_cost": "50.00"},
        ],
    )

    from app.modules.procurement.models import MaterialRequisitionItem

    rows = await session.execute(
        MaterialRequisitionItem.__table__.select().where(MaterialRequisitionItem.requisition_id == req.id)
    )
    links = {row.description: row.cost_line_id for row in rows}
    assert links == {
        "Reinforced concrete, C30/37": cost_line.id,
        "Site welfare consumables": None,
    }
