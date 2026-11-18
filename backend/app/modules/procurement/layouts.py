# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layouts of the purchase order and the goods receipt.

Each layout declares the merge fields, the line item columns, the sections only
this module draws and what may never be hidden, and ships the standard template:
the blocks that print the form exactly as the hand-written form printed it,
including the sections a workspace switched off in its per-type settings.

Locks are the neutral minimum of a purchase order and a goods receipt in any
market (who orders what from whom, at which price; what arrived against which
order). Country packs add their own through ``document_requirements.json``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.doc_templates.layout.spec import (
    COMMON_FIELDS,
    CollectionSpec,
    ColumnSpec,
    LayoutContext,
    LayoutSpec,
    SectionSpec,
    register_layout,
)
from app.core.doc_templates.registry import MandatoryField, MergeField
from app.core.register_export import ProjectHeader

__all__ = [
    "GOODS_RECEIPT",
    "PURCHASE_ORDER",
    "goods_receipt_standard",
    "purchase_order_standard",
    "register_procurement_layouts",
]

_STANDARD = "Platform standard"
_PO_KEY = "procurement.purchase_order"
_GR_KEY = "procurement.goods_receipt"


def _hidden(sections: Mapping[str, bool] | None, name: str) -> bool:
    return sections is not None and sections.get(name, True) is False


