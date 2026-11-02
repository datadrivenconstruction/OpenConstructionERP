# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared builders for owner schedule tests: an owner workbook and a CSV."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

FIXTURES = Path(__file__).parent / "fixtures"


def agency_workbook(rows: list[tuple] | None = None) -> bytes:
    """An owner file in the example pack format: title block, fixed columns, formula total."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Bid Schedule"
    ws["A1"] = "Contract 24-117 Bid Schedule"
    ws["A1"].font = Font(bold=True)
    ws["A3"] = "Bidder:"
    ws["A5"], ws["B5"], ws["C5"], ws["D5"], ws["E5"], ws["F5"] = "Item", "Description", "Unit", "Qty", "Price", "Amount"
    rows = rows or [
        ("0201-001", "Clearing and grubbing", "LS", None),
        ("0203-010", "Unclassified excavation", "CY", 1234.5),
        ("0401-005", "Asphalt base course", "TON", 333.333),
        ("ALT-1", "Alternate: colored concrete", "SY", 120),
    ]
    r = 6
    for no, desc, unit, qty in rows:
        ws.cell(r, 1, no)
        ws.cell(r, 2, desc)
        ws.cell(r, 3, unit)
        if qty is not None:
            ws.cell(r, 4, qty)
        r += 1
    ws.cell(r, 1, "TOTAL")
    ws.cell(r, 6, f"=SUM(F6:F{r - 1})")
    ws.protection.sheet = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generic_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"
    ws.append(["Owner project"])
    ws.append([])
    ws.append(["Item No.", "Description", "Unit", "Quantity", "Unit Price", "Amount"])
    ws.append(["1", "Earthworks", None, None, None, None])
    ws.append(["1.1", "Excavation", "m3", 100, None, None])
    ws.append(["1.2", "Backfill", "m3", 40.5, None, None])
    ws.append(["2", "Concrete", None, None, None, None])
    ws.append(["2.1", "Foundations", "m3", 12.25, None, None])
    ws.append(["Total", None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generic_csv() -> bytes:
    return (
        b"Item No.;Description;Unit;Quantity;Unit Price;Amount\r\n"
        b"1.1;Excavation;m3;100;;\r\n"
        b"1.2;Backfill;m3;40,5;;\r\n"
        b"Total;;;;;\r\n"
    )


@pytest.fixture
def agency_profile():
    import json

    from app.modules.owner_schedule.profile import ScheduleProfile

    data = json.loads((FIXTURES / "pack_profile.json").read_text(encoding="utf-8"))
    return ScheduleProfile.model_validate({**data, "key": "example-pack." + data["key"], "source": "pack"})
