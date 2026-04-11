"""BOQ event handlers — activity log integration + vector indexing.

Subscribes to all ``boq.*`` events and creates activity log entries
for audit trail purposes.  Also keeps the ``oe_boq_positions`` vector
collection in sync with the underlying Position rows so semantic search
and the per-row "Similar items" panel always reflect the latest data.

This module is auto-imported by the module loader when the ``oe_boq``
module is loaded (see ``module_loader._load_module`` → ``events.py``).
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.boq.models import BOQActivityLog, Position
from app.modules.boq.vector_adapter import boq_position_adapter

logger = logging.getLogger(__name__)

# ── Mapping from event names to human-readable descriptions ──────────────────

_EVENT_DESCRIPTIONS: dict[str, str] = {
    "boq.boq.created": "Created BOQ",
    "boq.boq.updated": "Updated BOQ",
    "boq.boq.deleted": "Deleted BOQ",
    "boq.boq.duplicated": "Duplicated BOQ",
    "boq.boq.created_from_template": "Created BOQ from template",
    "boq.position.created": "Added position {ordinal}",
    "boq.position.updated": "Updated position",
    "boq.position.deleted": "Deleted position",
    "boq.position.duplicated": "Duplicated position",
    "boq.section.created": "Created section {ordinal}",
    "boq.markup.created": "Added markup: {name}",
    "boq.markup.updated": "Updated markup",
    "boq.markup.deleted": "Deleted markup",
    "boq.markups.defaults_applied": "Applied default markups ({region})",
}


def _resolve_target(event_name: str) -> str:
    """Derive the target_type from the event name.

    Convention: ``boq.<entity>.<action>`` → target_type = entity.
    Falls back to "boq" for non-standard names.
    """
    parts = event_name.split(".")
    if len(parts) >= 2:
        return parts[1]  # "boq", "position", "section", "markup", "markups"
    return "boq"


def _build_description(event_name: str, data: dict) -> str:
    """Build a human-readable description from the event name and payload."""
    template = _EVENT_DESCRIPTIONS.get(event_name, event_name)
    try:
        return template.format(**data)
    except (KeyError, IndexError):
        return template


def _extract_target_id(event_name: str, data: dict) -> uuid.UUID | None:
    """Extract the target entity UUID from the event payload."""
    entity = _resolve_target(event_name)

    # Try entity-specific ID keys first, then generic
    for key in (
        f"{entity}_id",
        f"new_{entity}_id",
        "boq_id",
        "position_id",
        "markup_id",
        "section_id",
    ):
        val = data.get(key)
        if val is not None:
            try:
                return uuid.UUID(str(val))
            except (ValueError, AttributeError):
                continue
    return None


def _extract_boq_id(data: dict) -> uuid.UUID | None:
    """Extract boq_id from the event payload."""
    val = data.get("boq_id") or data.get("new_boq_id")
    if val is not None:
        try:
            return uuid.UUID(str(val))
        except (ValueError, AttributeError):
            pass
    return None


def _extract_project_id(data: dict) -> uuid.UUID | None:
    """Extract project_id from the event payload."""
    val = data.get("project_id")
    if val is not None:
        try:
            return uuid.UUID(str(val))
        except (ValueError, AttributeError):
            pass
    return None


# ── Wildcard handler for all boq.* events ────────────────────────────────────


# Disabled: wildcard handler causes MissingGreenlet with SQLite
# Re-enable when using PostgreSQL
# @event_bus.on("*")
async def _log_boq_activity(event: Event) -> None:
    """Handle all events and log BOQ-related ones to the activity table.

    Uses a separate database session to ensure the log entry is persisted
    even if the calling transaction has unusual lifecycle.  Non-BOQ events
    are silently ignored.
    """
    if not event.name.startswith("boq."):
        return

    data = event.data or {}

    # We need a user_id for the log entry.  If the event doesn't carry one,
    # use a system placeholder (all-zeros UUID).
    user_id_raw = data.get("user_id")
    if user_id_raw:
        try:
            user_id = uuid.UUID(str(user_id_raw))
        except (ValueError, AttributeError):
            user_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    else:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    entry = BOQActivityLog(
        project_id=_extract_project_id(data),
        boq_id=_extract_boq_id(data),
        user_id=user_id,
        action=event.name.removeprefix("boq."),
        target_type=_resolve_target(event.name),
        target_id=_extract_target_id(event.name, data),
        description=_build_description(event.name, data),
        changes=data.get("changes", {}),
        metadata_={
            "event_id": event.id,
            "source_module": event.source_module,
        },
    )

    try:
        async with async_session_factory() as session:
            session.add(entry)
            await session.commit()
    except Exception:
        logger.exception("Failed to write activity log for event '%s'", event.name)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_boq_positions`` collection in sync with the live Position
# rows.  Each handler opens its own short-lived session, eager-loads the
# parent BOQ so ``project_id_of`` resolves cleanly, and forwards the row
# to the adapter.  Failures are logged and swallowed — vector indexing is
# best-effort and must never break a normal CRUD path.


async def _index_position(event: Event) -> None:
    """Re-embed a single Position row after create / update."""
    pid_raw = (event.data or {}).get("position_id")
    if not pid_raw:
        return
    try:
        position_id = uuid.UUID(str(pid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = (
                select(Position)
                .options(selectinload(Position.boq))
                .where(Position.id == position_id)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(boq_position_adapter, str(position_id))
                return
            project_id = None
            if row.boq is not None and row.boq.project_id is not None:
                project_id = str(row.boq.project_id)
            await vector_index_one(
                boq_position_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("BOQ vector index failed for %s", pid_raw, exc_info=True)


async def _delete_position_vector(event: Event) -> None:
    """Remove a deleted Position row from the vector store."""
    pid_raw = (event.data or {}).get("position_id")
    if not pid_raw:
        return
    try:
        await vector_delete_one(boq_position_adapter, str(pid_raw))
    except Exception:
        logger.debug("BOQ vector delete failed for %s", pid_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_position_created(event: Event) -> None:
    await _index_position(event)


async def _on_position_updated(event: Event) -> None:
    await _index_position(event)


async def _on_position_deleted(event: Event) -> None:
    await _delete_position_vector(event)


event_bus.subscribe("boq.position.created", _on_position_created)
event_bus.subscribe("boq.position.updated", _on_position_updated)
event_bus.subscribe("boq.position.deleted", _on_position_deleted)
event_bus.subscribe("boq.position.duplicated", _on_position_created)
