# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed change order register and the printed form of one change order.

The register is what a commercial manager attaches to a payment application
or a letter: every change order with its code, why it exists, where it
stands, the amount the contractor submitted, the amount the engineer
assessed, the amount approved and the time it adds. The columns are the ones
the change order row stores.

Amounts stay ``Decimal`` from the row to the page and are written in the
separators of the project's market. A register can hold orders in more than
one currency, so the currency is a column of its own rather than a line in
the header.

The builders are pure, like :mod:`app.modules.rfi.pdf_export`. The register's
layout is the shared one in :mod:`app.core.register_export`; the form of one
order is a document layout (:mod:`app.modules.changeorders.layouts`) whose
standard template prints it as it always printed.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.doc_templates.layout.spec import LayoutContext
from app.core.regional_format import NumberStyle, format_number
from app.core.register_export import (
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    RegisterColumn,
    RegisterDocument,
    build_record_pdf,
    build_register_pdf,
    build_register_xlsx,
    caps,
    format_amount,
    format_stored_date,
    person_name,
    printed_currency,
)
from app.modules.changeorders.pdf_translations import (
    CATALOGUE,
    DEFAULT_PDF_LOCALE,
    change_order_pdf_filename,
    normalize_pdf_locale,
    tr,
)

__all__ = [
    "build_change_order_pdf",
    "build_change_order_register_pdf",
    "build_change_order_register_xlsx",
    "change_order_context",
    "change_order_record",
    "change_order_register",
]


def _currency(order: Any, project: ProjectHeader) -> str:
    """The order's own currency, else the project's."""
    return (str(getattr(order, "currency", "") or "").strip().upper()) or project.currency


def _time_impact(order: Any) -> Any:
    """The claimed time in days: the variation field when set, else the schedule impact."""
    claimed = getattr(order, "time_impact_days", None)
    return claimed if claimed is not None else getattr(order, "schedule_impact_days", None)


def _decimal(value: Any) -> Decimal | None:
    """A stored number as a ``Decimal``, or ``None`` when there is none."""
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _trimmed(value: Any, style: NumberStyle, *, least: int, most: int) -> str:
    """A number with between ``least`` and ``most`` decimals, as many as it has.

    Two decimals for everything rounded a unit rate of 98,765 to 98,77 on
    the form, so the printed rate times the printed quantity no longer gave
    the printed difference. The stored digits are printed, trailing zeros
    beyond ``least`` dropped.
    """
    number = _decimal(value)
    if number is None:
        return "-"
    exponent = number.normalize().as_tuple().exponent
    decimals = max(least, min(most, -exponent if isinstance(exponent, int) else least))
    return format_number(number, decimals, style)


def _quantity(value: Any, style: NumberStyle) -> str:
    return _trimmed(value, style, least=2, most=4)


def _rate(value: Any, style: NumberStyle) -> str:
    return _trimmed(value, style, least=2, most=4)