def _fields(*paths: str, omit: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [{"field": p, **({"omit_empty": True} if p in omit else {})} for p in paths]


def _columns(*ids: str) -> list[dict[str, str]]:
    return [{"id": i} for i in ids]


def _template(body: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": 1,
        "primary_locale": "en",
        "title": {},
        "subject": {},
        "show_subject": True,
        "page": {"size": "A4", "orientation": "portrait"},
        "branding": {},
        "watermark": {},
        "header": [],
        "footer": [],
        "body": body,
    }


# ── Purchase order ───────────────────────────────────────────────────────


def purchase_order_standard(sections: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """The standard purchase order, with the sections the workspace switched off hidden.

    Args:
        sections: ``{section: printed}`` from :func:`app.core.pdf_appearance.resolve_sections`.
    """
    return _template(
        [
            {
                "id": "order_details",
                "type": "fields",
                "layout": "pairs",
                "hidden": False,
                "fields": _fields(
                    "supplier.name",
                    "supplier.tax_id",
                    "supplier.address",
                    "doc.po_type",
                    "doc.issue_date",
                    "doc.delivery_date",
                    "doc.delivery_address",
                    "doc.total",
                    "doc.created_by",
                    omit=("supplier.tax_id", "supplier.address", "doc.delivery_address"),
                ),
            },
            {
                "id": "line_items",
                "type": "table",
                "collection": "items",
                "hidden": _hidden(sections, "line_items"),
                "columns": _columns("no", "description", "quantity", "unit", "unit_rate", "amount"),
            },
            {
                "id": "totals",
                "type": "totals",
                "hidden": _hidden(sections, "totals"),
                "rows": [{"field": "doc.subtotal"}, {"field": "doc.tax"}, {"field": "doc.total_gross"}],
            },
            {
                "id": "terms",
                "type": "fields",
                "layout": "rows",
                "hidden": _hidden(sections, "terms"),
                "fields": _fields(
                    "doc.payment_terms",
                    "doc.retention",
                    "doc.retention_at",
                    "doc.invoice_tolerance",
                    omit=("doc.retention_at",),
                ),
            },
            {
                "id": "supplier_confirmation",
                "type": "section",
                "section": "supplier_confirmation",
                "hidden": _hidden(sections, "supplier_confirmation"),
            },
            {"id": "notes", "type": "section", "section": "notes", "hidden": _hidden(sections, "notes")},
            {
                "id": "signatures",
                "type": "signatures",
                "hidden": _hidden(sections, "signatures"),
                "signers": [{"field": "doc.created_by"}, {"field": "supplier.name"}],
            },
        ]
    )


_PO_FIELDS = (
    MergeField("doc.number", "text", "PO-2026-0142", "document"),
    MergeField("doc.po_type", "text", "Standard", "document"),
    MergeField("doc.issue_date", "date", "01.09.2026", "document"),
    MergeField("doc.delivery_date", "date", "15.09.2026", "document"),
    MergeField("doc.delivery_address", "text", "Riverside Block B, gate 2, 10115 Berlin", "document"),
    MergeField("doc.currency", "text", "EUR", "document"),
    MergeField("doc.subtotal", "money", "40.588,24 €", "document"),
    MergeField("doc.tax", "money", "7.711,76 €", "document"),
    MergeField("doc.total", "money", "48.300,00 €", "document"),
    MergeField("doc.total_gross", "money", "48.300,00 €", "document"),
    MergeField("doc.status", "text", "Issued", "document"),
    MergeField("doc.created_by", "text", "Maria Keller", "sender"),
    MergeField("doc.payment_terms", "text", "30 days net", "document"),
    MergeField("doc.retention", "text", "5 %", "document"),
    MergeField("doc.retention_at", "text", "At invoice", "document"),
    MergeField("doc.invoice_tolerance", "text", "2 %", "document"),
    MergeField("doc.notes", "text", "Deliver to gate B between 7 and 9 am.", "document"),
    MergeField("doc.supplier_reference", "text", "AB-7781", "document"),
    MergeField("doc.confirmed_delivery", "date", "14.09.2026", "document"),
    MergeField("supplier.name", "text", "Baustoffe Nord GmbH", "recipient"),
    MergeField("supplier.tax_id", "text", "DE811111111", "recipient"),
    MergeField("supplier.address", "text", "Hafenweg 3, 20457 Hamburg", "recipient"),
    *COMMON_FIELDS,
)

_PO_COLUMNS = (
    ColumnSpec("no", "No.", "index", right=True, weight=0.5, keep=True),
    ColumnSpec("description", "Description", "text", required=True, weight=4.0, source=_STANDARD),
    ColumnSpec("quantity", "Quantity", "quantity", required=True, right=True, weight=1.0, keep=True, source=_STANDARD),
    ColumnSpec("unit", "Unit", "text", required=True, weight=0.8, keep=True, source=_STANDARD),
    ColumnSpec("unit_rate", "Unit price", "money", required=True, right=True, weight=1.3, keep=True, source=_STANDARD),
    ColumnSpec("amount", "Amount", "money", required=True, right=True, weight=1.5, keep=True, source=_STANDARD),
)


def _sample_po() -> SimpleNamespace:
    item_id = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
    return SimpleNamespace(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        project_id=None,
        vendor_contact_id="Baustoffe Nord GmbH",
        po_number="PO-2026-0142",
        po_type="standard",
        issue_date="2026-09-01",
        delivery_date="2026-09-15",
        currency_code="EUR",
        amount_subtotal="40588.24",
        tax_amount="7711.76",
        amount_total="48300.00",
        retention_percent=Decimal("5.00"),
        retain_on_receipt=False,
        status="draft",
        supplier_acknowledged_at=None,
        supplier_reference="",
        supplier_confirmed_delivery_date=None,
        invoice_tolerance_pct="2",
        invoice_tolerance_abs=None,
        payment_terms="30 days net",
        delivery_address="Riverside Block B, gate 2, 10115 Berlin",
        notes="Deliver to gate B between 7 and 9 am.",
        created_by="Maria Keller",
        items=[
            SimpleNamespace(
                id=item_id,
                description="Ready-mix concrete C30/37",
                quantity="400",
                unit="m3",
                unit_rate="98.50",
                amount="39400.00",
                sort_order=0,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                description="Pump hire, per day",
                quantity="2",
                unit="d",
                unit_rate="594.12",
                amount="1188.24",
                sort_order=1,
            ),
        ],
    )


_SAMPLE_PROJECT = ProjectHeader(name="Riverside Block B", code="RB-B", currency="EUR")


def _po_sample(locale: str) -> LayoutContext:
    from app.modules.procurement.pdf_export import purchase_order_context

    return purchase_order_context(_sample_po(), project=_SAMPLE_PROJECT, locale=locale)


async def _po_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.procurement.models import PurchaseOrder

    stmt = select(PurchaseOrder.id, PurchaseOrder.po_number, PurchaseOrder.issue_date).order_by(
        PurchaseOrder.created_at.desc()
    )
    if project_ids is not None:
        stmt = stmt.where(PurchaseOrder.project_id.in_(project_ids))
    rows = (await session.execute(stmt.limit(50))).all()
    return [(str(i), f"{n} ({d})" if d else str(n)) for i, n, d in rows]


async def _po_context(session: Any, record_id: str, locale: str) -> LayoutContext:
    from app.core.party_names import resolve_party_details, resolve_party_names
    from app.core.register_context import generated_now, load_project_header
    from app.modules.procurement.models import PurchaseOrder
    from app.modules.procurement.pdf_export import purchase_order_context
    from app.modules.procurement.pdf_translations import normalize_pdf_locale, tr

    try:
        po = await session.get(PurchaseOrder, uuid.UUID(str(record_id)))
    except ValueError as exc:
        raise LookupError(record_id) from exc
    if po is None:
        raise LookupError(record_id)
    await session.refresh(po, ["items"])
    project = await load_project_header(session, po.project_id)
    lang = normalize_pdf_locale(locale)
    return purchase_order_context(
        po,
        project=project,
        people=await resolve_party_names(session, [po.vendor_contact_id, po.created_by]),
        parties=await resolve_party_details(session, [po.vendor_contact_id]),
        locale=lang,
        generated=generated_now(tr(lang, "datetime_format"), project),
    )


def _languages() -> tuple[str, ...]:
    from app.modules.procurement.pdf_translations import SUPPORTED_PDF_LOCALES

    langs = tuple(SUPPORTED_PDF_LOCALES)
    return langs if "en" in langs else ("en", *langs)


PURCHASE_ORDER = LayoutSpec(
    key=_PO_KEY,
    module="procurement",
    label="Purchase order",
    appearance_type="purchase_order",
    fields=_PO_FIELDS,
    collections=(CollectionSpec("items", "Line items", _PO_COLUMNS),),
    sections=(
        SectionSpec("order_details", "Order details", required=True, source=_STANDARD),
        SectionSpec("line_items", "Line items", required=True, source=_STANDARD),
        SectionSpec("totals", "Totals", required=True, source=_STANDARD),
        SectionSpec("terms", "Terms"),
        SectionSpec("supplier_confirmation", "Supplier confirmation", builtin=True),
        SectionSpec("notes", "Notes", builtin=True),
        SectionSpec("signatures", "Signatures"),
    ),
    standard=purchase_order_standard,
    sample=_po_sample,
    context=_po_context,
    records=_po_records,
    statuses=("draft", "approved", "issued", "partially_received", "completed", "cancelled"),
    mandatory=(
        MandatoryField(("doc.number",), "PO number", _STANDARD, "purchase order"),
        MandatoryField(("doc.issue_date",), "PO date", _STANDARD, "purchase order"),
        MandatoryField(("supplier.name",), "Supplier", _STANDARD, "purchase order"),
        MandatoryField(("doc.currency",), "Currency", _STANDARD, "purchase order"),
        MandatoryField(("doc.delivery_address",), "Delivery address", _STANDARD, "purchase order"),
    ),
    locked_fields={"supplier.name": _STANDARD, "doc.issue_date": _STANDARD},
)


# ── Goods receipt ────────────────────────────────────────────────────────


def goods_receipt_standard(sections: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """The standard goods receipt, with the sections the workspace switched off hidden."""
    return _template(
        [
            {
                "id": "receipt_details",
                "type": "fields",
                "layout": "pairs",
                "hidden": False,
                "fields": _fields(
                    "doc.po_number",
                    "supplier.name",
                    "supplier.tax_id",
                    "supplier.address",
                    "doc.receipt_date",
                    "doc.received_by",
                    "doc.delivery_note",
                    omit=("supplier.tax_id", "supplier.address"),
                ),
            },
            {
                "id": "line_items",
                "type": "table",
                "collection": "items",
                "hidden": _hidden(sections, "line_items"),
                "columns": _columns("no", "description", "unit", "ordered", "received", "rejected", "batch"),
            },
            {
                "id": "rejections",
                "type": "section",
                "section": "rejections",
                "hidden": _hidden(sections, "rejections"),
            },
            {"id": "notes", "type": "section", "section": "notes", "hidden": _hidden(sections, "notes")},
            {
                "id": "signatures",
                "type": "signatures",
                "hidden": _hidden(sections, "signatures"),
                "signers": [{"field": "supplier.name"}, {"field": "doc.received_by"}],
            },
        ]
    )


_GR_FIELDS = (
    MergeField("doc.number", "text", "DN-77", "document"),
    MergeField("doc.po_number", "text", "PO-2026-0142", "document"),
    MergeField("doc.receipt_date", "date", "14.09.2026", "document"),
    MergeField("doc.received_by", "text", "Maria Keller", "sender"),
    MergeField("doc.delivery_note", "text", "DN-77", "document"),
    MergeField("doc.status", "text", "Confirmed", "document"),
    MergeField("doc.notes", "text", "Two bags torn on arrival.", "document"),
    MergeField("supplier.name", "text", "Baustoffe Nord GmbH", "recipient"),
    MergeField("supplier.tax_id", "text", "DE811111111", "recipient"),
    MergeField("supplier.address", "text", "Hafenweg 3, 20457 Hamburg", "recipient"),
    *COMMON_FIELDS,
)

_GR_COLUMNS = (
    ColumnSpec("no", "No.", "index", right=True, weight=0.5, keep=True),
    ColumnSpec("description", "Description", "text", required=True, weight=3.6, source=_STANDARD),
    ColumnSpec("unit", "Unit", "text", weight=0.8, keep=True),
    ColumnSpec("ordered", "Ordered", "quantity", required=True, right=True, weight=1.1, keep=True, source=_STANDARD),
    ColumnSpec("received", "Received", "quantity", required=True, right=True, weight=1.1, keep=True, source=_STANDARD),
    ColumnSpec("rejected", "Rejected", "quantity", right=True, weight=1.1, keep=True),
    ColumnSpec("batch", "Batch / lot", "text", weight=1.3),
    ColumnSpec("reason", "Rejection reason", "text", weight=2.0),
)


def _gr_sample(locale: str) -> LayoutContext:
    from app.modules.procurement.pdf_export import goods_receipt_context

    po = _sample_po()
    receipt = SimpleNamespace(
        id=uuid.uuid4(),
        po_id=po.id,
        receipt_date="2026-09-14",
        received_by_id="Maria Keller",
        delivery_note_number="DN-77",
        status="confirmed",
        notes="Two bags torn on arrival.",
        items=[
            SimpleNamespace(
                po_item_id=po.items[0].id,
                quantity_ordered="400",
                quantity_received="398",
                quantity_rejected="2",
                rejection_reason="Slump out of tolerance",
                batch_lot="LOT-2209",
            )
        ],
    )
    return goods_receipt_context(receipt, po=po, project=_SAMPLE_PROJECT, locale=locale)


async def _gr_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.procurement.models import GoodsReceipt, PurchaseOrder

    stmt = (
        select(GoodsReceipt.id, PurchaseOrder.po_number, GoodsReceipt.receipt_date, GoodsReceipt.delivery_note_number)
        .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
        .order_by(GoodsReceipt.created_at.desc())
    )
    if project_ids is not None:
        stmt = stmt.where(PurchaseOrder.project_id.in_(project_ids))
    rows = (await session.execute(stmt.limit(50))).all()
    return [(str(i), " · ".join(str(p) for p in (note or n, d) if p)) for i, n, d, note in rows]


async def _gr_context(session: Any, record_id: str, locale: str) -> LayoutContext:
    from app.core.party_names import resolve_party_details, resolve_party_names
    from app.core.register_context import generated_now, load_project_header
    from app.modules.procurement.models import GoodsReceipt, PurchaseOrder
    from app.modules.procurement.pdf_export import goods_receipt_context
    from app.modules.procurement.pdf_translations import normalize_pdf_locale, tr

    try:
        receipt = await session.get(GoodsReceipt, uuid.UUID(str(record_id)))
    except ValueError as exc:
        raise LookupError(record_id) from exc
    if receipt is None:
        raise LookupError(record_id)
    po = await session.get(PurchaseOrder, receipt.po_id)
    if po is None:
        raise LookupError(record_id)
    await session.refresh(receipt, ["items"])
    await session.refresh(po, ["items"])
    project = await load_project_header(session, po.project_id)
    lang = normalize_pdf_locale(locale)
    return goods_receipt_context(
        receipt,
        po=po,
        project=project,
        people=await resolve_party_names(session, [po.vendor_contact_id, receipt.received_by_id]),
        parties=await resolve_party_details(session, [po.vendor_contact_id]),
        locale=lang,
        generated=generated_now(tr(lang, "datetime_format"), project),
    )


GOODS_RECEIPT = LayoutSpec(
    key=_GR_KEY,
    module="procurement",
    label="Goods receipt",
    appearance_type="goods_receipt",
    fields=_GR_FIELDS,
    collections=(CollectionSpec("items", "Received lines", _GR_COLUMNS),),
    sections=(
        SectionSpec("receipt_details", "Receipt details", required=True, source=_STANDARD),
        SectionSpec("line_items", "Line items", required=True, source=_STANDARD),
        SectionSpec("rejections", "Rejections", builtin=True),
        SectionSpec("notes", "Notes", builtin=True),
        SectionSpec("signatures", "Signatures"),
    ),
    standard=goods_receipt_standard,
    sample=_gr_sample,
    context=_gr_context,
    records=_gr_records,
    statuses=("draft", "confirmed"),
    mandatory=(
        MandatoryField(("doc.po_number",), "Purchase order reference", _STANDARD, "goods receipt"),
        MandatoryField(("doc.receipt_date",), "Receipt date", _STANDARD, "goods receipt"),
        MandatoryField(("doc.received_by",), "Received by", _STANDARD, "goods receipt"),
    ),
    locked_fields={"doc.po_number": _STANDARD, "doc.receipt_date": _STANDARD, "doc.received_by": _STANDARD},
)


def register_procurement_layouts() -> None:
    """Register both layouts with the document engine. Idempotent."""
    languages = _languages()
    from dataclasses import replace

    register_layout(replace(PURCHASE_ORDER, languages=languages))
    register_layout(replace(GOODS_RECEIPT, languages=languages))
