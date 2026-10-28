"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PO approval gate (TOP-30 #10).

A purchase order is committed money, so it must be approved before it can be
issued to a vendor. Approval (draft -> approved) is what publishes
``procurement.po.approved``, which the finance subscriber turns into a live
``ProjectBudget.committed`` increase; issuing (approved -> issued) is the
separate downstream step. These tests pin the FSM and the approval method
against real PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.schemas import POCreate, POItemCreate
from app.modules.procurement.service import ProcurementService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _draft_po(svc: ProcurementService):
    """A complete, approvable draft PO.

    Approval runs the blocking ``procurement`` rule set, so the fixture has to
    be a purchase order that a buyer could really approve: a named vendor, a
    line whose amount reconciles with the subtotal, and a currency. These tests
    pin the FSM, not completeness, and an incomplete fixture would make them
    fail for a reason none of them is about.
    """
    return await svc.create_po(
        POCreate(
            project_id=uuid.uuid4(),
            vendor_contact_id=str(uuid.uuid4()),
            currency_code="EUR",
            amount_subtotal="100000",
            tax_amount="19000",
            status="draft",
            items=[
                POItemCreate(
                    description="Structural steel supply",
                    quantity="1",
                    unit="lot",
                    unit_rate="100000",
                    amount="100000",
                    cost_category="structure",
                ),
            ],
        ),
    )


@pytest.mark.asyncio
async def test_draft_cannot_be_issued_directly(session: AsyncSession) -> None:
    svc = ProcurementService(session)
    po = await _draft_po(svc)
    with pytest.raises(HTTPException) as exc:
        await svc.issue_po(po.id)
    assert exc.value.status_code == 409
    assert "approved" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_approve_then_issue(session: AsyncSession) -> None:
    svc = ProcurementService(session)
    po = await _draft_po(svc)
    approved = await svc.approve_po(po.id, approver_id=str(uuid.uuid4()))
    assert approved.status == "approved"
    issued = await svc.issue_po(po.id)
    assert issued.status == "issued"


@pytest.mark.asyncio
async def test_approve_is_idempotent(session: AsyncSession) -> None:
    svc = ProcurementService(session)
    po = await _draft_po(svc)
    first = await svc.approve_po(po.id)
    again = await svc.approve_po(po.id)
    assert first.status == again.status == "approved"


@pytest.mark.asyncio
async def test_cannot_approve_an_issued_po(session: AsyncSession) -> None:
    svc = ProcurementService(session)
    po = await _draft_po(svc)
    await svc.approve_po(po.id)
    await svc.issue_po(po.id)
    with pytest.raises(HTTPException) as exc:
        await svc.approve_po(po.id)
    assert exc.value.status_code == 409
