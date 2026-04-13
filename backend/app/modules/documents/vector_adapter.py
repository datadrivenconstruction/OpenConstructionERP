"""Document vector adapter — feeds the ``oe_documents`` collection.

Each :class:`~app.modules.documents.models.Document` row is embedded as
its name, description, category, tags and any drawing metadata so that
semantic queries like *"structural rebar schedule level 02"* match
drawings, specs and photos regardless of the uploader's naming habits.

The adapter is intentionally narrow — it knows nothing about the event
bus or HTTP routing.  Wiring lives in :mod:`app.modules.documents.events`
and ``router.py`` respectively.
"""

from __future__ import annotations

import os
from typing import Any

from app.core.vector_index import COLLECTION_DOCUMENTS
from app.modules.documents.models import Document


def _file_name(row: Document) -> str:
    """Best-effort file name extraction — Document stores ``file_path`` only."""
    file_name = getattr(row, "file_name", None)
    if file_name:
        return str(file_name)
    file_path = getattr(row, "file_path", None) or ""
    if file_path:
        try:
            return os.path.basename(str(file_path))
        except Exception:
            return ""
    return ""


class DocumentVectorAdapter:
    """Embed project documents into the unified vector store."""

    collection_name: str = COLLECTION_DOCUMENTS
    module_name: str = "documents"

    def to_text(self, row: Document) -> str:
        """Build the canonical text that gets embedded.

        Concatenates the document name, description, category, tags and
        drawing metadata so that semantic search matches regardless of
        whether the user searched by title, drawing number, discipline
        or a free-text keyword from the description.
        """
        parts: list[str] = []
        name = getattr(row, "name", None)
        if name:
            parts.append(str(name).strip())
        description = getattr(row, "description", None)
        if description:
            parts.append(str(description).strip())
        category = getattr(row, "category", None)
        if category:
            parts.append(str(category).strip())
        tags = getattr(row, "tags", None)
        if isinstance(tags, list) and tags:
            tag_str = " ".join(str(t).strip() for t in tags if t)
            if tag_str:
                parts.append(tag_str)
        drawing_number = getattr(row, "drawing_number", None)
        if drawing_number:
            parts.append(str(drawing_number).strip())
        discipline = getattr(row, "discipline", None)
        if discipline:
            parts.append(str(discipline).strip())
        file_name = _file_name(row)
        if file_name:
            parts.append(file_name)
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: Document) -> dict[str, Any]:
        """Light metadata returned with every search hit so the UI can
        render a row card without an extra Postgres roundtrip."""
        name = getattr(row, "name", "") or ""
        return {
            "title": str(name)[:160],
            "category": getattr(row, "category", "") or "",
            "drawing_number": getattr(row, "drawing_number", "") or "",
            "discipline": getattr(row, "discipline", "") or "",
            "file_name": _file_name(row),
        }

    def project_id_of(self, row: Document) -> str | None:
        """Resolve the owning project id.

        Returns ``None`` if the document is detached from a project (should
        never happen in practice but defensive coding pays off).
        """
        project_id = getattr(row, "project_id", None)
        if project_id is None:
            return None
        return str(project_id)


# Singleton instance — adapters are stateless so one shared object is fine.
document_vector_adapter = DocumentVectorAdapter()
