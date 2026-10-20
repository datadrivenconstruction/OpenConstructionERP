# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""A report a person opens should read like a document - issue #441.

``run_report`` flattens each KPI's breakdown into ``breakdown__<key>``
columns and hands the rows straight to the renderer, so the PDF printed
``breakdown__ac_by_currency`` as a heading and
``{'EUR': Decimal('100000.00')}`` as a cell. Both are Python, in a
document sent to a client.

The row keys themselves are left alone: ``ReportRunResponse.rows`` is the
JSON the API returns and something machine-side matches on those keys.
Only the printed heading changes.

These tests read the PDF, which is one of three writers, and that is the
reason the XLSX and CSV shipped the defect for a further commit. What
every format has to say is asserted in
``test_bi_dashboards_every_writer_is_readable.py``; this file stays on
the PDF because the PDF is the one whose page geometry is at stake.

The reported third symptom, wide tables losing their right hand columns,
was already fixed - ``build_pdf_report`` computes column widths through
``pdf_table_column_widths``. That behaviour has its own tests in
``test_pdf_exports_stay_on_the_page.py`` and is not re-asserted here,
beyond one check that these changes did not undo it.

Run:
    cd backend
    python -m pytest tests/unit/test_bi_dashboards_report_is_readable.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal

import pypdf
import pytest

from app.modules.bi_dashboards.report_builder import (
    _format_cell,
    build_pdf_report,
    humanize_column,
)

#: The row shape ``run_report`` emits for one EVM KPI: four fixed columns
#: plus one column per breakdown key.
_EAC_ROW: dict[str, object] = {
    "kpi_code": "eac",
    "value": "123456.7890",
    "unit": "currency",
    "source_record_count": 42,
    "breakdown__ac_by_currency": {"EUR": Decimal("100000.00"), "USD": Decimal("23456.79")},
    "breakdown__missing_fx_codes": ["GBP", "CHF"],
    "breakdown__bac": Decimal("150000"),
    "breakdown__base_currency": "EUR",
}


def _pdf_text(rows: list[dict[str, object]], name: str = "readable_report") -> str:
    path, _size = build_pdf_report(report_name=name, rows=rows)
    try:
        reader = pypdf.PdfReader(path)
        return "\n".join(page.extract_text() for page in reader.pages)
    finally:
        if os.path.exists(path):
            os.remove(path)


def _collapse(text: str) -> str:
    """Join the line breaks reportlab inserts to wrap a cell.

    Extracted text carries the wrap points, so a heading that reads
    correctly on the page arrives here as ``Breakdown: AC\\nby currency``.
    Asserting on the collapsed form checks the words, which is what a
    reader sees; where the words break is the width test's question.
    """
    return " ".join(text.split())


# ── Headings ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("kpi_code", "KPI code"),
        ("value", "Value"),
        ("source_record_count", "Source record count"),
        ("breakdown__ac_by_currency", "Breakdown: AC by currency"),
        ("breakdown__missing_fx_codes", "Breakdown: Missing FX codes"),
        ("breakdown__bac", "Breakdown: BAC"),
        ("_section", "Section"),
        ("task_id", "Task ID"),
        ("earned_value", "Earned value"),
    ],
)
def test_humanize_column(key: str, expected: str) -> None:
    assert humanize_column(key) == expected


def test_humanize_leaves_a_heading_that_is_already_prose_alone() -> None:
    """Report columns are arbitrary - many are already written for a reader."""
    assert humanize_column("Column 0") == "Column 0"
    assert humanize_column("Rectification of defective works") == "Rectification of defective works"


def test_the_pdf_prints_headings_not_row_keys() -> None:
    text = _collapse(_pdf_text([_EAC_ROW]))
    assert "Breakdown: AC by currency" in text
    assert "KPI code" in text
    assert "breakdown__" not in text
    assert "source_record_count" not in text


# ── Cells ──────────────────────────────────────────────────────────────


def test_a_breakdown_dict_renders_as_pairs_a_reader_can_parse() -> None:
    rendered = _format_cell({"EUR": Decimal("100000.00"), "USD": Decimal("23456.79")})
    assert rendered == "EUR: 100,000; USD: 23,456.79"
    assert "Decimal" not in rendered
    assert "{" not in rendered


def test_a_list_renders_as_a_list_of_values() -> None:
    assert _format_cell(["GBP", "CHF"]) == "GBP, CHF"
    assert _format_cell([]) == ""
    assert _format_cell({}) == ""


def test_a_set_renders_in_a_stable_order() -> None:
    """Two runs of the same report must not disagree about the cell."""
    assert _format_cell({"GBP", "CHF", "SEK"}) == "CHF, GBP, SEK"


def test_a_boolean_is_not_dragged_through_the_decimal_branch() -> None:
    """``bool`` is an ``int``, so an order mistake here prints True as 1."""
    assert _format_cell(True) == "True"
    assert _format_cell(False) == "False"


def test_the_pdf_prints_no_python_literals() -> None:
    text = _pdf_text([_EAC_ROW])
    assert "Decimal(" not in text
    assert "'EUR'" not in text
    collapsed = _collapse(text)
    assert "EUR: 100,000; USD: 23,456.79" in collapsed
    assert "GBP, CHF" in collapsed


# ── The fix that was already there ─────────────────────────────────────


def test_the_wide_table_fix_still_holds_with_the_new_headings() -> None:
    """Longer headings must not push the table back off the sheet.

    Column widths are computed from this very table, headings included, so
    a change to the headings is a change to the width input. The geometry
    is measured rather than assumed, because a text extractor happily
    reads a column that was drawn onto no paper at all.
    """
    from app.core import pdf_reader

    rows = [dict(_EAC_ROW), {**_EAC_ROW, "kpi_code": "cpi", "breakdown__note": "x" * 120}]
    path, _size = build_pdf_report(report_name="wide_readable", rows=rows)
    try:
        with pdf_reader.open_pdf(path) as doc:
            page = doc[0]
            rightmost = max(word[2] for word in page.words())
            assert rightmost <= page.rect.x1, (
                f"ink reaches {rightmost:.0f}pt on a {page.rect.x1:.0f}pt sheet, so a column is off the page"
            )
    finally:
        if os.path.exists(path):
            os.remove(path)
