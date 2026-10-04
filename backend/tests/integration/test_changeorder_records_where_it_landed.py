# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An approved change order says which bill section and budget row it wrote.

Approval writes the order's scope into a bill of quantities as a section and
its money into a revised-budget row. The ids of both reached the
``changeorder.approved`` event and a log line, and nothing else, so the
change-order screen could say "applied to the project budget" without being
able to link to where. The approval now stamps ``metadata.writeback`` on the
order.

What is asserted is that the stamp names the rows that really exist, read back
from the database independently of the stamp, and that it names nothing when
nothing landed. A stamp that pointed at a different bill than the one holding
the section would be worse than no stamp, because the screen would follow it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.boq.models  # noqa: F401
import app.modules.changeorders.models  # noqa: F401
import app.modules.finance.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.modules.boq.models import BOQ, Position
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.changeorders.schemas import ChangeOrderResponse
from app.modules.changeorders.service import ChangeOrderService
from app.modules.finance.models import ProjectBudget
from app.modules.projects.models import Project
from tests._pg import transactional_session

SUBMITTER = "11111111-1111-1111-1111-111111111111"
APPROVER = "22222222-2222-2222-2222-222222222222"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _project(session: AsyncSession) -> Project:
    project = Project(name="Harbour Terminal", owner_id=uuid.uuid4(), currency="EUR", budget_estimate="1000000")
    session.add(project)
    await session.flush()
    return project


async def _bill(session: AsyncSession, project: Project, name: str, *, locked: bool = False) -> BOQ:
    boq = BOQ(project_id=project.id, name=name, is_locked=locked)
    session.add(boq)
    await session.flush()
    return boq


async def _submitted_order(
    session: AsyncSession,
    project: Project,
    *,
    code: str = "CO-001",
    items: int = 2,
    metadata: dict[str, Any] | None = None,
) -> ChangeOrder:
    order = ChangeOrder(
        project_id=project.id,
        code=code,
        title="Extra piling to grid F",
        description="Ground conditions differed from the geotechnical report.",
        status="submitted",
        submitted_by=SUBMITTER,
        submitted_at=datetime.now(UTC).isoformat()[:19],
        cost_impact=Decimal("12500.00"),
        currency="EUR",
        schedule_impact_days=4,
    )
    if metadata is not None:
        order.metadata_ = metadata
    session.add(order)
    await session.flush()
    for idx in range(items):
        session.add(
            ChangeOrderItem(
                change_order_id=order.id,
                description=f"Additional bored pile {idx + 1}",
                change_type="added",
                new_quantity=Decimal("1"),
                new_rate=Decimal("6250.00"),
                cost_delta=Decimal("6250.00"),
                unit="nr",
                sort_order=idx,
            )
        )
    await session.flush()
    return order


async def _persisted_metadata(session: AsyncSession, order_id: uuid.UUID) -> dict[str, Any]:
    # populate_existing re-reads the row over the identity-mapped instance, so
    # the value asserted is the database's, without expiring every object the
    # test still holds.
    stmt = select(ChangeOrder).where(ChangeOrder.id == order_id).execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one()
    return dict(row.metadata_ or {})


async def _section_for(session: AsyncSession, order_id: uuid.UUID) -> Position | None:
    """The section the approval wrote, found by its own stamp, not by the order's."""
    rows = (await session.execute(select(Position).where(Position.unit == "section"))).scalars().all()
    for row in rows:
        md = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if md.get("change_order_id") == str(order_id):
            return row
    return None


async def _budget_row_for(session: AsyncSession, order_id: uuid.UUID) -> ProjectBudget | None:
    rows = (await session.execute(select(ProjectBudget))).scalars().all()
    for row in rows:
        md = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if md.get("change_order_id") == str(order_id):
            return row
    return None


@pytest.mark.asyncio
async def test_the_stamp_names_the_section_and_budget_row_that_exist(session: AsyncSession) -> None:
    project = await _project(session)
    boq_id = (await _bill(session, project, "Main bill")).id
    order = await _submitted_order(session, project)

    await ChangeOrderService(session).approve_order(order.id, APPROVER)

    stamp = (await _persisted_metadata(session, order.id)).get("writeback")
    section = await _section_for(session, order.id)
    budget_row = await _budget_row_for(session, order.id)
    assert section is not None and budget_row is not None
    assert stamp == {
        "boq_id": str(boq_id),
        "boq_section_id": str(section.id),
        "budget_row_id": str(budget_row.id),
    }
    # The section really lives in the bill the stamp names.
    assert section.boq_id == boq_id


