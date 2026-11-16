# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One generic document PDF built from template blocks and code-rendered tables.

Used by kinds that have no dedicated generator (generic invoice, change order,
and the call-off order and sealed estimate certificate modules through
:func:`render_document_pdf`) and as the preview of any PDF kind without one.
Users edit words; the table, totals and legal zone are drawn from the record.

Layout: letterhead, title, meta rows (number, date, recipient), intro, body,
item table, totals, terms, legal zone (locked pack notes), closing, signature
image with its caption, footer text. Fonts are the bundled Unicode sans or, on
request, the bundled Noto Serif (OFL); a script the face cannot draw falls back
per paragraph through :mod:`app.core.pdf_fonts`.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.core.doc_templates.markup import to_plain, to_reportlab

__all__ = ["LegalNote", "SignatureImage", "TableSpec", "register_serif_font", "render_document_pdf"]

logger = logging.getLogger(__name__)

SERIF_FONT = "NotoSerif"
SERIF_BOLD_FONT = "NotoSerif-Bold"
_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts" / "noto"
_serif_lock = threading.Lock()
_serif_ok: bool | None = None

#: Signature images larger than this are not drawn (bytes, decoded).
MAX_SIGNATURE_BYTES = 300 * 1024


def register_serif_font() -> bool:
    """Register the bundled Noto Serif faces. Idempotent, never raises."""
    global _serif_ok
    if _serif_ok is not None:
        return _serif_ok
    with _serif_lock:
        if _serif_ok is not None:
            return _serif_ok
        try:
            from reportlab.lib.fonts import addMapping
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont(SERIF_FONT, str(_FONT_DIR / "NotoSerif-Regular.ttf")))
            pdfmetrics.registerFont(TTFont(SERIF_BOLD_FONT, str(_FONT_DIR / "NotoSerif-Bold.ttf")))
            pdfmetrics.registerFontFamily(
                SERIF_FONT, normal=SERIF_FONT, bold=SERIF_BOLD_FONT, italic=SERIF_FONT, boldItalic=SERIF_BOLD_FONT
            )
            for bold in (0, 1):
                for italic in (0, 1):
                    addMapping(SERIF_FONT, bold, italic, SERIF_BOLD_FONT if bold else SERIF_FONT)
            _serif_ok = True
        except Exception:  # noqa: BLE001 - a missing face falls back to the sans
            logger.warning("doc_templates: Noto Serif not available, sans used", exc_info=True)
            _serif_ok = False
    return _serif_ok


@dataclass(frozen=True)
class TableSpec:
    """A code-rendered item table. Cells are plain text, already formatted."""

    header: Sequence[str]
    rows: Sequence[Sequence[str]]
    col_widths_mm: Sequence[float] | None = None
    numeric_cols: Sequence[int] = ()


@dataclass(frozen=True)
class LegalNote:
    """A locked note from a country pack, printed in the legal zone."""

    text: str
    source: str = ""


@dataclass(frozen=True)
class SignatureImage:
    """A scanned signature, printed as a picture and labelled as such."""

    png_bytes: bytes
    caption: str = ""
    label: str = "Signature image, not an electronic signature"


@dataclass
class _Styles:
    body: object
    bold: object
    title: object
    small: object
    cell: object
    cell_right: object
    extra: dict[str, object] = field(default_factory=dict)


def _styles(serif: bool) -> _Styles:
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle

    from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts

    register_pdf_fonts()
    face, bold = BODY_FONT, BOLD_FONT
    if serif and register_serif_font():
        face, bold = SERIF_FONT, SERIF_BOLD_FONT
    body = ParagraphStyle("dt_body", fontName=face, fontSize=10, leading=14, spaceAfter=6)
    return _Styles(
        body=body,
        bold=ParagraphStyle("dt_bold", parent=body, fontName=bold),
        title=ParagraphStyle("dt_title", parent=body, fontName=bold, fontSize=15, leading=19, spaceAfter=10),
        small=ParagraphStyle("dt_small", parent=body, fontSize=8, leading=10, textColor="#555555"),
        cell=ParagraphStyle("dt_cell", parent=body, fontSize=9, leading=11, spaceAfter=0),
        cell_right=ParagraphStyle("dt_cell_r", parent=body, fontSize=9, leading=11, spaceAfter=0, alignment=TA_RIGHT),
    )


def _para(markup: str, style: object) -> object:
    from reportlab.platypus import Paragraph

    from app.core.pdf_fonts import pdf_style_for_text

    return Paragraph(markup, pdf_style_for_text(style, markup))


def _esc(text: str) -> str:
    import html

    return html.escape(text or "", quote=False)


