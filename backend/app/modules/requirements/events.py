"""Requirements event handlers​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — vector indexing.

Subscribes to ``requirements.requirement.*`` events and keeps the
``oe_requirements`` vector collection in sync with the underlying
Requirement rows so semantic search and the per-requirement "Similar
items" panel always reflect the latest data.

Also subscribes to ``requirements.requirement.linked_bim`` so the BIM
viewer's element list query gets invalidated automatically when a new
BIM↔requirement link is created (the elements endpoint reads requirement
links via the bim_hub eager-load path).

This module is auto-imported by the module loader when the
``oe_requirements`` module is loaded (see
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
from app.modules.requirements.models import Requirement
from app.modules.requirements.vector_adapter import requirement_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────


async def _index_requirement(event: Event) -> None:
    """Re-embed a single Requirement row after create / update / link.

    Loads the row in a fresh short-lived session with the parent
    RequirementSet eager-loaded so ``project_id_of`` resolves cleanly.
    Failures are swallowed — vector indexing is best-effort and must
    never break a normal CRUD or link path.
    """
    rid_raw = (event.data or {}).get("requirement_id")
    if not rid_raw:
        return
    try:
        req_id = uuid.UUID(str(rid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = (
                select(Requirement)
                .options(selectinload(Requirement.requirement_set))
                .where(Requirement.id == req_id)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(requirement_vector_adapter, str(req_id))
                return
            project_id = None
            rs = row.requirement_set
            if rs is not None and rs.project_id is not None:
                project_id = str(rs.project_id)
            await vector_index_one(
                requirement_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug(
            "Requirements vector index failed for %s", rid_raw, exc_info=True
        )


async def _delete_requirement_vector(event: Event) -> None:
    """Remove a deleted Requirement row from the vector store."""
    rid_raw = (event.data or {}).get("requirement_id")
    if not rid_raw:
        return
    try:
        await vector_delete_one(requirement_vector_adapter, str(rid_raw))
    except Exception:
        logger.debug(
            "Requirements vector delete failed for %s", rid_raw, exc_info=True
        )


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_requirement_created(event: Event) -> None:
    await _index_requirement(event)


async def _on_requirement_updated(event: Event) -> None:
    await _index_requirement(event)


async def _on_requirement_linked_bim(event: Event) -> None:
    """Re-index after a new BIM↔requirement link so the payload reflects
    the new ``metadata_["bim_element_ids"]`` array.  No frontend cache
    invalidation needed — React Query refetches the bim-elements query
    on its own when the BIM viewer's link modal closes."""
    await _index_requirement(event)


async def _on_requirement_deleted(event: Event) -> None:
    await _delete_requirement_vector(event)


event_bus.subscribe("requirements.requirement.created", _on_requirement_created)
event_bus.subscribe("requirements.requirement.updated", _on_requirement_updated)
event_bus.subscribe("requirements.requirement.deleted", _on_requirement_deleted)
event_bus.subscribe(
    "requirements.requirement.linked_bim", _on_requirement_linked_bim
)
