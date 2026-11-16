# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Import of a customer-owned rate table (CSV or XLSX) into a rate catalogue version.

The importer only maps columns. It ships no list content and no values: the customer brings
the table their company licenses. A :class:`ColumnProfile` says which source column feeds
which field, whether the numbers use a decimal comma, and which fields are written as
percent in the table (stored as fractions). Parsing is a dry run until the caller commits.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.equipment.rate_math import to_decimal
from app.modules.equipment.rate_validators import import_row_issue

#: Fields a rate item takes from the table. ``required`` ones must be numbers on every row.
TEXT_FIELDS: tuple[str, ...] = ("code", "name", "category", "size_key")
REQUIRED_NUMBER_FIELDS: tuple[str, ...] = (
    "value",
    "residual",
    "life_years",
    "months_per_year",
    "interest",
    "repair",
    "hours_per_month",
)
OPTIONAL_NUMBER_FIELDS: tuple[str, ...] = ("override_monthly_rate", "operating_cost_per_hour")
ALL_FIELDS: tuple[str, ...] = TEXT_FIELDS + REQUIRED_NUMBER_FIELDS + OPTIONAL_NUMBER_FIELDS

MAX_ROWS = 20000


@dataclass(frozen=True)
class ColumnProfile:
    """Which source column feeds which item field."""

    mapping: dict[str, str]
    decimal_comma: bool = False
    percent_fields: tuple[str, ...] = ("interest", "repair")


@dataclass
class ImportResult:
    """Outcome of one dry run."""

    items: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    total_rows: int = 0
    error_rows: int = 0

    @property
    def ready(self) -> int:
        return len(self.items)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def rows_from_csv(data: bytes) -> list[list[str]]:
    """Header row plus data rows of a CSV, delimiter sniffed from the first line."""
    text = _decode(data)
    first = text.split("\n", 1)[0]
    delimiter = max((";", "\t", ",", "|"), key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]


def rows_from_xlsx(data: bytes) -> list[list[str]]:
    """Header row plus data rows of the first sheet of an XLSX file."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows: list[list[str]] = []
        for raw in sheet.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in raw]
            if any(cells):
                rows.append(cells)
            if len(rows) > MAX_ROWS + 1:
                break
        return rows
    finally:
        workbook.close()


def read_table(filename: str, data: bytes) -> list[list[str]]:
    """Rows of an uploaded table, by file extension."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        return rows_from_xlsx(data)
    return rows_from_csv(data)


def _number(raw: str, decimal_comma: bool) -> Decimal | None:
    text = raw.strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if decimal_comma:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    return to_decimal(text)


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Obvious header matches by field name (no national layout is assumed)."""
    wanted = {
        "code": ("code", "id", "no"),
        "name": ("name", "machine", "description"),
        "category": ("category", "group"),
        "size_key": ("size", "capacity"),
        "value": ("value", "price", "new value"),
        "residual": ("residual", "salvage"),
        "life_years": ("life", "years"),
        "months_per_year": ("months",),
        "interest": ("interest",),
        "repair": ("repair",),
        "hours_per_month": ("hours",),
    }
    lowered = {h: h.lower() for h in headers}
    out: dict[str, str] = {}
    for fld, needles in wanted.items():
        for header, low in lowered.items():
            if any(low == n or low.startswith(n) for n in needles) and header not in out.values():
                out[fld] = header
                break
    return out


def parse_table(rows: list[list[str]], profile: ColumnProfile) -> ImportResult:
    """Dry run: items that are ready and one issue per bad field per bad row.

    Row numbers count the header as row 1, so they match what the user sees in a sheet.
    """
    result = ImportResult()
    if not rows:
        return result
    headers = rows[0]
    index = {h: i for i, h in enumerate(headers)}
    body = rows[1 : MAX_ROWS + 1]
    result.total_rows = len(body)
    for offset, raw in enumerate(body):
        number = offset + 2
        item: dict[str, Any] = {}
        row_issues: list[dict[str, Any]] = []
        for fld in TEXT_FIELDS:
            col = profile.mapping.get(fld)
            item[fld] = raw[index[col]].strip() if col in index and index[col] < len(raw) else ""
        if not item["code"]:
            row_issues.append(import_row_issue(number, "code"))
        if not item["name"]:
            row_issues.append(import_row_issue(number, "name"))
        for fld in REQUIRED_NUMBER_FIELDS + OPTIONAL_NUMBER_FIELDS:
            col = profile.mapping.get(fld)
            cell = raw[index[col]] if col in index and index[col] < len(raw) else ""
            value = _number(cell, profile.decimal_comma)
            if value is None:
                if fld in REQUIRED_NUMBER_FIELDS:
                    row_issues.append(import_row_issue(number, fld))
                item[fld] = None
                continue
            item[fld] = value / Decimal(100) if fld in profile.percent_fields else value
        if row_issues:
            result.issues.extend(row_issues)
            result.error_rows += 1
        else:
            result.items.append(item)
    return result
