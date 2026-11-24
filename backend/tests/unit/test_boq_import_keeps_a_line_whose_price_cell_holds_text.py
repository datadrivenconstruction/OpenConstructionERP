# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill line whose rate or quantity cell holds text is imported at 0, with a warning.

Bills carry "PM", "Inclus", "-" in the price column. Dropping the row loses a
line of the bill; the import keeps it, quotes the cell in a warning and in the
position's metadata.
"""

from __future__ import annotations

import asyncio
import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.modules.boq.importers.excel import ExcelImporter  # noqa: E402


def _workbook(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["No", "Description", "Unit", "Quantity", "Unit rate", "Total"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_text_unit_rate_imports_at_zero_with_a_warning() -> None:
    content = _workbook(
        [
            ["1.1", "Concrete", "m3", 10, 100, 1000],
            ["1.2", "Scaffolding", "m2", 5, "PM", None],
            ["1.3", "Cleaning", "m2", 5, "-", None],
            ["1.4", "Paint", "m2", 5, 0, 0],
        ]
    )
    result = asyncio.run(ExcelImporter.parse(content))

    assert not result.errors
    by_desc = {p.description: p for p in result.positions}
    assert set(by_desc) == {"Concrete", "Scaffolding", "Cleaning", "Paint"}
    assert by_desc["Scaffolding"].unit_rate == 0.0
    assert by_desc["Scaffolding"].quantity == 5.0
    assert by_desc["Scaffolding"].metadata["non_numeric_cells"] == {"unit_rate": "PM"}
    messages = [w["message"] for w in result.warnings]
    assert any("'PM'" in m and "not a number" in m for m in messages)
    assert any("'-'" in m for m in messages)


def test_text_quantity_imports_at_zero_with_a_warning() -> None:
    content = _workbook([["1.1", "Provisional sum", "item", "PM", 250, None]])
    result = asyncio.run(ExcelImporter.parse(content))

    assert not result.errors
    (position,) = result.positions
    assert position.quantity == 0.0
    assert position.unit_rate == 250.0
    assert position.metadata["non_numeric_cells"] == {"quantity": "PM"}
