# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Text extractors used by the file_search indexer.

Two engines:

* :func:`_extract_pdf_text` - pypdfium2 (PDFium). Pulls embedded vector
  text out of every page; the cheap path. Returns the full text and the
  page count.
* :func:`_extract_ocr_text` - pytesseract. Rasterises the input bytes
  (PIL.Image) and runs Tesseract OCR. Slow; only used when the PDF
  reports zero embedded text, or for non-PDF mime types (jpg/png/tiff).

The public entrypoint :func:`extract_text` picks the right engine for
the supplied ``mime`` and returns an :class:`ExtractionResult`. Every
path degrades gracefully: if a library is missing, the function returns
an empty string and engine ``"none"`` - never raises.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Hard cap so a 1000-page PDF or a corrupt OCR pass cannot push a single
# row past 1 MB. Truncation is plain Python slicing - UTF-8 boundaries
# are preserved by the slice falling on a codepoint boundary (we cut
# *after* decoding, so individual codepoints are atomic).
MAX_CONTENT_BYTES: int = 10 * 1024 * 1024
MAX_CONTENT_CHARS: int = MAX_CONTENT_BYTES  # 1 char per byte upper bound

# A scanned PDF can sometimes carry a few stray characters in embedded
# text (drawing block headers, sheet numbers); below this threshold we
# still fall through to OCR to get the real body.
EMBEDDED_TEXT_FALLBACK_THRESHOLD: int = 32

# OCR rasterisation caps. A page render has no size ceiling of its own,
# so a large-format sheet (an A0 drawing at 150 DPI is ~35 MP) or a
# maliciously oversized page can make a single render allocate hundreds of MB
# and OOM a 3 GB worker. We clamp every page render so its pixmap never exceeds
# ``MAX_OCR_PIXELS`` (mirroring geo_hub.raster_pipeline.MAX_RASTER_PIXELS) and
# cap how many pages one document is OCR'd through so a 1000-page scan cannot
# pin an OCR worker. Text OCR does not need a huge raster, so the pixel cap is
# tighter than the 64 MP geo_hub uses for its visual rasters.
OCR_RENDER_DPI: int = 150
MAX_OCR_PIXELS: int = 40_000_000
MAX_OCR_PAGES: int = 200


@dataclass(frozen=True)
class ExtractionResult:
    """Output of an extraction run.

    Attributes:
        text:        Extracted Unicode text (already truncated to
                     ``MAX_CONTENT_CHARS``). Never ``None``.
        page_count:  Number of pages the extractor saw, or ``None`` for
                     mime types that have no page concept.
        engine:      Which extractor produced the text - one of
                     ``"pdfium"``, ``"pytesseract"``, ``"none"``.
        language:    Detected language code (``"eng"``, ``"deu"``, ...),
                     or ``None`` if no language detection was performed.
    """

    text: str
    page_count: int | None
    engine: str
    language: str | None = None


def _truncate(text: str) -> str:
    if len(text) > MAX_CONTENT_CHARS:
        return text[:MAX_CONTENT_CHARS]
    return text


def _clamp_render_scale(width_pt: float, height_pt: float, dpi: int, max_pixels: int) -> float:
    """Scale factor to rasterise a PDF page at ``dpi`` without exceeding ``max_pixels``.

    PDF user space is 72 units per inch, so the base scale for ``dpi`` is
    ``dpi / 72``. When a page is so large that the resulting pixmap would blow
    past ``max_pixels`` we shrink the scale to land on the cap (the same
    ``sqrt(cap / area)`` clamp geo_hub uses), so a 2 m x 2 m survey sheet renders
    at a safe resolution instead of allocating hundreds of MB. Degenerate
    (non-positive) page dimensions fall back to the unclamped scale.
    """
    scale = dpi / 72.0
    if width_pt <= 0 or height_pt <= 0:
        return scale
    est_pixels = int(width_pt * scale) * int(height_pt * scale)
    if est_pixels > max_pixels:
        scale = math.sqrt(max_pixels / (width_pt * height_pt))
    return scale


def _extract_pdf_text(payload: bytes) -> tuple[str, int]:
    """Pull embedded vector text out of a PDF using pypdfium2.

    Returns ``(text, page_count)``. Raises only on truly catastrophic
    extractor failure - graceful "no text" returns an empty string with
    the real page count.
    """
    try:
        from app.core import pdf_reader
    except Exception:  # pragma: no cover - base dependency
        logger.debug("PDF reader unavailable - skipping embedded-text extraction")
        return "", 0

    try:
        with pdf_reader.open_pdf(payload) as doc:
            page_count = doc.page_count
            parts: list[str] = []
            for page in doc:
                try:
                    parts.append(page.text() or "")
                except Exception:
                    logger.exception("PDF page text read failed; continuing")
                    continue
            text = "\n".join(parts).strip()
            return text, page_count
    except Exception:
        logger.exception("PDF reader failed to open PDF payload")
        return "", 0


