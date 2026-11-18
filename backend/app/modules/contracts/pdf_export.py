# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed form of one contract: its terms, parties and schedule of values.

The context is pure, like :mod:`app.modules.changeorders.pdf_export`; the form is a
document layout (:mod:`app.modules.contracts.layouts`) the firm can restyle in the
document editor. Amounts stay ``Decimal`` from the row to the page.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.doc_templates.layout.spec import LayoutContext
from app.core.regional_format import NumberStyle, format_number
from app.core.register_export import (
    ProjectHeader,
    RecordDocument,
    build_record_pdf,
    caps,
    format_amount,
    format_stored_date,
    printed_currency,
)
from app.modules.contracts.pdf_translations import (
    CATALOGUE,
    DEFAULT_PDF_LOCALE,
    contract_pdf_filename,
    normalize_pdf_locale,
    tr,
)

__all__ = ["build_contract_pdf", "contract_context", "contract_record"]


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _trimmed(value: Any, style: NumberStyle, *, least: int, most: int) -> str:
    """The stored digits, between ``least`` and ``most`` decimals."""
    number = _decimal(value)
    if number is None:
        return "-"
    exponent = number.normalize().as_tuple().exponent
    decimals = max(least, min(most, -exponent if isinstance(exponent, int) else least))
    return format_number(number, decimals, style)


def _formatter(style: NumberStyle, date_format: str) -> Any:
    def _format(fmt: str, value: Any) -> str:
        if value is None or value == "":
            return "-"
        if fmt == "money":
            return format_amount(value, style)
        if fmt in {"quantity", "number"}:
            return _trimmed(value, style, least=2, most=4)
        if fmt == "percent":
            return f"{_trimmed(value, style, least=0, most=2)} %"
        if fmt == "date":
            return format_stored_date(value, date_format)
        return str(value).strip() or "-"

    return _format


