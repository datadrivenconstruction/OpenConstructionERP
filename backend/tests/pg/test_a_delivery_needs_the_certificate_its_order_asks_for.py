# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""From a delivery to the release of its payment, on PostgreSQL (BF-01).

Reinforcing steel is ordered with an EN 10204 type 3.1 certificate and an
incoming inspection. The receipt cannot be confirmed until a certificate that
satisfies the order is on the line; a certificate for another heat is flagged
but does not block. Whoever confirms chooses to start the project's approval
route for goods receipts and the incoming inspection, both written in the same
transaction. A payable invoice on the order is not released while that route
is open, and is once it is approved. The quality concept can point a proof at
the delivery.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi import HTTPException
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


@dataclass
class World:
    owner_id: uuid.UUID
    project_id: uuid.UUID
    po_id: uuid.UUID
    line_id: uuid.UUID
    plain_line_id: uuid.UUID


async def _world(session, *, with_route: bool = True, routes: int = 1) -> World:
    from app.modules.approval_routes.models import Route, Step
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"bf01-{tag}@site.example", hashed_password="x", full_name="Site manager")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Frame {tag}", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    po = PurchaseOrder(
        project_id=project.id,
        vendor_contact_id=str(uuid.uuid4()),
        po_number=f"PO-{tag.upper()}",
        currency_code="EUR",
        amount_subtotal="9000.00",
        amount_total="9000.00",
        status="issued",
    )
    session.add(po)
    await session.flush()
    rebar = PurchaseOrderItem(
        po_id=po.id,
        description="Rebar B500B 12 mm",
        quantity="10",
        unit="t",
        unit_rate="800",
        amount="8000",
        sort_order=0,
        required_certificate_type="en10204_3_1",
        requires_inspection=True,
    )
    spacers = PurchaseOrderItem(
        po_id=po.id, description="Spacers", quantity="100", unit="pcs", unit_rate="10", amount="1000", sort_order=1
    )
    session.add_all([rebar, spacers])
    await session.flush()
    if with_route:
        for n in range(routes):
            route = Route(project_id=project.id, name=f"Site approval {n + 1}", target_kind="goods_receipt")
            session.add(route)
            await session.flush()
            session.add(Step(route_id=route.id, ordinal=1, approver_user_id=owner.id, mode="any"))
        await session.flush()
    return World(owner.id, project.id, po.id, rebar.id, spacers.id)


async def _receipt(session, w: World, *, certificates: list[dict] | None = None, batch: str = "H-20931"):
    from app.modules.procurement.schemas import GRCreate, GRItemCreate
    from app.modules.procurement.service import ProcurementService

    return await ProcurementService(session).create_goods_receipt(
        GRCreate(
            po_id=w.po_id,
            receipt_date="2026-10-16",
            delivery_note_number="LS-4711",
            items=[
                GRItemCreate(
                    po_item_id=w.line_id,
                    quantity_ordered="10",
                    quantity_received="4",
                    batch_lot=batch,
                    certificates=certificates or [],
                ),
                GRItemCreate(po_item_id=w.plain_line_id, quantity_ordered="100", quantity_received="100"),
            ],
        ),
        user_id=str(w.owner_id),
    )


CERT_31 = {
    "certificate_type": "en10204_3_1",
    "certificate_number": "Z-118",
    "issuer": "Mill",
    "batch_number": "H-20931",
}


async def test_a_receipt_without_the_ordered_certificate_is_not_confirmed(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.models import GoodsReceipt
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session)
    gr = await _receipt(pg_session, w)

    with pytest.raises(HTTPException) as caught:
        await ProcurementService(pg_session).confirm_goods_receipt(gr.id, actor_id=str(w.owner_id))

    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "receipt_validation_failed"
    assert [e["rule_id"] for e in caught.value.detail["errors"]] == ["procurement.receipt_certificate_present"]
    assert (await pg_session.get(GoodsReceipt, gr.id)).status == "draft"


