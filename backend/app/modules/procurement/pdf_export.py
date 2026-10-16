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

Which sections print is the workspace's choice per document type (see
:func:`app.core.pdf_appearance.resolve_sections`); the builders take the
answer as a mapping and print every section it does not switch off.

The builders are pure, like :mod:`app.modules.changeorders.pdf_export`. The
layout is the shared record form in :mod:`app.core.register_export`.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.party_names import PartyDetails, party_detail_pairs
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
    grid_rows,
    person_name,
    printed_currency,
)
from app.modules.procurement.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_goods_receipt_pdf",
    "build_purchase_order_pdf",
    "goods_receipt_record",
    "purchase_order_record",
]


def _shown(sections: Mapping[str, bool] | None, name: str) -> bool:
    """Whether ``name`` prints. A section nobody switched off prints."""
    return True if sections is None else sections.get(name, True) is not False


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


def _supplier_details(po: Any, parties: Mapping[str, PartyDetails] | None, locale: str) -> list[tuple[str, str]]:
    """The supplier's tax id and address rows, where the contact has them."""
    return party_detail_pairs(
        getattr(po, "vendor_contact_id", None),
        parties,
        tr(locale, "counterparty_tax_id"),
        tr(locale, "counterparty_address"),
    )


def purchase_order_record(
    po: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    sections: Mapping[str, bool] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RecordDocument:
    """Describe the printable form of one purchase order.

    Args:
        po: The purchase order row with its ``items`` loaded, or any object
            with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the supplier contact
            and the user who prepared the order.
        parties: The supplier's tax id and address keyed by ``str(id)``, from
            :func:`app.core.party_names.resolve_party_details`.
        sections: ``{section: printed}`` from
            :func:`app.core.pdf_appearance.resolve_sections`; ``None`` prints
            every section.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The form, ready for the PDF renderer.
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
    grid = grid_rows(
        [
            (tr(locale, "supplier"), supplier),
            *_supplier_details(po, parties, locale),
            (tr(locale, "po_type"), CATALOGUE.label("po_type", getattr(po, "po_type", None), locale)),
            (tr(locale, "issue_date"), _date("issue_date")),
            (tr(locale, "delivery_date"), _date("delivery_date")),
            (tr(locale, "order_total"), _money("amount_total")),
            (tr(locale, "created_by"), preparer),
        ]
    )

    blocks: list[RecordBlock] = []
    if _shown(sections, "line_items"):
        items = sorted(getattr(po, "items", None) or [], key=lambda item: getattr(item, "sort_order", 0) or 0)
        if items:
            rows = [
                [
                    tr(locale, "col_no"),
                    tr(locale, "col_description"),
                    tr(locale, "col_quantity"),
                    tr(locale, "col_unit"),
                    tr(locale, "col_unit_rate"),
                    _amount_header(locale, currency),
                ]
            ]
            for index, item in enumerate(items, start=1):
                rows.append(
                    [
                        str(index),
                        _text(getattr(item, "description", None)) or EMPTY,
                        format_quantity(getattr(item, "quantity", None), style),
                        _text(getattr(item, "unit", None)) or EMPTY,
                        format_quantity(getattr(item, "unit_rate", None), style, least=2),
                        format_amount(getattr(item, "amount", None), style),
                    ]
                )
            blocks.append(
                RecordBlock(
                    tr(locale, "line_items"),
                    kind="table",
                    rows=rows,
                    weights=[0.5, 4.0, 1.0, 0.8, 1.3, 1.5],
                    right_aligned=[True, False, True, False, True, True],
                    keep_together=[True, False, True, True, True, True],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "line_items"), empty_text=tr(locale, "no_line_items")))
    if _shown(sections, "totals"):
        blocks.append(
            RecordBlock(
                tr(locale, "totals"),
                kind="grid",
                rows=[
                    [tr(locale, "subtotal"), _money("amount_subtotal")],
                    [tr(locale, "tax"), _money("tax_amount")],
                    [tr(locale, "total_gross"), _money("amount_total")],
                ],
            )
        )
    if _shown(sections, "terms"):
        retention = getattr(po, "retention_percent", None)
        terms = [
            [tr(locale, "payment_terms"), _text(getattr(po, "payment_terms", None)) or EMPTY],
            [tr(locale, "retention"), _percent(retention, style)],
        ]
        if retention is not None and _nonzero(retention):
            at = "retention_at_receipt" if getattr(po, "retain_on_receipt", False) else "retention_at_invoice"
            terms.append([tr(locale, "retention_at"), tr(locale, at)])
        tolerance = [
            part
            for part in (
                _percent(getattr(po, "invoice_tolerance_pct", None), style),
                format_amount(getattr(po, "invoice_tolerance_abs", None), style, currency, locale=locale),
            )
            if part != EMPTY
        ]
        terms.append([tr(locale, "invoice_tolerance"), " / ".join(tolerance) or EMPTY])
        blocks.append(RecordBlock(tr(locale, "terms"), kind="grid", rows=terms))
    if _shown(sections, "supplier_confirmation"):
        if getattr(po, "supplier_acknowledged_at", None):
            blocks.append(
                RecordBlock(
                    tr(locale, "supplier_confirmation"),
                    kind="grid",
                    rows=[
                        [tr(locale, "supplier_reference"), _text(getattr(po, "supplier_reference", None)) or EMPTY],
                        [tr(locale, "confirmed_delivery"), _date("supplier_confirmed_delivery_date")],
                        [tr(locale, "acknowledged_on"), _date("supplier_acknowledged_at")],
                    ],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "supplier_confirmation"), text=tr(locale, "not_confirmed")))
    if _shown(sections, "notes"):
        blocks.append(
            RecordBlock(tr(locale, "notes"), text=_text(getattr(po, "notes", None)), empty_text=tr(locale, "no_notes"))
        )
    if _shown(sections, "signatures"):
        blocks.append(
            RecordBlock(
                tr(locale, "signatures"),
                kind="signatures",
                rows=CATALOGUE.signature_rows(
                    locale, [(tr(locale, "sig_ordered_by"), preparer), (tr(locale, "supplier"), supplier)]
                ),
            )
        )

    status = CATALOGUE.label("po_status", getattr(po, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "po_title"),
        number=_text(getattr(po, "po_number", None)),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=f"{tr(locale, 'supplier')}: {supplier}",
        grid=grid,
        blocks=blocks,
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="purchase_order",
    )


def build_purchase_order_pdf(po: Any, **context: Any) -> bytes:
    """Render one purchase order as a PDF form; see :func:`purchase_order_record`."""
    return build_record_pdf(purchase_order_record(po, **context))


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
) -> RecordDocument:
    """Describe the printable form of one goods receipt.

    Args:
        receipt: The goods receipt row with its ``items`` loaded.
        po: The purchase order it was received against, with its ``items``,
            which carry the descriptions and units the receipt lines point at.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the supplier and the
            person who received the goods.
        parties: The supplier's tax id and address keyed by ``str(id)``.
        sections: ``{section: printed}``; ``None`` prints every section.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The form, ready for the PDF renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    po_number = _text(getattr(po, "po_number", None))
    supplier = person_name(getattr(po, "vendor_contact_id", None), people)
    receiver = person_name(getattr(receipt, "received_by_id", None), people)
    delivery_note = _text(getattr(receipt, "delivery_note_number", None))
    ordered_items = {str(getattr(item, "id", "")): item for item in getattr(po, "items", None) or []}

    grid = grid_rows(
        [
            (tr(locale, "purchase_order"), po_number or EMPTY),
            (tr(locale, "supplier"), supplier),
            *_supplier_details(po, parties, locale),
            (tr(locale, "receipt_date"), format_stored_date(getattr(receipt, "receipt_date", None), date_format)),
            (tr(locale, "received_by"), receiver),
            (tr(locale, "delivery_note"), delivery_note or EMPTY),
        ]
    )

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

    blocks: list[RecordBlock] = []
    if _shown(sections, "line_items"):
        if lines:
            rows = [
                [
                    tr(locale, "col_no"),
                    tr(locale, "col_description"),
                    tr(locale, "col_unit"),
                    tr(locale, "col_ordered"),
                    tr(locale, "col_received"),
                    tr(locale, "col_rejected"),
                    tr(locale, "col_batch"),
                ]
            ]
            for index, (description, unit, item) in enumerate(lines, start=1):
                rows.append(
                    [
                        str(index),
                        description,
                        unit,
                        format_quantity(getattr(item, "quantity_ordered", None), style),
                        format_quantity(getattr(item, "quantity_received", None), style),
                        format_quantity(getattr(item, "quantity_rejected", None), style),
                        _text(getattr(item, "batch_lot", None)) or EMPTY,
                    ]
                )
            blocks.append(
                RecordBlock(
                    tr(locale, "line_items"),
                    kind="table",
                    rows=rows,
                    weights=[0.5, 3.6, 0.8, 1.1, 1.1, 1.1, 1.3],
                    right_aligned=[True, False, False, True, True, True, False],
                    keep_together=[True, False, True, True, True, True, False],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "line_items"), empty_text=tr(locale, "no_line_items")))
    if _shown(sections, "rejections"):
        rejected = [
            (description, unit, item)
            for description, unit, item in lines
            if _nonzero(getattr(item, "quantity_rejected", None))
        ]
        if rejected:
            rows = [[tr(locale, "col_description"), tr(locale, "col_rejected"), tr(locale, "col_reason")]]
            rows.extend(
                [
                    description,
                    _with_unit(format_quantity(getattr(item, "quantity_rejected", None), style), unit),
                    _text(getattr(item, "rejection_reason", None)) or EMPTY,
                ]
                for description, unit, item in rejected
            )
            blocks.append(
                RecordBlock(
                    tr(locale, "rejections"),
                    kind="table",
                    rows=rows,
                    weights=[3.0, 1.2, 3.0],
                    right_aligned=[False, True, False],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "rejections"), text=tr(locale, "no_rejections")))
    if _shown(sections, "notes"):
        blocks.append(
            RecordBlock(
                tr(locale, "notes"), text=_text(getattr(receipt, "notes", None)), empty_text=tr(locale, "no_notes")
            )
        )
    if _shown(sections, "signatures"):
        blocks.append(
            RecordBlock(
                tr(locale, "signatures"),
                kind="signatures",
                rows=CATALOGUE.signature_rows(
                    locale, [(tr(locale, "sig_delivered_by"), supplier), (tr(locale, "received_by"), receiver)]
                ),
            )
        )

    status = CATALOGUE.label("gr_status", getattr(receipt, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "gr_title"),
        number=delivery_note or po_number,
        project_label=project.label,
        status_text=caps(status, locale),
        subject=" · ".join(part for part in (f"{tr(locale, 'purchase_order')} {po_number}".strip(), supplier) if part),
        grid=grid,
        blocks=blocks,
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="goods_receipt",
    )


def build_goods_receipt_pdf(receipt: Any, **context: Any) -> bytes:
    """Render one goods receipt as a PDF form; see :func:`goods_receipt_record`."""
    return build_record_pdf(goods_receipt_record(receipt, **context))
