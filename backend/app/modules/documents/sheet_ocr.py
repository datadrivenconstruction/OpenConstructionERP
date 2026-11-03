# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Optional OCR of a drawing's title block, for sheets that carry no text layer.

Only the bottom-right crop is rendered and read, one page at a time, so peak
memory stays at a single crop however long the set is. ``pytesseract`` (and the
``tesseract`` binary behind it) is optional: without it :class:`OcrUnavailable`
is raised and the caller keeps the sheet, flagged for a person to read.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pages OCR is attempted on in one drawing set; later scanned pages are kept
# without a read so a huge scan cannot hold a worker for minutes.
MAX_OCR_PAGES = 200

OCR_DPI = 200

# The title block's corner, as fractions of the page measured from the top-left:
# right of the first and below the second. Mirrors ``service._TITLE_BLOCK_REGION``.
TITLE_BLOCK_REGION = (0.5, 0.55)

# takeoff's language codes (PaddleOCR style) to tesseract's.
_TESSERACT_LANG = {
    "en": "eng",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "it": "ita",
    "ru": "rus",
    "hi": "hin",
    "ta": "tam",
    "te": "tel",
    "ar": "ara",
    "zh": "chi_sim",
    "ja": "jpn",
    "ko": "kor",
}


class OcrUnavailable(RuntimeError):  # noqa: N818 - reads as the state, like StopIteration
    """OCR cannot run here: no ``pytesseract``, no ``tesseract`` binary, or a failed read."""


def ocr_languages() -> list[str]:
    """Tesseract language codes for the configured takeoff languages, English always included."""
    try:
        from app.modules.takeoff.service import _ocr_langs  # noqa: PLC0415

        codes = _ocr_langs()
    except Exception:  # noqa: BLE001 - takeoff is a sibling module, never a hard dependency
        codes = ["en"]
    langs = [_TESSERACT_LANG[c] for c in codes if c in _TESSERACT_LANG]
    return list(dict.fromkeys(["eng", *langs]))


def _installed(pytesseract: Any, wanted: list[str]) -> list[str]:
    """The wanted languages tesseract has packs for (a missing pack fails the whole read)."""
    try:
        have = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - old wrappers: trust the request
        return wanted
    return [lang for lang in wanted if lang in have] or ["eng"]


def mean_confidence(data: dict[str, list[Any]]) -> tuple[str, float]:
    """Text and mean word confidence (0..1) from ``image_to_data`` output.

    Words with a negative confidence (tesseract's "not a word" marker) and empty
    words are ignored. No word at all reads as confidence 0.
    """
    words: list[str] = []
    confs: list[float] = []
    lines: dict[tuple[Any, Any, Any], list[str]] = {}
    texts = data.get("text", [])
    for i, raw in enumerate(texts):
        text = (raw or "").strip()
        try:
            conf = float(data["conf"][i])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if not text or conf < 0:
            continue
        words.append(text)
        confs.append(conf)
        key = (
            data.get("block_num", [0] * len(texts))[i],
            data.get("par_num", [0] * len(texts))[i],
            data.get("line_num", [0] * len(texts))[i],
        )
        lines.setdefault(key, []).append(text)
    if not words:
        return "", 0.0
    # Lines kept apart: the field regexes are line based ("SHEET NO: A-101").
    return "\n".join(" ".join(parts) for parts in lines.values()), round(sum(confs) / len(confs) / 100.0, 4)


def ocr_title_block(
    pdf_path: str | Path,
    page_index: int,
    langs: list[str] | None = None,
    render_lock: Any = None,
) -> tuple[str, float]:
    """OCR the title block corner of one page: ``(text, confidence 0..1)``.

    ``render_lock`` serialises the PDFium render with the caller's other PDFium
    use; the (slow) recognition runs outside it.

    Raises:
        OcrUnavailable: pytesseract or the tesseract binary is missing, the
            page is past ``MAX_OCR_PAGES`` or cannot be rendered.
    """
    if page_index >= MAX_OCR_PAGES:
        raise OcrUnavailable("page is past the OCR page cap")
    try:
        import pytesseract  # type: ignore[import-not-found]  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise OcrUnavailable("pytesseract is not installed") from exc

    from app.core import pdf_reader  # noqa: PLC0415

    image = None
    try:
        with pdf_reader.open_pdf(Path(pdf_path)) as doc:
            if not 0 <= page_index < doc.page_count:
                raise OcrUnavailable("page not found")
            page = doc[page_index]
            try:
                rect = page.rect
                width, height = rect.x1 - rect.x0, rect.y1 - rect.y0
                left, top = TITLE_BLOCK_REGION
                clip = (rect.x0 + width * left, rect.y0 + height * top, rect.x1, rect.y1)
                if render_lock is not None:
                    with render_lock:
                        rendered = page.render(dpi=OCR_DPI, clip=clip)
                else:
                    rendered = page.render(dpi=OCR_DPI, clip=clip)
            finally:
                page.close()
            image = rendered.pil()
        del rendered
        lang = "+".join(_installed(pytesseract, langs or ocr_languages()))
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    except OcrUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - missing binary, bad render: the sheet is kept either way
        logger.warning("title block OCR failed on page %d of %s", page_index + 1, pdf_path, exc_info=True)
        raise OcrUnavailable(str(exc)) from exc
    finally:
        if image is not None:
            image.close()
    return mean_confidence(data)


def ocr_enabled() -> bool:
    """Operators can switch OCR off (``OE_SHEET_OCR=0``) on a server that has tesseract but no spare RAM."""
    return os.environ.get("OE_SHEET_OCR", "1").strip().lower() not in {"0", "false", "no", "off"}
