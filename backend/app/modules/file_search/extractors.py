# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Text extractors used by the file_search indexer.

Two engines:

* :func:`_extract_pdf_text` — PyMuPDF (``fitz``). Pulls embedded vector
  text out of every page; the cheap path. Returns the full text and the
  page count.
* :func:`_extract_ocr_text` — pytesseract. Rasterises the input bytes
  (PIL.Image) and runs Tesseract OCR. Slow; only used when PyMuPDF
  reports zero embedded text, or for non-PDF mime types (jpg/png/tiff).

The public entrypoint :func:`extract_text` picks the right engine for
the supplied ``mime`` and returns an :class:`ExtractionResult`. Every
path degrades gracefully: if a library is missing, the function returns
an empty string and engine ``"none"`` — never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Hard cap so a 1000-page PDF or a corrupt OCR pass cannot push a single
# row past 1 MB. Truncation is plain Python slicing — UTF-8 boundaries
# are preserved by the slice falling on a codepoint boundary (we cut
# *after* decoding, so individual codepoints are atomic).
MAX_CONTENT_BYTES: int = 1 * 1024 * 1024
MAX_CONTENT_CHARS: int = MAX_CONTENT_BYTES  # 1 char per byte upper bound

# A scanned PDF can sometimes carry a few stray characters in embedded
# text (drawing block headers, sheet numbers); below this threshold we
# still fall through to OCR to get the real body.
EMBEDDED_TEXT_FALLBACK_THRESHOLD: int = 32


@dataclass(frozen=True)
class ExtractionResult:
    """Output of an extraction run.

    Attributes:
        text:        Extracted Unicode text (already truncated to
                     ``MAX_CONTENT_CHARS``). Never ``None``.
        page_count:  Number of pages the extractor saw, or ``None`` for
                     mime types that have no page concept.
        engine:      Which extractor produced the text — one of
                     ``"pymupdf"``, ``"pytesseract"``, ``"none"``.
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


def _extract_pdf_text(payload: bytes) -> tuple[str, int]:
    """Pull embedded vector text out of a PDF using PyMuPDF.

    Returns ``(text, page_count)``. Raises only on truly catastrophic
    extractor failure — graceful "no text" returns an empty string with
    the real page count.
    """
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - optional dep
        logger.debug("PyMuPDF not installed — skipping embedded-text extraction")
        return "", 0

    try:
        with fitz.open(stream=payload, filetype="pdf") as doc:
            page_count = doc.page_count
            parts: list[str] = []
            for page in doc:
                try:
                    parts.append(page.get_text("text") or "")
                except Exception:
                    logger.exception("PyMuPDF page read failed; continuing")
                    continue
            text = "\n".join(parts).strip()
            return text, page_count
    except Exception:
        logger.exception("PyMuPDF failed to open PDF payload")
        return "", 0


def _extract_ocr_text(payload: bytes, mime: str | None) -> tuple[str, int | None]:
    """Run Tesseract OCR over an image (or rasterised PDF).

    For PDF inputs we render every page with PyMuPDF first (so we get a
    page-count) and then OCR each page image. For image inputs we run
    a single OCR pass and return ``page_count=None``.

    Returns ``(text, page_count)``.
    """
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - optional dep
        logger.debug("pytesseract or Pillow not installed — skipping OCR")
        return "", None

    # PDF input → rasterise each page, OCR each one.
    if mime and "pdf" in mime.lower():
        try:
            from io import BytesIO

            import fitz  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover - optional dep
            logger.debug("PyMuPDF not installed — cannot rasterise PDF for OCR")
            return "", None

        try:
            with fitz.open(stream=payload, filetype="pdf") as doc:
                page_count = doc.page_count
                parts: list[str] = []
                for page in doc:
                    try:
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        with Image.open(BytesIO(img_bytes)) as img:
                            page_text = pytesseract.image_to_string(img) or ""
                        parts.append(page_text)
                    except Exception:
                        logger.exception("OCR failed for PDF page; continuing")
                        continue
                return "\n".join(parts).strip(), page_count
        except Exception:
            logger.exception("OCR rasterisation pipeline failed for PDF")
            return "", None

    # Image input — single OCR pass.
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
        * PDF:            PyMuPDF embedded text → fall back to OCR if
                          the PDF is image-only.
        * jpg/png/tiff:   pytesseract OCR.
        * everything else: best-effort UTF-8 decode of the payload
                          (covers .txt, .csv, .md, .json, .xml).

    Args:
        payload: Raw file bytes. May be ``b""`` (the caller forgot to
                 read the file) — we return an empty result, never
                 crash.
        mime:    Best-known mime type. Used only to route between
                 extractors; ``None`` is treated as "unknown".

    Returns:
        ExtractionResult — see class docstring.
    """
    if not payload:
        return ExtractionResult(text="", page_count=None, engine="none")

    mime_lower = (mime or "").lower()

    # ── PDF ───────────────────────────────────────────────────────────
    if "pdf" in mime_lower:
        text, page_count = _extract_pdf_text(payload)
        engine = "pymupdf"
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