async def test_a_lower_certificate_does_not_do_and_the_ordered_one_does(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.receiving import ReceivingService
    from app.modules.procurement.schemas import GRCertificateCreate
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session)
    gr = await _receipt(pg_session, w)
    service = ProcurementService(pg_session)
    receiving = ReceivingService(pg_session)
    line = next(i for i in gr.items if i.po_item_id == w.line_id)

    po = await service.get_po(w.po_id)
    await receiving.add_certificate(
        gr, po, line.id, GRCertificateCreate(certificate_type="en10204_2_2", certificate_number="T-1"), actor_id=None
    )
    with pytest.raises(HTTPException):
        await service.confirm_goods_receipt(gr.id)

    gr = await service.get_goods_receipt(gr.id)
    await receiving.add_certificate(gr, po, line.id, GRCertificateCreate(**CERT_31), actor_id=None)
    confirmed = await service.confirm_goods_receipt(gr.id)

    assert confirmed.status == "confirmed"
    assert {c.certificate_type for i in confirmed.items for c in i.certificates} == {"en10204_2_2", "en10204_3_1"}
    assert confirmed.approval_instance_id is None and confirmed.inspection_id is None, "nothing starts unasked"


async def test_another_heat_on_the_certificate_warns_and_does_not_block(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.receiving import ReceivingService
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session)
    gr = await _receipt(pg_session, w, certificates=[{**CERT_31, "batch_number": "H-99999"}])
    service = ProcurementService(pg_session)

    report = await ReceivingService(pg_session).validate_receipt(gr, await service.get_po(w.po_id))

    assert report.has_errors is False
    assert [r.rule_id for r in report.warnings] == ["procurement.receipt_certificate_batch"]
    assert (await service.confirm_goods_receipt(gr.id)).status == "confirmed"


async def test_confirming_starts_the_chosen_route_and_the_due_inspection(pg_session, no_detached_subscribers) -> None:
    from app.modules.approval_routes.models import Instance
    from app.modules.inspections.models import QualityInspection
    from app.modules.procurement.schemas import GRConfirmRequest
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session)
    gr = await _receipt(pg_session, w, certificates=[CERT_31])

    confirmed = await ProcurementService(pg_session).confirm_goods_receipt(
        gr.id,
        GRConfirmRequest(start_approval_route=True, create_inspection=True),
        actor_id=str(w.owner_id),
    )

    instance = await pg_session.get(Instance, confirmed.approval_instance_id)
    assert instance is not None
    assert (instance.target_kind, instance.target_id, instance.status) == ("goods_receipt", gr.id, "pending")
    inspection = await pg_session.get(QualityInspection, confirmed.inspection_id)
    assert inspection is not None and inspection.status == "scheduled"
    assert inspection.project_id == w.project_id
    assert inspection.metadata_["goods_receipt_id"] == str(gr.id)
    assert inspection.metadata_["lines"] == ["1 (Rebar B500B 12 mm)"], "only the line whose order asks for it"


async def test_a_route_that_cannot_be_chosen_confirms_nothing(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.models import GoodsReceipt
    from app.modules.procurement.schemas import GRConfirmRequest
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session, routes=2)
    gr = await _receipt(pg_session, w, certificates=[CERT_31])

    with pytest.raises(HTTPException) as caught:
        await ProcurementService(pg_session).confirm_goods_receipt(gr.id, GRConfirmRequest(start_approval_route=True))

    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "approval_route_ambiguous"
    assert (await pg_session.get(GoodsReceipt, gr.id)).status == "draft"


async def test_the_invoice_waits_for_the_receipt_approval(pg_session, no_detached_subscribers) -> None:
    from app.modules.approval_routes.models import Instance
    from app.modules.finance.models import Invoice
    from app.modules.finance.service import FinanceService
    from app.modules.procurement.schemas import GRConfirmRequest
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session)
    gr = await _receipt(pg_session, w, certificates=[CERT_31])
    confirmed = await ProcurementService(pg_session).confirm_goods_receipt(
        gr.id, GRConfirmRequest(start_approval_route=True), actor_id=str(w.owner_id)
    )
    invoice = Invoice(
        project_id=w.project_id,
        invoice_direction="payable",
        purchase_order_id=w.po_id,
        invoice_number="RE-2026-118",
        invoice_date="2026-10-20",
        currency_code="EUR",
        status="draft",
    )
    pg_session.add(invoice)
    await pg_session.flush()
    finance = FinanceService(pg_session)

    with pytest.raises(HTTPException) as caught:
        await finance.approve_invoice(invoice.id)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "payment_release_blocked"
    assert [e["element_ref"] for e in caught.value.detail["errors"]] == ["LS-4711"]

    instance = await pg_session.get(Instance, confirmed.approval_instance_id)
    instance.status = "approved"
    await pg_session.flush()
    approved = await finance.approve_invoice(invoice.id)
    assert approved.status == "approved"


