# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A supplier tells the site what is on its way, through the portal (BF-01).

The supplier holds a portal account and a ``po`` access rule. With ``submit``
it can send a delivery note, quantities per line and certificates; that is a
DRAFT goods receipt marked as supplier-submitted, which only site staff can
confirm. Without a rule the order does not exist for it (404), with ``view``
it can read but not submit, and it cannot attach another account's document.
Exercised over HTTP on PostgreSQL with the portal session resolved to the
supplier, exactly as the portal dependency would.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/portal"


@dataclass
class World:
    supplier: object
    project_id: uuid.UUID
    po_id: uuid.UUID
    other_po_id: uuid.UUID
    line_id: uuid.UUID


async def _world(session, *, permission: str = "submit") -> World:
    from app.modules.portal.models import PortalAccessRule, PortalUser
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"bf01-portal-{tag}@site.example", hashed_password="x", full_name="Buyer")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Portal frame {tag}", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    pos = []
    for n in range(2):
        po = PurchaseOrder(
            project_id=project.id,
            po_number=f"PO-{tag.upper()}-{n}",
            currency_code="EUR",
            amount_subtotal="8000",
            amount_total="8000",
            status="issued",
        )
        session.add(po)
        await session.flush()
        pos.append(po)
    line = PurchaseOrderItem(
        po_id=pos[0].id,
        description="Rebar cage C-12",
        quantity="10",
        unit="t",
        unit_rate="800",
        amount="8000",
        required_certificate_type="en10204_3_1",
    )
    session.add(line)
    supplier = PortalUser(
        email=f"supplier-{tag}@mill.example", full_name="Mill", portal_role="supplier", status="active"
    )
    session.add(supplier)
    await session.flush()
    session.add(
        PortalAccessRule(portal_user_id=supplier.id, resource_type="po", resource_id=pos[0].id, permission=permission)
    )
    await session.flush()
    return World(supplier, project.id, pos[0].id, pos[1].id, line.id)


def _client(session, world: World) -> httpx.AsyncClient:
    from app.dependencies import get_session
    from app.modules.portal.dependencies import get_current_portal_user
    from app.modules.portal.router import router

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_portal_user] = lambda: world.supplier
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal-test")


def _delivery(world: World, **over) -> dict:
    body = {
        "po_id": str(world.po_id),
        "delivery_note_number": "LS-4711",
        "delivery_date": "2026-10-16",
        "lines": [
            {
                "po_item_id": str(world.line_id),
                "quantity": "4",
                "batch_lot": "H-20931",
                "certificates": [
                    {"certificate_type": "en10204_3_1", "certificate_number": "Z-118", "batch_number": "H-20931"}
                ],
            }
        ],
    }
    body.update(over)
    return body


async def test_a_submitted_delivery_is_a_draft_the_site_still_confirms(pg_session, no_detached_subscribers) -> None:
    from app.modules.procurement.models import GoodsReceipt

    w = await _world(pg_session)
    async with _client(pg_session, w) as c:
        listed = await c.get(f"{BASE}/me/purchase-orders")
        sent = await c.post(f"{BASE}/me/deliveries", json=_delivery(w))
        mine = await c.get(f"{BASE}/me/deliveries")

    assert listed.status_code == 200
    orders = listed.json()["items"]
    assert [o["id"] for o in orders] == [str(w.po_id)], "only the order shared with this supplier"
    assert orders[0]["can_deliver"] is True
    assert orders[0]["lines"][0]["required_certificate_type"] == "en10204_3_1"
    assert "en10204_3_1" in {c["code"] for c in listed.json()["certificate_types"]}

    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "draft"
    assert sent.json()["lines"][0]["certificate_count"] == 1
    gr = (
        await pg_session.execute(select(GoodsReceipt).where(GoodsReceipt.id == uuid.UUID(sent.json()["id"])))
    ).scalar_one()
    assert (gr.status, gr.source, gr.portal_user_id, gr.received_by_id) == (
        "draft",
        "supplier_portal",
        w.supplier.id,
        None,
    )
    assert gr.items[0].certificates[0].source == "supplier_portal"
    assert [d["id"] for d in mine.json()["items"]] == [sent.json()["id"]]


async def test_an_order_not_shared_answers_404(pg_session, no_detached_subscribers) -> None:
    w = await _world(pg_session)
    async with _client(pg_session, w) as c:
        foreign = await c.post(f"{BASE}/me/deliveries", json=_delivery(w, po_id=str(w.other_po_id)))
        foreign_line = await c.post(
            f"{BASE}/me/deliveries",
            json=_delivery(w, lines=[{"po_item_id": str(uuid.uuid4()), "quantity": "1"}]),
        )
    assert foreign.status_code == 404
    assert foreign_line.status_code == 404


async def test_view_access_reads_but_cannot_submit(pg_session, no_detached_subscribers) -> None:
    w = await _world(pg_session, permission="view")
    async with _client(pg_session, w) as c:
        listed = await c.get(f"{BASE}/me/purchase-orders")
        sent = await c.post(f"{BASE}/me/deliveries", json=_delivery(w))
    assert listed.json()["items"][0]["can_deliver"] is False
    assert sent.status_code == 404


async def test_a_supplier_cannot_attach_another_accounts_document(pg_session, no_detached_subscribers) -> None:
    from app.modules.documents.models import Document

    w = await _world(pg_session)
    doc = Document(project_id=w.project_id, name="someone-else.pdf", uploaded_by=str(uuid.uuid4()))
    own = Document(project_id=w.project_id, name="LS-4711.pdf", uploaded_by=str(w.supplier.id))
    pg_session.add_all([doc, own])
    await pg_session.flush()

    async with _client(pg_session, w) as c:
        refused = await c.post(f"{BASE}/me/deliveries", json=_delivery(w, delivery_note_document_id=str(doc.id)))
        accepted = await c.post(f"{BASE}/me/deliveries", json=_delivery(w, delivery_note_document_id=str(own.id)))

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "document_not_in_project"
    assert accepted.status_code == 201


async def test_an_unknown_certificate_type_is_refused(pg_session, no_detached_subscribers) -> None:
    w = await _world(pg_session)
    body = _delivery(w)
    body["lines"][0]["certificates"][0]["certificate_type"] = "made_up"
    async with _client(pg_session, w) as c:
        sent = await c.post(f"{BASE}/me/deliveries", json=body)
    assert sent.status_code == 422