def change_order_register(
    orders: Sequence[Any],
    *,
    project: ProjectHeader,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the change order register of one project.

    Args:
        orders: :class:`~app.modules.changeorders.models.ChangeOrder` rows, or
            objects with the same attributes, in print order.
        project: The project the register belongs to.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The register, ready for the PDF or the workbook renderer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_code"), weight=1.1, xlsx_width=13, nobreak=True),
        RegisterColumn(tr(locale, "col_title"), weight=3.0, xlsx_width=42, wrap=True),
        RegisterColumn(tr(locale, "col_reason"), weight=1.5, xlsx_width=22),
        RegisterColumn(tr(locale, "status"), weight=1.1, xlsx_width=14),
        RegisterColumn(tr(locale, "col_submitted"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_contractor_amount"), kind="money", weight=1.5, xlsx_width=18, total=True),
        RegisterColumn(tr(locale, "col_engineer_amount"), kind="money", weight=1.5, xlsx_width=18, total=True),
        RegisterColumn(tr(locale, "col_approved_amount"), kind="money", weight=1.5, xlsx_width=18, total=True),
        RegisterColumn(tr(locale, "col_cost_impact"), kind="money", weight=1.5, xlsx_width=18, total=True),
        RegisterColumn(tr(locale, "currency"), kind="currency", weight=0.8, xlsx_width=10),
        RegisterColumn(tr(locale, "col_time_impact"), kind="count", weight=0.9, xlsx_width=12),
        RegisterColumn(tr(locale, "col_approved_time"), kind="count", weight=0.9, xlsx_width=12),
    ]
    rows = [
        [
            getattr(order, "code", ""),
            getattr(order, "title", ""),
            CATALOGUE.label("reason", getattr(order, "reason_category", None), locale),
            CATALOGUE.label("status", getattr(order, "status", None), locale),
            getattr(order, "submitted_at", None),
            getattr(order, "contractor_amount", None),
            getattr(order, "engineer_amount", None),
            getattr(order, "approved_amount", None),
            getattr(order, "cost_impact", None),
            _currency(order, project),
            _time_impact(order),
            getattr(order, "approved_time_days", None),
        ]
        for order in orders
    ]
    return RegisterDocument(
        title=tr(locale, "register_title"),
        columns=columns,
        rows=rows,
        details=CATALOGUE.register_details(locale, project, count=len(rows), with_currency=True),
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty_register"),
        currency_column=9,
        **CATALOGUE.furniture(locale, project),
    )


def build_change_order_register_pdf(orders: Sequence[Any], **context: Any) -> bytes:
    """Render the change order register as a PDF; see :func:`change_order_register`."""
    return build_register_pdf(change_order_register(orders, **context))


def build_change_order_register_xlsx(orders: Sequence[Any], **context: Any) -> io.BytesIO:
    """Render the change order register as a workbook; see :func:`change_order_register`."""
    return build_register_xlsx(change_order_register(orders, **context))


def _formatter(style: NumberStyle, date_format: str) -> Any:
    """``(format, raw) -> text`` in the project's number style, for computed and reformatted columns."""

    def _format(fmt: str, value: Any) -> str:
        if value is None or value == "":
            return "-"
        if fmt == "money":
            return format_amount(value, style)
        if fmt in {"quantity", "number"}:
            return _quantity(value, style)
        if fmt == "percent":
            return f"{_trimmed(value, style, least=0, most=2)} %"
        if fmt == "date":
            return format_stored_date(value, date_format)
        return str(value).strip() or "-"

    return _format


def change_order_context(
    order: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> LayoutContext:
    """One change order's data for its document layout, formatted in the document language.

    Args:
        order: The change order row with its ``items`` loaded, or any object
            with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)`` for who submitted and approved.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    from app.core.doc_templates.seller import resolve_seller

    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    currency = _currency(order, project)

    def _money(name: str) -> str:
        return format_amount(getattr(order, name, None), style, currency, locale=locale)

    def _date(name: str) -> str:
        return format_stored_date(getattr(order, name, None), date_format)

    submitter = person_name(getattr(order, "submitted_by", None), people)
    approver = person_name(getattr(order, "approved_by", None), people)
    status_code = getattr(order, "status", None) or "draft"
    status = CATALOGUE.label("status", status_code, locale)
    description = str(getattr(order, "description", None) or "")
    values = {
        **resolve_seller().as_fields(),
        "project.name": project.name or "",
        "project.code": project.code or "",
        "project.label": project.label,
        "doc.generated": generated,
        "doc.number": str(getattr(order, "code", "") or ""),
        "doc.title": str(getattr(order, "title", "") or ""),
        "doc.description": description,
        "doc.reason": CATALOGUE.label("reason", getattr(order, "reason_category", None), locale),
        "doc.instrument": CATALOGUE.label("instrument", getattr(order, "variation_type", None), locale),
        "doc.status": status,
        "doc.currency": currency,
        "doc.contractor_amount": _money("contractor_amount"),
        "doc.engineer_amount": _money("engineer_amount"),
        "doc.approved_amount": _money("approved_amount"),
        "doc.cost_impact": _money("cost_impact"),
        # The value carries its own unit ("5 days"), so the label does not.
        "doc.time_impact": CATALOGUE.days(_time_impact(order), locale),
        "doc.approved_time": CATALOGUE.days(getattr(order, "approved_time_days", None), locale),
        "doc.submitted_at": _date("submitted_at"),
        "doc.submitted_by": submitter,
        "doc.approved_at": _date("approved_at"),
        "doc.approved_by": approver,
    }
    raw = {
        "doc.number": values["doc.number"] or None,
        "doc.title": values["doc.title"] or None,
        "doc.description": description or None,
        "doc.reason": getattr(order, "reason_category", None),
        "doc.instrument": getattr(order, "variation_type", None),
        "doc.status": status_code,
        "doc.currency": currency or None,
        "doc.contractor_amount": _decimal(getattr(order, "contractor_amount", None)),
        "doc.engineer_amount": _decimal(getattr(order, "engineer_amount", None)),
        "doc.approved_amount": _decimal(getattr(order, "approved_amount", None)),
        "doc.cost_impact": _decimal(getattr(order, "cost_impact", None)),
        "doc.time_impact": _decimal(_time_impact(order)),
        "doc.approved_time": _decimal(getattr(order, "approved_time_days", None)),
        "doc.submitted_at": getattr(order, "submitted_at", None),
        "doc.approved_at": getattr(order, "approved_at", None),
        "project.name": project.name or None,
    }
    items = sorted(getattr(order, "items", None) or [], key=lambda item: getattr(item, "sort_order", 0) or 0)
    rows = []
    for item in items:
        delta = _decimal(getattr(item, "cost_delta", None))
        # The kind of change is one word, so it goes on a line of its own under the description.
        text = "\n".join(
            part
            for part in (
                str(getattr(item, "description", "") or "").strip(),
                CATALOGUE.label("change", getattr(item, "change_type", None), locale),
            )
            if part and part != "-"
        )
        rows.append(
            {
                "description": (getattr(item, "description", None), text or "-"),
                "unit": (getattr(item, "unit", None), str(getattr(item, "unit", "") or "-")),
                "original_quantity": (
                    _decimal(getattr(item, "original_quantity", None)),
                    _quantity(getattr(item, "original_quantity", None), style),
                ),
                "new_quantity": (
                    _decimal(getattr(item, "new_quantity", None)),
                    _quantity(getattr(item, "new_quantity", None), style),
                ),
                "original_rate": (
                    _decimal(getattr(item, "original_rate", None)),
                    _rate(getattr(item, "original_rate", None), style),
                ),
                "new_rate": (_decimal(getattr(item, "new_rate", None)), _rate(getattr(item, "new_rate", None), style)),
                "cost_delta": (delta, format_amount(delta, style)),
            }
        )
    delta_label = tr(locale, "item_cost_delta")
    labels = {
        "field:doc.number": tr(locale, "col_code"),
        "field:doc.title": tr(locale, "col_title"),
        "field:doc.description": tr(locale, "description"),
        "field:doc.reason": tr(locale, "col_reason"),
        "field:doc.instrument": tr(locale, "col_instrument"),
        "field:doc.contractor_amount": tr(locale, "col_contractor_amount"),
        "field:doc.engineer_amount": tr(locale, "col_engineer_amount"),
        "field:doc.approved_amount": tr(locale, "col_approved_amount"),
        "field:doc.cost_impact": tr(locale, "col_cost_impact"),
        "field:doc.time_impact": tr(locale, "time_impact"),
        "field:doc.approved_time": tr(locale, "approved_time"),
        "field:doc.submitted_at": tr(locale, "col_submitted"),
        "field:doc.submitted_by": tr(locale, "submitted_by"),
        "field:doc.approved_at": tr(locale, "col_approved"),
        "field:doc.approved_by": tr(locale, "approved_by"),
        "column:items.description": f"{tr(locale, 'item_description')} / {tr(locale, 'item_change')}",
        "column:items.unit": tr(locale, "item_unit"),
        "column:items.original_quantity": tr(locale, "item_original_quantity"),
        "column:items.new_quantity": tr(locale, "item_new_quantity"),
        "column:items.original_rate": tr(locale, "item_original_rate"),
        "column:items.new_rate": tr(locale, "item_new_rate"),
        "column:items.cost_delta": f"{delta_label} ({printed_currency(currency, locale)})" if currency else delta_label,
        "section:items": tr(locale, "items"),
        "section:signatures": tr(locale, "signatures"),
        "signer:doc.submitted_by": tr(locale, "submitted_by"),
        "signer:doc.approved_by": tr(locale, "approved_by"),
        "total": tr(locale, "total"),
        "subtotal": tr(locale, "total"),
    }
    base = RecordDocument(
        title=tr(locale, "doc_title"),
        number=values["doc.number"],
        project_label=project.label,
        status_text=caps(status, locale),
        subject=values["doc.title"],
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )
    return LayoutContext(
        locale=locale,
        values=values,
        raw=raw,
        labels=labels,
        collections={"items": rows},
        sections={
            "description": [
                RecordBlock(tr(locale, "description"), text=description, empty_text=tr(locale, "no_description"))
            ]
        },
        base=base,
        status=str(status_code).lower(),
        format=_formatter(style, date_format),
        signature_rows=lambda signers: CATALOGUE.signature_rows(locale, list(signers)),
        project_id=getattr(order, "project_id", None),
        filename=change_order_pdf_filename(getattr(order, "code", None)),
        empty="-",
    )


def change_order_record(
    order: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    template: Mapping[str, Any] | None = None,
) -> RecordDocument:
    """Describe the printable form of one change order with its items.

    Args:
        order: The change order row with its ``items`` loaded, or any object
            with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)`` for who submitted and approved.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        template: A published document layout; the standard one when ``None``.

    Returns:
        The form, ready for the PDF renderer.
    """
    from app.core.doc_templates.layout.compile import compile_layout
    from app.modules.changeorders.layouts import CHANGE_ORDER, change_order_standard

    ctx = change_order_context(order, project=project, people=people, locale=locale, generated=generated)
    return compile_layout(template or change_order_standard(), CHANGE_ORDER, ctx)


def build_change_order_pdf(order: Any, **context: Any) -> bytes:
    """Render one change order as a PDF form; see :func:`change_order_record`."""
    return build_record_pdf(change_order_record(order, **context))
