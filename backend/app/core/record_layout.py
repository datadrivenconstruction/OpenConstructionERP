# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Block kinds a document layout adds to the record form, and the page furniture it draws.

The record form in :mod:`app.core.register_export` prints boxed text, label and
value grids, tables and signature rows. A document layout
(:mod:`app.core.doc_templates.layout`) composes a form from those and from the
kinds drawn here: rich text, headings, spacers, page breaks, images, QR codes
and side-by-side columns, each with an optional style (alignment, font size,
spacing). A form built by hand never uses them, so it prints as it always did.

Nothing here reads the database or evaluates user text: blocks arrive already
compiled, rich text as reportlab markup built from escaped text.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Flowable, Image, KeepTogether, PageBreak, Paragraph, Spacer, Table

from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_fit_line, pdf_fitted_style, pdf_markup, pdf_style_for_text

__all__ = ["PAGE_NUMBER", "PAGE_TOTAL", "draw_page_decor", "layout_flowables", "restyle"]

logger = logging.getLogger(__name__)

#: Placeholders a compiled header or footer line carries for the page counter.
PAGE_NUMBER = "\x01page\x01"
PAGE_TOTAL = "\x01total\x01"

_ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
_MAX_IMAGE_HEIGHT = 60 * mm


def restyle(styles: dict[str, ParagraphStyle], *, ink: Any, default_ink: Any, serif: bool) -> dict[str, ParagraphStyle]:
    """Copies of the form styles in the layout's accent colour and, on request, the bundled serif."""
    face, bold = BODY_FONT, BOLD_FONT
    if serif:
        from app.core.doc_templates.pdf import SERIF_BOLD_FONT, SERIF_FONT, register_serif_font

        if register_serif_font():
            face, bold = SERIF_FONT, SERIF_BOLD_FONT
    out: dict[str, ParagraphStyle] = {}
    for key, style in styles.items():
        changes: dict[str, Any] = {}
        if ink is not None and style.textColor == default_ink:
            changes["textColor"] = ink
        if style.fontName == BODY_FONT:
            changes["fontName"] = face
        elif style.fontName == BOLD_FONT:
            changes["fontName"] = bold
        out[key] = ParagraphStyle(f"{style.name}_l", parent=style, **changes) if changes else style
    return out


def _styled(base: ParagraphStyle, style: Mapping[str, Any] | None) -> ParagraphStyle:
    if not style:
        return base
    changes: dict[str, Any] = {}
    align = _ALIGN.get(str(style.get("align") or ""))
    if align is not None:
        changes["alignment"] = align
    size = style.get("font_size")
    if isinstance(size, int | float) and 6 <= size <= 24:
        changes["fontSize"] = float(size)
        changes["leading"] = round(float(size) * 1.35, 2)
    return ParagraphStyle(f"{base.name}_s", parent=base, **changes) if changes else base


