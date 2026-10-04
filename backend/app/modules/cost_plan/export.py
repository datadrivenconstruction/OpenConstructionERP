# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Excel workbook of an NRM 1 cost plan.

Built from the same :class:`CostPlanResponse` the screen renders, row for row.
Nothing is computed here: a workbook that summed its own rows would be a second
rollup, and the first time it disagreed with the screen nobody could say which
one to believe. Totals are written as values, not formulas, so the file says
what the plan said on the day it was exported.

Labels come from a small catalogue in this file, resolved through
:mod:`app.core.document_locale` like the platform's other documents. Element
and group names are data from the NRM 1 table and are written as they are.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.core.document_locale import translate
from app.core.xlsx_branding import apply_company_header
from app.core.xlsx_text import store_strings_as_text
from app.modules.cost_plan.engine import FACILITATING_GROUP
from app.modules.cost_plan.schemas import CostPlanResponse, GroupRow, MarkupRow, SubtotalRow

__all__ = ["DEFAULT_LOCALE", "EXPORT_LOCALES", "build_cost_plan_workbook", "label"]

DEFAULT_LOCALE = "en"

_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "sheet_plan": "NRM 1 cost plan",
        "sheet_unallocated": "Not allocated",
        "title": "Elemental cost plan (NRM 1)",
        "bill": "Bill of quantities",
        "currency": "Currency",
        "gifa": "GIFA (m2)",
        "gifa_project": "from the project",
        "gifa_entered": "entered for this export",
        "gifa_none": "not set, cost per m2 not shown",
        "col_code": "Code",
        "col_description": "Element",
        "col_positions": "Positions",
        "col_basis": "Basis",
        "col_total": "Total",
        "col_per_m2": "Cost per m2 GIFA",
        "col_share": "% of total",
        "col_running": "Running total",
        "group_level": "Group level, no element given",
        "facilitating_works_estimate": "Facilitating works estimate",
        "works_estimate": "Building works estimate",
        "addons_heading": "NRM 1 groups 9-14 priced as bill items",
        "unallocated": "Not allocated to an element",
        "direct_cost": "Direct cost of the bill",
        "markups_heading": "Markups (the bill's own cascade, in order)",
        "markups_total": "Markups total",
        "grand_total": "Cost plan total",
        "basis_direct": "{pct}% on direct cost",
        "basis_running": "{pct}% on running subtotal",
        "basis_lump": "Lump sum",
        "basis_banded": "Banded scale",
        "basis_escalation": "Index escalation",
        "basis_other": "{kind}",
        "basis_scoped": "section-scoped",
        "col_ordinal": "Ordinal",
        "col_position": "Description",
        "col_written_code": "Code as written",
        "col_reason": "Reason",
        "reason_no_code": "No NRM code on the position or its sections",
        "reason_invalid_code": "Code is not an NRM number",
        "reason_unknown_group": "NRM 1 has no such group",
        "truncated": "List shortened to the first {shown} of {count} positions; the total covers all of them.",
    },
    "de": {
        "sheet_plan": "NRM 1 Kostenplan",
        "sheet_unallocated": "Nicht zugeordnet",
        "title": "Elementbasierter Kostenplan (NRM 1)",
        "bill": "Leistungsverzeichnis",
        "currency": "Währung",
        "gifa": "BGF innen (m2)",
        "gifa_project": "aus dem Projekt",
        "gifa_entered": "für diesen Export eingegeben",
        "gifa_none": "nicht gesetzt, Kosten je m2 nicht ausgewiesen",
        "col_code": "Code",
        "col_description": "Element",
        "col_positions": "Positionen",
        "col_basis": "Bezugsbasis",
        "col_total": "Summe",
        "col_per_m2": "Kosten je m2 BGF",
        "col_share": "% der Summe",
        "col_running": "Laufende Summe",
        "group_level": "Gruppenebene, kein Element angegeben",
        "facilitating_works_estimate": "Kosten der vorbereitenden Maßnahmen",
        "works_estimate": "Kosten der Bauleistungen",
        "addons_heading": "NRM 1 Gruppen 9-14 als Positionen bepreist",
        "unallocated": "Keinem Element zugeordnet",
        "direct_cost": "Direkte Kosten des LV",
        "markups_heading": "Zuschläge (Reihenfolge des LV)",
        "markups_total": "Zuschläge gesamt",
        "grand_total": "Summe Kostenplan",
        "basis_direct": "{pct}% auf direkte Kosten",
        "basis_running": "{pct}% auf laufende Zwischensumme",
        "basis_lump": "Pauschale",
        "basis_banded": "Staffel",
        "basis_escalation": "Indexgleitung",
        "basis_other": "{kind}",
        "basis_scoped": "abschnittsbezogen",
        "col_ordinal": "OZ",
        "col_position": "Beschreibung",
        "col_written_code": "Code wie erfasst",
        "col_reason": "Grund",
        "reason_no_code": "Kein NRM-Code an der Position oder ihren Abschnitten",
        "reason_invalid_code": "Code ist keine NRM-Nummer",
        "reason_unknown_group": "Diese Gruppe gibt es in NRM 1 nicht",
        "truncated": "Liste auf die ersten {shown} von {count} Positionen gekürzt; die Summe umfasst alle.",
    },
    "ru": {
        "sheet_plan": "План затрат NRM 1",
        "sheet_unallocated": "Не распределено",
        "title": "Поэлементный план затрат (NRM 1)",
        "bill": "Ведомость объемов работ",
        "currency": "Валюта",
        "gifa": "Внутренняя площадь (м2)",
        "gifa_project": "из проекта",
        "gifa_entered": "введена для этого экспорта",
        "gifa_none": "не задана, стоимость за м2 не показана",
        "col_code": "Код",
        "col_description": "Элемент",
        "col_positions": "Позиций",
        "col_basis": "База",
        "col_total": "Сумма",
        "col_per_m2": "Стоимость за м2",
        "col_share": "% от итога",
        "col_running": "Нарастающий итог",
        "group_level": "Уровень группы, элемент не указан",
        "facilitating_works_estimate": "Стоимость подготовительных работ",
        "works_estimate": "Стоимость строительных работ",
        "addons_heading": "Группы NRM 1 9-14, оцененные позициями ведомости",
        "unallocated": "Не отнесено к элементу",
        "direct_cost": "Прямые затраты ведомости",
        "markups_heading": "Начисления (каскад ведомости по порядку)",
        "markups_total": "Начисления всего",
        "grand_total": "Итого по плану затрат",
        "basis_direct": "{pct}% от прямых затрат",
        "basis_running": "{pct}% от нарастающего итога",
        "basis_lump": "Фиксированная сумма",
        "basis_banded": "Ступенчатая шкала",
        "basis_escalation": "Индексация",
        "basis_other": "{kind}",
        "basis_scoped": "только для раздела",
        "col_ordinal": "Номер",
        "col_position": "Описание",
        "col_written_code": "Код как записан",
        "col_reason": "Причина",
        "reason_no_code": "Нет кода NRM у позиции и ее разделов",
        "reason_invalid_code": "Код не является номером NRM",
        "reason_unknown_group": "В NRM 1 нет такой группы",
        "truncated": "Список сокращен до первых {shown} из {count} позиций; итог учитывает все.",
    },
}