@pytest.mark.asyncio
async def test_the_stamp_follows_the_bill_the_approver_named(session: AsyncSession) -> None:
    """Two unlocked bills: the stamp must name the chosen one, not the older one."""
    project = await _project(session)
    await _bill(session, project, "Base contract bill")
    chosen = (await _bill(session, project, "Variations bill")).id
    order = await _submitted_order(session, project)

    await ChangeOrderService(session).approve_order(order.id, APPROVER, boq_id=chosen)

    stamp = (await _persisted_metadata(session, order.id))["writeback"]
    section = await _section_for(session, order.id)
    assert section is not None
    assert section.boq_id == chosen
    assert stamp["boq_id"] == str(chosen)
    assert stamp["boq_section_id"] == str(section.id)


@pytest.mark.asyncio
async def test_no_bill_means_no_bill_keys_but_the_budget_row_is_still_named(session: AsyncSession) -> None:
    project = await _project(session)
    order = await _submitted_order(session, project)

    await ChangeOrderService(session).approve_order(order.id, APPROVER)

    stamp = (await _persisted_metadata(session, order.id))["writeback"]
    budget_row = await _budget_row_for(session, order.id)
    assert budget_row is not None
    # No null-filled bill keys: an absent key keeps meaning "wrote no bill".
    assert stamp == {"budget_row_id": str(budget_row.id)}
    assert await _section_for(session, order.id) is None


@pytest.mark.asyncio
async def test_existing_metadata_survives_the_stamp(session: AsyncSession) -> None:
    """The contract link and origin the order already carried are kept."""
    project = await _project(session)
    await _bill(session, project, "Main bill")
    contract_id = str(uuid.uuid4())
    order = await _submitted_order(session, project, metadata={"contract_id": contract_id, "note": "keep me"})

    await ChangeOrderService(session).approve_order(order.id, APPROVER)

    md = await _persisted_metadata(session, order.id)
    assert md["contract_id"] == contract_id
    assert md["note"] == "keep me"
    assert set(md["writeback"]) == {"boq_id", "boq_section_id", "budget_row_id"}


@pytest.mark.asyncio
async def test_the_stamp_reaches_the_wire(session: AsyncSession) -> None:
    """The response model reads ``metadata_``; the stamp has to come out of it."""
    project = await _project(session)
    boq_id = (await _bill(session, project, "Main bill")).id
    order = await _submitted_order(session, project)

    await ChangeOrderService(session).approve_order(order.id, APPROVER)

    stmt = select(ChangeOrder).where(ChangeOrder.id == order.id).execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one()
    wire = ChangeOrderResponse.model_validate(row).model_dump(mode="json")
    assert wire["metadata"]["writeback"]["boq_id"] == str(boq_id)


class _RecordingRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def update_fields(self, order_id: uuid.UUID, **fields: Any) -> None:
        self.calls.append(fields)


@pytest.mark.asyncio
async def test_nothing_landed_writes_no_stamp() -> None:
    """A skipped writeback and a failed budget write leave the order untouched."""
    service = ChangeOrderService.__new__(ChangeOrderService)
    repo = _RecordingRepo()
    service.repo = repo  # type: ignore[assignment]

    await service._stamp_writeback(
        uuid.uuid4(),
        {"contract_id": "x"},
        {"applied": False, "reason": "no_items"},
        {"action": "skipped", "budget_id": None},
    )

    assert repo.calls == []


@pytest.mark.asyncio
async def test_a_section_without_its_bill_is_not_stamped() -> None:
    """Half a link is not a link: a section id with no bill id names no page."""
    service = ChangeOrderService.__new__(ChangeOrderService)
    repo = _RecordingRepo()
    service.repo = repo  # type: ignore[assignment]

    await service._stamp_writeback(
        uuid.uuid4(),
        {},
        {"applied": False, "reason": "already_applied", "section_id": "s-1"},
        {"action": "created", "budget_id": "b-1"},
    )

    assert repo.calls == [{"metadata_": {"writeback": {"budget_row_id": "b-1"}}}]
