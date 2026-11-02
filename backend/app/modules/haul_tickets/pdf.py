# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ ticket print: one A5 sheet per ticket with its QR code.

Uses the platform branding (header, footer, "Page x of y") so a printed ticket
looks like every other document of the workspace. The QR encodes the ticket
token, which the field screen resolves back to the ticket.
"""

from __future__ import annotations

import base64
import io
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_doc_metadata, branded_header_footer, build_with_page_count
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text, register_pdf_fonts
from app.modules.haul_tickets.models import HaulTicket

register_pdf_fonts()

DEFAULT_LABELS: dict[str, str] = {
    "title": "Haul ticket",
    "ticket_number": "Ticket no.",
    "date": "Date",
    "time_out": "Time out",
    "time_in": "Time in",
    "origin": "Origin",
    "destination": "Destination",
    "material": "Material",
    "gross": "Gross (t)",
    "tare": "Tare (t)",
    "net": "Net (t)",
    "volume": "Volume (m3)",
    "loads": "Loads",
    "haulier": "Haulier",
    "plate": "Plate",
    "driver": "Driver",
    "cost_code": "Cost code",
    "waste_code": "Waste code",
    "facility": "Receiving facility",
    "status": "Status",
    "receiver": "Received by",
    "signature": "Signature",
}


def _qr(value: str, size: float = 32 * mm) -> Drawing:
    widget = QrCodeWidget(value)
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(widget)
    return drawing


def _signature_image(data_url: str | None) -> Image | None:
    if not data_url or "," not in data_url:
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        return Image(io.BytesIO(raw), width=50 * mm, height=18 * mm, kind="proportional")
    except Exception:  # noqa: BLE001 - a broken signature image must not break the print
        return None


def _v(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M") if hasattr(value, "hour") else value.isoformat()
    return str(value)


def render_ticket_pdf(row: HaulTicket, *, project_name: str = "", labels: dict[str, str] | None = None) -> bytes:
    lab = {**DEFAULT_LABELS, **(labels or {})}
    label_style = ParagraphStyle("lab", fontName=BODY_FONT, fontSize=7.5, textColor=colors.HexColor("#555555"))
    value_style = ParagraphStyle("val", fontName=BOLD_FONT, fontSize=9.5, leading=12)
    title_style = ParagraphStyle("title", fontName=BOLD_FONT, fontSize=15, leading=18)

    def para(text: Any, style: ParagraphStyle) -> Paragraph:
        s = _v(text)
        return Paragraph(escape(s), pdf_style_for_text(style, s))

    buffer = io.BytesIO()
    meta = branded_doc_metadata()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A5,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=20 * mm,
        bottomMargin=16 * mm,
        title=f"{lab['title']} {row.ticket_number}".strip(),
        author=meta["author"],
        creator=meta["creator"],
    )
    head = Table(
        [
            [
                [
                    para(lab["title"], title_style),
                    para(project_name, label_style),
                    Spacer(1, 2 * mm),
                    para(f"{lab['ticket_number']} {row.ticket_number}", value_style),
                ],
                _qr(row.qr_token),
            ]
        ],
        colWidths=[doc.width - 34 * mm, 34 * mm],
    )
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    pairs: list[tuple[str, Any]] = [
        ("date", row.ticket_date),
        ("status", row.status),
        ("time_out", row.time_out),
        ("time_in", row.time_in),
        ("origin", row.origin),
        ("destination", row.destination),
        ("material", row.material_name or row.material_code),
        ("loads", row.loads),
        ("gross", row.gross_t),
        ("tare", row.tare_t),
        ("net", row.net_t),
        ("volume", row.volume_m3),
        ("haulier", row.haulier_name),
        ("plate", row.plate),
        ("driver", row.driver_name),
        ("cost_code", row.cost_code),
    ]
    if row.haul_type == "waste":
        pairs += [("waste_code", row.waste_code), ("facility", row.receiving_facility)]
    cells = [[para(lab[k], label_style), para(v, value_style)] for k, v in pairs]
    grid_rows = [cells[i] + (cells[i + 1] if i + 1 < len(cells) else ["", ""]) for i in range(0, len(cells), 2)]
    col = doc.width / 4
    grid = Table(grid_rows, colWidths=[col * 0.8, col * 1.2, col * 0.8, col * 1.2])
    grid.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    sig = _signature_image(row.signature)
    sign = Table(
        [
            [para(lab["receiver"], label_style), para(lab["signature"], label_style)],
            [para(row.receiver_name, value_style), sig or ""],
        ],
        colWidths=[doc.width / 2, doc.width / 2],
        rowHeights=[None, 22 * mm],
    )
    sign.setStyle(
        TableStyle([("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    )
    story: list[Any] = [head, Spacer(1, 4 * mm), grid, Spacer(1, 6 * mm), sign]
    build_with_page_count(doc, story, onFirstPage=branded_header_footer, onLaterPages=branded_header_footer)
    return buffer.getvalue()
