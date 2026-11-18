# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule PDF import: the activity table of a printed programme read through the spreadsheet parser.

Fixtures are drawn in the test with reportlab: a vector print in the layout a
planning tool produces (table left, timescale and bars right, a page footer),
and an image-only page standing in for a scan.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from app.modules.schedule import pdf_table
from app.modules.schedule.tabular_import import preview
from app.modules.schedule.validators import PDF_IMPORT_RULE_SET

HEADER = ("ID", "Task Name", "Duration", "Start", "Finish", "Predecessors")
COLUMNS_X = (30, 60, 250, 310, 390, 470)
ROW_PITCH = 16


def _schedule_pdf(pages: list[list[tuple[str, ...]]], *, indent: dict[str, int] | None = None) -> bytes:
    """Rows per page; ``indent`` shifts a task name right by that many outline steps."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=landscape(A4))
    _, height = landscape(A4)
    for rows in pages:
        pdf.setFont("Helvetica", 8)
        y = height - 60
        for x, label in zip(COLUMNS_X, HEADER, strict=True):
            pdf.drawString(x, y, label)
        pdf.drawString(580, y, "Feb 2026")
        pdf.drawString(680, y, "Mar 2026")
        for row in rows:
            y -= ROW_PITCH
            for x, value in zip(COLUMNS_X, row, strict=False):
                shift = 10 * (indent or {}).get(value, 0) if x == COLUMNS_X[1] else 0
                pdf.drawString(x + shift, y, value)
            pdf.rect(580, y, 60, 6, fill=1)
            pdf.drawString(650, y, "Crew A")
        pdf.drawString(30, 30, "Project: Riverside block   Page 1")
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _scanned_pdf() -> bytes:
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    image = Image.new("RGB", (200, 100), "white")
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.drawImage(ImageReader(image), 50, 500, width=400, height=200)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


ROWS = [
    ("1", "Site works", "15 days", "Mon 2/2/26", "Fri 2/20/26", ""),
    ("2", "Excavation", "5 days", "Mon 2/2/26", "Fri 2/6/26", ""),
    ("3", "Foundations", "10 days", "Mon 2/9/26", "Fri 2/20/26", "2"),
    ("4", "Handover", "0 days", "Fri 2/20/26", "Fri 2/20/26", "3"),
]


def _codes(result, severity: str | None = None) -> list[str]:
    return [i.code for i in result.issues if severity is None or i.severity == severity]


def test_vector_print_reads_rows_dates_and_hierarchy() -> None:
    data = _schedule_pdf([ROWS], indent={"Excavation": 1, "Foundations": 1})
    result = preview(data, "programme.pdf")
    assert result.file_format == "pdf"
    assert not result.has_errors, result.issues
    acts = result.document["activities"]
    assert [a["name"] for a in acts] == ["Site works", "Excavation", "Foundations", "Handover"]
    assert acts[1]["start_date"] == date(2026, 2, 2).isoformat()
    assert acts[2]["end_date"] == date(2026, 2, 20).isoformat()
    assert acts[2]["duration_days"] == 10
    # 2/20 cannot be day/month, so the order comes from the values.
    assert result.date_order == "mdy"
    assert result.outline_source == "indent"
    parent = acts[0]["ref"]
    assert acts[1]["parent_ref"] == parent and acts[2]["parent_ref"] == parent
    assert acts[3]["parent_ref"] is None
    assert result.relationship_count == 2


def test_bar_labels_timescale_and_footer_stay_out_of_the_table() -> None:
    table = pdf_table.read_pdf_table(_schedule_pdf([ROWS]))
    assert table.rows[0] == HEADER
    assert len(table.rows) == 1 + len(ROWS)
    assert all("Crew A" not in " ".join(row) for row in table.rows)
    assert all("Page" not in " ".join(row) for row in table.rows)


def test_repeated_header_on_the_next_page_is_skipped() -> None:
    data = _schedule_pdf([ROWS[:2], ROWS[2:]])
    result = preview(data, "programme.pdf")
    assert result.activity_count == 4
    assert not result.has_errors, result.issues


def test_ambiguous_numeric_dates_are_flagged_until_the_order_is_chosen() -> None:
    rows = [
        ("1", "Excavation", "3 days", "03/02/2026", "05/02/2026", ""),
        ("2", "Foundations", "2 days", "06/02/2026", "09/02/2026", "1"),
    ]
    data = _schedule_pdf([rows])
    result = preview(data, "programme.pdf")
    assert "date_order_unconfirmed" in _codes(result)
    confirmed = preview(data, "programme.pdf", date_order="dmy")
    assert confirmed.document["activities"][0]["start_date"] == "2026-02-03"
    assert "date_order_unconfirmed" not in _codes(confirmed)


def test_checks_finish_before_start_duplicate_and_unknown_predecessor() -> None:
    rows = [
        ("1", "Excavation", "5 days", "Mon 2/9/26", "Fri 2/6/26", ""),
        ("1", "Foundations", "10 days", "Mon 2/9/26", "Fri 2/20/26", ""),
        ("3", "Walls", "4 days", "Mon 2/23/26", "Thu 2/26/26", "99"),
        ("4", "Roof", "9 days", "Mon 3/2/26", "Fri 3/6/26", "3"),
    ]
    result = preview(_schedule_pdf([rows]), "programme.pdf")
    codes = _codes(result)
    assert "finish_before_start" in codes
    assert "duplicate_id" in codes
    assert "predecessor_unknown" in codes
    assert "duration_mismatch" in codes
    assert result.has_errors


def test_unparsable_date_is_an_error_on_its_row() -> None:
    rows = [("1", "Excavation", "5 days", "next week", "Fri 2/6/26", "")]
    result = preview(_schedule_pdf([rows]), "programme.pdf")
    issue = next(i for i in result.issues if i.code == "date_invalid")
    assert issue.severity == "error"
    assert issue.row == 2


def test_scan_without_text_layer_is_refused_with_the_other_imports_named() -> None:
    result = preview(_scanned_pdf(), "scan.pdf")
    assert _codes(result) == ["pdf_no_text_layer"]
    assert "MS Project XML" in result.issues[0].message
    assert result.document is None


def test_text_without_a_schedule_table_is_refused() -> None:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.drawString(50, 700, "Minutes of the site meeting")
    pdf.showPage()
    pdf.save()
    assert _codes(preview(buf.getvalue(), "minutes.pdf")) == ["pdf_table_not_found"]


def test_damaged_pdf_is_unreadable() -> None:
    assert _codes(preview(b"%PDF-1.7\n...", "plan.pdf")) == ["file_unreadable"]


@pytest.mark.asyncio
async def test_pdf_import_rules_report_preview_issues() -> None:
    from app.core.validation.engine import validation_engine

    rows = [("1", "Excavation", "5 days", "Mon 2/9/26", "Fri 2/6/26", "")]
    result = preview(_schedule_pdf([rows]), "programme.pdf")
    report = await validation_engine.validate(
        {"issues": [i.to_dict() for i in result.issues]}, [PDF_IMPORT_RULE_SET], target_type="schedule"
    )
    failed = {r.rule_id for r in report.results if not r.passed}
    assert "schedule_pdf_import.finish_before_start" in failed
    assert "schedule_pdf_import.no_text_layer" not in failed

    scan = preview(_scanned_pdf(), "scan.pdf")
    report = await validation_engine.validate(
        {"issues": [i.to_dict() for i in scan.issues]}, [PDF_IMPORT_RULE_SET], target_type="schedule"
    )
    assert {r.rule_id for r in report.results if not r.passed} == {"schedule_pdf_import.no_text_layer"}
