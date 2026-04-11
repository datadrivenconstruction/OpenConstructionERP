"""Documents event handlers — vector indexing.

Subscribes to the ``documents.document.*`` event family and keeps the
``oe_documents`` vector collection in sync with the underlying Document
rows so semantic search and the per-row "Similar items" panel always
reflect the latest data.

This module is auto-imported by the module loader when the
``oe_documents`` module is loaded (see ``module_loader._load_module``
→ ``events.py``).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.documents.models import Document
from app.modules.documents.vector_adapter import document_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_documents`` collection in sync with the live Document
# rows.  Each handler opens its own short-lived session, fetches the row
# by id and forwards it to the adapter.  Failures are logged and
# swallowed — vector indexing is best-effort and must never break a
# normal CRUD path.


async def _index_document(event: Event) -> None:
    """Re-embed a single Document row after create / update."""
    did_raw = (event.data or {}).get("document_id")
    if not did_raw:
        return
    try:
        document_id = uuid.UUID(str(did_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = select(Document).where(Document.id == document_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(document_vector_adapter, str(document_id))
                return
            project_id = (
                str(row.project_id) if row.project_id is not None else None
            )
            await vector_index_one(
                document_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Documents vector index failed for %s", did_raw, exc_info=True)


async def _delete_document_vector(event: Event) -> None:
    """Remove a deleted Document row from the vector store."""
    did_raw = (event.data or {}).get("document_id")
    if not did_raw:
        return
    try:
        await vector_delete_one(document_vector_adapter, str(did_raw))
    except Exception:
        logger.debug("Documents vector delete failed for %s", did_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_document_created(event: Event) -> None:
    await _index_document(event)


async def _on_document_updated(event: Event) -> None:
    await _index_document(event)


async def _on_document_deleted(event: Event) -> None:
    await _delete_document_vector(event)


event_bus.subscribe("documents.document.created", _on_document_created)
event_bus.subscribe("documents.document.updated", _on_document_updated)
event_bus.subscribe("documents.document.deleted", _on_document_deleted)
