# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable change report of a drawing revision compare.

What a reviewer sends with an RFI or files with a re-measure: which two
revisions were compared, how they were aligned, and one row per changed
region with its preview, kind, location, detail, the reviewer's call and what
was raised from it.

Previews: JPEG thumbnails from the browser are embedded as they are; the SVG
thumbnails the server draws for DWG regions are redrawn as vector paths (they
only use move/line commands). PNG previews need Pillow and are skipped when it
is absent, the row still prints. The renderer is pure: rows and labels in,
bytes out.
"""

from __future__ import annotations

import base64
import binascii
import html
import io
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from reportlab.graphics.shapes import Drawing, PolyLine
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.i18n import t
from app.core.pdf_fonts import pdf_font, pdf_style_for_text

_THUMB_W = 34 * mm
_THUMB_H = 24 * mm
_PATH_RE = re.compile(r'<path d="([^"]*)" fill="none" stroke="(#[0-9a-fA-F]{6})" stroke-width="([0-9.]+)"')
_SIZE_RE = re.compile(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"')
_CMD_RE = re.compile(r"([MLhv])\s*(-?[0-9.]+)(?:\s+(-?[0-9.]+))?")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    body, bold = pdf_font("Helvetica"), pdf_font("Helvetica", bold=True)
    return {
        "title": ParagraphStyle("DcTitle", parent=base, fontName=bold, fontSize=15, leading=19),
        "label": ParagraphStyle("DcLabel", parent=base, fontName=body, fontSize=8.5, leading=11, textColor=colors.grey),
        "value": ParagraphStyle("DcValue", parent=base, fontName=body, fontSize=9.5, leading=12),
        "head": ParagraphStyle("DcHead", parent=base, fontName=bold, fontSize=8, leading=10),
        "cell": ParagraphStyle("DcCell", parent=base, fontName=body, fontSize=8, leading=10),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    rendered = "" if text is None else str(text)
    return Paragraph(html.escape(rendered, quote=True).replace("\n", "<br/>"), pdf_style_for_text(style, rendered))


def _svg_drawing(svg: str) -> Drawing | None:
    size = _SIZE_RE.search(svg)
    if size is None:
        return None
    width, height = float(size.group(1)), float(size.group(2))
    if width <= 0 or height <= 0:
        return None
    scale = min(_THUMB_W / width, _THUMB_H / height)
    drawing = Drawing(width * scale, height * scale)
    for d, colour, stroke in _PATH_RE.findall(svg):
        x = y = 0.0
        run: list[float] = []

        def flush(points: list[float], colour: str = colour, stroke: str = stroke) -> None:
            if len(points) >= 4:
                drawing.add(
                    PolyLine(points, strokeColor=colors.HexColor(colour), strokeWidth=float(stroke) * scale * 0.8)
                )

        for cmd, a, b in _CMD_RE.findall(html.unescape(d)):
            if cmd == "M":
                flush(run)
                x, y = float(a), float(b or 0)
                run = [x * scale, (height - y) * scale]
                continue
            if cmd == "L":
                x, y = float(a), float(b or 0)
            elif cmd == "h":
                x += float(a)
            elif cmd == "v":
                y += float(a)
            run.extend([x * scale, (height - y) * scale])
        flush(run)
    return drawing


def thumbnail_flowable(data_url: str | None) -> Any:
    """A flowable for a stored thumbnail, or an empty string when it cannot print."""
    if not data_url or "," not in data_url:
        return ""
    head, b64 = data_url.split(",", 1)
    try:
        raw = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        return ""
    if head.startswith("data:image/svg+xml"):
        return _svg_drawing(raw.decode("utf-8", errors="ignore")) or ""
    try:
        img = Image(io.BytesIO(raw))
        ratio = min(_THUMB_W / img.imageWidth, _THUMB_H / img.imageHeight)
        img.drawWidth, img.drawHeight = img.imageWidth * ratio, img.imageHeight * ratio
    except Exception:  # noqa: BLE001 - PNG without Pillow, corrupt data: print the row without it
        return ""
    return img


def _numbered_canvas(page_label: str, footer: str) -> type[rl_canvas.Canvas]:
    class _Numbered(rl_canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 - reportlab API
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont(pdf_font("Helvetica"), 7.5)
                self.setFillColor(colors.grey)
                width, _ = self._pagesize
                self.drawString(12 * mm, 8 * mm, footer)
                self.drawRightString(width - 12 * mm, 8 * mm, page_label.format(page=self._pageNumber, total=total))
                super().showPage()
            super().save()

    return _Numbered


def _location(change: Any, source_kind: str, tr: Callable[..., str]) -> str:
    coords = f"{change.x:.0f}, {change.y:.0f} ({change.w:.0f} x {change.h:.0f})"
    if source_kind == "pdf" and change.page:
        return tr("report.page_at", page=change.page, coords=coords)
    return coords


def _detail(change: Any, tr: Callable[..., str]) -> str:
    parts: list[str] = []
    if change.old_text is not None or change.new_text is not None:
        parts.append(tr("text_change", old=change.old_text or "", new=change.new_text or ""))
    if change.layer:
        parts.append(tr("report.layer", layer=change.layer))
    counts = (change.details or {}).get("counts") if isinstance(change.details, dict) else None
    if isinstance(counts, dict):
        parts.append(
            t(
                "drawing_compare.report.entity_counts",
                added=counts.get("added", 0),
                removed=counts.get("removed", 0),
                modified=counts.get("modified", 0),
            )
        )
    return "\n".join(parts)


def _follow_up(change: Any, rfi_numbers: dict[str, str], tr: Callable[..., str]) -> str:
    parts: list[str] = []
    if change.rfi_id:
        parts.append(tr("report.rfi", number=rfi_numbers.get(change.rfi_id, "")))
    if change.markup_id:
        parts.append(tr("report.markup"))
    flagged = len(change.flagged_measurement_ids or []) + len(change.flagged_annotation_ids or [])
    if change.flagged_at:
        parts.append(
            t(
                "drawing_compare.report.remeasure",
                items=flagged,
                positions=len(change.flagged_position_ids or []),
            )
        )
    return "\n".join(parts)


def build_change_report_pdf(
    comparison: Any,
    changes: Sequence[Any],
    *,
    project_name: str = "",
    rfi_numbers: dict[str, str] | None = None,
    locale: str | None = None,
) -> bytes:
    """Render the change report of one compare as PDF bytes."""
    rfi_numbers = rfi_numbers or {}
    styles = _styles()

    def tr(key: str, **params: Any) -> str:
        return t(f"drawing_compare.{key}", locale=locale, **params)

    def side(label: str, revision: str | None, page: int | None) -> str:
        text = f"{label} ({revision})" if revision else label
        if comparison.source_kind == "pdf" and page:
            text = tr("sheet_page", label=text, page=page)
        return text

    alignment = comparison.alignment or {}
    method = str(alignment.get("method") or "none")
    align_text = tr(f"report.alignment_{method}")
    if isinstance(alignment.get("confidence"), (int, float)):
        align_text = f"{align_text}, " + tr("report.confidence", value=f"{alignment['confidence']:.0%}")
    summary = comparison.summary or {}
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    details = [
        (tr("report.project"), project_name or ""),
        (tr("report.name"), comparison.name or ""),
        (tr("report.old_revision"), side(comparison.old_label, comparison.old_revision, comparison.old_page)),
        (tr("report.new_revision"), side(comparison.new_label, comparison.new_revision, comparison.new_page)),
        (tr("report.alignment"), align_text),
        (
            tr("report.summary"),
            tr(
                "report.summary_counts",
                total=summary.get("total", len(changes)),
                added=summary.get("added", 0),
                removed=summary.get("removed", 0),
                modified=summary.get("modified", 0),
                text=summary.get("text", 0),
            ),
        ),
        (tr("report.generated_on"), generated),
    ]
    story: list[Any] = [_p(tr("report.title"), styles["title"]), Spacer(1, 4 * mm)]
    head_table = Table(
        [[_p(k, styles["label"]), _p(v, styles["value"])] for k, v in details],
        colWidths=[45 * mm, 210 * mm],
    )
    head_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [head_table, Spacer(1, 5 * mm)]

    if not changes:
        story.append(_p(tr("report.no_changes"), styles["value"]))
    else:
        headers = [
            tr("report.col_no"),
            tr("report.col_preview"),
            tr("report.col_kind"),
            tr("report.col_location"),
            tr("report.col_detail"),
            tr("report.col_status"),
            tr("report.col_comment"),
            tr("report.col_follow_up"),
        ]
        rows: list[list[Any]] = [[_p(h, styles["head"]) for h in headers]]
        for ch in changes:
            rows.append(
                [
                    _p(str(ch.seq), styles["cell"]),
                    thumbnail_flowable(ch.thumbnail),
                    _p(tr(f"kind.{ch.kind}"), styles["cell"]),
                    _p(_location(ch, comparison.source_kind, tr), styles["cell"]),
                    _p(_detail(ch, tr), styles["cell"]),
                    _p(tr(f"status.{ch.status}"), styles["cell"]),
                    _p(ch.comment or "", styles["cell"]),
                    _p(_follow_up(ch, rfi_numbers, tr), styles["cell"]),
                ]
            )
        table = Table(
            rows,
            colWidths=[10 * mm, 38 * mm, 22 * mm, 38 * mm, 55 * mm, 22 * mm, 40 * mm, 32 * mm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=tr("report.title"),
    )
    footer = tr("report.generated", timestamp=generated)
    doc.build(story, canvasmaker=_numbered_canvas(tr("report.page_of"), footer))
    return buf.getvalue()
