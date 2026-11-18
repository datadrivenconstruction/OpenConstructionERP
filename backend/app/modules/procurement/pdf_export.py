# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed purchase order and the printed goods receipt.

A purchase order is what goes to the supplier: who orders what, at which
rate, by when, on which terms. A goods receipt is the delivery record signed
at the gate: what was ordered, what arrived, what was turned away and why.

Amounts are printed exactly as the order stores them. The net amount, the
tax and the total are three stored fields, written to the page as they are,
never derived from one another here: a form that recomputes the tax from the
net prints a second opinion next to the books, and once printed a total with
the tax added on top of a total that already carried it. Amounts stay
``Decimal`` (the order stores them as decimal strings) from the row to the
page and are written in the separators of the project's market.

The form is a document layout (:mod:`app.core.doc_templates.layout`): the
context builders here turn a record into formatted values, rows and the two
sections only this module draws (the supplier confirmation, the rejections);
:mod:`app.modules.procurement.layouts` holds the standard template that
reproduces the form as it always printed, and a firm's published template
rearranges, rewords or extends it. The workspace's per-type section switches
(:func:`app.core.pdf_appearance.resolve_sections`) still hide sections of the
standard template.

The builders are pure, like :mod:`app.modules.changeorders.pdf_export`.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.doc_templates.layout.spec import LayoutContext
from app.core.party_names import PartyDetails
from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    build_record_pdf,
    caps,
    format_amount,
    format_quantity,
    format_stored_date,
    person_name,
    printed_currency,
)
from app.modules.procurement.pdf_translations import (
    CATALOGUE,
    DEFAULT_PDF_LOCALE,
    goods_receipt_pdf_filename,
    normalize_pdf_locale,
    purchase_order_pdf_filename,
    tr,
)

__all__ = [
    "build_goods_receipt_pdf",
    "build_purchase_order_pdf",
    "goods_receipt_context",
    "goods_receipt_record",
    "purchase_order_context",
    "purchase_order_record",
]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _amount_header(locale: str, currency: str) -> str:
    """The amount column heading, with the currency every row of it is in."""
    label = tr(locale, "col_amount")
    return f"{label} ({printed_currency(currency, locale)})" if currency else label


def _nonzero(value: Any) -> bool:
    """Whether a stored number is present and not zero."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return False
    return number.is_finite() and number != 0


def _with_unit(quantity: str, unit: str) -> str:
    return quantity if unit == EMPTY else f"{quantity} {unit}"


def _percent(value: Any, style: Any) -> str:
    text = format_quantity(value, style, least=0, most=2)
    return EMPTY if text == EMPTY else f"{text} %"


def _dec(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _formatter(style: Any, date_format: str) -> Any:
    """``(format, raw) -> text`` in the project's number style, for computed and reformatted columns."""

    def _format(fmt: str, value: Any) -> str:
        if value is None or value == "":
            return EMPTY
        if fmt == "money":
            return format_amount(value, style)
        if fmt in {"quantity", "number"}:
            return format_quantity(value, style)
        if fmt == "percent":
            return _percent(value, style)
        if fmt == "date":
            return format_stored_date(value, date_format)
        return _text(value) or EMPTY

    return _format


def _base_values(project: ProjectHeader, generated: str) -> dict[str, str]:
    from app.core.doc_templates.seller import resolve_seller

    return {
        **resolve_seller().as_fields(),
        "project.name": project.name or "",
        "project.code": project.code or "",
        "project.label": project.label,
        "doc.generated": generated,
    }


