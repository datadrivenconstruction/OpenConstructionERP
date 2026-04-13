"""BIM Hub event handlers​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — vector indexing for BIM elements.

Subscribes to ``bim_hub.element.*`` events and keeps the
``oe_bim_elements`` vector collection in sync with the underlying
``BIMElement`` rows so semantic search and the per-element "Similar
items" panel always reflect the latest data.

This module is auto-imported by the module loader when the
``oe_bim_hub`` module is loaded (see
``module_loader._load_module`` → ``events.py``).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.bim_hub.models import BIMElement
from app.modules.bim_hub.vector_adapter import bim_element_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_bim_elements`` collection in sync with the live
# BIMElement rows.  Each handler opens its own short-lived session,
# eager-loads the parent BIMModel so ``project_id_of`` resolves cleanly,
# and forwards the row to the adapter.  Failures are logged and
# swallowed — vector indexing is best-effort and must never break a
# normal CRUD path.


async def _index_element(event: Event) -> None:
    """Re-embed a single BIMElement row after create / update."""
    eid_raw = (event.data or {}).get("element_id")
    if not eid_raw:
        return
    try:
        element_id = uuid.UUID(str(eid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = (
                select(BIMElement)
                .options(selectinload(BIMElement.model))
                .where(BIMElement.id == element_id)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(
                    bim_element_vector_adapter, str(element_id)
                )
                return
            project_id = None
            if row.model is not None and row.model.project_id is not None:
                project_id = str(row.model.project_id)
            await vector_index_one(
                bim_element_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("BIM vector index failed for %s", eid_raw, exc_info=True)


async def _delete_element_vector(event: Event) -> None:
    """Remove a deleted BIMElement row from the vector store."""
    eid_raw = (event.data or {}).get("element_id")
    if not eid_raw:
        return
    try:
        await vector_delete_one(bim_element_vector_adapter, str(eid_raw))
    except Exception:
        logger.debug("BIM vector delete failed for %s", eid_raw, exc_info=True)


# NOTE: orphan-link cleanup used to live here as an event subscriber, but
# the subscriber opened its own session and crashed under SQLite write
# lock contention when the upstream service was still mid-transaction.
# The cleanup now runs INLINE in the service layer (see
# ``bim_hub.service._strip_orphaned_bim_links``) so it shares the active
# request session, has no lock contention, and runs inside the same
# transaction so a failure rolls back atomically with the upstream delete.


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_element_created(event: Event) -> None:
    await _index_element(event)


async def _on_element_updated(event: Event) -> None:
    await _index_element(event)


async def _on_element_deleted(event: Event) -> None:
    await _delete_element_vector(event)


event_bus.subscribe("bim_hub.element.created", _on_element_created)
# bim_hub.element.updated has no publisher today — BIM elements are
# refreshed via the bulk import path which fires `created` for the new
# rows.  The subscription is kept as a forward-compat hook so the day a
# PATCH /elements/{id}/ endpoint lands (e.g. for manual classification
# overrides), vector freshness will work without any wiring change.
event_bus.subscribe("bim_hub.element.updated", _on_element_updated)
event_bus.subscribe("bim_hub.element.deleted", _on_element_deleted)