def _rich(markup: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(markup, pdf_style_for_text(style, markup))


def _plain(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(pdf_markup(text, style, line_breaks=True), pdf_style_for_text(style, text))


def _image(data: bytes, width_mm: float, align: str) -> Image | None:
    try:
        img = Image(io.BytesIO(data))
        ratio = (img.imageHeight or 1) / (img.imageWidth or 1)
        width = max(10.0, min(width_mm or 40.0, 180.0)) * mm
        img.drawWidth = width
        img.drawHeight = min(width * ratio, _MAX_IMAGE_HEIGHT)
        img.hAlign = {"center": "CENTER", "right": "RIGHT"}.get(align, "LEFT")
        return img
    except Exception:  # noqa: BLE001 - a bad picture never breaks the document
        logger.warning("record_layout: image block skipped", exc_info=True)
        return None


def _qr(value: str, size_mm: float, align: str) -> Flowable | None:
    if not value:
        return None
    try:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing

        size = max(12.0, min(size_mm or 22.0, 60.0)) * mm
        widget = QrCodeWidget(value[:500])
        x0, y0, x1, y1 = widget.getBounds()
        drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        drawing.add(widget)
        drawing.hAlign = {"center": "CENTER", "right": "RIGHT"}.get(align, "LEFT")
        return drawing
    except Exception:  # noqa: BLE001 - a code that cannot be drawn is left out
        logger.warning("record_layout: QR block skipped", exc_info=True)
        return None


def _kind_flowables(
    block: Any, usable: float, styles: dict[str, ParagraphStyle], frame_height: float, helpers: Mapping[str, Any]
) -> list[Any]:
    style = block.style or {}
    align = str(style.get("align") or "left")
    kind = block.kind
    if kind == "bare_grid":
        columns = max((len(row) for row in block.rows), default=2)
        if columns >= 4:
            half = usable / 2
            widths = [32 * mm, half - 32 * mm, 32 * mm, half - 32 * mm]
        else:
            widths = [45 * mm, usable - 45 * mm]
        return [helpers["label_value_table"](block.rows, styles, widths)] if block.rows else []
    if kind == "heading":
        base = styles["subject"] if block.level <= 1 else styles["section"]
        return [_plain(block.title, _styled(base, style))] if block.title.strip() else []
    if kind == "rich":
        body = _styled(styles["body"], style)
        paras = [_rich(markup, body) for markup in block.markup]
        out: list[Any] = []
        if block.title.strip():
            out.append(_plain(block.title, styles["section"]))
        out.extend(paras or ([_plain(block.empty_text, styles["muted"])] if block.empty_text else []))
        return [CondPageBreak(30 * mm), *out] if len(out) > 1 else out
    if kind == "spacer":
        return [Spacer(1, max(0.0, min(block.height, 120.0)) * mm)]
    if kind == "page_break":
        return [PageBreak()]
    if kind == "image":
        img = _image(block.image, block.width, align) if block.image else None
        return [img] if img is not None else []
    if kind == "qr":
        code = _qr(block.text, block.width, align)
        if code is None:
            return []
        if block.title.strip():
            return [KeepTogether([code, _plain(block.title, _styled(styles["muted"], {"align": align}))])]
        return [code]
    if kind == "columns":
        count = len(block.children)
        if not count:
            return []
        shares = list(block.ratios) if len(block.ratios) == count else [1.0] * count
        total = sum(shares) or 1.0
        gap = 4 * mm
        widths = [(usable - gap * (count - 1)) * share / total for share in shares]
        cells = []
        for children, width in zip(block.children, widths, strict=True):
            flow: list[Any] = []
            for child in children:
                flow.extend(_cell_flowables(helpers["block_flowables"](child, width, styles, frame_height)))
            cells.append(flow or [Spacer(1, 1)])
        col_widths: list[float] = []
        row: list[Any] = []
        for index, (cell, width) in enumerate(zip(cells, widths, strict=True)):
            if index:
                row.append("")
                col_widths.append(gap)
            row.append(cell)
            col_widths.append(width)
        table = Table([row], colWidths=col_widths)
        table.setStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
        return [Spacer(1, 2 * mm), table]
    return helpers["block_flowables"](replace(block, style=None), usable, styles, frame_height)


def layout_flowables(
    block: Any, usable: float, styles: dict[str, ParagraphStyle], frame_height: float, helpers: Mapping[str, Any]
) -> list[Any]:
    """The flowables of one layout block, with its spacing before and after."""
    style = block.style or {}
    flow = _kind_flowables(block, usable, styles, frame_height, helpers)
    before = style.get("space_before")
    after = style.get("space_after")
    if isinstance(before, int | float) and before > 0:
        flow = [Spacer(1, min(float(before), 60.0) * mm), *flow]
    if isinstance(after, int | float) and after > 0:
        flow = [*flow, Spacer(1, min(float(after), 60.0) * mm)]
    return flow


def _page_text(text: str, page: int, total: int) -> str:
    return text.replace(PAGE_NUMBER, str(page)).replace(PAGE_TOTAL, str(total))


def _draw_line(canvas: Any, text: str, align: str, *, x: float, width: float, top: float, bold: bool = False) -> None:
    fitted, _face, size = pdf_fit_line(text, width, size=7.5, bold=bold, base=BOLD_FONT if bold else BODY_FONT)
    style = ParagraphStyle(
        "LayoutFurniture",
        fontName=BOLD_FONT if bold else BODY_FONT,
        fontSize=7.5,
        leading=9,
        textColor="#555555",
        alignment=_ALIGN.get(align, TA_LEFT),
    )
    para = Paragraph(pdf_markup(fitted, style), pdf_fitted_style(style, fitted, size))
    _, height = para.wrapOn(canvas, width, 20)
    para.drawOn(canvas, x, top - height)


def _cell_flowables(flowables: Sequence[Any]) -> list[Any]:
    """Flowables a table cell can hold: no page breaks, and no KeepTogether (it forces a split in a cell)."""
    out: list[Any] = []
    for f in flowables:
        if isinstance(f, (CondPageBreak, PageBreak)):
            continue
        if isinstance(f, KeepTogether):
            out.extend(_cell_flowables(getattr(f, "_content", [])))
        else:
            out.append(f)
    return out


def draw_page_decor(canvas: Any, doc: Any, decor: Any, *, total_pages: int, margin_side: float) -> None:
    """Status watermark, header lines and footer lines of a layout, on one sheet. Never raises."""
    try:
        page_w, page_h = doc.pagesize
        width = page_w - 2 * margin_side
        if decor.watermark_text:
            from app.core.pdf_branding import draw_watermark

            draw_watermark(canvas, {"watermark_text": decor.watermark_text}, page_w=page_w, page_h=page_h)
        if decor.header_lines and (doc.page > 1 or decor.header_on_first_page):
            for index, (align, text) in enumerate(decor.header_lines[:3]):
                line = _page_text(text, doc.page, total_pages)
                _draw_line(canvas, line, align, x=margin_side, width=width, top=page_h - 7 * mm - index * 3.6 * mm)
        for index, (align, text) in enumerate(decor.footer_lines[:2]):
            line = _page_text(text, doc.page, total_pages)
            _draw_line(canvas, line, align, x=margin_side, width=width, top=11.5 * mm - index * 3.6 * mm)
    except Exception:  # noqa: BLE001 - page furniture never costs the document
        logger.warning("record_layout: page decor skipped", exc_info=True)
