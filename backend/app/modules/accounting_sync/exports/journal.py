# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Generic​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ journal export (CSV and Excel) with configurable columns.

Works in any country: one row per debit or credit line of the neutral journal.
The connection's ``settings.journal_columns`` picks and orders the columns;
amounts are written as exact decimal strings (CSV) or numbers with two decimals
(Excel), never floats rounded twice.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from app.modules.accounting_sync.postings import JournalLine

#: Every column the export knows, in default order.
JOURNAL_COLUMNS: tuple[str, ...] = (
    "entry_no",
    "posting_date",
    "document_number",
    "source",
    "account",
    "account_name",
    "debit",
    "credit",
    "currency",
    "tax_code",
    "tax_key",
    "tax_rate",
    "tax_amount",
    "cost_centre",
    "project",
    "counterparty",
    "description",
)


def resolve_columns(requested: list[str] | None) -> list[str]:
    """Known columns in the requested order; the full default set when none are given."""
    cols = [c for c in (requested or []) if c in JOURNAL_COLUMNS]
    return cols or list(JOURNAL_COLUMNS)


def _cell(line: JournalLine, col: str) -> Any:
    value = getattr(line, col)
    if col == "posting_date":
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:.2f}" if col != "tax_rate" else str(value)
    return "" if value is None else value


def to_csv(lines: list[JournalLine], columns: list[str] | None = None, delimiter: str = ",") -> bytes:
    """UTF-8 CSV with a BOM so spreadsheet tools detect the encoding."""
    cols = resolve_columns(columns)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(cols)
    for ln in lines:
        writer.writerow([_cell(ln, c) for c in cols])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(lines: list[JournalLine], columns: list[str] | None = None) -> bytes:
    """Excel workbook with one sheet ``Journal``; money columns as numbers with two decimals."""
    from openpyxl import Workbook

    cols = resolve_columns(columns)
    wb = Workbook()
    ws = wb.active
    ws.title = "Journal"
    ws.append(cols)
    money_cols = {"debit", "credit", "tax_amount"}
    for ln in lines:
        row = []
        for c in cols:
            value = getattr(ln, c)
            row.append(value if c in money_cols else _cell(ln, c))
        ws.append(row)
    for i, c in enumerate(cols, start=1):
        if c in money_cols:
            for cell in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                for x in cell:
                    x.number_format = "#,##0.00"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