def contract_context(
    contract: Any,
    lines: list[Any],
    *,
    project: ProjectHeader,
    counterparty: str | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> LayoutContext:
    """One contract's data for its document layout, formatted in the document language.

    Args:
        contract: The contract row, or any object with the same attributes.
        lines: Its schedule of values lines.
        project: The owning project.
        counterparty: The counterparty's resolved name; the party role when ``None``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    from app.core.doc_templates.seller import resolve_seller

    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    style = project.number_style
    currency = (str(getattr(contract, "currency", "") or "").strip().upper()) or project.currency
    role = str(getattr(contract, "counterparty_type", "") or "client")
    status_code = getattr(contract, "status", None) or "draft"
    status = CATALOGUE.label("status", status_code, locale)
    party = (counterparty or "").strip() or CATALOGUE.label("party", role, locale)

    def _money(name: str) -> str:
        return format_amount(getattr(contract, name, None), style, currency, locale=locale)

    def _date(name: str) -> str:
        return format_stored_date(getattr(contract, name, None), date_format)

    retention = getattr(contract, "retention_percent", None)
    values = {
        **resolve_seller().as_fields(),
        "project.name": project.name or "",
        "project.code": project.code or "",
        "project.label": project.label,
        "doc.generated": generated,
        "doc.number": str(getattr(contract, "code", "") or ""),
        "doc.title": str(getattr(contract, "title", "") or ""),
        "doc.type": CATALOGUE.label("type", getattr(contract, "contract_type", None), locale),
        "doc.role": CATALOGUE.label("party", role, locale),
        "doc.counterparty": party,
        "doc.status": status,
        "doc.currency": currency,
        "doc.total_value": _money("total_value"),
        "doc.original_value": _money("original_contract_value"),
        "doc.retention_percent": f"{_trimmed(retention, style, least=0, most=2)} %" if retention is not None else "",
        "doc.start_date": _date("start_date"),
        "doc.end_date": _date("end_date"),
        "doc.signed_at": _date("signed_at"),
    }
    raw = {
        "doc.number": values["doc.number"] or None,
        "doc.title": values["doc.title"] or None,
        "doc.type": getattr(contract, "contract_type", None),
        "doc.role": role,
        "doc.counterparty": (counterparty or "").strip() or None,
        "doc.status": status_code,
        "doc.currency": currency or None,
        "doc.total_value": _decimal(getattr(contract, "total_value", None)),
        "doc.original_value": _decimal(getattr(contract, "original_contract_value", None)),
        "doc.retention_percent": _decimal(retention),
        "doc.start_date": getattr(contract, "start_date", None),
        "doc.end_date": getattr(contract, "end_date", None),
        "doc.signed_at": getattr(contract, "signed_at", None),
        "project.name": project.name or None,
    }
    rows = []
    for line in sorted(lines, key=lambda ln: getattr(ln, "order_index", 0) or 0):
        total = _decimal(getattr(line, "total_value", None))
        rows.append(
            {
                "code": (getattr(line, "code", None), str(getattr(line, "code", "") or "-")),
                "description": (
                    getattr(line, "description", None),
                    str(getattr(line, "description", "") or "-"),
                ),
                "unit": (getattr(line, "unit", None), str(getattr(line, "unit", "") or "-")),
                "quantity": (
                    _decimal(getattr(line, "quantity", None)),
                    _trimmed(getattr(line, "quantity", None), style, least=2, most=4),
                ),
                "unit_rate": (
                    _decimal(getattr(line, "unit_rate", None)),
                    _trimmed(getattr(line, "unit_rate", None), style, least=2, most=4),
                ),
                "total_value": (total, format_amount(total, style)),
            }
        )
    total_label = tr(locale, "col_total_value")
    labels = {
        "field:doc.number": tr(locale, "col_code"),
        "field:doc.title": tr(locale, "col_title"),
        "field:doc.type": tr(locale, "col_type"),
        "field:doc.role": tr(locale, "col_role"),
        "field:doc.counterparty": tr(locale, "col_counterparty"),
        "field:doc.status": tr(locale, "status"),
        "field:doc.total_value": total_label,
        "field:doc.original_value": tr(locale, "col_original_value"),
        "field:doc.retention_percent": tr(locale, "col_retention"),
        "field:doc.start_date": tr(locale, "col_start"),
        "field:doc.end_date": tr(locale, "col_end"),
        "field:doc.signed_at": tr(locale, "col_signed"),
        "column:lines.code": tr(locale, "line_code"),
        "column:lines.description": tr(locale, "line_description"),
        "column:lines.unit": tr(locale, "line_unit"),
        "column:lines.quantity": tr(locale, "line_quantity"),
        "column:lines.unit_rate": tr(locale, "line_unit_rate"),
        "column:lines.total_value": f"{total_label} ({printed_currency(currency, locale)})"
        if currency
        else total_label,
        "section:lines": tr(locale, "lines"),
        "section:signatures": tr(locale, "signatures"),
        "signer:entity.legal_name": tr(locale, "signer_company"),
        "signer:doc.counterparty": tr(locale, "col_counterparty"),
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
        collections={"lines": rows},
        sections={},
        base=base,
        status=str(status_code).lower(),
        format=_formatter(style, date_format),
        signature_rows=lambda signers: CATALOGUE.signature_rows(locale, list(signers)),
        project_id=getattr(contract, "project_id", None),
        filename=contract_pdf_filename(getattr(contract, "code", None)),
        empty="-",
    )


def contract_record(
    contract: Any,
    lines: list[Any],
    *,
    project: ProjectHeader,
    template: Mapping[str, Any] | None = None,
    **context: Any,
) -> RecordDocument:
    """Describe the printable form of one contract; the standard layout unless ``template`` is given."""
    from app.core.doc_templates.layout.compile import compile_layout
    from app.modules.contracts.layouts import CONTRACT, contract_standard

    ctx = contract_context(contract, lines, project=project, **context)
    return compile_layout(template or contract_standard(), CONTRACT, ctx)


def build_contract_pdf(contract: Any, lines: list[Any], **context: Any) -> bytes:
    """Render one contract as a PDF form; see :func:`contract_record`."""
    return build_record_pdf(contract_record(contract, lines, **context))