async def test_an_invoice_on_an_order_never_routed_is_released_as_before(pg_session, no_detached_subscribers) -> None:
    from app.modules.finance.models import Invoice
    from app.modules.finance.service import FinanceService
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session, with_route=False)
    gr = await _receipt(pg_session, w, certificates=[CERT_31])
    await ProcurementService(pg_session).confirm_goods_receipt(gr.id)
    invoice = Invoice(
        project_id=w.project_id,
        invoice_direction="payable",
        purchase_order_id=w.po_id,
        invoice_number="RE-2026-119",
        invoice_date="2026-10-20",
        currency_code="EUR",
        status="draft",
    )
    pg_session.add(invoice)
    await pg_session.flush()

    assert (await FinanceService(pg_session).approve_invoice(invoice.id)).status == "approved"


async def test_a_quality_proof_can_point_at_the_delivery(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.service import ProcurementService
    from app.modules.quality_concept import links

    w = await _world(pg_session, with_route=False)
    gr = await _receipt(pg_session, w, certificates=[CERT_31])

    draft_fact = await links.resolve(pg_session, w.project_id, "goods_receipt", str(gr.id))
    assert draft_fact is not None and draft_fact.outcome == "pending"
    await ProcurementService(pg_session).confirm_goods_receipt(gr.id)
    fact = await links.resolve(pg_session, w.project_id, "goods_receipt", str(gr.id))
    assert fact is not None and fact.outcome == "pass"
    assert await links.resolve(pg_session, uuid.uuid4(), "goods_receipt", str(gr.id)) is None, "another project"
    found = await links.candidates(pg_session, w.project_id, "goods_receipt")
    assert [c["id"] for c in found] == [str(gr.id)]


async def test_a_requirement_can_be_set_on_an_issued_line(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.models import PurchaseOrderItem
    from app.modules.procurement.schemas import POItemRequirementsUpdate
    from app.modules.procurement.service import ProcurementService

    w = await _world(pg_session, with_route=False)
    await ProcurementService(pg_session).update_po_item_requirements(
        w.po_id,
        w.plain_line_id,
        POItemRequirementsUpdate(required_certificate_type="en10204_2_1", requires_inspection=True),
    )

    row = (
        await pg_session.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.id == w.plain_line_id))
    ).scalar_one()
    assert (row.required_certificate_type, row.requires_inspection) == ("en10204_2_1", True)


async def test_the_confirm_dialog_reads_and_fixes_the_receipt_over_http(pg_session, no_detached_subscribers) -> None:
    import httpx
    from fastapi import FastAPI

    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.procurement.router import router

    w = await _world(pg_session)
    gr = await _receipt(pg_session, w)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/procurement")

    async def _session():
        yield pg_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(w.owner_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(w.owner_id),
        "role": "admin",
        "permissions": [],
    }
    base = f"/api/v1/procurement/goods-receipts/{gr.id}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gr-test") as c:
        types = await c.get("/api/v1/procurement/certificate-types/")
        before = await c.get(f"{base}/readiness/")
        rebar = next(line for line in before.json()["lines"] if line["required_certificate_type"])
        added = await c.post(f"{base}/certificates/", json={"gr_item_id": rebar["gr_item_id"], **CERT_31})
        after = await c.get(f"{base}/readiness/")
        confirmed = await c.post(f"{base}/confirm/", json={"start_approval_route": True, "create_inspection": True})

    assert types.status_code == 200
    assert "en10204_3_1" in {t["code"] for t in types.json()}
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["can_confirm"] is False
    assert body["validation"]["status"] == "errors"
    assert body["inspection_due"] is True
    assert [r["name"] for r in body["approval_routes"]] == ["Site approval 1"]
    assert rebar["label"].endswith("(Rebar B500B 12 mm)") and rebar["unit"] == "t"
    assert added.status_code == 201, added.text
    assert after.json()["can_confirm"] is True
    assert len(next(li for li in after.json()["lines"] if li["gr_item_id"] == rebar["gr_item_id"])["certificates"]) == 1
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["approval_instance_id"] and confirmed.json()["inspection_id"]
