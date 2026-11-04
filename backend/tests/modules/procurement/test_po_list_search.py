"""Purchase order list search: by PO number or vendor name, within one project."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.procurement.models import PurchaseOrder
from app.modules.procurement.repository import PurchaseOrderRepository
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _po(session: AsyncSession, project_id: uuid.UUID, number: str, vendor: str | None = None) -> None:
    session.add(
        PurchaseOrder(
            project_id=project_id,
            po_number=number,
            status="issued",
            vendor_contact_id=vendor,
            currency_code="EUR",
            amount_subtotal="1",
            amount_total="1",
        )
    )
    await session.flush()


async def test_search_matches_number_and_vendor_name_in_project(session: AsyncSession) -> None:
    project, other = uuid.uuid4(), uuid.uuid4()
    contact = Contact(contact_type="supplier", company_name="Acme Steel GmbH")
    session.add(contact)
    await session.flush()
    for n in range(1, 131):
        await _po(session, project, f"PO-{n:04d}")
    await _po(session, project, "PO-9001", str(contact.id))
    await _po(session, other, "PO-0007")
    repo = PurchaseOrderRepository(session)

    items, total = await repo.list(project_id=project, search="po-0007")
    assert [p.po_number for p in items] == ["PO-0007"] and total == 1

    items, _ = await repo.list(project_id=project, search="acme")
    assert [p.po_number for p in items] == ["PO-9001"]

    # an order beyond the first 100 stays reachable
    items, _ = await repo.list(project_id=project, search="PO-0125")
    assert [p.po_number for p in items] == ["PO-0125"]

    # wildcards are literal
    items, total = await repo.list(project_id=project, search="%")
    assert total == 0
