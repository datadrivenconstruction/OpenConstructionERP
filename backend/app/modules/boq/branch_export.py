# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable branch comparison (PDF and XLSX) on :mod:`app.core.register_export`.

Three views of one compare: every position, totals by section, totals by cost
group. Labels come from the backend locale files under ``boq.branch.export``,
so the sheet is in the reader's language wherever a translation exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from app.core.i18n import t
from app.core.regional_format import number_style
from app.core.register_export import (
    RegisterColumn,
    RegisterDocument,
    build_register_pdf,
    build_register_xlsx,
    export_filename,
    format_amount,
)

ExportView = Literal["positions", "sections", "cost_groups"]
ExportFormat = Literal["xlsx", "pdf"]


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def comparison_document(
    compare: dict[str, Any],
    *,
    view: ExportView,
    project_name: str,
    country: str | None,
    locale: str,
) -> RegisterDocument:
    """Build the register for one view of a branch compare."""

    def tr(key: str, **kwargs: Any) -> str:
        return t(f"boq.branch.export.{key}", locale=locale, **kwargs)

    currency = compare.get("currency") or ""
    style = number_style(country, currency)
    summary = compare["summary"]
    a_name, b_name = compare["a_name"], compare["b_name"]

    if view == "positions":
        columns = [
            RegisterColumn(tr("col_ordinal"), nobreak=True, xlsx_width=12),
            RegisterColumn(tr("col_description"), weight=3.0, wrap=True, xlsx_width=48),
            RegisterColumn(tr("col_unit"), xlsx_width=8),
            RegisterColumn(tr("col_change"), xlsx_width=14),
            RegisterColumn(tr("col_qty_a"), nobreak=True),
            RegisterColumn(tr("col_qty_b"), nobreak=True),
            RegisterColumn(tr("col_rate_a"), kind="money"),
            RegisterColumn(tr("col_rate_b"), kind="money"),
            RegisterColumn(tr("col_total_a"), kind="money", total=True),
            RegisterColumn(tr("col_total_b"), kind="money", total=True),
            RegisterColumn(tr("col_delta"), kind="money", total=True),
        ]
        rows = [
            [
                r["ordinal"],
                r["description"],
                r["unit"],
                tr(f"change_{r['change_type']}"),
                r.get("a_quantity") or "",
                r.get("b_quantity") or "",
                _dec(r.get("a_unit_rate")),
                _dec(r.get("b_unit_rate")),
                _dec(r.get("a_total")),
                _dec(r.get("b_total")),
                _dec(r.get("delta")),
            ]
            for r in compare["rows"]
            if r["change_type"] != "unchanged"
        ]
    else:
        groups = compare["by_section"] if view == "sections" else compare["by_cost_group"]
        label_key = "col_section" if view == "sections" else "col_cost_group"
        columns = [
            RegisterColumn(tr(label_key), weight=3.0, wrap=True, xlsx_width=48),
            RegisterColumn(tr("col_total_a"), kind="money", total=True),
            RegisterColumn(tr("col_total_b"), kind="money", total=True),
            RegisterColumn(tr("col_delta"), kind="money", total=True),
        ]
        rows = [
            [g["label"] or tr("ungrouped"), _dec(g["total_a"]), _dec(g["total_b"]), _dec(g["delta"])] for g in groups
        ]

    title = tr(f"title_{view}")
    return RegisterDocument(
        title=title,
        columns=columns,
        rows=rows,
        details=[
            (tr("project"), project_name or "-"),
            (tr("bill_a"), a_name),
            (tr("bill_b"), b_name),
            (tr("total_a"), format_amount(summary["total_a"], style, currency)),
            (tr("total_b"), format_amount(summary["total_b"], style, currency)),
            (tr("delta"), format_amount(summary["delta"], style, currency)),
            (
                tr("counts"),
                tr(
                    "counts_value",
                    added=summary["added"],
                    removed=summary["removed"],
                    changed=summary["changed"],
                ),
            ),
        ],
        locale=locale,
        number_style=style,
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        empty_text=tr("empty"),
        sheet_title=title,
        totals_label=tr("total"),
        currency=currency,
    )


def render(document: RegisterDocument, fmt: ExportFormat) -> bytes:
    """Render the register as XLSX or PDF bytes."""
    if fmt == "xlsx":
        return build_register_xlsx(document).getvalue()
    return build_register_pdf(document)


def filename(a_name: str, b_name: str, fmt: ExportFormat) -> str:
    """A download name that names both bills."""
    return export_filename(f"{a_name}_vs_{b_name}", "branch_compare", fmt)
