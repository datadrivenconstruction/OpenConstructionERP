# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The measurement sheet's CSV download does not hand a spreadsheet a formula.

Every text cell of a measurement sheet comes from a user or an imported file:
the reference, the description, the formula, the unit, the error. A cell that
starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return is run as a
formula by the spreadsheet that opens the file, so the download writes such a
cell as text, with the same helper the cost and BoQ exports use. The figures
the sheet computes itself (factor, sign, quantity) are numbers and stay as
they are, or a deduction would stop reading as a negative number.
"""

import csv
import io

import pytest

from app.modules.measurement import build_sheet, render_csv

_PROBES = [
    '=HYPERLINK("http://x","y")',
    "+cmd|' /C calc'!A0",
    "-2+3",
    "@SUM(1,2)",
    "\t=1+1",
    "\r=1+1",
]
_TEXT_COLUMNS = ("ref", "description", "unit")


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


@pytest.mark.parametrize("probe", _PROBES)
@pytest.mark.parametrize("column", _TEXT_COLUMNS)
def test_a_text_cell_that_would_run_as_a_formula_is_written_as_text(column: str, probe: str) -> None:
    line = {"description": "wall", "formula": "2", "ref": "A1", "unit": "m2", column: probe}
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=[line])
    cell = _rows(render_csv(sheet))[0][column]
    # A description is stored trimmed, so a leading tab or CR is gone before
    # it is written; whatever remains must still start with the apostrophe.
    assert cell[:1] == "'", cell
    assert cell[1:].strip() == probe.strip()


def test_a_formula_that_starts_like_one_is_written_as_text() -> None:
    sheet = build_sheet(item_ref="1", description="d", unit="m2", lines=[{"description": "x", "formula": "-2+3"}])
    assert _rows(render_csv(sheet))[0]["formula"] == "'-2+3"


def test_an_error_echoing_the_input_is_written_as_text() -> None:
    sheet = build_sheet(
        item_ref="1",
        description="d",
        unit="m2",
        lines=[{"description": "x", "formula": '=HYPERLINK("http://x","y")'}],
        strict=False,
    )
    row = _rows(render_csv(sheet))[0]
    assert row["formula"].startswith("'=")
    assert not row["error"] or row["error"][0] not in "=+-@\t\r"


def test_the_computed_figures_stay_numbers() -> None:
    sheet = build_sheet(
        item_ref="1",
        description="d",
        unit="m2",
        lines=[{"description": "opening", "formula": "1.5", "sign": "-", "factor": "2"}],
    )
    rows = _rows(render_csv(sheet))
    assert rows[0]["sign"] == "-"
    assert rows[0]["quantity"] == "-3.000"
    assert rows[0]["factor"] == "2"
    assert rows[1]["quantity"] == "-3.000"
