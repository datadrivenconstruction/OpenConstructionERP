# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Volume report PDF: the numbers, how they were made, who confirmed them, and a cut/fill map."""

from __future__ import annotations

import io
import math
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_doc_metadata, branded_header_logo, branded_letterhead
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts

register_pdf_fonts()

METHOD_LABEL = {"grid": "Grid", "tin": "TIN (triangle prisms)", "end_area": "Average end area"}
CUT = colors.HexColor("#c2410c")
FILL = colors.HexColor("#1d4ed8")
MAP_CELLS = 2500


def _m3(value: Any) -> str:
    return f"{float(value or 0):,.1f} m3"


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), style)


def _heat_drawing(heat: dict | None, width: float) -> Drawing | None:
    if not heat or not heat.get("dh"):
        return None
    nx, ny = int(heat["nx"]), int(heat["ny"])
    if nx <= 0 or ny <= 0:
        return None
    step = max(1, math.ceil(math.sqrt(nx * ny / MAP_CELLS)))
    gx, gy = math.ceil(nx / step), math.ceil(ny / step)
    size = min(width / gx, 90 * mm / gy)
    values = heat["dh"]
    peak = max((abs(v) for v in values if v is not None), default=0.0) or 1.0
    d = Drawing(gx * size, gy * size)
    for j in range(gy):
        for i in range(gx):
            block = [
                values[jj * nx + ii]
                for jj in range(j * step, min(ny, (j + 1) * step))
                for ii in range(i * step, min(nx, (i + 1) * step))
                if values[jj * nx + ii] is not None
            ]
            if not block:
                continue
            mean = sum(block) / len(block)
            base = CUT if mean > 0 else FILL
            t = min(1.0, abs(mean) / peak)
            col = colors.Color(1 - (1 - base.red) * t, 1 - (1 - base.green) * t, 1 - (1 - base.blue) * t)
            d.add(Rect(i * size, j * size, size, size, fillColor=col, strokeColor=None))
    return d


def build_volume_report(volume: dict[str, Any], project_name: str, history: list[dict[str, Any]]) -> bytes:
    """Render one calculation as an A4 PDF.

    Args:
        volume: the calculation as served by the API (``VolumeDetail`` dumped to a dict).
        project_name: shown under the title.
        history: its History lines (``VolumeEventOut`` dicts), oldest first.

    Returns:
        PDF bytes.
    """
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
        title=f"Volume report {volume.get('code', '')}",
        **branded_doc_metadata(),
    )
    story: list[Any] = [
        _p(f"Volume report {volume.get('code', '')}: {volume.get('name', '')}", title),
        _p(project_name, body),
        Spacer(1, 4 * mm),
    ]

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

    net = float(volume.get("net_m3") or 0)
    story += [
        _p("Result (bank volume, in the ground)", bold),
        table(
            [
                ("Cut", _m3(volume.get("cut_m3"))),
                ("Fill", _m3(volume.get("fill_m3"))),
                ("Net", f"{_m3(abs(net))} {'cut' if net > 0 else 'fill' if net < 0 else ''}".strip()),
                ("Loose cut (x swell)", f"{_m3(volume.get('loose_cut_m3'))} (x {volume.get('swell_factor', 1)})"),
                ("Coverage", f"{float(volume.get('coverage_pct') or 0):.1f} %"),
                ("Confidence", f"{round(100 * float(volume.get('confidence') or 0))} %"),
            ]
        ),
        _p("How it was computed", bold),
        table(
            [
                ("Base (earlier)", volume.get("base_name", "")),
                ("Compare (later)", volume.get("compare_name", "")),
                ("Method", METHOD_LABEL.get(str(volume.get("method")), volume.get("method"))),
                (
                    "Cell size",
                    f"{volume.get('cell_size_m')} m{' (auto)' if volume.get('cell_auto') else ''}"
                    if volume.get("cell_size_m")
                    else "-",
                ),
                ("Area computed", f"{float(volume.get('calc_area_m2') or 0):,.1f} m2"),
                (
                    "Boundary",
                    f"{len(volume.get('boundary') or [])} corners" if volume.get("boundary") else "Whole surface",
                ),
                (
                    "Coordinate system",
                    f"EPSG {volume.get('crs_epsg')} {volume.get('crs_name', '')}".strip()
                    if volume.get("crs_epsg")
                    else "Not declared",
                ),
                ("Scan accuracy tier", volume.get("accuracy_tier") or "-"),
                ("Material", volume.get("material") or "-"),
                ("Override reason", volume.get("override_reason") or "-"),
            ]
        ),
    ]
    drawing = _heat_drawing(volume.get("heat"), doc.width - 12)
    if drawing is not None:
        story += [_p("Cut (orange) and fill (blue), north up", bold), drawing]
    findings = volume.get("findings") or []
    if findings:
        story.append(_p("Checks", bold))
        for f in findings:
            story.append(_p(f"{f.get('rule_id')} ({f.get('severity')}): {f.get('message')}", body))
    story += [
        _p("Sign-off", bold),
        table(
            [
                ("Status", volume.get("status", "")),
                ("Confirmed by", volume.get("confirmed_by_name") or "-"),
                ("Confirmed at", str(volume.get("confirmed_at") or "-")),
                ("Printed", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
            ]
        ),
    ]
    if history:
        story.append(_p("History", bold))
        for h in history:
            qty = f" {float(h['quantity']):,.1f} m3" if h.get("quantity") is not None else ""
            story.append(_p(f"{h.get('created_at', '')} {h.get('user_name', '')}: {h.get('action')}{qty}", body))

    letterhead = branded_letterhead(doc.width - 12, doc_type="survey_volume")
    if letterhead is not None:
        story.insert(0, letterhead)

    def _first_page(canvas: Any, page_doc: Any) -> None:
        if letterhead is None:
            branded_header_logo(canvas, page_doc)

    doc.build(story, onFirstPage=_first_page, onLaterPages=branded_header_logo)
    return buf.getvalue()
