# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reusable PDF renderer for confirmed meeting minutes.

The minutes document (present/absent, per-agenda discussion and decision,
action items with brought-forward and overdue markers, next meeting date and
summary) is the human-confirmed record - not the raw meeting row. This module
holds the single source of truth for rendering it to bytes so both the export
endpoint and the record-publishing module (one-tap publish-and-distribute)
produce the exact same document.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.meetings.models import Meeting, MinutesRecord

#: The grey both minutes renderers draw their running head and footer in.
_FURNITURE_GREY = "#999999"


def draw_minutes_footer(canvas_obj: Any, doc: Any, appearance: dict[str, Any], *, margin: float) -> None:
    """Draw the minutes footer: the page number, and a saved footer line.

    Shared by :func:`build_minutes_pdf` and the export in
    ``app.modules.meetings.router``, and follows the document appearance for
    meeting minutes as the RFI footer does: the footer colour colours the
    footer and page numbers can be switched off. The minutes print no footer
    line of their own, so a saved one is added at the left margin rather than
    put in place of one.

    Expects the caller to have saved the canvas state and set the fill to
    :data:`_FURNITURE_GREY`, which the running head is drawn in. The colour is
    set again only when the footer's differs, so the default look draws the
    page it always drew.

    Args:
        canvas_obj: The page's canvas.
        doc: The document being built, for the page size and number.
        appearance: The document appearance, read once for the whole document.
        margin: The side margin both renderers lay the page out with.
    """
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    from app.core.pdf_branding import draw_watermark
    from app.core.pdf_fonts import BODY_FONT, pdf_fit_line, pdf_fitted_style

    page_width = doc.pagesize[0]
    draw_watermark(canvas_obj, appearance, page_w=page_width, page_h=doc.pagesize[1])
    colour = appearance.get("footer_color") or _FURNITURE_GREY
    if colour != _FURNITURE_GREY:
        canvas_obj.setFillColor(colors.HexColor(colour))
    page_text = f"Page {doc.page}" if appearance.get("show_page_numbers", True) is not False else ""
    if page_text:
        canvas_obj.setFont(BODY_FONT, 7)
        canvas_obj.drawRightString(page_width - margin, 10 * mm, page_text)
    footer_text = str(appearance.get("footer_text") or "").strip()
    if footer_text:
        # A Paragraph, so a Thai or Devanagari line is shaped. Printed as saved,
        # untranslated, on the page number's baseline and clear of it. Fitted
        # onto one line rather than wrapped, because the paragraph is placed by
        # the top of its box and a second line would land on the bottom edge.
        style = ParagraphStyle(
            "MinutesFooter", fontName=BODY_FONT, fontSize=7, leading=8, textColor=colors.HexColor(colour)
        )
        room = page_width - 2 * margin - 40 * mm
        footer_text, _face, size = pdf_fit_line(footer_text, room, base=BODY_FONT)
        line = Paragraph(escape(footer_text, quote=True), pdf_fitted_style(style, footer_text, size))
        _, height = line.wrapOn(canvas_obj, room, 20)
        line.drawOn(canvas_obj, margin, 10 * mm - height + 7)


def minutes_pdf_filename(meeting: Meeting, content: dict) -> str:
    """Build the download filename for a meeting's minutes PDF."""
    safe_title = str(content.get("title") or meeting.title).replace(" ", "_")[:50]
    return f"minutes_{meeting.meeting_number}_{safe_title}.pdf"


