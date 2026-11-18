# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed invoice and the printed payment record.

Amounts are printed exactly as the invoice stores them. The net amount, the
tax, the total and the retention are separate stored fields with fixed
meanings (``amount_total`` is the net plus the tax, see
:mod:`app.modules.finance.service`), and the form writes each
one under its own label instead of deriving one from another. A PDF that
added the tax again on top of a total that already carried it is the reason
this rule is spelled out. The two figures the form does derive are plain
differences and sums of stored ``Decimal`` amounts, never a rate applied to
an amount: what is still payable once the retention is held back
(``amount_total - retention_amount``, the same split the payment service
makes), and the gross a payment settled (the cash paid plus the retention
withheld from it).

The form is a document layout (:mod:`app.core.doc_templates.layout`): the
context builders here turn a record into formatted values, rows and the
sections only this module draws (the payments, the notes, the withholding);
:mod:`app.modules.finance.layouts` holds the standard templates that reproduce
the forms as they always printed, and a firm's published template rearranges,
rewords or extends them. Which sections of the standard template print is the
workspace's choice per document type (see
:func:`app.core.pdf_appearance.resolve_sections`). The builders are pure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from app.modules.finance.pdf_translations import (
    CATALOGUE,
    DEFAULT_PDF_LOCALE,
    invoice_pdf_filename,
    normalize_pdf_locale,
    payment_pdf_filename,
    tr,
)

__all__ = [
    "build_invoice_pdf",
    "build_payment_pdf",
    "invoice_context",
    "invoice_record",
    "payment_context",
    "payment_record",
]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any) -> Decimal | None:
    """A stored amount as a ``Decimal``, or ``None`` when there is none."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _counterparty_label(invoice: Any, locale: str) -> str:
    """The counterparty's caption: the supplier on a payable invoice, the client on a receivable one."""
    return tr(locale, "client" if getattr(invoice, "invoice_direction", None) == "receivable" else "supplier")


def _currency(record: Any, project: ProjectHeader) -> str:
    return _text(getattr(record, "currency_code", None)).upper() or project.currency


def _party(record: Any, parties: Mapping[str, PartyDetails] | None) -> PartyDetails | None:
    contact = getattr(record, "contact_id", None)
    if contact is None or not parties:
        return None
    return parties.get(str(contact).strip())


def _percent(value: Any, style: Any) -> str:
    text = format_quantity(value, style, least=0, most=2)
    return EMPTY if text == EMPTY else f"{text} %"


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


def _counterparty(record: Any, people: Any, parties: Any) -> tuple[str, dict[str, str], dict[str, Any]]:
    """The counterparty's printed name, its values and its raw values."""
    name = person_name(getattr(record, "contact_id", None), people)
    details = _party(record, parties)
    tax_id = (details.tax_id if details else "") or ""
    address = (details.address if details else "") or ""
    values = {"counterparty.name": name, "counterparty.tax_id": tax_id, "counterparty.address": address}
    raw = {
        "counterparty.name": None if name == EMPTY else name,
        "counterparty.tax_id": tax_id or None,
        "counterparty.address": address or None,
    }
    return name, values, raw


def _counterparty_labels(invoice: Any, locale: str) -> dict[str, str]:
    return {
        "field:counterparty.name": _counterparty_label(invoice, locale),
        "field:counterparty.tax_id": tr(locale, "counterparty_tax_id"),
        "field:counterparty.address": tr(locale, "counterparty_address"),
    }


