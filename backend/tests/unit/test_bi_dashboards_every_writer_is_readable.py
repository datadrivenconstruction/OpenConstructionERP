# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A report reads like a document in every format it is offered in.

``build_report`` dispatches on ``output_format``, which is a per-report
setting somebody chose once. The readability work that stopped the PDF
printing ``breakdown__ac_by_currency`` and ``{'EUR': Decimal('100000.00')}``
reached exactly one of the three writers, and the other two shipped the
original defect:

* the XLSX shared the cell formatter and not the heading logic, so the
  same report opened as a spreadsheet still had ``breakdown__ac_by_currency``
  across the top;
* the CSV shared neither, so it stringified through ``str`` and wrote a
  Python dict repr into a cell.

**The assertions here are per format, deliberately.** The tests that came
with the PDF fix read the PDF only, and that is the whole reason two
writers stayed broken through a change whose commit message said the fix
was shared. A test suite that checks the one format somebody happened to
be looking at cannot tell "fixed" from "fixed in the format under the
lamp", so the last test in the first section asserts the three formats
agree with each other rather than each agreeing with itself.

A second defect only shows up in a cell: a ``top_by`` KPI's breakdown is
``{group: {"label": ..., "value": ...}}`` and ``run_report`` flattens one
level, so ``_format_cell`` receives the inner record and printed
``label: Precast beam; value: 12345.6789``. Those two words are field
names from the query layer, printed at the reader.

Run:
    cd backend
    python -m pytest tests/unit/test_bi_dashboards_every_writer_is_readable.py -v
