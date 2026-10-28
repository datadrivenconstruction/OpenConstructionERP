# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Sample purchase order, goods receipt, invoice and payment for the PDF tests.

Plain namespaces with the attributes the ORM rows carry, so the builders are
exercised without a database. Shared by the record form tests and the
per-document-type appearance gates, which render every configurable type.

The amounts are deliberately not ones a float survives: 1234.57 net plus
234.57 tax (a 19 % rate applied to the net would give 234.5683) is a total
of 1469.14. A form that printed anything but these three stored figures,
or added the tax to the total again, shows up as a different string.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.register_export import ProjectHeader

PROJECT = ProjectHeader(name="Harbour Tower", code="HT-01", currency="EUR", country="DE")
VENDOR_ID = "aaaaaaaa-0000-0000-0000-000000000001"
USER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
PEOPLE = {VENDOR_ID: "Baustoffe Nord GmbH", str(USER_ID): "Maria Keller"}
PO_ITEM_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")


def purchase_order(**overrides: Any) -> SimpleNamespace:
    po = SimpleNamespace(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        project_id=uuid.uuid4(),
        vendor_contact_id=VENDOR_ID,
        po_number="PO-0042",
        po_type="standard",
        issue_date="2026-09-01",
        delivery_date="2026-09-15",
        currency_code="EUR",
        amount_subtotal="1234.57",
        tax_amount="234.57",
        amount_total="1469.14",
        retention_percent=Decimal("5.00"),
        retain_on_receipt=False,
        status="issued",
        supplier_acknowledged_at="2026-09-02T10:00:00",
        supplier_reference="AB-7781",
        supplier_confirmed_delivery_date="2026-09-14",
        invoice_tolerance_pct="2",
        invoice_tolerance_abs=None,
        payment_terms="30 days net",
        notes="Deliver to gate B between 7 and 9 am.",
        created_by=USER_ID,
        items=[
            SimpleNamespace(
                id=PO_ITEM_ID,
                description="Ready-mix concrete C30/37",
                quantity="12.5",
                unit="m3",
                unit_rate="98.7656",
                amount="1234.57",
                sort_order=0,
            )
        ],
    )
    for key, value in overrides.items():
        setattr(po, key, value)
    return po


def goods_receipt(**overrides: Any) -> SimpleNamespace:
    receipt = SimpleNamespace(
        id=uuid.uuid4(),
        po_id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        receipt_date="2026-09-14",
        received_by_id=USER_ID,
        delivery_note_number="DN-77",
        status="confirmed",
        notes="Two bags torn on arrival.",
        items=[
            SimpleNamespace(
                po_item_id=PO_ITEM_ID,
                quantity_ordered="12.5",
                quantity_received="12",
                quantity_rejected="0.5",
                rejection_reason="Slump out of tolerance",
                batch_lot="LOT-2209",
            )
        ],
    )
    for key, value in overrides.items():
        setattr(receipt, key, value)
    return receipt


def payment(**overrides: Any) -> SimpleNamespace:
    record = SimpleNamespace(
        id=uuid.uuid4(),
        invoice_id=uuid.uuid4(),
        payment_date="2026-10-01",
        amount=Decimal("1395.18"),
        currency_code="EUR",
        exchange_rate_snapshot=Decimal("1"),
        reference="SEPA-55012",
        is_refund=False,
        withholding_amount=Decimal("73.96"),
        withholding_release_date="2027-10-01",
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def invoice(**overrides: Any) -> SimpleNamespace:
    record = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        contact_id=VENDOR_ID,
        invoice_direction="payable",
        purchase_order_id=None,
        invoice_number="INV-2026-0042",
        invoice_date="2026-09-20",
        due_date="2026-10-20",
        currency_code="EUR",
        amount_subtotal=Decimal("1234.57"),
        tax_amount=Decimal("234.57"),
        retention_amount=Decimal("73.96"),
        amount_total=Decimal("1469.14"),
        status="approved",
        payment_terms_days="30",
        notes="Quote the invoice number on the transfer.",
        created_by=USER_ID,
        line_items=[
            SimpleNamespace(
                description="Ready-mix concrete C30/37",
                quantity=Decimal("12.5"),
                unit="m3",
                unit_rate=Decimal("98.7656"),
                amount=Decimal("1234.57"),
                vat_rate=Decimal("19"),
                sort_order=0,
            )
        ],
        payments=[payment()],
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def render_purchase_order() -> bytes:
    from app.core.pdf_appearance import resolve_sections
    from app.modules.procurement.pdf_export import build_purchase_order_pdf

    return build_purchase_order_pdf(
        purchase_order(), project=PROJECT, people=PEOPLE, sections=resolve_sections("purchase_order")
    )


def render_goods_receipt() -> bytes:
    from app.core.pdf_appearance import resolve_sections
    from app.modules.procurement.pdf_export import build_goods_receipt_pdf

    return build_goods_receipt_pdf(
        goods_receipt(), po=purchase_order(), project=PROJECT, people=PEOPLE, sections=resolve_sections("goods_receipt")
    )


def render_invoice() -> bytes:
    from app.core.pdf_appearance import resolve_sections
    from app.modules.finance.pdf_export import build_invoice_pdf

    return build_invoice_pdf(invoice(), project=PROJECT, people=PEOPLE, sections=resolve_sections("invoice"))


def render_payment() -> bytes:
    from app.core.pdf_appearance import resolve_sections
    from app.modules.finance.pdf_export import build_payment_pdf

    return build_payment_pdf(
        payment(), invoice=invoice(), project=PROJECT, people=PEOPLE, sections=resolve_sections("payment")
    )
