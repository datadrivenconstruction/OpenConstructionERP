# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable daily plan: one section per foreman, one row per card. Text is escaped."""

from __future__ import annotations

import html
import io
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text, register_pdf_fonts

register_pdf_fonts()

_BODY = ParagraphStyle("DispBody", fontName=BODY_FONT, fontSize=9, leading=11)
_HEAD = ParagraphStyle("DispHead", fontName=BOLD_FONT, fontSize=14, leading=18, spaceAfter=4)
_TH = ParagraphStyle("DispTh", fontName=BOLD_FONT, fontSize=9, leading=11)


def _p(text: Any, style: ParagraphStyle = _BODY) -> Paragraph:
    rendered = "" if text is None else str(text)
    return Paragraph(html.escape(rendered, quote=True), pdf_style_for_text(style, rendered))


def render_daily_plan(day: date, plans: list[dict[str, Any]]) -> bytes:
    """A4 landscape PDF, a page per foreman so each one can be handed out."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Daily plan {day.isoformat()}",
    )
    story: list[Any] = []
    if not plans:
        story.append(_p(f"Daily plan {day.isoformat()}", _HEAD))
        story.append(_p("Nothing is dispatched for this day."))
    for i, plan in enumerate(plans):
        if i:
            story.append(PageBreak())
        story.append(_p(f"Daily plan {day.isoformat()}: {plan.get('foreman') or 'No foreman'}", _HEAD))
        story.append(Spacer(1, 3 * mm))
        rows: list[list[Any]] = [[_p(h, _TH) for h in ("Start", "Where", "Who / what", "Operator", "Notes")]]
        for ln in plan.get("lines") or []:
            rows.append(
                [
                    _p(ln.get("start_time")),
                    _p(ln.get("location")),
                    _p(ln.get("who_or_what")),
                    _p(ln.get("operator")),
                    _p(ln.get("notes")),
                ]
            )
        table = Table(rows, colWidths=[18 * mm, 55 * mm, 105 * mm, 40 * mm, 55 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)
    doc.build(story)
    return buf.getvalue()
