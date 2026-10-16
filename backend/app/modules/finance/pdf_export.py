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

Which sections print is the workspace's choice per document type (see
:func:`app.core.pdf_appearance.resolve_sections`). The builders are pure; the
layout is the shared record form in :mod:`app.core.register_export`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from app.modules.finance.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_invoice_pdf",
    "build_payment_pdf",
    "invoice_record",
    "payment_record",
]


def _shown(sections: Mapping[str, bool] | None, name: str) -> bool:
    """Whether ``name`` prints. A section nobody switched off prints."""
    return True if sections is None else sections.get(name, True) is not False


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


def _counterparty_details(
    invoice: Any, parties: Mapping[str, PartyDetails] | None, locale: str
) -> list[tuple[str, str]]:
    """The counterparty's tax id and address rows, where the contact has them."""
    return party_detail_pairs(
        getattr(invoice, "contact_id", None),
        parties,
        tr(locale, "counterparty_tax_id"),
        tr(locale, "counterparty_address"),
    )


def _currency(record: Any, project: ProjectHeader) -> str:
    return _text(getattr(record, "currency_code", None)).upper() or project.currency


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
) -> RecordDocument:
    """Describe the printable form of one invoice.

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
        sections: ``{section: printed}``; ``None`` prints every section.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The form, ready for the PDF renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    currency = _currency(invoice, project)

    def _money(value: Any, code: str = currency) -> str:
        return format_amount(value, style, code, locale=locale)

    counterparty = person_name(getattr(invoice, "contact_id", None), people)
    preparer = person_name(getattr(invoice, "created_by", None), people)
    terms_days = _text(getattr(invoice, "payment_terms_days", None))
    grid = grid_rows(
        [
            (
                tr(locale, "direction"),
                CATALOGUE.label("direction", getattr(invoice, "invoice_direction", None), locale),
            ),
            (_counterparty_label(invoice, locale), counterparty),
            *_counterparty_details(invoice, parties, locale),
            (tr(locale, "invoice_date"), format_stored_date(getattr(invoice, "invoice_date", None), date_format)),
            (tr(locale, "due_date"), format_stored_date(getattr(invoice, "due_date", None), date_format)),
            (tr(locale, "payment_terms"), CATALOGUE.days(terms_days, locale) if terms_days else EMPTY),
            (tr(locale, "purchase_order"), _text(purchase_order_number) or EMPTY),
            (tr(locale, "invoice_total"), _money(getattr(invoice, "amount_total", None))),
        ]
    )

    blocks: list[RecordBlock] = []
    if _shown(sections, "line_items"):
        items = sorted(getattr(invoice, "line_items", None) or [], key=lambda item: getattr(item, "sort_order", 0) or 0)
        if items:
            with_vat = any(getattr(item, "vat_rate", None) is not None for item in items)
            header = [
                tr(locale, "col_no"),
                tr(locale, "col_description"),
                tr(locale, "col_quantity"),
                tr(locale, "col_unit"),
                tr(locale, "col_unit_rate"),
            ]
            if with_vat:
                header.append(tr(locale, "col_vat"))
            amount_label = tr(locale, "col_amount")
            header.append(f"{amount_label} ({printed_currency(currency, locale)})" if currency else amount_label)
            rows = [header]
            for index, item in enumerate(items, start=1):
                row = [
                    str(index),
                    _text(getattr(item, "description", None)) or EMPTY,
                    format_quantity(getattr(item, "quantity", None), style),
                    _text(getattr(item, "unit", None)) or EMPTY,
                    format_quantity(getattr(item, "unit_rate", None), style, least=2),
                ]
                if with_vat:
                    rate = format_quantity(getattr(item, "vat_rate", None), style, least=0, most=2)
                    row.append(EMPTY if rate == EMPTY else f"{rate} %")
                row.append(format_amount(getattr(item, "amount", None), style))
                rows.append(row)
            weights = [0.5, 3.8, 1.0, 0.8, 1.3] + ([0.8] if with_vat else []) + [1.5]
            numeric = [True, False, True, False, True] + ([True] if with_vat else []) + [True]
            blocks.append(
                RecordBlock(
                    tr(locale, "line_items"),
                    kind="table",
                    rows=rows,
                    weights=weights,
                    right_aligned=numeric,
                    keep_together=[column != 1 for column in range(len(numeric))],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "line_items"), empty_text=tr(locale, "no_line_items")))
    if _shown(sections, "totals"):
        totals = [
            [tr(locale, "subtotal"), _money(getattr(invoice, "amount_subtotal", None))],
            [tr(locale, "tax"), _money(getattr(invoice, "tax_amount", None))],
            [tr(locale, "total_gross"), _money(getattr(invoice, "amount_total", None))],
        ]
        retention = _decimal(getattr(invoice, "retention_amount", None))
        total = _decimal(getattr(invoice, "amount_total", None))
        if retention is not None and retention != 0:
            totals.append([tr(locale, "retention"), _money(retention)])
            if total is not None:
                totals.append([tr(locale, "amount_due"), _money(total - retention)])
        blocks.append(RecordBlock(tr(locale, "totals"), kind="grid", rows=totals))
    if _shown(sections, "payments"):
        recorded = list(payments if payments is not None else getattr(invoice, "payments", None) or [])
        recorded.sort(key=lambda payment: _text(getattr(payment, "payment_date", None)))
        if recorded:
            rows = [
                [
                    tr(locale, "col_date"),
                    tr(locale, "col_reference"),
                    tr(locale, "col_paid"),
                    tr(locale, "col_withheld"),
                ]
            ]
            for payment in recorded:
                code = _currency(payment, project) or currency
                reference = _text(getattr(payment, "reference", None)) or EMPTY
                if getattr(payment, "is_refund", False):
                    reference = f"{tr(locale, 'refund')}: {reference}"
                rows.append(
                    [
                        format_stored_date(getattr(payment, "payment_date", None), date_format),
                        reference,
                        _money(getattr(payment, "amount", None), code),
                        _money(getattr(payment, "withholding_amount", None), code),
                    ]
                )
            blocks.append(
                RecordBlock(
                    tr(locale, "payments"),
                    kind="table",
                    rows=rows,
                    weights=[1.2, 3.0, 1.6, 1.6],
                    right_aligned=[False, False, True, True],
                    keep_together=[True, False, True, True],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "payments"), text=tr(locale, "no_payments")))
    if _shown(sections, "notes"):
        blocks.append(
            RecordBlock(
                tr(locale, "notes"), text=_text(getattr(invoice, "notes", None)), empty_text=tr(locale, "no_notes")
            )
        )
    if _shown(sections, "signatures"):
        blocks.append(
            RecordBlock(
                tr(locale, "signatures"),
                kind="signatures",
                rows=CATALOGUE.signature_rows(
                    locale,
                    [(tr(locale, "sig_prepared_by"), preparer), (tr(locale, "sig_approved_by"), EMPTY)],
                ),
            )
        )

    status = CATALOGUE.label("invoice_status", getattr(invoice, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "invoice_title"),
        number=_text(getattr(invoice, "invoice_number", None)),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=f"{_counterparty_label(invoice, locale)}: {counterparty}",
        grid=grid,
        blocks=blocks,
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="invoice",
    )


def build_invoice_pdf(invoice: Any, **context: Any) -> bytes:
    """Render one invoice as a PDF form; see :func:`invoice_record`."""
    return build_record_pdf(invoice_record(invoice, **context))


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
) -> RecordDocument:
    """Describe the printable record of one payment.

    Args:
        payment: The payment row.
        invoice: The invoice it was recorded against.
        project: The owning project.
        people: Display names keyed by ``str(id)``, for the invoice's
            counterparty.
        parties: The counterparty's tax id and address keyed by ``str(id)``.
        sections: ``{section: printed}``; ``None`` prints every section.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The form, ready for the PDF renderer.
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
    counterparty = person_name(getattr(invoice, "contact_id", None), people)
    pairs: list[tuple[str, str] | None] = [
        (tr(locale, "payment_date"), format_stored_date(getattr(payment, "payment_date", None), date_format)),
        (tr(locale, "amount_paid"), _money(getattr(payment, "amount", None))),
        (tr(locale, "kind"), tr(locale, "kind_refund" if refund else "kind_payment")),
        (tr(locale, "reference"), _text(getattr(payment, "reference", None)) or EMPTY),
    ]
    rate = _decimal(getattr(payment, "exchange_rate_snapshot", None))
    if rate is not None and rate != 1:
        pairs.append((tr(locale, "exchange_rate"), format_quantity(rate, style, least=2, most=6)))

    blocks: list[RecordBlock] = []
    if _shown(sections, "invoice"):
        blocks.append(
            RecordBlock(
                tr(locale, "invoice"),
                kind="grid",
                rows=grid_rows(
                    [
                        (tr(locale, "invoice_number"), invoice_number or EMPTY),
                        (
                            tr(locale, "invoice_date"),
                            format_stored_date(getattr(invoice, "invoice_date", None), date_format),
                        ),
                        (_counterparty_label(invoice, locale), counterparty),
                        *_counterparty_details(invoice, parties, locale),
                        (tr(locale, "invoice_total"), _money(getattr(invoice, "amount_total", None), invoice_currency)),
                    ]
                ),
            )
        )
    if _shown(sections, "withholding"):
        withheld = _decimal(getattr(payment, "withholding_amount", None))
        if withheld is not None and withheld != 0:
            paid = _decimal(getattr(payment, "amount", None))
            blocks.append(
                RecordBlock(
                    tr(locale, "withholding"),
                    kind="grid",
                    rows=[
                        [tr(locale, "withheld_amount"), _money(withheld)],
                        [
                            tr(locale, "release_date"),
                            format_stored_date(getattr(payment, "withholding_release_date", None), date_format),
                        ],
                        [tr(locale, "gross_settled"), _money(paid + withheld) if paid is not None else EMPTY],
                    ],
                )
            )
        else:
            blocks.append(RecordBlock(tr(locale, "withholding"), text=tr(locale, "no_withholding")))
    if _shown(sections, "signatures"):
        blocks.append(
            RecordBlock(
                tr(locale, "signatures"),
                kind="signatures",
                rows=CATALOGUE.signature_rows(
                    locale, [(tr(locale, "sig_prepared_by"), EMPTY), (tr(locale, "sig_approved_by"), EMPTY)]
                ),
            )
        )

    status = CATALOGUE.label("payment_status", "refunded" if refund else "completed", locale)
    return RecordDocument(
        title=tr(locale, "payment_title"),
        number=_text(getattr(payment, "reference", None)) or invoice_number,
        project_label=project.label,
        status_text=caps(status, locale),
        subject=" · ".join(
            part for part in (f"{tr(locale, 'invoice')} {invoice_number}".strip(), counterparty) if part
        ),
        grid=grid_rows(pairs),
        blocks=blocks,
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
        doc_type="payment",
    )


def build_payment_pdf(payment: Any, **context: Any) -> bytes:
    """Render one payment record as a PDF form; see :func:`payment_record`."""
    return build_record_pdf(payment_record(payment, **context))
