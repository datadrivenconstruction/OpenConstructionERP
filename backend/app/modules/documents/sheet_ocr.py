"""OCR fallback for scanned drawing sheets.

A scanned sheet has no text layer, so the title block reader finds nothing.
This reads only the title block corner of such a page and returns text plus a
mean word confidence; the existing title block parser then runs over that text,
so there is one parser with two text sources. Tesseract is optional: without it
the sheet is still created and flagged for review.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: A page with fewer text-layer characters than this is treated as a scan.
SCAN_CHAR_THRESHOLD = 20
OCR_DPI = 200
#: Below this confidence a scan is held un-stacked until a person confirms it.
STACK_MIN_CONFIDENCE = 0.6
REASON_UNAVAILABLE = "ocr_unavailable"
REASON_FAILED = "ocr_failed"
REASON_PAGE_CAP = "ocr_page_cap"


@dataclass(frozen=True)
class OcrRead:
    """Text read from one title block and how sure the engine was, 0..1."""

    text: str = ""
    confidence: float = 0.0
    reason: str = ""


def _langs() -> str:
    return os.environ.get("OE_SHEET_OCR_LANGS", "").strip() or "eng"


def mean_confidence(data: dict[str, list[Any]]) -> tuple[str, float]:
    """Text and mean word confidence (0..1) from a tesseract ``image_to_data`` dict."""
    words: list[str] = []
    confs: list[float] = []
    for text, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
        token = (text or "").strip()
        try:
            value = float(conf)
        except (TypeError, ValueError):
            continue
        if not token or value < 0:
            continue
        words.append(token)
        confs.append(value)
    if not confs:
        return "", 0.0
    return " ".join(words), round(sum(confs) / len(confs) / 100.0, 3)


class TitleBlockOcr:
    """Reads the title block corner of single pages of one PDF; one crop in memory at a time."""

    def __init__(self, pdf_path: Path, max_pages: int | None = None) -> None:
        from app.modules.file_search.extractors import MAX_OCR_PAGES  # noqa: PLC0415

        self._path = pdf_path
        self._max = MAX_OCR_PAGES if max_pages is None else max_pages
        self._done = 0
        self._doc: Any = None

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def __enter__(self) -> TitleBlockOcr:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read(self, page_index: int) -> OcrRead:
        """OCR the bottom-right title block region of one page (zero-based index)."""
        try:
            import pytesseract  # type: ignore[import-not-found]  # noqa: PLC0415
        except Exception:
            return OcrRead(reason=REASON_UNAVAILABLE)
        if self._done >= self._max:
            return OcrRead(reason=REASON_PAGE_CAP)
        self._done += 1
        try:
            from app.core import pdf_reader  # noqa: PLC0415
            from app.modules.documents.service import _TITLE_BLOCK_REGION  # noqa: PLC0415
            from app.modules.file_search.extractors import MAX_OCR_PIXELS, _clamp_render_scale  # noqa: PLC0415

            if self._doc is None:
                self._doc = pdf_reader.open_pdf(self._path)
            page = self._doc[page_index]
            try:
                width, height = page.width, page.height
                from_left, from_top = _TITLE_BLOCK_REGION
                clip = (width * from_left, height * from_top, width, height)
                crop_w, crop_h = width - clip[0], height - clip[1]
                scale = _clamp_render_scale(crop_w, crop_h, OCR_DPI, MAX_OCR_PIXELS)
                image = page.render(zoom=scale, clip=clip).pil()
                data = pytesseract.image_to_data(image, lang=_langs(), output_type=pytesseract.Output.DICT)
            finally:
                page.close()
            text, conf = mean_confidence(data)
            return OcrRead(text=text, confidence=conf)
        except Exception:
            logger.warning("Title block OCR failed on page %d", page_index + 1, exc_info=True)
            return OcrRead(reason=REASON_FAILED)


def extraction_meta(source: str, read: OcrRead | None = None) -> dict[str, Any]:
    """The ``Sheet.metadata_["extraction"]`` value for a page read from ``source``."""
    if source != "ocr" or read is None:
        return {"source": "text", "confidence": 1.0, "needs_review": False}
    meta: dict[str, Any] = {"source": "ocr", "confidence": read.confidence, "needs_review": True}
    if read.reason:
        meta["reason"] = read.reason
    return meta


def is_held(metadata: dict[str, Any] | None) -> bool:
    """True for a scan whose reading is too weak to stack until somebody confirms it."""
    extraction = (metadata or {}).get("extraction")
    if not isinstance(extraction, dict) or not extraction.get("needs_review"):
        return False
    return float(extraction.get("confidence") or 0.0) < STACK_MIN_CONFIDENCE
