# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layouts of the invoice and the payment record.

Each layout declares the merge fields, the line item columns, the sections only
this module draws and what may never be hidden, and ships the standard template
that prints the form exactly as the hand-written form printed it, including the
sections a workspace switched off in its per-type settings.

The invoice uses the field names of the EN 16931 minimum (``doc.date``,
``doc.total_net``, ``recipient.name`` ...) so the country packs' requirements for
``finance.invoice`` apply to it unchanged. Locks are the neutral minimum of any
invoice; packs add their own through ``document_requirements.json``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
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
    "INVOICE",
    "PAYMENT",
    "invoice_standard",
    "payment_standard",
    "register_finance_layouts",
]

_STANDARD = "Platform standard"
_EN16931 = "EN 16931"
_INVOICE_KEY = "finance.invoice"
_PAYMENT_KEY = "finance.payment"


def _hidden(sections: Mapping[str, bool] | None, name: str) -> bool:
    return sections is not None and sections.get(name, True) is False


def _fields(*paths: str, omit: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [{"field": p, **({"omit_empty": True} if p in omit else {})} for p in paths]


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


# ── Invoice ──────────────────────────────────────────────────────────────


def invoice_standard(sections: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """The standard invoice, with the sections the workspace switched off hidden."""
    return _template(
        [
            {
                "id": "invoice_details",
                "type": "fields",
                "layout": "pairs",
                "hidden": False,
                "fields": _fields(
                    "doc.direction",
                    "counterparty.name",
                    "counterparty.tax_id",
                    "counterparty.address",
                    "doc.date",
                    "doc.due_date",
                    "doc.payment_terms",
                    "doc.purchase_order",
                    "doc.invoice_total",
                    omit=("counterparty.tax_id", "counterparty.address"),
                ),
            },
            {
                "id": "line_items",
                "type": "table",
                "collection": "items",
                "hidden": _hidden(sections, "line_items"),
                "columns": [
                    {"id": "no"},
                    {"id": "description"},
                    {"id": "quantity"},
                    {"id": "unit"},
                    {"id": "unit_rate"},
                    {"id": "vat_rate", "omit_empty": True},
                    {"id": "amount"},
                ],
            },
            {
                "id": "totals",
                "type": "totals",
                "hidden": _hidden(sections, "totals"),
                "rows": [
                    {"field": "doc.total_net"},
                    {"field": "doc.total_vat"},
                    {"field": "doc.total_gross"},
                    {"field": "doc.retention", "condition": {"field": "doc.retention", "op": "not_empty"}},
                    {"field": "doc.amount_due", "condition": {"field": "doc.amount_due", "op": "not_empty"}},
                ],
            },
            {"id": "payments", "type": "section", "section": "payments", "hidden": _hidden(sections, "payments")},
            {"id": "notes", "type": "section", "section": "notes", "hidden": _hidden(sections, "notes")},
            {
                "id": "signatures",
                "type": "signatures",
                "hidden": _hidden(sections, "signatures"),
                "signers": [{"field": "doc.created_by"}, {"field": "doc.approved_by"}],
            },
        ]
    )


_INVOICE_FIELDS = (
    MergeField("doc.number", "text", "INV-2026-0042", "document"),
    MergeField("doc.direction", "text", "Receivable", "document"),
    MergeField("doc.date", "date", "20.09.2026", "document"),
    MergeField("doc.due_date", "date", "20.10.2026", "document"),
    MergeField("doc.supply_date", "date", "20.09.2026", "document"),
    MergeField("doc.payment_terms", "text", "30 days", "document"),
    MergeField("doc.purchase_order", "text", "PO-2026-0142", "document"),
    MergeField("doc.currency", "text", "EUR", "document"),
    MergeField("doc.invoice_total", "money", "1.469,14 €", "document"),
    MergeField("doc.total_net", "money", "1.234,57 €", "document"),
    MergeField("doc.total_vat", "money", "234,57 €", "document"),
    MergeField("doc.total_gross", "money", "1.469,14 €", "document"),
    MergeField("doc.retention", "money", "73,96 €", "document"),
    MergeField("doc.amount_due", "money", "1.395,18 €", "document"),
    MergeField("doc.status", "text", "Approved", "document"),
    MergeField("doc.notes", "text", "Quote the invoice number on the transfer.", "document"),
    MergeField("doc.created_by", "text", "Maria Keller", "sender"),
    MergeField("doc.approved_by", "text", "", "sender"),
    MergeField("counterparty.name", "text", "Bau AG", "recipient"),
    MergeField("counterparty.tax_id", "text", "DE987654321", "recipient"),
    MergeField("counterparty.address", "text", "Ring 5, 80331 München", "recipient"),
    MergeField("recipient.name", "text", "Bau AG", "recipient"),
    MergeField("recipient.address", "text", "Ring 5, 80331 München", "recipient"),
    MergeField("recipient.vat_id", "text", "DE987654321", "recipient"),
    *COMMON_FIELDS,
)

_INVOICE_COLUMNS = (
    ColumnSpec("no", "No.", "index", right=True, weight=0.5, keep=True),
    ColumnSpec("description", "Description", "text", required=True, weight=3.8, source=_EN16931),
    ColumnSpec("quantity", "Quantity", "quantity", required=True, right=True, weight=1.0, keep=True, source=_EN16931),
    ColumnSpec("unit", "Unit", "text", required=True, weight=0.8, keep=True, source=_EN16931),
    ColumnSpec("unit_rate", "Unit price", "money", required=True, right=True, weight=1.3, keep=True, source=_EN16931),
    ColumnSpec("vat_rate", "VAT", "percent", required=True, right=True, weight=0.8, keep=True, source=_EN16931),
    ColumnSpec("amount", "Net amount", "money", required=True, right=True, weight=1.5, keep=True, source=_EN16931),
)

_SAMPLE_PROJECT = ProjectHeader(name="Riverside Block B", code="RB-B", currency="EUR")


def _sample_payment(**over: Any) -> SimpleNamespace:
    record = SimpleNamespace(
        id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000006"),
        invoice_id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
        payment_date="2026-10-01",
        amount=Decimal("1395.18"),
        currency_code="EUR",
        exchange_rate_snapshot=Decimal("1"),
        reference="SEPA-55012",
        is_refund=False,
        withholding_amount=Decimal("73.96"),
        withholding_release_date="2027-10-01",
    )
    for key, value in over.items():
        setattr(record, key, value)
    return record


def _sample_invoice() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("eeeeeeee-0000-0000-0000-000000000005"),
        project_id=None,
        contact_id="Bau AG",
        invoice_direction="receivable",
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
        created_by="Maria Keller",
        metadata_={},
        line_items=[
            SimpleNamespace(
                description="Ready-mix concrete C30/37",
                quantity=Decimal("12.5"),
                unit="m3",
                unit_rate=Decimal("98.7656"),
                amount=Decimal("1234.57"),
                vat_rate=Decimal("19"),
                vat_category="S",
                sort_order=0,
            )
        ],
        payments=[_sample_payment()],
    )


def _invoice_sample(locale: str) -> LayoutContext:
    from app.modules.finance.pdf_export import invoice_context

    return invoice_context(
        _sample_invoice(), project=_SAMPLE_PROJECT, purchase_order_number="PO-2026-0142", locale=locale
    )


async def _invoice_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.finance.models import Invoice

    stmt = select(Invoice.id, Invoice.invoice_number, Invoice.invoice_date).order_by(Invoice.created_at.desc())
    if project_ids is not None:
        stmt = stmt.where(Invoice.project_id.in_(project_ids))
    rows = (await session.execute(stmt.limit(50))).all()
    return [(str(i), f"{n} ({d})" if d else str(n)) for i, n, d in rows]


async def load_invoice(session: Any, record_id: Any) -> Any:
    """The invoice with its lines and payments, or ``LookupError``."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.modules.finance.models import Invoice

    try:
        key = uuid.UUID(str(record_id))
    except ValueError as exc:
        raise LookupError(record_id) from exc
    invoice = (
        await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items), selectinload(Invoice.payments))
            .where(Invoice.id == key)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise LookupError(record_id)
    return invoice


async def invoice_po_number(session: Any, invoice: Any) -> str | None:
    """Number of the purchase order the invoice bills, when it is linked to one."""
    if getattr(invoice, "purchase_order_id", None) is None:
        return None
    from sqlalchemy import select

    from app.modules.procurement.models import PurchaseOrder

    try:
        return (
            await session.execute(select(PurchaseOrder.po_number).where(PurchaseOrder.id == invoice.purchase_order_id))
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - procurement may be absent; the form prints a dash
        return None


async def invoice_layout_context(session: Any, invoice: Any, locale: str) -> LayoutContext:
    """One stored invoice's layout context, names and party details resolved."""
    from app.core.party_names import resolve_party_details, resolve_party_names
    from app.core.register_context import generated_now, load_project_header
    from app.modules.finance.pdf_export import invoice_context
    from app.modules.finance.pdf_translations import normalize_pdf_locale, tr

    project = await load_project_header(session, invoice.project_id)
    lang = normalize_pdf_locale(locale)
    return invoice_context(
        invoice,
        project=project,
        people=await resolve_party_names(session, [invoice.contact_id, invoice.created_by]),
        parties=await resolve_party_details(session, [invoice.contact_id]),
        purchase_order_number=await invoice_po_number(session, invoice),
        locale=lang,
        generated=generated_now(tr(lang, "datetime_format"), project),
    )


async def _invoice_context(session: Any, record_id: str, locale: str) -> LayoutContext:
    return await invoice_layout_context(session, await load_invoice(session, record_id), locale)


INVOICE = LayoutSpec(
    key=_INVOICE_KEY,
    module="finance",
    label="Invoice",
    appearance_type="invoice",
    fields=_INVOICE_FIELDS,
    collections=(CollectionSpec("items", "Line items", _INVOICE_COLUMNS),),
    sections=(
        SectionSpec("invoice_details", "Invoice details", required=True, source=_EN16931),
        SectionSpec("line_items", "Line items", required=True, source=_EN16931),
        SectionSpec("totals", "Totals", required=True, source=_EN16931),
        SectionSpec("payments", "Payments", builtin=True),
        SectionSpec("notes", "Notes", builtin=True),
        SectionSpec("signatures", "Signatures"),
    ),
    standard=invoice_standard,
    sample=_invoice_sample,
    context=_invoice_context,
    records=_invoice_records,
    statuses=("draft", "pending", "approved", "paid", "partially_paid", "overdue", "cancelled"),
    mandatory=(
        MandatoryField(("doc.number",), "Invoice number", _EN16931, "invoice"),
        MandatoryField(("doc.date",), "Invoice date", _EN16931, "invoice"),
        MandatoryField(("doc.currency",), "Currency", _EN16931, "invoice"),
        MandatoryField(("counterparty.name",), "Counterparty", _EN16931, "invoice"),
        MandatoryField(("doc.due_date", "doc.payment_terms"), "Due date or payment terms", _EN16931, "invoice"),
    ),
    locked_fields={
        "counterparty.name": _EN16931,
        "doc.date": _EN16931,
        "doc.due_date": _EN16931,
        "doc.invoice_total": _EN16931,
    },
)


# ── Payment ──────────────────────────────────────────────────────────────


def payment_standard(sections: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """The standard payment record, with the sections the workspace switched off hidden."""
    return _template(
        [
            {
                "id": "payment_details",
                "type": "fields",
                "layout": "pairs",
                "hidden": False,
                "fields": _fields(
                    "doc.payment_date",
                    "doc.amount_paid",
                    "doc.kind",
                    "doc.reference",
                    "doc.exchange_rate",
                    omit=("doc.exchange_rate",),
                ),
            },
            {
                "id": "invoice",
                "type": "fields",
                "layout": "pairs",
                "hidden": _hidden(sections, "invoice"),
                "fields": _fields(
                    "invoice.number",
                    "invoice.date",
                    "counterparty.name",
                    "counterparty.tax_id",
                    "counterparty.address",
                    "invoice.total",
                    omit=("counterparty.tax_id", "counterparty.address"),
                ),
            },
            {
                "id": "withholding",
                "type": "section",
                "section": "withholding",
                "hidden": _hidden(sections, "withholding"),
            },
            {
                "id": "signatures",
                "type": "signatures",
                "hidden": _hidden(sections, "signatures"),
                "signers": [{"field": "doc.prepared_by"}, {"field": "doc.approved_by"}],
            },
        ]
    )


_PAYMENT_FIELDS = (
    MergeField("doc.number", "text", "SEPA-55012", "document"),
    MergeField("doc.payment_date", "date", "01.10.2026", "document"),
    MergeField("doc.amount_paid", "money", "1.395,18 €", "document"),
    MergeField("doc.kind", "text", "Payment", "document"),
    MergeField("doc.reference", "text", "SEPA-55012", "document"),
    MergeField("doc.exchange_rate", "quantity", "", "document"),
    MergeField("doc.currency", "text", "EUR", "document"),
    MergeField("doc.withheld", "money", "73,96 €", "document"),
    MergeField("doc.release_date", "date", "01.10.2027", "document"),
    MergeField("doc.prepared_by", "text", "", "sender"),
    MergeField("doc.approved_by", "text", "", "sender"),
    MergeField("invoice.number", "text", "INV-2026-0042", "document"),
    MergeField("invoice.date", "date", "20.09.2026", "document"),
    MergeField("invoice.total", "money", "1.469,14 €", "document"),
    MergeField("counterparty.name", "text", "Bau AG", "recipient"),
    MergeField("counterparty.tax_id", "text", "DE987654321", "recipient"),
    MergeField("counterparty.address", "text", "Ring 5, 80331 München", "recipient"),
    *COMMON_FIELDS,
)


def _payment_sample(locale: str) -> LayoutContext:
    from app.modules.finance.pdf_export import payment_context

    return payment_context(_sample_payment(), invoice=_sample_invoice(), project=_SAMPLE_PROJECT, locale=locale)


async def _payment_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.finance.models import Invoice, Payment

    stmt = (
        select(Payment.id, Invoice.invoice_number, Payment.payment_date, Payment.reference)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .order_by(Payment.created_at.desc())
    )
    if project_ids is not None:
        stmt = stmt.where(Invoice.project_id.in_(project_ids))
    rows = (await session.execute(stmt.limit(50))).all()
    return [(str(i), " · ".join(str(p) for p in (ref or n, d) if p)) for i, n, d, ref in rows]


async def payment_layout_context(session: Any, payment: Any, invoice: Any, locale: str) -> LayoutContext:
    """One stored payment's layout context, names and party details resolved."""
    from app.core.party_names import resolve_party_details, resolve_party_names
    from app.core.register_context import generated_now, load_project_header
    from app.modules.finance.pdf_export import payment_context
    from app.modules.finance.pdf_translations import normalize_pdf_locale, tr

    project = await load_project_header(session, invoice.project_id)
    lang = normalize_pdf_locale(locale)
    return payment_context(
        payment,
        invoice=invoice,
        project=project,
        people=await resolve_party_names(session, [invoice.contact_id]),
        parties=await resolve_party_details(session, [invoice.contact_id]),
        locale=lang,
        generated=generated_now(tr(lang, "datetime_format"), project),
    )


async def _payment_context(session: Any, record_id: str, locale: str) -> LayoutContext:
    from app.modules.finance.models import Invoice, Payment

    try:
        payment = await session.get(Payment, uuid.UUID(str(record_id)))
    except ValueError as exc:
        raise LookupError(record_id) from exc
    invoice = await session.get(Invoice, payment.invoice_id) if payment is not None else None
    if payment is None or invoice is None:
        raise LookupError(record_id)
    return await payment_layout_context(session, payment, invoice, locale)


PAYMENT = LayoutSpec(
    key=_PAYMENT_KEY,
    module="finance",
    label="Payment record",
    appearance_type="payment",
    fields=_PAYMENT_FIELDS,
    collections=(),
    sections=(
        SectionSpec("payment_details", "Payment details", required=True, source=_STANDARD),
        SectionSpec("invoice", "Invoice"),
        SectionSpec("withholding", "Withholding", builtin=True),
        SectionSpec("signatures", "Signatures"),
    ),
    standard=payment_standard,
    sample=_payment_sample,
    context=_payment_context,
    records=_payment_records,
    statuses=("completed", "refunded"),
    mandatory=(
        MandatoryField(("doc.payment_date",), "Payment date", _STANDARD, "payment"),
        MandatoryField(("invoice.number",), "Invoice number", _STANDARD, "payment"),
    ),
    locked_fields={"doc.payment_date": _STANDARD, "doc.amount_paid": _STANDARD},
)


def _languages() -> tuple[str, ...]:
    from app.modules.finance.pdf_translations import SUPPORTED_PDF_LOCALES

    langs = tuple(SUPPORTED_PDF_LOCALES)
    return langs if "en" in langs else ("en", *langs)


def register_finance_layouts() -> None:
    """Register both layouts with the document engine. Idempotent."""
    languages = _languages()
    register_layout(replace(INVOICE, languages=languages))
    register_layout(replace(PAYMENT, languages=languages))