def build_minutes_pdf(meeting: Meeting, minutes: MinutesRecord, project_name: str) -> bytes:
    """Render the confirmed meeting minutes to PDF bytes.

    Args:
        meeting: the meeting row (title, number, date, project).
        minutes: the confirmed minutes record (its ``content`` JSON is the
            source of truth for the rendered document, with the meeting row as
            fallback for a few header fields).
        project_name: display name of the owning project for the header.

    Returns:
        The rendered PDF as bytes.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    from app.core.pdf_branding import (
        branded_appearance,
        branded_doc_metadata,
        branded_header_logo,
        branded_letterhead,
    )
    from app.core.pdf_fonts import (
        BODY_FONT,
        BOLD_FONT,
        pdf_font_for_text,
        pdf_style_for_text,
        pdf_table_paragraph_rows,
        register_pdf_fonts,
    )

    register_pdf_fonts()

    content: dict = minutes.content if isinstance(minutes.content, dict) else {}

    PAGE_WIDTH, PAGE_HEIGHT = A4
    MARGIN = 20 * mm
    USABLE_WIDTH = PAGE_WIDTH - 2 * MARGIN

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "MinutesTitle",
        parent=styles["Normal"],
        fontName=BOLD_FONT,
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=3 * mm,
    )
    style_subtitle = ParagraphStyle(
        "MinutesSubtitle",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
        spaceAfter=6 * mm,
    )
    style_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName=BOLD_FONT,
        fontSize=12,
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
    )
    style_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
    )
    style_small = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=8,
        textColor=colors.HexColor("#777777"),
    )
    style_cell = ParagraphStyle(
        "InfoCell",
        parent=styles["Normal"],
        fontName=BODY_FONT,
        fontSize=9,
        leading=11,
    )
    style_cell_label = ParagraphStyle("InfoLabel", parent=style_cell, fontName=BOLD_FONT)
    # The attendance and action tables named a face for their header row only,
    # so reportlab drew every body cell in its own default. Keeping Helvetica
    # here keeps those rows looking exactly as they did; pdf_style_for_text
    # still escalates a cell Helvetica cannot draw, which is what carried the
    # Chinese before.
    style_grid_cell = ParagraphStyle(
        "GridCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    style_grid_head = ParagraphStyle("GridHead", parent=style_grid_cell, fontName=BOLD_FONT)

    def _first_column_label(_row_index: int, col_index: int):
        """The label column is bold, every other column is a plain value."""
        return style_cell_label if col_index == 0 else None

    elements: list = []
    # The firm's letterhead, when the company profile has one. The frame pads
    # 6pt on each side, so this is the width a flowable can use.
    letterhead = branded_letterhead(USABLE_WIDTH - 12, doc_type="meeting_minutes")
    if letterhead is not None:
        elements.append(letterhead)
    elements.append(Paragraph("Meeting Minutes", style_title))
    status_tag = "ISSUED" if minutes.status == "issued" else "DRAFT"
    elements.append(
        Paragraph(f"{escape(project_name)} &middot; {status_tag}", pdf_style_for_text(style_subtitle, project_name))
    )
    meeting_title = str(content.get("title") or meeting.title)
    elements.append(Paragraph(escape(meeting_title), pdf_style_for_text(style_heading, meeting_title)))

    info_data = [
        ["Date:", str(content.get("meeting_date") or meeting.meeting_date or "N/A")],
        ["Location:", str(content.get("location") or "N/A") or "N/A"],
        ["Type:", str(content.get("meeting_type") or "").replace("_", " ").title()],
        ["Meeting #:", str(content.get("meeting_number") or meeting.meeting_number)],
        ["Chairperson:", str(content.get("chairperson") or "N/A") or "N/A"],
        ["Next meeting:", str(content.get("next_meeting_date") or "Not scheduled")],
    ]
    # Paragraph cells rather than bare strings. A bare cell is drawn through
    # canvas.drawString, which neither wraps nor shapes: a site address longer
    # than the column ran off the right hand side of the sheet, and a Thai or
    # Devanagari value was mis-arranged whatever face it was given. A Paragraph
    # does both and carries its own face and size, so the font commands and the
    # FONTNAME and FONTSIZE that used to sit here are gone rather than left to
    # describe a layout nothing obeys.
    info_data = pdf_table_paragraph_rows(info_data, style_cell, style_for=_first_column_label)
    info_table = Table(info_data, colWidths=[32 * mm, USABLE_WIDTH - 32 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    elements.append(info_table)

    # Attendance (present / absent)
    present = content.get("attendees_present") or []
    absent = content.get("attendees_absent") or []
    if present or absent:
        elements.append(Paragraph("Attendance", style_heading))
        if present:
            names = ", ".join(escape(str(a.get("name") or "")) for a in present if isinstance(a, dict))
            elements.append(Paragraph(f"<b>Present:</b> {names}", pdf_style_for_text(style_body, names)))
        if absent:
            names = ", ".join(escape(str(a.get("name") or "")) for a in absent if isinstance(a, dict))
            elements.append(Paragraph(f"<b>Absent / excused:</b> {names}", pdf_style_for_text(style_body, names)))

    # Agenda with discussion + decision
    agenda = content.get("agenda") or []
    if agenda:
        elements.append(Paragraph("Agenda, discussion and decisions", style_heading))
        for idx, item in enumerate(agenda, 1):
            if not isinstance(item, dict):
                continue
            topic = escape(str(item.get("topic") or ""))
            num = escape(str(item.get("number") or idx))
            req = " <font color='#b45309'>(required)</font>" if item.get("required") else ""
            elements.append(Paragraph(f"<b>{num}. {topic}</b>{req}", pdf_style_for_text(style_body, topic)))
            if item.get("discussion"):
                discussion = str(item["discussion"])
                elements.append(
                    Paragraph(
                        f"&nbsp;&nbsp;<b>Discussion:</b> {escape(discussion)}",
                        pdf_style_for_text(style_small, discussion),
                    )
                )
            if item.get("decision"):
                decision = str(item["decision"])
                elements.append(
                    Paragraph(
                        f"&nbsp;&nbsp;<b>Decision:</b> {escape(decision)}",
                        pdf_style_for_text(style_small, decision),
                    )
                )
            elements.append(Spacer(1, 1.5 * mm))

    # Action items
    actions = content.get("action_items") or []
    if actions:
        elements.append(Paragraph("Action items", style_heading))
        act_data = [["#", "Action", "Owner", "Due", "Status"]]
        for idx, ai in enumerate(actions, 1):
            if not isinstance(ai, dict):
                continue
            desc = str(ai.get("description") or "")
            if ai.get("brought_forward"):
                desc = f"[Brought forward] {desc}"
            status_str = str(ai.get("status") or "open").replace("_", " ").title()
            if ai.get("overdue"):
                status_str += " (overdue)"
            act_data.append([str(idx), desc, str(ai.get("owner") or ""), str(ai.get("due_date") or ""), status_str])
        # Paragraph cells for the reason given at the info table above. The
        # description is the column this matters most in: it is a sentence in
        # a 44 percent column and it was printed over the owner beside it.
        act_data = pdf_table_paragraph_rows(act_data, style_grid_cell, header_style=style_grid_head, header_rows=1)
        act_table = Table(
            act_data,
            colWidths=[
                USABLE_WIDTH * 0.06,
                USABLE_WIDTH * 0.44,
                USABLE_WIDTH * 0.20,
                USABLE_WIDTH * 0.13,
                USABLE_WIDTH * 0.17,
            ],
            # An action item's description is Text with no length limit, and it
            # is drawn in a column just over two fifths of the page. Once the
            # cell wraps, a long enough item makes a row taller than the frame,
            # and reportlab refuses a row it cannot fit rather than splitting
            # one: the export answered 500 above about 2900 characters. The
            # obligation in a meeting action is usually in its last sentence,
            # so the row splits across the page break and every word is kept.
            splitInRow=1,
        )
        act_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(act_table)

    # Summary
    if content.get("summary"):
        summary = str(content["summary"])
        elements.append(Paragraph("Summary", style_heading))
        elements.append(Paragraph(escape(summary).replace("\n", "<br/>"), pdf_style_for_text(style_body, summary)))

    elements.append(Spacer(1, 8 * mm))
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    issued_note = ""
    if minutes.status == "issued" and minutes.issued_at:
        issued_note = f" &middot; Issued {minutes.issued_at.strftime('%Y-%m-%d %H:%M UTC')}"
    elements.append(Paragraph(f"Generated: {stamp}{issued_note}", style_small))

    buf = io.BytesIO()
    look = branded_appearance(doc_type="meeting_minutes")

    def _header_footer(canvas_obj, doc):  # type: ignore[no-untyped-def]
        # On a page that opens with the letterhead, the letterhead is the page's
        # header: the running head and the logo above it would repeat it.
        under_letterhead = letterhead is not None and doc.page == 1
        canvas_obj.saveState()
        canvas_obj.setFillColor(colors.HexColor(_FURNITURE_GREY))
        if not under_letterhead:
            running_head = f"{project_name} - Minutes"
            canvas_obj.setFont(pdf_font_for_text(running_head), 7)
            canvas_obj.drawString(MARGIN, PAGE_HEIGHT - 12 * mm, running_head)
        draw_minutes_footer(canvas_obj, doc, look, margin=MARGIN)
        canvas_obj.restoreState()
        if not under_letterhead:
            branded_header_logo(canvas_obj, doc)

    frame = Frame(MARGIN, MARGIN, USABLE_WIDTH, PAGE_HEIGHT - 2 * MARGIN, id="main")
    # The margins are the frame's, so the header logo, placed from the right
    # margin, lines up with the text under it instead of reportlab's inch.
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        **branded_doc_metadata(),
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_header_footer)])
    doc.build(elements)

    return buf.getvalue()