"""

from __future__ import annotations

import csv
import os
from decimal import Decimal
from typing import Any

import pypdf
import pytest

from app.modules.bi_dashboards.report_builder import (
    _format_cell,
    build_csv_report,
    build_pdf_report,
    build_xlsx_report,
    export_widget_csv,
    humanize_column,
)

#: The row shape ``run_report`` emits for one EVM KPI: four fixed columns
#: plus one column per breakdown key.
_EAC_ROW: dict[str, Any] = {
    "kpi_code": "eac",
    "value": "123456.7890",
    "unit": "currency",
    "source_record_count": 42,
    "breakdown__ac_by_currency": {"EUR": Decimal("100000.00"), "USD": Decimal("23456.79")},
    "breakdown__missing_fx_codes": ["GBP", "CHF"],
    "breakdown__bac": Decimal("150000"),
    "breakdown__base_currency": "EUR",
}

#: What a reader has to see, whichever format they opened. Written out
#: rather than derived from ``humanize_column`` and ``_format_cell``: a
#: test that computes its expectation the way the code does agrees with
#: the code by construction and cannot fail.
_EXPECTED_HEADINGS: list[str] = [
    "KPI code",
    "Value",
    "Unit",
    "Source record count",
    "Breakdown: AC by currency",
    "Breakdown: Missing FX codes",
    "Breakdown: BAC",
    "Breakdown: Base currency",
]
_EXPECTED_CELLS: list[str] = [
    "eac",
    "123456.7890",
    "currency",
    "42",
    "EUR: 100,000; USD: 23,456.79",
    "GBP, CHF",
    "150,000",
    "EUR",
]

#: One group of a ``top_by`` KPI, as ``kpi_spec._evaluate_top_by`` builds
#: it and ``run_report`` flattens it. The group key is the column, the
#: record below it is the cell.
_TOP_BY_ROW: dict[str, Any] = {
    "kpi_code": "largest_position_per_bid",
    "value": "12345.6789",
    "unit": "currency",
    "source_record_count": 3,
    "breakdown__WBS-01": {"label": "Precast beam", "value": "12345.6789"},
}


def _csv_table(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    """Read a CSV report back as ``(headings, data rows)``."""
    path, _size = build_csv_report(report_name="every_writer", rows=rows)
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            table = list(csv.reader(handle))
    finally:
        if os.path.exists(path):
            os.remove(path)
    return table[0], table[1:]


def _xlsx_table(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    """Read an XLSX report back as ``(headings, data rows)``."""
    openpyxl = pytest.importorskip("openpyxl")
    path, _size = build_xlsx_report(report_name="every_writer", rows=rows)
    try:
        sheet = openpyxl.load_workbook(path).active
        table = [["" if cell is None else str(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        if os.path.exists(path):
            os.remove(path)
    return table[0], table[1:]


def _pdf_text(rows: list[dict[str, Any]]) -> str:
    """Extract a PDF report's text, with reportlab's wrap points joined.

    A heading that reads correctly on the page arrives from the extractor
    as ``Breakdown: AC\\nby currency``; where it breaks is the width
    tests' question, not this file's.
    """
    path, _size = build_pdf_report(report_name="every_writer", rows=rows)
    try:
        reader = pypdf.PdfReader(path)
        return " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Headings, per format ───────────────────────────────────────────────


def test_the_xlsx_prints_headings_not_row_keys() -> None:
    """The heading row was the one thing the XLSX did not share."""
    headings, _data = _xlsx_table([_EAC_ROW])
    assert headings == _EXPECTED_HEADINGS


def test_the_csv_prints_headings_not_row_keys() -> None:
    headings, _data = _csv_table([_EAC_ROW])
    assert headings == _EXPECTED_HEADINGS


# ── Cells, per format ──────────────────────────────────────────────────


def test_the_csv_prints_no_python_literals() -> None:
    """``csv.DictWriter`` stringifies through ``str``, which is the defect."""
    _headings, data = _csv_table([_EAC_ROW])
    assert data == [_EXPECTED_CELLS]


def test_the_xlsx_prints_no_python_literals() -> None:
    """The control: the XLSX already shared the cell formatter."""
    _headings, data = _xlsx_table([_EAC_ROW])
    assert data == [_EXPECTED_CELLS]


# ── The three writers have to agree ────────────────────────────────────


def test_every_format_of_one_report_says_the_same_thing() -> None:
    """The test the PDF-only suite could not be.

    Each writer builds its own column list and its own heading row, so
    "the formatter is shared" was true of the cells and false of the
    headings, and nothing failed. Asserting the formats against each
    other is what catches the next writer that goes its own way.
    """
    csv_headings, csv_data = _csv_table([_EAC_ROW])
    xlsx_headings, xlsx_data = _xlsx_table([_EAC_ROW])
    assert csv_headings == xlsx_headings
    assert csv_data == xlsx_data

    pdf = _pdf_text([_EAC_ROW])
    for heading in csv_headings:
        assert heading in pdf, f"the PDF is missing the heading {heading!r} that the CSV and XLSX print"
    for cell in csv_data[0]:
        assert cell in pdf, f"the PDF is missing the cell {cell!r} that the CSV and XLSX print"


@pytest.mark.parametrize("reader", [_csv_table, _xlsx_table])
def test_no_format_leaks_the_api_shape(reader: Any) -> None:
    headings, data = reader([_EAC_ROW])
    printed = " ".join(headings + [cell for row in data for cell in row])
    assert "breakdown__" not in printed
    assert "source_record_count" not in printed
    assert "Decimal(" not in printed
    assert "{" not in printed


# ── A top_by record is not two field names ─────────────────────────────


def test_a_top_by_record_prints_its_label_and_its_value() -> None:
    """``{"label": ..., "value": ...}`` is a record, not a mapping of data.

    The generic mapping branch renders keys and values alike, which is
    right for ``{"EUR": 100000}`` where the key is a currency and wrong
    here, where the keys are the names of the query's own columns.
    """
    assert _format_cell({"label": "Precast beam", "value": "12345.6789"}) == "Precast beam: 12345.6789"


def test_a_top_by_record_with_nothing_to_label_prints_only_its_value() -> None:
    assert _format_cell({"label": "", "value": "12345.6789"}) == "12345.6789"
    assert _format_cell({"label": None, "value": "12345.6789"}) == "12345.6789"


def test_a_mapping_that_is_not_a_record_still_renders_as_pairs() -> None:
    """The record branch must not swallow a breakdown whose keys are data."""
    assert _format_cell({"label": "x", "value": "y", "unit": "m3"}) == "label: x; value: y; unit: m3"
    assert _format_cell({"EUR": Decimal("100000.00")}) == "EUR: 100,000"


@pytest.mark.parametrize("reader", [_csv_table, _xlsx_table])
def test_no_format_prints_the_words_label_and_value_as_data(reader: Any) -> None:
    headings, data = reader([_TOP_BY_ROW])
    assert headings[-1] == "Breakdown: WBS-01"
    assert data[0][-1] == "Precast beam: 12345.6789"


def test_the_pdf_does_not_print_the_words_label_and_value_as_data() -> None:
    pdf = _pdf_text([_TOP_BY_ROW])
    assert "Precast beam: 12345.6789" in pdf
    assert "label:" not in pdf
    assert "value: 12345.6789" not in pdf


# ── The key for a group that had no value ──────────────────────────────


def test_the_reserved_key_for_an_absent_group_is_not_printed_as_itself() -> None:
    """``__null__`` is a key a consumer recognises, not a word a reader reads.

    ``kpi_spec`` keys rows with no value in the grouped column on a
    reserved name so that a consumer can tell them from a group whose
    value is the text "(unset)" - the two used to collide and one group
    was lost. This module is the consumer that turns that name back into
    something printable, and left alone the word splitter reads it as
    "Null", which is the plumbing showing through in a different spelling.
    """
    assert humanize_column("breakdown____null__") == "Breakdown: (not set)"
    assert _format_cell("__null__") == "(not set)"
    assert _format_cell({"label": "__null__", "value": "12345.6789"}) == "(not set): 12345.6789"


@pytest.mark.parametrize("reader", [_csv_table, _xlsx_table])
def test_no_format_prints_the_reserved_key_for_an_absent_group(reader: Any) -> None:
    headings, data = reader([{**_TOP_BY_ROW, "breakdown____null__": {"label": "__null__", "value": "9"}}])
    printed = " ".join(headings + [cell for row in data for cell in row])
    assert "__null__" not in printed
    assert "(not set)" in printed


def test_a_widget_export_gets_the_same_cell_as_a_report() -> None:
    """The fourth writer in this module, and it is not a report writer.

    ``export_widget_csv`` dumps one widget's breakdown as key/value pairs
    rather than as a table, so it shares ``_format_cell`` and nothing
    else. It carries the same breakdowns, so the record that used to print
    the query's field names printed them here too.
    """
    path, _size = export_widget_csv(
        widget_label="largest_position_per_bid",
        breakdown={"WBS-01": {"label": "Precast beam", "value": "12345.6789"}},
    )
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            table = list(csv.reader(handle))
    finally:
        if os.path.exists(path):
            os.remove(path)
    assert table[1] == ["WBS-01", "Precast beam: 12345.6789"]