#: The languages this workbook can be written in.
EXPORT_LOCALES: frozenset[str] = frozenset(_LABELS)

_MONEY_FORMAT = "#,##0.00"
_PCT_FORMAT = "0.00"
_BOLD = Font(bold=True)
_HEADER_FILL = PatternFill("solid", fgColor="E8EEF5")
_TOTAL_FILL = PatternFill("solid", fgColor="F3F4F6")

# Column layout, 1-based.
_COL_CODE, _COL_DESC, _COL_POS, _COL_BASIS, _COL_TOTAL, _COL_M2, _COL_SHARE, _COL_RUNNING = range(1, 9)


def label(locale: str, key: str, **params: Any) -> str:
    """One catalogue string in ``locale`` (English when missing)."""
    return translate(_LABELS, locale, key, DEFAULT_LOCALE, **params)


def _num(value: Decimal | None) -> float | None:
    """A Decimal as a spreadsheet number, or an empty cell."""
    return None if value is None else float(value)


def _plain_pct(value: Decimal | None) -> str:
    """A percentage as written by the estimator, without trailing zeros."""
    if value is None:
        return ""
    text = format(value.normalize(), "f")
    return text


class _Writer:
    """Appends rows to the plan sheet and remembers which rows are totals."""

    def __init__(self, ws: Any, locale: str) -> None:
        self.ws = ws
        self.locale = locale

    def money_row(
        self,
        *,
        code: str = "",
        description: str,
        row: SubtotalRow,
        positions: int | None = None,
        basis: str = "",
        running: Decimal | None = None,
        bold: bool = False,
        fill: PatternFill | None = None,
        indent: int = 0,
    ) -> None:
        self.ws.append(
            [
                code,
                description,
                positions,
                basis,
                _num(row.total),
                _num(row.cost_per_m2),
                _num(row.share_pct),
                _num(running),
            ]
        )
        index = self.ws.max_row
        for col in (_COL_TOTAL, _COL_M2, _COL_RUNNING):
            self.ws.cell(row=index, column=col).number_format = _MONEY_FORMAT
        self.ws.cell(row=index, column=_COL_SHARE).number_format = _PCT_FORMAT
        if indent:
            self.ws.cell(row=index, column=_COL_DESC).alignment = Alignment(indent=indent)
        if bold or fill is not None:
            for col in range(_COL_CODE, _COL_RUNNING + 1):
                cell = self.ws.cell(row=index, column=col)
                if bold:
                    cell.font = _BOLD
                if fill is not None:
                    cell.fill = fill

    def heading(self, text: str) -> None:
        self.ws.append([text])
        self.ws.cell(row=self.ws.max_row, column=1).font = _BOLD

    def group(self, group: GroupRow, *, show_empty_elements: bool) -> None:
        self.money_row(
            code=group.code,
            description=group.name,
            row=group,
            positions=group.position_count,
            bold=True,
        )
        for element in group.elements:
            if not show_empty_elements and element.position_count == 0 and element.total == 0:
                continue
            self.money_row(
                code=element.code,
                description=element.name,
                row=element,
                positions=element.position_count,
                indent=1,
            )
        if group.group_level is not None:
            codes = ", ".join(group.group_level.codes)
            self.money_row(
                code=codes,
                description=label(self.locale, "group_level"),
                row=group.group_level,
                positions=group.group_level.position_count,
                indent=1,
            )