def purchase_order_context(
    po: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> LayoutContext:
    """One purchase order's data for its document layout, formatted in the document language.

    Args:
        po: The purchase order row with its ``items`` loaded, or any object
            with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the supplier contact
            and the user who prepared the order.
        parties: The supplier's tax id and address keyed by ``str(id)``, from
            :func:`app.core.party_names.resolve_party_details`.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    currency = _text(getattr(po, "currency_code", None)).upper() or project.currency

    def _money(name: str) -> str:
        return format_amount(getattr(po, name, None), style, currency, locale=locale)

    def _date(name: str) -> str:
        return format_stored_date(getattr(po, name, None), date_format)

    supplier = person_name(getattr(po, "vendor_contact_id", None), people)
    preparer = person_name(getattr(po, "created_by", None), people)
    details = _party(po, parties)
    retention = getattr(po, "retention_percent", None)
    retention_at = ""
    if retention is not None and _nonzero(retention):
        at = "retention_at_receipt" if getattr(po, "retain_on_receipt", False) else "retention_at_invoice"
        retention_at = tr(locale, at)
    tolerance = [
        part
        for part in (
            _percent(getattr(po, "invoice_tolerance_pct", None), style),
            format_amount(getattr(po, "invoice_tolerance_abs", None), style, currency, locale=locale),
        )
        if part != EMPTY
    ]
    status_code = getattr(po, "status", None) or "draft"
    status = CATALOGUE.label("po_status", status_code, locale)
    values = {
        **_base_values(project, generated),
        "doc.number": _text(getattr(po, "po_number", None)),
        "doc.po_type": CATALOGUE.label("po_type", getattr(po, "po_type", None), locale),
        "doc.issue_date": _date("issue_date"),
        "doc.delivery_date": _date("delivery_date"),
        "doc.currency": currency,
        "doc.subtotal": _money("amount_subtotal"),
        "doc.tax": _money("tax_amount"),
        "doc.total": _money("amount_total"),
        "doc.total_gross": _money("amount_total"),
        "doc.status": status,
        "doc.created_by": preparer,
        "doc.payment_terms": _text(getattr(po, "payment_terms", None)) or EMPTY,
        "doc.retention": _percent(retention, style),
        "doc.retention_at": retention_at,
        "doc.invoice_tolerance": " / ".join(tolerance) or EMPTY,
        "doc.notes": _text(getattr(po, "notes", None)),
        "doc.supplier_reference": _text(getattr(po, "supplier_reference", None)),
        "doc.confirmed_delivery": _date("supplier_confirmed_delivery_date"),
        "supplier.name": supplier,
        "supplier.tax_id": details.tax_id if details else "",
        "supplier.address": details.address if details else "",
    }
    raw = {
        "doc.number": values["doc.number"] or None,
        "doc.po_type": getattr(po, "po_type", None),
        "doc.issue_date": getattr(po, "issue_date", None),
        "doc.delivery_date": getattr(po, "delivery_date", None),
        "doc.currency": currency or None,
        "doc.subtotal": _dec(getattr(po, "amount_subtotal", None)),
        "doc.tax": _dec(getattr(po, "tax_amount", None)),
        "doc.total": _dec(getattr(po, "amount_total", None)),
        "doc.total_gross": _dec(getattr(po, "amount_total", None)),
        "doc.status": status_code,
        "doc.retention": _dec(retention) if retention is not None else None,
        "doc.payment_terms": _text(getattr(po, "payment_terms", None)) or None,
        "doc.notes": _text(getattr(po, "notes", None)) or None,
        "doc.acknowledged": bool(getattr(po, "supplier_acknowledged_at", None)),
        "supplier.name": None if supplier == EMPTY else supplier,
        "supplier.tax_id": (details.tax_id if details else "") or None,
        "supplier.address": (details.address if details else "") or None,
        "project.name": project.name or None,
    }
    items = sorted(getattr(po, "items", None) or [], key=lambda item: getattr(item, "sort_order", 0) or 0)
    rows = [
        {
            "description": (getattr(item, "description", None), _text(getattr(item, "description", None)) or EMPTY),
            "quantity": (
                _dec(getattr(item, "quantity", None)),
                format_quantity(getattr(item, "quantity", None), style),
            ),
            "unit": (getattr(item, "unit", None), _text(getattr(item, "unit", None)) or EMPTY),
            "unit_rate": (
                _dec(getattr(item, "unit_rate", None)),
                format_quantity(getattr(item, "unit_rate", None), style, least=2),
            ),
            "amount": (_dec(getattr(item, "amount", None)), format_amount(getattr(item, "amount", None), style)),
        }
        for item in items
    ]
    sections: dict[str, list[RecordBlock]] = {}
    if getattr(po, "supplier_acknowledged_at", None):
        sections["supplier_confirmation"] = [
            RecordBlock(
                tr(locale, "supplier_confirmation"),
                kind="grid",
                rows=[
                    [tr(locale, "supplier_reference"), _text(getattr(po, "supplier_reference", None)) or EMPTY],
                    [tr(locale, "confirmed_delivery"), _date("supplier_confirmed_delivery_date")],
                    [tr(locale, "acknowledged_on"), _date("supplier_acknowledged_at")],
                ],
            )
        ]
    else:
        sections["supplier_confirmation"] = [
            RecordBlock(tr(locale, "supplier_confirmation"), text=tr(locale, "not_confirmed"))
        ]
    sections["notes"] = [
        RecordBlock(tr(locale, "notes"), text=_text(getattr(po, "notes", None)), empty_text=tr(locale, "no_notes"))
    ]
    labels = {
        "field:supplier.name": tr(locale, "supplier"),
        "field:supplier.tax_id": tr(locale, "counterparty_tax_id"),
        "field:supplier.address": tr(locale, "counterparty_address"),
        "field:doc.po_type": tr(locale, "po_type"),
        "field:doc.issue_date": tr(locale, "issue_date"),
        "field:doc.delivery_date": tr(locale, "delivery_date"),
        "field:doc.total": tr(locale, "order_total"),
        "field:doc.created_by": tr(locale, "created_by"),
        "field:doc.subtotal": tr(locale, "subtotal"),
        "field:doc.tax": tr(locale, "tax"),
        "field:doc.total_gross": tr(locale, "total_gross"),
        "field:doc.payment_terms": tr(locale, "payment_terms"),
        "field:doc.retention": tr(locale, "retention"),
        "field:doc.retention_at": tr(locale, "retention_at"),
        "field:doc.invoice_tolerance": tr(locale, "invoice_tolerance"),
        "field:doc.supplier_reference": tr(locale, "supplier_reference"),
        "field:doc.confirmed_delivery": tr(locale, "confirmed_delivery"),
        "column:items.no": tr(locale, "col_no"),
        "column:items.description": tr(locale, "col_description"),
        "column:items.quantity": tr(locale, "col_quantity"),
        "column:items.unit": tr(locale, "col_unit"),
        "column:items.unit_rate": tr(locale, "col_unit_rate"),
        "column:items.amount": _amount_header(locale, currency),
        "section:line_items": tr(locale, "line_items"),
        "empty:line_items": tr(locale, "no_line_items"),
        "section:totals": tr(locale, "totals"),
        "section:terms": tr(locale, "terms"),
        "section:signatures": tr(locale, "signatures"),
        "signer:doc.created_by": tr(locale, "sig_ordered_by"),
        "signer:supplier.name": tr(locale, "supplier"),
        "subtotal": tr(locale, "subtotal"),
    }
    base = RecordDocument(
        title=tr(locale, "po_title"),
        number=_text(getattr(po, "po_number", None)),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=f"{tr(locale, 'supplier')}: {supplier}",
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="purchase_order",
    )
    return LayoutContext(
        locale=locale,
        values=values,
        raw=raw,
        labels=labels,
        collections={"items": rows},
        sections=sections,
        base=base,
        status=str(status_code).lower(),
        format=_formatter(style, date_format),
        signature_rows=lambda signers: CATALOGUE.signature_rows(locale, list(signers)),
        project_id=getattr(po, "project_id", None),
        filename=purchase_order_pdf_filename(getattr(po, "po_number", None)),
        empty=EMPTY,
    )


def _party(po: Any, parties: Mapping[str, PartyDetails] | None) -> PartyDetails | None:
    contact = getattr(po, "vendor_contact_id", None)
    if contact is None or not parties:
        return None
    return parties.get(str(contact).strip())


def purchase_order_record(
    po: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    sections: Mapping[str, bool] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    template: Mapping[str, Any] | None = None,
) -> RecordDocument:
    """Describe the printable form of one purchase order.

    Args:
        po: The purchase order row with its ``items`` loaded.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        parties: The supplier's tax id and address keyed by ``str(id)``.
        sections: ``{section: printed}`` from
            :func:`app.core.pdf_appearance.resolve_sections`; ``None`` prints
            every section. Read only when no ``template`` is given.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        template: A published document layout; the standard one when ``None``.

    Returns:
        The form, ready for the PDF renderer.
    """
    from app.core.doc_templates.layout.compile import compile_layout
    from app.modules.procurement.layouts import PURCHASE_ORDER, purchase_order_standard

    ctx = purchase_order_context(
        po, project=project, people=people, parties=parties, locale=locale, generated=generated
    )
    return compile_layout(template or purchase_order_standard(sections), PURCHASE_ORDER, ctx)


def build_purchase_order_pdf(po: Any, **context: Any) -> bytes:
    """Render one purchase order as a PDF form; see :func:`purchase_order_record`."""
    return build_record_pdf(purchase_order_record(po, **context))


def goods_receipt_context(
    receipt: Any,
    *,
    po: Any,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> LayoutContext:
    """One goods receipt's data for its document layout, formatted in the document language.

    Args:
        receipt: The goods receipt row with its ``items`` loaded.
        po: The purchase order it was received against, with its ``items``,
            which carry the descriptions and units the receipt lines point at.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        parties: The supplier's tax id and address keyed by ``str(id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    po_number = _text(getattr(po, "po_number", None))
    supplier = person_name(getattr(po, "vendor_contact_id", None), people)
    receiver = person_name(getattr(receipt, "received_by_id", None), people)
    delivery_note = _text(getattr(receipt, "delivery_note_number", None))
    details = _party(po, parties)
    ordered_items = {str(getattr(item, "id", "")): item for item in getattr(po, "items", None) or []}

    lines = []
    for item in getattr(receipt, "items", None) or []:
        ordered = ordered_items.get(str(getattr(item, "po_item_id", "") or ""))
        lines.append(
            (
                _text(getattr(ordered, "description", None)) or EMPTY,
                _text(getattr(ordered, "unit", None)) or EMPTY,
                item,
            )
        )
    rows = [
        {
            "description": (description, description),
            "unit": (unit, unit),
            "ordered": (
                _dec(getattr(item, "quantity_ordered", None)),
                format_quantity(getattr(item, "quantity_ordered", None), style),
            ),
            "received": (
                _dec(getattr(item, "quantity_received", None)),
                format_quantity(getattr(item, "quantity_received", None), style),
            ),
            "rejected": (
                _dec(getattr(item, "quantity_rejected", None)),
                format_quantity(getattr(item, "quantity_rejected", None), style),
            ),
            "batch": (getattr(item, "batch_lot", None), _text(getattr(item, "batch_lot", None)) or EMPTY),
            "reason": (
                getattr(item, "rejection_reason", None),
                _text(getattr(item, "rejection_reason", None)) or EMPTY,
            ),
        }
        for description, unit, item in lines
    ]
    rejected = [
        (description, unit, item)
        for description, unit, item in lines
        if _nonzero(getattr(item, "quantity_rejected", None))
    ]
    sections: dict[str, list[RecordBlock]] = {}
    if rejected:
        table = [[tr(locale, "col_description"), tr(locale, "col_rejected"), tr(locale, "col_reason")]]
        table.extend(
            [
                description,
                _with_unit(format_quantity(getattr(item, "quantity_rejected", None), style), unit),
                _text(getattr(item, "rejection_reason", None)) or EMPTY,
            ]
            for description, unit, item in rejected
        )
        sections["rejections"] = [
            RecordBlock(
                tr(locale, "rejections"),
                kind="table",
                rows=table,
                weights=[3.0, 1.2, 3.0],
                right_aligned=[False, True, False],
            )
        ]
    else:
        sections["rejections"] = [RecordBlock(tr(locale, "rejections"), text=tr(locale, "no_rejections"))]
    sections["notes"] = [
        RecordBlock(tr(locale, "notes"), text=_text(getattr(receipt, "notes", None)), empty_text=tr(locale, "no_notes"))
    ]
    status_code = getattr(receipt, "status", None) or "draft"
    status = CATALOGUE.label("gr_status", status_code, locale)
    values = {
        **_base_values(project, generated),
        "doc.number": delivery_note or po_number,
        "doc.po_number": po_number or EMPTY,
        "doc.receipt_date": format_stored_date(getattr(receipt, "receipt_date", None), date_format),
        "doc.received_by": receiver,
        "doc.delivery_note": delivery_note or EMPTY,
        "doc.status": status,
        "doc.notes": _text(getattr(receipt, "notes", None)),
        "supplier.name": supplier,
        "supplier.tax_id": details.tax_id if details else "",
        "supplier.address": details.address if details else "",
    }
    raw = {
        "doc.number": (delivery_note or po_number) or None,
        "doc.po_number": po_number or None,
        "doc.receipt_date": getattr(receipt, "receipt_date", None),
        "doc.received_by": None if receiver == EMPTY else receiver,
        "doc.delivery_note": delivery_note or None,
        "doc.status": status_code,
        "doc.notes": _text(getattr(receipt, "notes", None)) or None,
        "doc.has_rejections": bool(rejected),
        "supplier.name": None if supplier == EMPTY else supplier,
        "supplier.tax_id": (details.tax_id if details else "") or None,
        "supplier.address": (details.address if details else "") or None,
        "project.name": project.name or None,
    }
    labels = {
        "field:doc.po_number": tr(locale, "purchase_order"),
        "field:supplier.name": tr(locale, "supplier"),
        "field:supplier.tax_id": tr(locale, "counterparty_tax_id"),
        "field:supplier.address": tr(locale, "counterparty_address"),
        "field:doc.receipt_date": tr(locale, "receipt_date"),
        "field:doc.received_by": tr(locale, "received_by"),
        "field:doc.delivery_note": tr(locale, "delivery_note"),
        "column:items.no": tr(locale, "col_no"),
        "column:items.description": tr(locale, "col_description"),
        "column:items.unit": tr(locale, "col_unit"),
        "column:items.ordered": tr(locale, "col_ordered"),
        "column:items.received": tr(locale, "col_received"),
        "column:items.rejected": tr(locale, "col_rejected"),
        "column:items.batch": tr(locale, "col_batch"),
        "column:items.reason": tr(locale, "col_reason"),
        "section:line_items": tr(locale, "line_items"),
        "empty:line_items": tr(locale, "no_line_items"),
        "section:signatures": tr(locale, "signatures"),
        "signer:supplier.name": tr(locale, "sig_delivered_by"),
        "signer:doc.received_by": tr(locale, "received_by"),
        "subtotal": tr(locale, "subtotal"),
    }
    base = RecordDocument(
        title=tr(locale, "gr_title"),
        number=delivery_note or po_number,
        project_label=project.label,
        status_text=caps(status, locale),
        subject=" · ".join(part for part in (f"{tr(locale, 'purchase_order')} {po_number}".strip(), supplier) if part),
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="goods_receipt",
    )
    return LayoutContext(
        locale=locale,
        values=values,
        raw=raw,
        labels=labels,
        collections={"items": rows},
        sections=sections,
        base=base,
        status=str(status_code).lower(),
        format=_formatter(style, date_format),
        signature_rows=lambda signers: CATALOGUE.signature_rows(locale, list(signers)),
        project_id=getattr(po, "project_id", None),
        filename=goods_receipt_pdf_filename(po_number, delivery_note),
        empty=EMPTY,
    )


def goods_receipt_record(
    receipt: Any,
    *,
    po: Any,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    sections: Mapping[str, bool] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    template: Mapping[str, Any] | None = None,
) -> RecordDocument:
    """Describe the printable form of one goods receipt.

    Args:
        receipt: The goods receipt row with its ``items`` loaded.
        po: The purchase order it was received against, with its ``items``.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        parties: The supplier's tax id and address keyed by ``str(id)``.
        sections: ``{section: printed}``; ``None`` prints every section. Read only without ``template``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        template: A published document layout; the standard one when ``None``.

    Returns:
        The form, ready for the PDF renderer.
    """
    from app.core.doc_templates.layout.compile import compile_layout
    from app.modules.procurement.layouts import GOODS_RECEIPT, goods_receipt_standard

    ctx = goods_receipt_context(
        receipt, po=po, project=project, people=people, parties=parties, locale=locale, generated=generated
    )
    return compile_layout(template or goods_receipt_standard(sections), GOODS_RECEIPT, ctx)


def build_goods_receipt_pdf(receipt: Any, **context: Any) -> bytes:
    """Render one goods receipt as a PDF form; see :func:`goods_receipt_record`."""
    return build_record_pdf(goods_receipt_record(receipt, **context))
