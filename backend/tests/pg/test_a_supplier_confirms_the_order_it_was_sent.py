# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A buyer records that the supplier confirmed an issued order.

An issued purchase order is a promise the buyer made; the supplier's order
confirmation is the answer, often with its own reference and a delivery date
that differs from the one asked for. Until it is recorded the site plans on a
date nobody agreed to. The confirmation is stored in columns, not in metadata,
so the register can list the orders still waiting for one.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


async def _seed_po(pg_session, *, status: str) -> uuid.UUID:
    from app.modules.procurement.models import PurchaseOrder
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"po-ack-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Buyer",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(id=uuid.uuid4(), name="Order confirmation", owner_id=owner.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()
    po = PurchaseOrder(
        id=uuid.uuid4(),
        project_id=project.id,
        vendor_contact_id=str(uuid.uuid4()),
        po_number=f"PO-A-{uuid.uuid4().hex[:6].upper()}",
        delivery_date="2026-11-02",
        currency_code="EUR",
        amount_subtotal="1000.00",
        amount_total="1000.00",
        status=status,
    )
    pg_session.add(po)
    await pg_session.flush()
    return po.id


async def test_an_issued_order_takes_the_suppliers_confirmation(pg_session) -> None:
    from app.modules.procurement.service import ProcurementService

    po_id = await _seed_po(pg_session, status="issued")
    service = ProcurementService(pg_session)

    po = await service.acknowledge_po(
        po_id,
        supplier_reference="AB-2026-0815",
        confirmed_delivery_date="2026-11-09",
        actor_id="buyer-1",
    )

    assert po.supplier_reference == "AB-2026-0815"
    assert po.supplier_confirmed_delivery_date == "2026-11-09"
    assert po.supplier_acknowledged_by == "buyer-1"
    assert po.supplier_acknowledged_at
    assert po.delivery_date == "2026-11-02", "the date asked for stays; the supplier's answer sits beside it"
    assert po.status == "issued", "a confirmation is not a status change"


async def test_a_revised_confirmation_replaces_the_first(pg_session) -> None:
    from app.modules.procurement.service import ProcurementService

    po_id = await _seed_po(pg_session, status="partially_received")
    service = ProcurementService(pg_session)
    await service.acknowledge_po(po_id, supplier_reference="AB-1", confirmed_delivery_date="2026-11-09")

    po = await service.acknowledge_po(po_id, supplier_reference="AB-1/rev", confirmed_delivery_date=None)

    assert po.supplier_reference == "AB-1/rev"
    assert po.supplier_confirmed_delivery_date is None


@pytest.mark.parametrize("status", ["draft", "approved", "completed", "cancelled"])
async def test_only_an_order_out_with_the_supplier_can_be_confirmed(pg_session, status: str) -> None:
    from app.modules.procurement.service import ProcurementService

    po_id = await _seed_po(pg_session, status=status)

    with pytest.raises(HTTPException) as caught:
        await ProcurementService(pg_session).acknowledge_po(po_id, supplier_reference="AB-9")

    assert caught.value.status_code == 409