def _basis(line: MarkupRow, locale: str) -> str:
    """How a markup line was priced, in words."""
    kind = (line.markup_type or "percentage").lower()
    if kind == "fixed":
        text = label(locale, "basis_lump")
    elif kind == "percentage":
        compounding = (line.apply_to or "").lower() in ("cumulative", "subtotal")
        key = "basis_running" if compounding else "basis_direct"
        text = label(locale, key, pct=_plain_pct(line.percentage))
    elif kind == "banded":
        text = label(locale, "basis_banded")
    elif kind == "escalation":
        text = label(locale, "basis_escalation")
    else:
        text = label(locale, "basis_other", kind=line.markup_type)
    if line.scoped:
        text = f"{text} ({label(locale, 'basis_scoped')})"
    return text


def build_cost_plan_workbook(plan: CostPlanResponse, *, locale: str = DEFAULT_LOCALE) -> bytes:
    """Write the cost plan as an .xlsx file and return its bytes.

    Args:
        plan: The plan exactly as the API returns it.
        locale: One of :data:`EXPORT_LOCALES`; anything else writes English.

    Returns:
        The workbook bytes.
    """
    if locale not in EXPORT_LOCALES:
        locale = DEFAULT_LOCALE
    wb = Workbook()
    ws = wb.active
    ws.title = label(locale, "sheet_plan")[:31]

    gifa_note = label(locale, f"gifa_{plan.gifa_source}")
    ws.append([label(locale, "title")])
    ws.cell(row=1, column=1).font = Font(bold=True, size=13)
    ws.append([label(locale, "bill"), plan.boq_name])
    ws.append([label(locale, "currency"), plan.currency])
    ws.append([label(locale, "gifa"), _num(plan.gifa), gifa_note])
    ws.append([])

    header = [
        label(locale, "col_code"),
        label(locale, "col_description"),
        label(locale, "col_positions"),
        label(locale, "col_basis"),
        label(locale, "col_total"),
        label(locale, "col_per_m2"),
        label(locale, "col_share"),
        label(locale, "col_running"),
    ]
    ws.append(header)
    for col in range(1, len(header) + 1):
        cell = ws.cell(row=ws.max_row, column=col)
        cell.font = _BOLD
        cell.fill = _HEADER_FILL
    header_row = ws.max_row

    writer = _Writer(ws, locale)
    # NRM 1 subtotals group 0 on its own and groups 1-8 on their own; the
    # building works estimate never carries the facilitating works. The code
    # column of the building subtotal names its range ("1-8") so a reader sees
    # what it sums without a new label.
    for group in plan.groups:
        if group.code == FACILITATING_GROUP:
            writer.group(group, show_empty_elements=False)
    writer.money_row(
        description=label(locale, "facilitating_works_estimate"),
        row=plan.facilitating_works_estimate,
        bold=True,
        fill=_TOTAL_FILL,
    )
    building_codes = [g.code for g in plan.groups if g.code != FACILITATING_GROUP]
    for group in plan.groups:
        if group.code != FACILITATING_GROUP:
            writer.group(group, show_empty_elements=False)
    writer.money_row(
        code=f"{building_codes[0]}-{building_codes[-1]}" if building_codes else "",
        description=label(locale, "works_estimate"),
        row=plan.building_works_estimate,
        bold=True,
        fill=_TOTAL_FILL,
    )

    priced_addons = [g for g in plan.addon_groups if g.position_count or g.total]
    if priced_addons:
        ws.append([])
        writer.heading(label(locale, "addons_heading"))
        for group in priced_addons:
            writer.group(group, show_empty_elements=False)

    ws.append([])
    writer.money_row(
        description=label(locale, "unallocated"),
        row=plan.unallocated,
        positions=plan.unallocated.position_count,
    )
    writer.money_row(
        description=label(locale, "direct_cost"),
        row=plan.direct_cost,
        positions=plan.position_count,
        bold=True,
        fill=_TOTAL_FILL,
    )

    if plan.markups:
        ws.append([])
        writer.heading(label(locale, "markups_heading"))
        for line in plan.markups:
            writer.money_row(
                description=line.name,
                row=line,
                basis=_basis(line, locale),
                running=line.running_total,
                indent=1,
            )
        writer.money_row(description=label(locale, "markups_total"), row=plan.markups_total, bold=True)

    writer.money_row(
        description=label(locale, "grand_total"),
        row=plan.grand_total,
        running=plan.grand_total.total,
        bold=True,
        fill=_TOTAL_FILL,
    )

    widths = {"A": 12, "B": 52, "C": 11, "D": 30, "E": 18, "F": 18, "G": 12, "H": 18}
    for column, width in widths.items():
        ws.column_dimensions[column].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    _write_unallocated_sheet(wb, plan, locale)

    for sheet in wb.worksheets:
        store_strings_as_text(sheet)
    apply_company_header(ws)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _write_unallocated_sheet(wb: Workbook, plan: CostPlanResponse, locale: str) -> None:
    """List every unallocated position, so the gap can be worked off."""
    block = plan.unallocated
    if not block.position_count:
        return
    ws = wb.create_sheet(label(locale, "sheet_unallocated")[:31])
    header = [
        label(locale, "col_ordinal"),
        label(locale, "col_position"),
        label(locale, "col_written_code"),
        label(locale, "col_reason"),
        label(locale, "col_total"),
    ]
    ws.append(header)
    for col in range(1, len(header) + 1):
        ws.cell(row=1, column=col).font = _BOLD
        ws.cell(row=1, column=col).fill = _HEADER_FILL
    for position in block.positions:
        ws.append(
            [
                position.ordinal,
                position.description,
                position.code or "",
                label(locale, f"reason_{position.reason}"),
                _num(position.total),
            ]
        )
        ws.cell(row=ws.max_row, column=5).number_format = _MONEY_FORMAT
    if block.positions_truncated:
        ws.append([])
        ws.append([label(locale, "truncated", shown=len(block.positions), count=block.position_count)])
    for column, width in {"A": 12, "B": 60, "C": 16, "D": 44, "E": 18}.items():
        ws.column_dimensions[column].width = width
