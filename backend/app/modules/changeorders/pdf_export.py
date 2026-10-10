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

The builders are pure, like :mod:`app.modules.rfi.pdf_export`. The layout is
the shared one in :mod:`app.core.register_export`.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

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
    grid_rows,
    person_name,
    printed_currency,
)
from app.modules.changeorders.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_change_order_pdf",
    "build_change_order_register_pdf",
    "build_change_order_register_xlsx",
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


def change_order_record(
    order: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RecordDocument:
    """Describe the printable form of one change order with its items.

    Args:
        order: The change order row with its ``items`` loaded, or any object
            with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)`` for who submitted and approved.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.

    Returns:
        The form, ready for the PDF renderer.
    """
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
    # The project is in the line under the title, so the grid does not say it
    # again; a row of its own cost the form a line and told the reader nothing.
    grid = grid_rows(
        [
            (tr(locale, "col_reason"), CATALOGUE.label("reason", getattr(order, "reason_category", None), locale)),
            (
                tr(locale, "col_instrument"),
                CATALOGUE.label("instrument", getattr(order, "variation_type", None), locale),
            ),
            (tr(locale, "col_contractor_amount"), _money("contractor_amount")),
            (tr(locale, "col_engineer_amount"), _money("engineer_amount")),
            (tr(locale, "col_approved_amount"), _money("approved_amount")),
            (tr(locale, "col_cost_impact"), _money("cost_impact")),
            # The value carries its own unit ("5 days"), so the label does not.
            (tr(locale, "time_impact"), CATALOGUE.days(_time_impact(order), locale)),
            (tr(locale, "approved_time"), CATALOGUE.days(getattr(order, "approved_time_days", None), locale)),
            (tr(locale, "col_submitted"), _date("submitted_at")),
            (tr(locale, "submitted_by"), submitter),
            (tr(locale, "col_approved"), _date("approved_at")),
            (tr(locale, "approved_by"), approver),
        ]
    )
    blocks = [
        RecordBlock(
            tr(locale, "description"),
            text=str(getattr(order, "description", None) or ""),
            empty_text=tr(locale, "no_description"),
        )
    ]
    items = sorted(getattr(order, "items", None) or [], key=lambda item: getattr(item, "sort_order", 0) or 0)
    if items:
        # A portrait page has room for the six figures or for a readable
        # description, not for both and a column of "Added" beside them. The
        # kind of change is one word, so it goes on a line of its own under
        # the description and the description gets that column's width.
        header = [
            f"{tr(locale, 'item_description')} / {tr(locale, 'item_change')}",
            tr(locale, "item_unit"),
            tr(locale, "item_original_quantity"),
            tr(locale, "item_new_quantity"),
            tr(locale, "item_original_rate"),
            tr(locale, "item_new_rate"),
            f"{tr(locale, 'item_cost_delta')} ({printed_currency(currency, locale)})"
            if currency
            else tr(locale, "item_cost_delta"),
        ]
        item_rows = [header]
        total = Decimal(0)
        for item in items:
            delta = _decimal(getattr(item, "cost_delta", None))
            if delta is not None:
                total += delta
            item_rows.append(
                [
                    "\n".join(
                        part
                        for part in (
                            str(getattr(item, "description", "") or "").strip(),
                            CATALOGUE.label("change", getattr(item, "change_type", None), locale),
                        )
                        if part and part != "-"
                    )
                    or "-",
                    str(getattr(item, "unit", "") or "-"),
                    _quantity(getattr(item, "original_quantity", None), style),
                    _quantity(getattr(item, "new_quantity", None), style),
                    _rate(getattr(item, "original_rate", None), style),
                    _rate(getattr(item, "new_rate", None), style),
                    format_amount(delta, style),
                ]
            )
        # The items are all in the order's one currency, so one total is the
        # whole sum and nothing is added across currencies.
        item_rows.append([tr(locale, "total"), "", "", "", "", "", format_amount(total, style)])
        blocks.append(
            RecordBlock(
                tr(locale, "items"),
                kind="table",
                rows=item_rows,
                weights=[4.4, 0.8, 1.1, 1.1, 1.3, 1.3, 1.5],
                right_aligned=[False, False, True, True, True, True, True],
                keep_together=[False, True, True, True, True, True, True],
                total_rows=1,
            )
        )
    blocks.append(
        RecordBlock(
            tr(locale, "signatures"),
            kind="signatures",
            rows=CATALOGUE.signature_rows(
                locale, [(tr(locale, "submitted_by"), submitter), (tr(locale, "approved_by"), approver)]
            ),
        )
    )
    status = CATALOGUE.label("status", getattr(order, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "doc_title"),
        number=str(getattr(order, "code", "") or ""),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=str(getattr(order, "title", "") or ""),
        grid=grid,
        blocks=blocks,
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )


def build_change_order_pdf(order: Any, **context: Any) -> bytes:
    """Render one change order as a PDF form; see :func:`change_order_record`."""
    return build_record_pdf(change_order_record(order, **context))