def decode_png_data_url(value: str | None) -> bytes | None:
    """PNG/JPEG bytes from a ``data:image/...;base64,`` URL, sniffed. ``None`` otherwise."""
    if not value or not isinstance(value, str) or ";base64," not in value[:40]:
        return None
    try:
        raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) > MAX_SIGNATURE_BYTES:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff"):
        return raw
    return None


def render_document_pdf(
    *,
    blocks: Mapping[str, str],
    values: Mapping[str, object],
    known: frozenset[str] | set[str] | None = None,
    meta: Sequence[tuple[str, str]] = (),
    table: TableSpec | None = None,
    totals: Sequence[tuple[str, str]] = (),
    legal: Sequence[LegalNote] = (),
    signature: SignatureImage | None = None,
    appearance_type: str | None = None,
    serif: bool = False,
    title_fallback: str = "",
) -> bytes:
    """Render a document PDF. Never raises for bad user text; reportlab errors propagate.

    Args:
        blocks: Resolved block texts (``title``, ``intro``, ``body``, ``terms``,
            ``closing``, ``signature``, ``footer``).
        values: Merge values, already formatted in the document locale.
        known: Declared field paths; others render empty.
        meta: Label/value rows under the title (number, date, recipient).
        table: Optional item table.
        totals: Label/value rows under the table, right aligned.
        legal: Locked legal notes; always printed, never editable.
        signature: Optional signature picture.
        appearance_type: Per-type look key for the letterhead.
        serif: Use the bundled Noto Serif face for the text.
        title_fallback: Title when the title block is empty.
    """
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.core.pdf_appearance import resolve_page_size
    from app.core.pdf_branding import (
        branded_doc_metadata,
        branded_footer,
        branded_header_footer,
        branded_letterhead,
        build_with_page_count,
    )

    st = _styles(serif)
    buf = io.BytesIO()
    page = resolve_page_size()
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        **branded_doc_metadata(),
    )
    width = page[0] - 40 * mm
    story: list[object] = []
    letterhead = branded_letterhead(width, appearance_type)
    if letterhead is not None:
        story += [letterhead, Spacer(1, 6 * mm)]

    def _blocks(name: str, style: object) -> None:
        for markup in to_reportlab(blocks.get(name) or "", values, known):
            story.append(_para(markup, style))

    title = to_plain(blocks.get("title") or "", values, known) or title_fallback
    if title:
        story.append(_para(_esc(title), st.title))
    if meta:
        rows = [[_para(_esc(k), st.small), _para(_esc(v), st.cell)] for k, v in meta]
        tbl = Table(rows, colWidths=[45 * mm, width - 45 * mm], hAlign="LEFT")
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story += [tbl, Spacer(1, 5 * mm)]
    _blocks("intro", st.body)
    _blocks("body", st.body)
    if table is not None and table.header:
        ncol = len(table.header)
        widths = (
            [w * mm for w in table.col_widths_mm]
            if table.col_widths_mm and len(table.col_widths_mm) == ncol
            else [width / ncol] * ncol
        )
        data = [[_para(f"<b>{_esc(h)}</b>", st.cell) for h in table.header]]
        for row in table.rows:
            data.append(
                [
                    _para(_esc(str(c)), st.cell_right if i in table.numeric_cols else st.cell)
                    for i, c in enumerate(list(row)[:ncol])
                ]
            )
        tbl = Table(data, colWidths=widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#333333")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story += [Spacer(1, 3 * mm), tbl]
    if totals:
        rows = [[_para(_esc(k), st.cell_right), _para(f"<b>{_esc(v)}</b>", st.cell_right)] for k, v in totals]
        tbl = Table(rows, colWidths=[width - 45 * mm, 45 * mm])
        tbl.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#333333"))]))
        story += [Spacer(1, 2 * mm), tbl]
    story.append(Spacer(1, 4 * mm))
    _blocks("terms", st.body)
    for note in legal:
        line = _esc(note.text) + (
            f' <font size="7" color="#777777">({_esc(note.source)})</font>' if note.source else ""
        )
        story.append(_para(line, st.bold))
    _blocks("closing", st.body)
    if signature is not None:
        try:
            img = Image(io.BytesIO(signature.png_bytes))
            ratio = (img.imageHeight or 1) / (img.imageWidth or 1)
            img.drawWidth = 45 * mm
            img.drawHeight = min(45 * mm * ratio, 20 * mm)
            img.hAlign = "LEFT"
            story.append(img)
            story.append(_para(_esc(signature.label), st.small))
        except Exception:  # noqa: BLE001 - a bad picture never breaks the document
            logger.warning("doc_templates: signature image skipped", exc_info=True)
    _blocks("signature", st.body)
    _blocks("footer", st.small)
    first = branded_footer if letterhead is not None else branded_header_footer
    build_with_page_count(doc, story, onFirstPage=first, onLaterPages=branded_header_footer)
    return buf.getvalue()
