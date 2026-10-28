# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A supplier invoice line can be attributed to the bill item it paid for.

Issue #454. The link from an invoice line to the cost spine has always existed,
and it has always been spelled ``cost_line_id``. Nobody entering a supplier
invoice thinks in cost lines; they think in the bill item the work was for, and
having to look the cost line up first is why 72 invoices on the reporter's
installation sit at project level with nothing attributed to anything.

So the line accepts the position and the service resolves it. Both refusals
matter more than the happy path: a position off the cost spine and a position
that contradicts an explicitly named cost line are the two ways this could
quietly post the money nowhere or somewhere wrong, and both come back as a 422
that says what to do instead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.models import CostLine
from app.modules.finance.models import InvoiceLineItem
from app.modules.finance.schemas import InvoiceCreate, InvoiceLineItemCreate
from app.modules.finance.service import FinanceService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed_project(session: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"attrib-{uuid.uuid4().hex[:10]}@cost-spine.io",
        hashed_password="x",
        full_name="Attribution Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Attribution project", owner_id=owner.id, currency="EUR", fx_rates=[])
    session.add(project)
    await session.flush()
    return project.id


async def _seed_position(session: AsyncSession, project_id: uuid.UUID, *, on_spine: bool = True) -> Position:
    boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal="1.1",
        description="Reinforced concrete, C30/37",
        unit="m3",
        quantity="120",
        unit_rate="180.00",
        total="21600.00",
    )
    session.add(position)
    await session.flush()
    if not on_spine:
        return position
    cost_line = CostLine(
        project_id=project_id,
        code="CL-1.1",
        description=position.description,
        unit="m3",
        source="boq",
        boq_position_id=position.id,
        boq_id=boq.id,
        estimate_amount="21600.00",
        currency="EUR",
        status="active",
    )
    session.add(cost_line)
    await session.flush()
    position.cost_line_id = cost_line.id
    await session.flush()
    return position


async def _create(session: AsyncSession, project_id: uuid.UUID, items: list[InvoiceLineItemCreate]) -> uuid.UUID:
    invoice = await FinanceService(session).create_invoice(
        InvoiceCreate(
            project_id=project_id,
            invoice_direction="payable",
            currency_code="EUR",
            amount_subtotal="1000.00",
            tax_amount="0",
            line_items=items,
        )
    )
    return invoice.id


async def _lines(session: AsyncSession, invoice_id: uuid.UUID) -> list[InvoiceLineItem]:
    rows = await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id))
    return list(rows.scalars().all())


async def test_naming_a_position_stores_the_cost_line_it_belongs_to(session: AsyncSession) -> None:
    """One link on the row, so the rollup keeps exactly one way to find it."""
    project_id = await _seed_project(session)
    position = await _seed_position(session, project_id)

    invoice_id = await _create(
        session,
        project_id,
        [
            InvoiceLineItemCreate(
                description="Ready-mix delivered 12 August",
                amount="1000.00",
                cost_category="material",
                boq_position_id=position.id,
            )
        ],
    )

    (line,) = await _lines(session, invoice_id)
    assert line.cost_line_id == position.cost_line_id
    assert Decimal(str(line.amount)) == Decimal("1000.00")


async def test_a_line_that_names_nothing_is_untouched(session: AsyncSession) -> None:
    """Every line written before this existed, and every unattributed one since.

    An invoice covering six items honestly names none of them, and staying at
    project level has to remain possible rather than becoming an error.
    """
    project_id = await _seed_project(session)
    invoice_id = await _create(
        session,
        project_id,
        [InvoiceLineItemCreate(description="Site consumables", amount="1000.00")],
    )

    (line,) = await _lines(session, invoice_id)
    assert line.cost_line_id is None


async def test_a_position_off_the_spine_is_refused_not_dropped(session: AsyncSession) -> None:
    """Silently keeping the money at project level is the bug being fixed.

    The refusal names the call that fixes it, because a 422 that only says no
    sends the reader looking for a permission they do not lack.
    """
    project_id = await _seed_project(session)
    position = await _seed_position(session, project_id, on_spine=False)

    with pytest.raises(HTTPException) as excinfo:
        await _create(
            session,
            project_id,
            [
                InvoiceLineItemCreate(
                    description="Ready-mix delivered 12 August",
                    amount="1000.00",
                    boq_position_id=position.id,
                )
            ],
        )
    assert excinfo.value.status_code == 422
    assert "generate-from-boq" in str(excinfo.value.detail)


async def test_a_position_that_does_not_exist_is_refused(session: AsyncSession) -> None:
    project_id = await _seed_project(session)

    with pytest.raises(HTTPException) as excinfo:
        await _create(
            session,
            project_id,
            [InvoiceLineItemCreate(description="Ready-mix", amount="1000.00", boq_position_id=uuid.uuid4())],
        )
    assert excinfo.value.status_code == 422


async def test_two_answers_to_one_question_are_refused(session: AsyncSession) -> None:
    """Picking either one would be picking somebody's mistake."""
    project_id = await _seed_project(session)
    position = await _seed_position(session, project_id)

    with pytest.raises(HTTPException) as excinfo:
        await _create(
            session,
            project_id,
            [
                InvoiceLineItemCreate(
                    description="Ready-mix",
                    amount="1000.00",
                    boq_position_id=position.id,
                    cost_line_id=uuid.uuid4(),
                )
            ],
        )
    assert excinfo.value.status_code == 422


async def test_naming_both_and_agreeing_is_not_a_conflict(session: AsyncSession) -> None:
    """The control for the rule above: agreement must not read as contradiction."""
    project_id = await _seed_project(session)
    position = await _seed_position(session, project_id)

    invoice_id = await _create(
        session,
        project_id,
        [
            InvoiceLineItemCreate(
                description="Ready-mix",
                amount="1000.00",
                boq_position_id=position.id,
                cost_line_id=position.cost_line_id,
            )
        ],
    )
    (line,) = await _lines(session, invoice_id)
    assert line.cost_line_id == position.cost_line_id


async def test_an_explicit_cost_line_still_works_on_its_own(session: AsyncSession) -> None:
    """The path that existed before is not narrowed by the one added beside it."""
    project_id = await _seed_project(session)
    position = await _seed_position(session, project_id)

    invoice_id = await _create(
        session,
        project_id,
        [InvoiceLineItemCreate(description="Ready-mix", amount="1000.00", cost_line_id=position.cost_line_id)],
    )
    (line,) = await _lines(session, invoice_id)
    assert line.cost_line_id == position.cost_line_id
