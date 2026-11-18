# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine period report PDF: plan, actual with its volume trail, compliance, trucks, findings."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_doc_metadata, branded_header_logo, branded_letterhead
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts

register_pdf_fonts()


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), style)


def _n(value: Any, places: int = 1, unit: str = "") -> str:
    return "-" if value is None else f"{float(value):,.{places}f}{unit}"


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2f} %"


def _signed(value: Any) -> str:
    return "-" if value is None else f"{float(value):+.2f} %"


def build_period_report(data: dict[str, Any], project_name: str) -> bytes:
    """Render one period as an A4 landscape PDF.

    Args:
        data: ``{"period", "entries", "totals", "crs_epsg"}`` as built by ``MineService.report_data``.
        project_name: shown under the title.

    Returns:
        PDF bytes. The header names the profile and who confirmed each actual, so a printed compliance
        is never read as signed off when its volume is still a draft.
    """
    period, entries, totals = data["period"], data["entries"], data["totals"]
    body = ParagraphStyle("b", fontName=BODY_FONT, fontSize=8, leading=10)
    bold = ParagraphStyle("h", fontName=BOLD_FONT, fontSize=11, leading=14, spaceBefore=6, spaceAfter=4)
    title = ParagraphStyle("t", fontName=BOLD_FONT, fontSize=16, leading=20)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Mine period report {period.get('label', '')}",
        **branded_doc_metadata(),
    )

    def grid(rows: list[list[Any]], widths: list[float], header: bool) -> Table:
        t = Table([[_p(c, body) for c in r] for r in rows], colWidths=widths, repeatRows=1 if header else 0)
        style = [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        style.append(("BACKGROUND", (0, 0), (-1, 0) if header else (0, -1), colors.HexColor("#f1f5f9")))
        t.setStyle(TableStyle(style))
        return t

    band = (
        f"{_n(period.get('band_lo_pct'), 0)} - {_n(period.get('band_hi_pct'), 0)} %"
        if period.get("band_lo_pct") is not None
        else "-"
    )
    tol = f"{_n(period.get('truck_tolerance_pct'), 0)} %" if period.get("truck_tolerance_pct") is not None else "-"
    crs = f"EPSG {data['crs_epsg']}" if data.get("crs_epsg") else "-"
    head = [
        ["Period", f"{period['period_start']} to {period['period_end']}"],
        ["Coordinate system", crs],
        ["Compliance band / truck check", f"{band} / {tol}"],
        ["Profile", period.get("profile_label") or "-"],
        ["Method", "Grid cut of the end surface against the start surface (Volumes)"],
    ]
    rows = [
        [
            "Unit",
            "Type",
            "Plan m3",
            "Actual m3",
            "Compliance",
            "Plan t",
            "Survey t",
            "Truck t",
            "Truck factor",
            "Actual status",
        ]
    ]
    findings: list[str] = []
    for e in entries:
        actual = e.get("actual")
        who = f" ({actual['confirmed_by_name']})" if actual and actual.get("confirmed_by_name") else ""
        rows.append(
            [
                f"{e['unit_code']} {e['unit_name']}",
                e["unit_type"],
                _n(e["plan_m3"]),
                _n(e["actual_m3"]),
                _pct(e["compliance_pct"]),
                _n(e["plan_t"], 2),
                _n(e["survey_t"], 2),
                _n(e["truck_t"], 2),
                _signed(e["truck_factor_pct"]),
                f"{actual['code']} {actual['status']}{who}" if actual else "-",
            ]
        )
        findings += [
            f"{e['unit_name']}: {f['rule_id']} ({f['severity']}) {f['message']}" for f in e.get("findings", [])
        ]
    rows.append(
        [
            "Total",
            "",
            _n(totals["plan_m3"]),
            _n(totals["actual_m3"]),
            _pct(totals["compliance_pct"]),
            "",
            _n(totals["survey_t"], 2),
            _n(totals["truck_t"], 2),
            _signed(totals["truck_factor_pct"]),
            "",
        ]
    )
    w = doc.width
    story: list[Any] = [
        _p(f"Mine period report {period.get('label', '')}", title),
        _p(project_name, body),
        Spacer(1, 3 * mm),
        grid(head, [55 * mm, w - 55 * mm], header=False),
        _p("Result", bold),
        grid(rows, [w * f for f in (0.17, 0.07, 0.08, 0.09, 0.09, 0.08, 0.09, 0.09, 0.08, 0.16)], header=True),
    ]
    if findings:
        story.append(_p("Checks", bold))
        story += [_p(f, body) for f in findings]
    story += [Spacer(1, 3 * mm), _p(f"Printed {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}", body)]
    letterhead = branded_letterhead(doc.width - 12, doc_type="mine_period_report")
    if letterhead is not None:
        story.insert(0, letterhead)

    def _first_page(canvas: Any, page_doc: Any) -> None:
        if letterhead is None:
            branded_header_logo(canvas, page_doc)

    doc.build(story, onFirstPage=_first_page, onLaterPages=branded_header_logo)
    return buf.getvalue()
