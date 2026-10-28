# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Reusable PDF stamp / burn core.

This module owns the *pure-ish* stamp logic that overlays an approval
stamp onto a PDF and expands the canonical SVG placeholders. It was
extracted out of ``app.modules.file_approvals.service`` so any module that
needs to burn a stamp (file approvals today, transmittals / document
control tomorrow) shares one implementation rather than copying it.

Two entry points:

* :func:`expand_svg_placeholders` - a pure string transform that fills the
  ``{{text}}`` / ``{{date}}`` / ``{{approver}}`` tokens in an SVG template.
  Unknown placeholders are left untouched so template authors can use raw
  curly-braces in their SVG content.
* :func:`burn_pdf_stamp` - overlays a single stamp box (top-right corner)
  onto every page of a PDF via ``pypdf`` + ``reportlab``. Returns the
  stamped bytes, or ``None`` when the optional dependency stack is not
  importable / any failure occurs, so callers can fall back to a JSON
  sidecar. It NEVER raises - a stamp failure must not break a final
  approval.

``burn_pdf_stamp`` is "pure-ish": given the same inputs it deterministically
produces the same overlay geometry, but it does touch the process-global
reportlab font registry (via :func:`app.core.pdf_fonts.register_pdf_fonts`,
which is idempotent) and depends on the presence of the optional pypdf /
reportlab packages. It performs no I/O of its own - bytes in, bytes out.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Default stamp stroke/fill colour used when a template colour is not a
#: valid hex string. Matches the historic file-approvals fallback.
_DEFAULT_STAMP_COLOR = "#16a34a"

#: Stamp box geometry (points). Kept module-level so callers/tests can
#: reason about placement without duplicating the magic numbers.
_STAMP_W = 220
_STAMP_H = 80
_STAMP_MARGIN = 36
_STAMP_MIN_INSET = 24


def expand_svg_placeholders(svg: str, *, text: str, approver: str, decision_date: str) -> str:
    """Expand the canonical ``{{text}}``/``{{date}}``/``{{approver}}``
    placeholders inside the SVG template.

    Unknown placeholders are left untouched so future template authors
    can use raw curly-braces in their SVG content.
    """
    out = svg
    out = out.replace("{{text}}", text)
    out = out.replace("{{date}}", decision_date)
    out = out.replace("{{approver}}", approver)
    return out


def burn_pdf_stamp(
    pdf_bytes: bytes,
    *,
    template_text: str,
    template_color: str,
    approver: str,
    decision_date: str,
) -> bytes | None:
    """Overlay a stamp page onto a PDF via ``pypdf`` + ``reportlab``.

    Returns the stamped bytes, or ``None`` when the dependency stack is
    not importable / a failure occurs (callers then fall back to a
    JSON sidecar).
    """
    try:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas

        from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts
    except Exception:  # noqa: BLE001 - optional deps
        logger.debug(
            "pypdf / reportlab unavailable; sidecar fallback for stamp",
            exc_info=True,
        )
        return None

    register_pdf_fonts()

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        # Build a single-page overlay sized to the first page so the
        # stamp lands consistently regardless of orientation.
        if reader.pages:
            mb = reader.pages[0].mediabox
            try:
                page_w = float(mb.width)
                page_h = float(mb.height)
            except Exception:  # noqa: BLE001
                page_w, page_h = LETTER
        else:
            page_w, page_h = LETTER

        overlay_buf = BytesIO()
        c = canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
        try:
            stroke = HexColor(template_color)
        except Exception:  # noqa: BLE001 - invalid hex → fall back
            stroke = HexColor(_DEFAULT_STAMP_COLOR)
        c.setStrokeColor(stroke)
        c.setFillColor(stroke)
        c.setLineWidth(3)
        # Stamp box: top-right corner with margin.
        stamp_w = _STAMP_W
        stamp_h = _STAMP_H
        x0 = max(page_w - stamp_w - _STAMP_MARGIN, _STAMP_MIN_INSET)
        y0 = max(page_h - stamp_h - _STAMP_MARGIN, _STAMP_MIN_INSET)
        c.rect(x0, y0, stamp_w, stamp_h, stroke=1, fill=0)
        c.setFont(BOLD_FONT, 14)
        c.drawString(x0 + 12, y0 + stamp_h - 22, template_text[:40])
        c.setFont(BODY_FONT, 9)
        c.drawString(x0 + 12, y0 + stamp_h - 42, f"Approved by {approver[:32]}")
        c.drawString(x0 + 12, y0 + stamp_h - 58, decision_date)
        c.showPage()
        c.save()

        overlay_reader = PdfReader(BytesIO(overlay_buf.getvalue()))
        overlay_page = overlay_reader.pages[0]

        writer = PdfWriter()
        for page in reader.pages:
            page.merge_page(overlay_page)
            writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - never let stamp-burn crash final approve
        logger.exception("PDF stamp overlay failed; sidecar fallback")
        return None


__all__ = ["burn_pdf_stamp", "expand_svg_placeholders"]