def _extract_ocr_text(payload: bytes, mime: str | None) -> tuple[str, int | None]:
    """Run Tesseract OCR over an image (or rasterised PDF).

    For PDF inputs we render every page with pypdfium2 first (so we get a
    page-count) and then OCR each page image. For image inputs we run
    a single OCR pass and return ``page_count=None``.

    Returns ``(text, page_count)``.
    """
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - optional dep
        logger.debug("pytesseract or Pillow not installed - skipping OCR")
        return "", None

    # PDF input → rasterise each page, OCR each one.
    if mime and "pdf" in mime.lower():
        try:
            from io import BytesIO

            from app.core import pdf_reader
        except Exception:  # pragma: no cover - base dependency
            logger.debug("PDF reader unavailable - cannot rasterise PDF for OCR")
            return "", None

        try:
            with pdf_reader.open_pdf(payload) as doc:
                page_count = doc.page_count
                parts: list[str] = []
                for page_index, page in enumerate(doc):
                    if page_index >= MAX_OCR_PAGES:
                        logger.info(
                            "OCR page cap (%d) reached; skipping the remaining %d page(s)",
                            MAX_OCR_PAGES,
                            page_count - MAX_OCR_PAGES,
                        )
                        break
                    pix = None
                    try:
                        scale = _clamp_render_scale(page.rect.width, page.rect.height, OCR_RENDER_DPI, MAX_OCR_PIXELS)
                        pix = page.render(zoom=scale)
                        with Image.open(BytesIO(pix.png())) as img:
                            page_text = pytesseract.image_to_string(img) or ""
                        parts.append(page_text)
                    except Exception:
                        logger.exception("OCR failed for PDF page; continuing")
                        continue
                    finally:
                        # Drop the page pixmap (can be ~100 MB) before the next
                        # iteration so peak memory is a single page, never the
                        # whole document's rasters.
                        pix = None
                return "\n".join(parts).strip(), page_count
        except Exception:
            logger.exception("OCR rasterisation pipeline failed for PDF")
            return "", None

    # Image input - single OCR pass.
    try:
        from io import BytesIO

        with Image.open(BytesIO(payload)) as img:
            return (pytesseract.image_to_string(img) or "").strip(), None
    except Exception:
        logger.exception("OCR failed for image payload")
        return "", None


def extract_text(payload: bytes, mime: str | None) -> ExtractionResult:
    """Extract searchable text from a file payload.

    Routing:
        * PDF:            pypdfium2 embedded text → fall back to OCR if
                          the PDF is image-only.
        * jpg/png/tiff:   pytesseract OCR.
        * everything else: best-effort UTF-8 decode of the payload
                          (covers .txt, .csv, .md, .json, .xml).

    Args:
        payload: Raw file bytes. May be ``b""`` (the caller forgot to
                 read the file) - we return an empty result, never
                 crash.
        mime:    Best-known mime type. Used only to route between
                 extractors; ``None`` is treated as "unknown".

    Returns:
        ExtractionResult - see class docstring.
    """
    if not payload:
        return ExtractionResult(text="", page_count=None, engine="none")

    mime_lower = (mime or "").lower()

    # ── PDF ───────────────────────────────────────────────────────────
    if "pdf" in mime_lower:
        text, page_count = _extract_pdf_text(payload)
        engine = "pdfium"
        if len(text) < EMBEDDED_TEXT_FALLBACK_THRESHOLD:
            ocr_text, ocr_pages = _extract_ocr_text(payload, mime_lower)
            if len(ocr_text) > len(text):
                text = ocr_text
                engine = "pytesseract"
                if ocr_pages is not None:
                    page_count = ocr_pages
        if not text:
            engine = "none"
        return ExtractionResult(
            text=_truncate(text),
            page_count=page_count if page_count else None,
            engine=engine,
        )

    # ── Image ─────────────────────────────────────────────────────────
    if mime_lower.startswith("image/"):
        text, _ = _extract_ocr_text(payload, mime_lower)
        engine = "pytesseract" if text else "none"
        return ExtractionResult(
            text=_truncate(text),
            page_count=None,
            engine=engine,
        )

    # ── Plain-text-ish ────────────────────────────────────────────────
    if (
        mime_lower.startswith("text/")
        or mime_lower
        in {
            "application/json",
            "application/xml",
            "application/yaml",
            "application/x-yaml",
        }
        or mime_lower == ""
    ):
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception:
            logger.exception("UTF-8 decode failed for payload mime=%s", mime_lower)
            text = ""
        engine = "plaintext" if text else "none"
        return ExtractionResult(
            text=_truncate(text),
            page_count=None,
            engine=engine,
        )

    # Unknown binary → no extraction.
    return ExtractionResult(text="", page_count=None, engine="none")
