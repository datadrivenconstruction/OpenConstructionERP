# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill as the market's estimate sheet, in the column order the pack lays down.

The pack names the columns (``export_layout`` in its pricing file) by neutral
field keys and gives each a label per language and the form column it fills.
This module knows the fields, not the market: it splits each line's per-unit
resources into labour, machines and materials, multiplies by the quantity,
and writes the sheet. Nothing here names a country or a form.

Fields a layout may use: ``ordinal``, ``norm_code``, ``description``, ``unit``,
``quantity``, ``unit_rate``, ``unit_labour``, ``unit_machine``,
``unit_material``, ``total``, ``total_labour``, ``total_machine``,
``total_material``, ``labour_hours_unit``, ``labour_hours_total``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.norm_bases import label_in, quantize_money

FIELDS = frozenset(
    {
        "ordinal",
        "norm_code",
        "description",
        "unit",
        "quantity",
        "unit_rate",
        "unit_labour",
        "unit_machine",
        "unit_material",
        "total",
        "total_labour",
        "total_machine",
        "total_material",
        "labour_hours_unit",
        "labour_hours_total",
    }
)
_MONEY = frozenset(
    {
        "unit_rate",
        "unit_labour",
        "unit_machine",
        "unit_material",
        "total",
        "total_labour",
        "total_machine",
        "total_material",
    }
)
_KIND = {
    "labor": "labour",
    "labour": "labour",
    "machine": "machine",
    "equipment": "machine",
    "machinery": "machine",
    "material": "material",
    "materials": "material",
}


def _dec(value: Any) -> Decimal:
    if value is None or isinstance(value, bool) or value == "":
        return Decimal("0")
    try:
        out = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return out if out.is_finite() else Decimal("0")


def resource_split(metadata: dict[str, Any] | None) -> dict[str, Decimal]:
    """Per-unit labour, machine and material money and labour hours of one line.

    Resource rows are per-unit norms (``quantity`` per one unit of the line), so
    ``quantity x unit_rate`` of each row is its share of the unit rate.
    """
    out = {"labour": Decimal("0"), "machine": Decimal("0"), "material": Decimal("0"), "hours": Decimal("0")}
    rows = (metadata or {}).get("resources")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        kind = _KIND.get(str(row.get("type") or "").strip().lower())
        if kind is None:
            continue
        qty = _dec(row.get("quantity"))
        out[kind] += qty * _dec(row.get("unit_rate"))
        if kind == "labour":
            out["hours"] += qty
    return out


@dataclass
class Sheet:
    """The sheet as values: header labels, form column numbers, body rows, summary rows."""

    title: str
    labels: list[str]
    form_columns: list[str]
    money_columns: list[int]
    rows: list[list[Any]] = field(default_factory=list)
    section_rows: list[int] = field(default_factory=list)
    summary: list[tuple[str, Decimal]] = field(default_factory=list)
    #: Index of the column the summary amounts stand under (the line total).
    total_column: int | None = None


def _line_values(pos: dict[str, Any], classification_key: str) -> dict[str, Any]:
    qty = _dec(pos.get("quantity"))
    split = resource_split(pos.get("metadata"))
    classification = pos.get("classification") or {}
    values: dict[str, Any] = {
        "ordinal": pos.get("ordinal") or "",
        "norm_code": str(classification.get(classification_key) or "") if classification_key else "",
        "description": pos.get("description") or "",
        "unit": pos.get("unit") or "",
        "quantity": qty,
        "unit_rate": quantize_money(_dec(pos.get("unit_rate"))),
        "total": quantize_money(_dec(pos.get("total"))),
        "labour_hours_unit": split["hours"],
        "labour_hours_total": (split["hours"] * qty).quantize(Decimal("0.0001")).normalize(),
    }
    for kind, name in (("labour", "labour"), ("machine", "machine"), ("material", "material")):
        values[f"unit_{name}"] = quantize_money(split[kind])
        values[f"total_{name}"] = quantize_money(split[kind] * qty)
    return values