def invoice_context(
    invoice: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    purchase_order_number: str | None = None,
    payments: Sequence[Any] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> LayoutContext:
    """One invoice's data for its document layout, formatted in the document language.

    Args:
        invoice: The invoice row with its ``line_items`` loaded, or any object
            with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the counterparty
            contact and the user who created the invoice.
        parties: The counterparty's tax id and address keyed by ``str(id)``,
            from :func:`app.core.party_names.resolve_party_details`.
        purchase_order_number: The number of the order the invoice bills, when
            it is linked to one.
        payments: The payments recorded against the invoice, oldest first.
            ``None`` reads ``invoice.payments``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    currency = _currency(invoice, project)

    def _money(value: Any, code: str = currency) -> str:
        return format_amount(value, style, code, locale=locale)

    def _date(name: str) -> str:
        return format_stored_date(getattr(invoice, name, None), date_format)

    counterparty, party_values, party_raw = _counterparty(invoice, people, parties)
    preparer = person_name(getattr(invoice, "created_by", None), people)
    terms_days = _text(getattr(invoice, "payment_terms_days", None))
    meta = getattr(invoice, "metadata_", None)
    meta = meta if isinstance(meta, Mapping) else {}
    supply = meta.get("supply_date") or meta.get("service_period") or getattr(invoice, "invoice_date", None)
    items = sorted(getattr(invoice, "line_items", None) or [], key=lambda item: getattr(item, "sort_order", 0) or 0)
    retention = _decimal(getattr(invoice, "retention_amount", None))
    retention = retention if retention is not None and retention != 0 else None
    total = _decimal(getattr(invoice, "amount_total", None))
    due = total - retention if retention is not None and total is not None else None
    status_code = getattr(invoice, "status", None) or "draft"
    status = CATALOGUE.label("invoice_status", status_code, locale)
    number = _text(getattr(invoice, "invoice_number", None))
    reverse_charge = any(_text(getattr(item, "vat_category", None)).upper() == "AE" for item in items)
    values = {
        **_base_values(project, generated),
        **party_values,
        "doc.number": number,
        "doc.direction": CATALOGUE.label("direction", getattr(invoice, "invoice_direction", None), locale),
        "doc.date": _date("invoice_date"),
        "doc.due_date": _date("due_date"),
        "doc.supply_date": format_stored_date(supply, date_format),
        "doc.payment_terms": CATALOGUE.days(terms_days, locale) if terms_days else EMPTY,
        "doc.purchase_order": _text(purchase_order_number) or EMPTY,
        "doc.currency": currency,
        "doc.invoice_total": _money(getattr(invoice, "amount_total", None)),
        "doc.total_net": _money(getattr(invoice, "amount_subtotal", None)),
        "doc.total_vat": _money(getattr(invoice, "tax_amount", None)),
        "doc.total_gross": _money(getattr(invoice, "amount_total", None)),
        "doc.retention": _money(retention) if retention is not None else "",
        "doc.amount_due": _money(due) if due is not None else "",
        "doc.status": status,
        "doc.notes": _text(getattr(invoice, "notes", None)),
        "doc.created_by": preparer,
        "doc.approved_by": "",
        "doc.reverse_charge": "1" if reverse_charge else "",
        "doc.small_business": "1" if meta.get("small_business") else "",
        "doc.private_customer": "1" if meta.get("private_customer") else "",
        "recipient.name": party_values["counterparty.name"] if party_raw["counterparty.name"] else "",
        "recipient.address": party_values["counterparty.address"],
        "recipient.vat_id": party_values["counterparty.tax_id"],
    }
    raw = {
        **party_raw,
        "doc.number": number or None,
        "doc.direction": getattr(invoice, "invoice_direction", None),
        "doc.date": getattr(invoice, "invoice_date", None),
        "doc.due_date": getattr(invoice, "due_date", None),
        "doc.supply_date": supply,
        "doc.payment_terms": terms_days or None,
        "doc.purchase_order": _text(purchase_order_number) or None,
        "doc.currency": currency or None,
        "doc.invoice_total": total,
        "doc.total_net": _decimal(getattr(invoice, "amount_subtotal", None)),
        "doc.total_vat": _decimal(getattr(invoice, "tax_amount", None)),
        "doc.total_gross": total,
        "doc.retention": retention,
        "doc.amount_due": due,
        "doc.status": status_code,
        "doc.notes": values["doc.notes"] or None,
        "recipient.name": values["recipient.name"] or None,
        "recipient.address": values["recipient.address"] or None,
        "project.name": project.name or None,
    }
    rows = [
        {
            "description": (getattr(item, "description", None), _text(getattr(item, "description", None)) or EMPTY),
            "quantity": (
                _decimal(getattr(item, "quantity", None)),
                format_quantity(getattr(item, "quantity", None), style),
            ),
            "unit": (getattr(item, "unit", None), _text(getattr(item, "unit", None)) or EMPTY),
            "unit_rate": (
                _decimal(getattr(item, "unit_rate", None)),
                format_quantity(getattr(item, "unit_rate", None), style, least=2),
            ),
            "vat_rate": (_decimal(getattr(item, "vat_rate", None)), _percent(getattr(item, "vat_rate", None), style)),
            "amount": (_decimal(getattr(item, "amount", None)), format_amount(getattr(item, "amount", None), style)),
        }
        for item in items
    ]
    amount_label = tr(locale, "col_amount")
    labels = {
        **_counterparty_labels(invoice, locale),
        "field:doc.number": tr(locale, "invoice_number"),
        "field:doc.direction": tr(locale, "direction"),
        "field:doc.date": tr(locale, "invoice_date"),
        "field:doc.due_date": tr(locale, "due_date"),
        "field:doc.supply_date": tr(locale, "supply_date"),
        "field:doc.payment_terms": tr(locale, "payment_terms"),
        "field:doc.purchase_order": tr(locale, "purchase_order"),
        "field:doc.invoice_total": tr(locale, "invoice_total"),
        "field:doc.total_net": tr(locale, "subtotal"),
        "field:doc.total_vat": tr(locale, "tax"),
        "field:doc.total_gross": tr(locale, "total_gross"),
        "field:doc.retention": tr(locale, "retention"),
        "field:doc.amount_due": tr(locale, "amount_due"),
        "field:doc.notes": tr(locale, "notes"),
        "column:items.no": tr(locale, "col_no"),
        "column:items.description": tr(locale, "col_description"),
        "column:items.quantity": tr(locale, "col_quantity"),
        "column:items.unit": tr(locale, "col_unit"),
        "column:items.unit_rate": tr(locale, "col_unit_rate"),
        "column:items.vat_rate": tr(locale, "col_vat"),
        "column:items.amount": f"{amount_label} ({printed_currency(currency, locale)})" if currency else amount_label,
        "section:line_items": tr(locale, "line_items"),
        "empty:line_items": tr(locale, "no_line_items"),
        "section:totals": tr(locale, "totals"),
        "section:signatures": tr(locale, "signatures"),
        "signer:doc.created_by": tr(locale, "sig_prepared_by"),
        "signer:doc.approved_by": tr(locale, "sig_approved_by"),
        "subtotal": tr(locale, "subtotal"),
    }
    sections = {
        "payments": [_payments_block(invoice, payments, project, currency, locale, date_format)],
        "notes": [RecordBlock(tr(locale, "notes"), text=values["doc.notes"], empty_text=tr(locale, "no_notes"))],
    }
    base = RecordDocument(
        title=tr(locale, "invoice_title"),
        number=number,
        project_label=project.label,
        status_text=caps(status, locale),
        subject=f"{_counterparty_label(invoice, locale)}: {counterparty}",
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="invoice",
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
        project_id=getattr(invoice, "project_id", None),
        filename=invoice_pdf_filename(getattr(invoice, "invoice_number", None)),
        empty=EMPTY,
    )


def _payments_block(
    invoice: Any,
    payments: Sequence[Any] | None,
    project: ProjectHeader,
    currency: str,
    locale: str,
    date_format: str,
) -> RecordBlock:
    """The payments recorded against the invoice, oldest first, each in its own currency."""
    style = project.number_style
    recorded = list(payments if payments is not None else getattr(invoice, "payments", None) or [])
    recorded.sort(key=lambda payment: _text(getattr(payment, "payment_date", None)))
    if not recorded:
        return RecordBlock(tr(locale, "payments"), text=tr(locale, "no_payments"))
    rows = [[tr(locale, "col_date"), tr(locale, "col_reference"), tr(locale, "col_paid"), tr(locale, "col_withheld")]]
    for payment in recorded:
        code = _currency(payment, project) or currency
        reference = _text(getattr(payment, "reference", None)) or EMPTY
        if getattr(payment, "is_refund", False):
            reference = f"{tr(locale, 'refund')}: {reference}"
        rows.append(
            [
                format_stored_date(getattr(payment, "payment_date", None), date_format),
                reference,
                format_amount(getattr(payment, "amount", None), style, code, locale=locale),
                format_amount(getattr(payment, "withholding_amount", None), style, code, locale=locale),
            ]
        )
    return RecordBlock(
        tr(locale, "payments"),
        kind="table",
        rows=rows,
        weights=[1.2, 3.0, 1.6, 1.6],
        right_aligned=[False, False, True, True],
        keep_together=[True, False, True, True],
    )


def invoice_record(
    invoice: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    purchase_order_number: str | None = None,
    payments: Sequence[Any] | None = None,
    sections: Mapping[str, bool] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    template: Mapping[str, Any] | None = None,
) -> RecordDocument:
    """Describe the printable form of one invoice.

    Args:
        invoice: The invoice row with its ``line_items`` loaded.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        parties: The counterparty's tax id and address keyed by ``str(id)``.
        purchase_order_number: The number of the order the invoice bills.
        payments: The payments recorded against the invoice; ``None`` reads ``invoice.payments``.
        sections: ``{section: printed}``; ``None`` prints every section. Read only
            when no ``template`` is given.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        template: A published document layout; the standard one when ``None``.

    Returns:
        The form, ready for the PDF renderer.
    """
    from app.core.doc_templates.layout.compile import compile_layout
    from app.modules.finance.layouts import INVOICE, invoice_standard

    ctx = invoice_context(
        invoice,
        project=project,
        people=people,
        parties=parties,
        purchase_order_number=purchase_order_number,
        payments=payments,
        locale=locale,
        generated=generated,
    )
    return compile_layout(template or invoice_standard(sections), INVOICE, ctx)


def build_invoice_pdf(invoice: Any, **context: Any) -> bytes:
    """Render one invoice as a PDF form; see :func:`invoice_record`."""
    return build_record_pdf(invoice_record(invoice, **context))


def payment_context(
    payment: Any,
    *,
    invoice: Any,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> LayoutContext:
    """One payment's data for its document layout, formatted in the document language.

    Args:
        payment: The payment row.
        invoice: The invoice it was recorded against.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the invoice's counterparty.
        parties: The counterparty's tax id and address keyed by ``str(id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    invoice_currency = _currency(invoice, project)
    currency = _currency(payment, project) or invoice_currency

    def _money(value: Any, code: str = currency) -> str:
        return format_amount(value, style, code, locale=locale)

    refund = bool(getattr(payment, "is_refund", False))
    invoice_number = _text(getattr(invoice, "invoice_number", None))
    reference = _text(getattr(payment, "reference", None))
    counterparty, party_values, party_raw = _counterparty(invoice, people, parties)
    rate = _decimal(getattr(payment, "exchange_rate_snapshot", None))
    rate = rate if rate is not None and rate != 1 else None
    withheld = _decimal(getattr(payment, "withholding_amount", None))
    withheld = withheld if withheld is not None and withheld != 0 else None
    paid = _decimal(getattr(payment, "amount", None))
    values = {
        **_base_values(project, generated),
        **party_values,
        "doc.number": reference or invoice_number,
        "doc.payment_date": format_stored_date(getattr(payment, "payment_date", None), date_format),
        "doc.amount_paid": _money(getattr(payment, "amount", None)),
        "doc.kind": tr(locale, "kind_refund" if refund else "kind_payment"),
        "doc.reference": reference or EMPTY,
        "doc.exchange_rate": format_quantity(rate, style, least=2, most=6) if rate is not None else "",
        "doc.currency": currency,
        "doc.withheld": _money(withheld) if withheld is not None else "",
        "doc.release_date": format_stored_date(getattr(payment, "withholding_release_date", None), date_format),
        "doc.prepared_by": "",
        "doc.approved_by": "",
        "invoice.number": invoice_number,
        "invoice.date": format_stored_date(getattr(invoice, "invoice_date", None), date_format),
        "invoice.total": _money(getattr(invoice, "amount_total", None), invoice_currency),
    }
    raw = {
        **party_raw,
        "doc.number": values["doc.number"] or None,
        "doc.payment_date": getattr(payment, "payment_date", None),
        "doc.amount_paid": paid,
        "doc.kind": "refund" if refund else "payment",
        "doc.reference": reference or None,
        "doc.exchange_rate": rate,
        "doc.currency": currency or None,
        "doc.withheld": withheld,
        "invoice.number": invoice_number or None,
        "invoice.date": getattr(invoice, "invoice_date", None),
        "invoice.total": _decimal(getattr(invoice, "amount_total", None)),
        "project.name": project.name or None,
    }
    if withheld is not None:
        withholding = RecordBlock(
            tr(locale, "withholding"),
            kind="grid",
            rows=[
                [tr(locale, "withheld_amount"), values["doc.withheld"]],
                [tr(locale, "release_date"), values["doc.release_date"]],
                [tr(locale, "gross_settled"), _money(paid + withheld) if paid is not None else EMPTY],
            ],
        )
    else:
        withholding = RecordBlock(tr(locale, "withholding"), text=tr(locale, "no_withholding"))
    labels = {
        **_counterparty_labels(invoice, locale),
        "field:doc.payment_date": tr(locale, "payment_date"),
        "field:doc.amount_paid": tr(locale, "amount_paid"),
        "field:doc.kind": tr(locale, "kind"),
        "field:doc.reference": tr(locale, "reference"),
        "field:doc.exchange_rate": tr(locale, "exchange_rate"),
        "field:doc.withheld": tr(locale, "withheld_amount"),
        "field:doc.release_date": tr(locale, "release_date"),
        "field:invoice.number": tr(locale, "invoice_number"),
        "field:invoice.date": tr(locale, "invoice_date"),
        "field:invoice.total": tr(locale, "invoice_total"),
        "section:invoice": tr(locale, "invoice"),
        "section:signatures": tr(locale, "signatures"),
        "signer:doc.prepared_by": tr(locale, "sig_prepared_by"),
        "signer:doc.approved_by": tr(locale, "sig_approved_by"),
    }
    status_code = "refunded" if refund else "completed"
    status = CATALOGUE.label("payment_status", status_code, locale)
    base = RecordDocument(
        title=tr(locale, "payment_title"),
        number=values["doc.number"],
        project_label=project.label,
        status_text=caps(status, locale),
        subject=" · ".join(
            part for part in (f"{tr(locale, 'invoice')} {invoice_number}".strip(), counterparty) if part
        ),
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="payment",
    )
    return LayoutContext(
        locale=locale,
        values=values,
        raw=raw,
        labels=labels,
        collections={},
        sections={"withholding": [withholding]},
        base=base,
        status=status_code,
        format=_formatter(style, date_format),
        signature_rows=lambda signers: CATALOGUE.signature_rows(locale, list(signers)),
        project_id=getattr(invoice, "project_id", None),
        filename=payment_pdf_filename(invoice_number, getattr(payment, "payment_date", None)),
        empty=EMPTY,
    )


def payment_record(
    payment: Any,
    *,
    invoice: Any,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    parties: Mapping[str, PartyDetails] | None = None,
    sections: Mapping[str, bool] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    template: Mapping[str, Any] | None = None,
) -> RecordDocument:
    """Describe the printable record of one payment.

    Args:
        payment: The payment row.
        invoice: The invoice it was recorded against.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the invoice's counterparty.
        parties: The counterparty's tax id and address keyed by ``str(id)``.
        sections: ``{section: printed}``; ``None`` prints every section. Read only
            when no ``template`` is given.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        template: A published document layout; the standard one when ``None``.

    Returns:
        The form, ready for the PDF renderer.
    """
    from app.core.doc_templates.layout.compile import compile_layout
    from app.modules.finance.layouts import PAYMENT, payment_standard

    ctx = payment_context(
        payment, invoice=invoice, project=project, people=people, parties=parties, locale=locale, generated=generated
    )
    return compile_layout(template or payment_standard(sections), PAYMENT, ctx)


def build_payment_pdf(payment: Any, **context: Any) -> bytes:
    """Render one payment record as a PDF form; see :func:`payment_record`."""
    return build_record_pdf(payment_record(payment, **context))
