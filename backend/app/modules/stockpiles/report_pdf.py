# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile report PDF: volume, density with its source, tonnes, variance against the book."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_doc_metadata, branded_header_logo, branded_letterhead
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts

register_pdf_fonts()

SOURCE_LABEL = {"measured": "measured", "supplier": "supplier", "assumed": "assumed"}


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), style)


def _t(value: Any) -> str:
    return "-" if value is None else f"{float(value):,.2f} t"


def build_stockpile_report(data: dict[str, Any], project_name: str) -> bytes:
    """Render one survey of one stockpile as an A4 PDF.

    Args:
        data: ``{"stockpile": {...}, "survey": {...}}`` as built by ``StockpileService.report_data``.
        project_name: shown under the title.

    Returns:
        PDF bytes. The first block names the density source, so a printed tonnage is never read as measured
        when it was assumed.
    """
    pile, s = data["stockpile"], data["survey"]
    body = ParagraphStyle("b", fontName=BODY_FONT, fontSize=9, leading=12)
    bold = ParagraphStyle("h", fontName=BOLD_FONT, fontSize=11, leading=14, spaceBefore=6, spaceAfter=4)
    title = ParagraphStyle("t", fontName=BOLD_FONT, fontSize=16, leading=20)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Stockpile report {pile.get('code', '')}",
        **branded_doc_metadata(),
    )

    def table(rows: list[tuple[str, Any]]) -> Table:
        t = Table([[_p(k, body), _p(v, body)] for k, v in rows], colWidths=[55 * mm, doc.width - 55 * mm - 12])
        t.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return t

    density = f"{float(s['density_t_m3']):g} t/m3, {SOURCE_LABEL.get(s['density_source'], s['density_source'])}"
    pct = s.get("variance_pct")
    story: list[Any] = [
        _p(f"Stockpile report {pile.get('code', '')}: {pile.get('name', '')}", title),
        _p(project_name, body),
        _p(f"Density source: {s['density_source']}", bold),
        _p("Result", bold),
        table(
            [
                ("Survey date", s["surveyed_on"]),
                ("Volume above base", f"{float(s['volume_m3']):,.1f} m3"),
                ("Density", density),
                ("Tonnes (volume x density)", _t(s["tonnes"])),
                ("Book stock", _t(s.get("book_tonnes"))),
                ("Variance", f"{_t(s.get('variance_t'))} ({float(pct):+.2f} %)" if pct is not None else "-"),
            ]
        ),
        _p("How it was measured", bold),
        table(
            [
                ("Material", pile.get("material") or "-"),
                ("Base surface", pile.get("base_name") or "-"),
                ("Pile", s.get("pile_name") or "Volume typed from field software"),
                (
                    "Cell size / coverage",
                    f"{s.get('cell_size_m')} m / {float(s['coverage_pct']):.1f} %"
                    if s.get("coverage_pct") is not None
                    else "-",
                ),
                ("Coordinate system", f"EPSG {s['crs_epsg']}" if s.get("crs_epsg") else "-"),
            ]
        ),
    ]
    findings = s.get("findings") or []
    if findings:
        story.append(_p("Checks", bold))
        story += [_p(f"{f['rule_id']} ({f['severity']}): {f['message']}", body) for f in findings]
    adj = s.get("adjustment")
    story += [
        _p("Inventory adjustment", bold),
        table(
            [
                ("Status", adj["status"] if adj else "none"),
                ("Quantity", _t(adj["delta_t"]) if adj else "-"),
                ("Confirmed by", (adj or {}).get("confirmed_by_name") or "-"),
                ("Printed", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
            ]
        ),
        Spacer(1, 2 * mm),
    ]
    letterhead = branded_letterhead(doc.width - 12, doc_type="stockpile_survey")
    if letterhead is not None:
        story.insert(0, letterhead)

    def _first_page(canvas: Any, page_doc: Any) -> None:
        if letterhead is None:
            branded_header_logo(canvas, page_doc)

    doc.build(story, onFirstPage=_first_page, onLaterPages=branded_header_logo)
    return buf.getvalue()