def build_sheet(
    layout: dict[str, Any],
    structured: dict[str, Any],
    *,
    classification_key: str,
    locale: str | None,
) -> Sheet:
    """Lay a structured bill out in the pack's columns.

    ``structured`` is the bill as every export reads it: ``sections`` (each with
    ``ordinal``, ``description`` and ``positions``), ungrouped ``positions``,
    ``direct_cost``, ``markups`` (``name``, ``amount``) and ``grand_total``.
    """
    columns = [c for c in layout.get("columns") or [] if isinstance(c, dict) and c.get("field") in FIELDS]
    if not columns:
        raise ValueError("the layout names no known column")
    fields = [str(c["field"]) for c in columns]
    sheet = Sheet(
        title=label_in(layout.get("title") or {}, locale),
        labels=[label_in(c.get("label") or c["field"], locale) for c in columns],
        form_columns=[str(c.get("form_column") or "") for c in columns],
        money_columns=[i for i, f in enumerate(fields) if f in _MONEY],
        total_column=fields.index("total") if "total" in fields else None,
    )
    labour = material = Decimal("0")

    def add_lines(positions: list[dict[str, Any]]) -> None:
        nonlocal labour, material
        for pos in positions:
            values = _line_values(pos, classification_key)
            labour += values["total_labour"]
            material += values["total_material"]
            sheet.rows.append([values[f] for f in fields])

    for section in structured.get("sections") or []:
        head = [""] * len(fields)
        text = " ".join(p for p in (section.get("ordinal"), section.get("description")) if p)
        head[fields.index("description") if "description" in fields else 0] = text
        sheet.section_rows.append(len(sheet.rows))
        sheet.rows.append(head)
        add_lines(section.get("positions") or [])
    add_lines(structured.get("positions") or [])

    words = layout.get("summary") or {}
    sheet.summary.append((label_in(words.get("direct") or "Direct costs", locale), _dec(structured.get("direct_cost"))))
    if "materials" in words:
        sheet.summary.append((label_in(words["materials"], locale), material))
    if "labour" in words:
        sheet.summary.append((label_in(words["labour"], locale), labour))
    for markup in structured.get("markups") or []:
        if markup.get("is_active", True):
            sheet.summary.append((str(markup.get("name") or ""), quantize_money(_dec(markup.get("amount")))))
    sheet.summary.append(
        (label_in(words.get("grand_total") or "Total", locale), quantize_money(_dec(structured.get("grand_total"))))
    )
    return sheet


def render_xlsx(sheet: Sheet, *, heading: str = "") -> bytes:
    """The sheet as an xlsx workbook: title, header, form column numbers, lines, summary."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet.title or "Estimate")[:31]
    ws.append([sheet.title])
    ws["A1"].font = Font(bold=True, size=12)
    if heading:
        ws.append([heading])
    ws.append([])
    header_row = ws.max_row + 1
    ws.append(sheet.labels)
    ws.append(sheet.form_columns)
    for cell in ws[header_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    for cell in ws[header_row + 1]:
        cell.alignment = Alignment(horizontal="center")
    first_body = ws.max_row + 1
    for i, row in enumerate(sheet.rows):
        ws.append(row)
        if i in sheet.section_rows:
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
    money_letters = {get_column_letter(i + 1) for i in sheet.money_columns}
    for row in ws.iter_rows(min_row=first_body, max_row=ws.max_row):
        for cell in row:
            if cell.column_letter in money_letters and isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00"
    ws.append([])
    label_col = 3 if len(sheet.labels) >= 3 else 1
    value_col = sheet.total_column + 1 if sheet.total_column is not None else len(sheet.labels)
    for text, amount in sheet.summary:
        ws.append([])
        r = ws.max_row
        ws.cell(row=r, column=label_col, value=text)
        cell = ws.cell(row=r, column=value_col, value=amount)
        cell.number_format = "#,##0.00"
    ws.cell(row=ws.max_row, column=label_col).font = Font(bold=True)
    widths = {1: 8, 2: 14, 3: 48}
    for i in range(1, len(sheet.labels) + 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(i, 14)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
