# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ schedule export to Excel and PDF.

Excel cells carry the exact amounts as numbers built from the Decimal string (openpyxl
writes a Decimal as its decimal text), so no float rounding enters the workbook.
Column headings are English, as in the other register exports; the screen is translated.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

COLUMNS: tuple[tuple[str, str], ...] = (
    ("project_name", "Project"),
    ("currency", "Currency"),
    ("contract_value", "Contract value incl. approved changes"),
    ("estimated_cost", "Estimated total cost"),
    ("cost_to_date", "Cost to date"),
    ("percent_complete", "Percent complete"),
    ("earned_revenue", "Earned revenue"),
    ("billed_to_date", "Billed to date"),
    ("over_billing", "Over billing"),
    ("under_billing", "Under billing"),
    ("projected_gross_profit", "Projected gross profit"),
    ("fade", "Fade or gain"),
    ("backlog", "Backlog"),
)
_TEXT = {"project_name", "currency"}


def to_xlsx(data: dict[str, Any]) -> bytes:
    """Workbook with one sheet of project rows and one of totals per currency."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "WIP schedule"
    ws.append([f"WIP schedule as of {data['as_of']}"])
    ws["A1"].font = Font(bold=True)
    ws.append([label for _, label in COLUMNS])
    for cell in ws[2]:
        cell.font = Font(bold=True)
    for row in data["rows"]:
        ws.append([row.get(key) if key in _TEXT else row.get(key) for key, _ in COLUMNS])
    for col in ws.iter_cols(min_row=3, min_col=3):
        for cell in col:
            cell.number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 36
    totals = wb.create_sheet("Totals")
    keys = [k for k, _ in COLUMNS if k not in ("project_name", "fade")] + ["fade"]
    totals.append(["Projects", *[dict(COLUMNS)[k] for k in keys]])
    for t in data["totals"]:
        totals.append([t["projects"], *[t.get(k) for k in keys]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    try:
        return format(value, ",.2f")
    except (TypeError, ValueError):
        return str(value)


def to_pdf(data: dict[str, Any]) -> bytes:
    """Landscape A4 table of the schedule with the totals under it."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = "Helvetica"
    try:
        from app.core.pdf_fonts import register_pdf_fonts

        if register_pdf_fonts():
            font = "DejaVuSans"
    except Exception:  # noqa: BLE001 - fall back to the built-in face
        font = "Helvetica"

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm)
    head = [label for _, label in COLUMNS]
    body = [[str(r.get(k) or "") if k in _TEXT else _fmt(r.get(k)) for k, _ in COLUMNS] for r in data["rows"]]
    for t in data["totals"]:
        body.append([f"Total ({t['projects']})", t["currency"], *[_fmt(t.get(k)) for k, _ in COLUMNS[2:]]])
    table = Table([head, *body], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c0c8d2")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    as_of = data["as_of"].isoformat() if isinstance(data["as_of"], date) else str(data["as_of"])
    doc.build([Paragraph(f"WIP schedule as of {as_of}", styles["Title"]), Spacer(1, 4 * mm), table])
    return buf.getvalue()
