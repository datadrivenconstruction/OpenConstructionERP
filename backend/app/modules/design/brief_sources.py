"""Attached project documents -> ``SourceDoc`` (text pages, or images when a page has no text).

Uses the ERP's own intake: the file-search text extractor (embedded PDF text, OCR when installed,
plain text) and the DWG/DXF takeoff service for CAD files. No converter is added here.
"""

from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path

from .brief_model import SourceDoc

logger = logging.getLogger(__name__)

MIN_PAGE_TEXT = 40  # a PDF page with less text than this is treated as a picture
MAX_RENDERED_PAGES = 4
TEXT_LAYER_CHARS = 60000
CAD_EXT = (".dwg", ".dxf")
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def cad_pages(entities: list[dict]) -> list[str]:
    """Readable text of a drawing: the text annotations, grouped by layer, in drawing order.

    Annotation text is kept verbatim so a quote from it can be found again."""
    by_layer: dict[str, list[str]] = {}
    for e in entities:
        if e.get("type") not in ("TEXT", "MTEXT"):
            continue
        text = " ".join(str(e.get("text") or "").split())
        if text:
            by_layer.setdefault(str(e.get("layer", "0")), []).append(text)
    lines: list[str] = []
    for layer, items in by_layer.items():
        lines.append(f"[layer {layer}]")
        lines.extend(items)
    return ["\n".join(lines)[:TEXT_LAYER_CHARS]] if lines else []


def split_pages(text: str) -> list[str]:
    return text.split("\f") if text else []


def _render_pages(payload: bytes, pages: list[int]) -> list[tuple[int, str, str]]:
    from app.core import pdf_reader

    out = []
    with pdf_reader.open_pdf(payload) as doc:
        for n in pages[:MAX_RENDERED_PAGES]:
            png = doc[n - 1].render(dpi=110).png()
            out.append((n, base64.b64encode(png).decode("ascii"), "image/png"))
    return out


async def load_source_docs(
    session, project_id: uuid.UUID, user_id: uuid.UUID, document_ids: list[uuid.UUID], *, with_images: bool
) -> list[SourceDoc]:
    from app.modules.documents.models import Document
    from app.modules.file_search.extractors import extract_text

    docs: list[SourceDoc] = []
    for doc_id in document_ids:
        row = await session.get(Document, doc_id)
        if row is None or row.project_id != project_id:
            docs.append(
                SourceDoc(str(doc_id), str(doc_id), "document", note=f"Document {doc_id} is not in this project.")
            )
            continue
        name = row.name or str(doc_id)
        ext = Path(name).suffix.lower()
        path = Path(row.file_path) if row.file_path else None
        if ext in CAD_EXT:
            docs.append(await _load_cad(session, row, user_id, name))
            continue
        if path is None or not path.is_file():
            docs.append(SourceDoc(str(doc_id), name, "document", note=f"The file of '{name}' is not on disk."))
            continue
        payload = path.read_bytes()
        mime = row.mime_type or ("application/pdf" if ext == ".pdf" else IMAGE_MIME.get(ext, ""))
        result = extract_text(payload, mime)
        pages = split_pages(result.text)
        if ext in IMAGE_MIME or mime.startswith("image/"):
            images = [(1, base64.b64encode(payload).decode("ascii"), mime or IMAGE_MIME.get(ext, "image/png"))]
            docs.append(
                SourceDoc(str(doc_id), name, "sketch", pages=pages[:1] or [""], images=images if with_images else [])
            )
            continue
        kind = "drawing" if row.category == "drawing" else "document"
        sd = SourceDoc(str(doc_id), name, kind, pages=pages)
        if "pdf" in mime and with_images:
            count = result.page_count or len(pages)
            bare = [
                n for n in range(1, count + 1) if n > len(pages) or len((pages[n - 1] or "").strip()) < MIN_PAGE_TEXT
            ]
            if bare:
                try:
                    sd.images = _render_pages(payload, bare)
                    sd.pages = pages + [""] * (count - len(pages))
                except Exception:  # noqa: BLE001 - a page that cannot be rendered is reported, not fatal
                    logger.exception("rendering pages of %s failed", doc_id)
                    sd.note = f"Pages without text in '{name}' could not be rendered for the model."
        if not result.text.strip() and not sd.images:
            sd.note = f"No text could be read from '{name}' (scanned file without OCR available)."
        docs.append(sd)
    return docs


async def _load_cad(session, row, user_id: uuid.UUID, name: str) -> SourceDoc:
    try:
        from app.modules.dwg_takeoff.service import DwgTakeoffService
    except ImportError:
        return SourceDoc(
            str(row.id),
            name,
            "drawing",
            note=f"'{name}' was not read: this ERP has no CAD intake (dwg_takeoff) installed.",
        )

    service = DwgTakeoffService(session)
    try:
        drawing = await service.import_drawing_from_document(row.id, str(user_id), name=name)
    except Exception as exc:  # noqa: BLE001 - HTTPException from the takeoff service carries a reason
        detail = getattr(exc, "detail", None) or str(exc)
        return SourceDoc(str(row.id), name, "drawing", note=f"'{name}' could not be opened as a drawing: {detail}")
    if drawing.status not in ("ready",):
        return SourceDoc(
            str(row.id),
            name,
            "drawing",
            note=f"'{name}' is still being converted (status {drawing.status}); run the extraction again when it is ready.",
        )
    entities = await service.get_entities(drawing.id)
    pages = cad_pages(entities)
    sd = SourceDoc(str(row.id), name, "drawing", pages=pages)
    if not pages:
        sd.note = f"'{name}' has no text annotations; nothing could be read from it."
    return sd
