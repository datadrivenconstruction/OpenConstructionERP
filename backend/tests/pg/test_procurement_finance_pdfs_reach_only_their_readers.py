# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The purchase order, goods receipt, invoice and payment PDFs over the API (#514).

Through the real routers and a real PostgreSQL database:

* the project's reader downloads each document as a PDF, in the language asked
  for, and the stored totals are the ones on the page;
* a user without access to the project gets the same 404 the detail routes
  give, so a record that cannot be opened cannot be printed either;
* a role without the module's read permission gets 403;
* an id that matches nothing is a 404;
* a section the workspace hid is not on the page.

``verify_project_access`` is the real one, so project scoping is the
application's and not a stand-in.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import httpx
import pypdf
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.core.pdf_appearance import write_hidden_sections
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.finance.models import Invoice, InvoiceLineItem, Payment
from app.modules.finance.permissions import register_finance_permissions
from app.modules.finance.router import router as finance_router
from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem, PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.permissions import register_procurement_permissions
from app.modules.procurement.router import router as procurement_router
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest_asyncio.fixture
async def db() -> AsyncIterator:
    async with transactional_session() as session:
        yield session


async def _user(session) -> str:
    user = User(email=f"pdf-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    return str(user.id)


async def _records(session, owner_id: str) -> dict[str, uuid.UUID]:
    project = Project(name="Harbour Tower", owner_id=uuid.UUID(owner_id), currency="EUR", country_code="DE")
    session.add(project)
    await session.flush()
    po = PurchaseOrder(
        project_id=project.id,
        po_number="PO-0042",
        currency_code="EUR",
        amount_subtotal="1234.57",
        tax_amount="234.57",
        amount_total="1469.14",
        status="issued",
        notes="Deliver to gate B between 7 and 9 am.",
    )
    session.add(po)
    await session.flush()
    item = PurchaseOrderItem(
        po_id=po.id,
        description="Ready-mix concrete C30/37",
        quantity="12.5",
        unit="m3",
        unit_rate="98.7656",
        amount="1234.57",
    )
    session.add(item)
    await session.flush()
    receipt = GoodsReceipt(po_id=po.id, receipt_date="2026-09-14", delivery_note_number="DN-77", status="confirmed")
    session.add(receipt)
    await session.flush()
    session.add(
        GoodsReceiptItem(
            receipt_id=receipt.id,
            po_item_id=item.id,
            quantity_ordered="12.5",
            quantity_received="12.5",
            quantity_rejected="0",
        )
    )
    invoice = Invoice(
        project_id=project.id,
        invoice_direction="payable",
        purchase_order_id=po.id,
        invoice_number="INV-2026-0042",
        invoice_date="2026-09-20",
        currency_code="EUR",
        amount_subtotal=Decimal("1234.57"),
        tax_amount=Decimal("234.57"),
        retention_amount=Decimal("0"),
        amount_total=Decimal("1469.14"),
        status="approved",
    )
    session.add(invoice)
    await session.flush()
    session.add(
        InvoiceLineItem(
            invoice_id=invoice.id,
            description="Ready-mix concrete C30/37",
            quantity=Decimal("12.5"),
            unit="m3",
            unit_rate=Decimal("98.7656"),
            amount=Decimal("1234.57"),
        )
    )
    payment = Payment(
        invoice_id=invoice.id,
        payment_date="2026-10-01",
        amount=Decimal("1469.14"),
        currency_code="EUR",
        reference="SEPA-55012",
    )
    session.add(payment)
    await session.flush()
    return {"po": po.id, "gr": receipt.id, "invoice": invoice.id, "payment": payment.id}


def _client(session, caller_id: str, role: str = "viewer") -> httpx.AsyncClient:
    register_procurement_permissions()
    register_finance_permissions()
    app = FastAPI()
    app.include_router(procurement_router, prefix="/v1/procurement")
    app.include_router(finance_router, prefix="/v1/finance")

    async def _session_override():
        yield session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        return {"sub": caller_id, "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _paths(ids: dict[str, uuid.UUID]) -> dict[str, str]:
    return {
        "purchase_order": f"/v1/procurement/{ids['po']}/export/pdf/",
        "goods_receipt": f"/v1/procurement/goods-receipts/{ids['gr']}/export/pdf/",
        "invoice": f"/v1/finance/invoices/{ids['invoice']}/export/pdf/",
        "payment": f"/v1/finance/payments/{ids['payment']}/export/pdf/",
    }


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


DOC_TYPES = ("purchase_order", "goods_receipt", "invoice", "payment")


@pytest.mark.parametrize("doc_type", DOC_TYPES)
async def test_the_reader_downloads_the_pdf_in_the_language_asked_for(db, doc_type: str) -> None:
    owner = await _user(db)
    path = _paths(await _records(db, owner))[doc_type]
    async with _client(db, owner) as client:
        response = await client.get(path, params={"locale": "de"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-language"] == "de"
    assert response.content.startswith(b"%PDF")
    text = _text(response.content)
    if doc_type in ("purchase_order", "invoice"):
        assert "1.469,14" in text
        assert "234,57" in text
        assert "1.703,71" not in text


@pytest.mark.parametrize("doc_type", DOC_TYPES)
async def test_a_user_outside_the_project_gets_a_404(db, doc_type: str) -> None:
    owner = await _user(db)
    outsider = await _user(db)
    path = _paths(await _records(db, owner))[doc_type]
    async with _client(db, outsider) as client:
        response = await client.get(path)
    assert response.status_code == 404


@pytest.mark.parametrize("doc_type", DOC_TYPES)
async def test_a_role_without_read_permission_gets_a_403(db, doc_type: str) -> None:
    owner = await _user(db)
    path = _paths(await _records(db, owner))[doc_type]
    # A role the registry does not know holds no permission at all.
    async with _client(db, owner, role="no_such_role") as client:
        response = await client.get(path)
    assert response.status_code == 403


@pytest.mark.parametrize("doc_type", DOC_TYPES)
async def test_an_unknown_record_is_a_404(db, doc_type: str) -> None:
    owner = await _user(db)
    missing = dict.fromkeys(("po", "gr", "invoice", "payment"), uuid.uuid4())
    async with _client(db, owner) as client:
        response = await client.get(_paths(missing)[doc_type])
    assert response.status_code == 404


async def test_a_hidden_section_is_not_on_the_downloaded_page(db, _data_dir: Path) -> None:
    owner = await _user(db)
    path = _paths(await _records(db, owner))["purchase_order"]
    async with _client(db, owner) as client:
        before = _text((await client.get(path)).content)
        write_hidden_sections("purchase_order", ["notes"], _data_dir)
        after = _text((await client.get(path)).content)
    assert "Deliver to gate B" in before
    assert "Deliver to gate B" not in after
