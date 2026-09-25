# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ event handlers - activity log integration + vector indexing.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.cache import _RateLimitedLogger
from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.boq.activity_text import READ_ONLY_ACTIVITY_ACTIONS, humanize_action
from app.modules.boq.models import BOQ, BOQActivityLog, Position
from app.modules.boq.vector_adapter import boq_position_adapter

logger = logging.getLogger(__name__)

# Dedicated rate limiter so a transient embedding-service outage doesn't
# flood the log - one line per (operation, error-type) per 60 s, with a
# "+N similar" suffix on the next emit.  Mirrors the cache-layer pattern.
_vector_warn = _RateLimitedLogger(window_seconds=60.0)


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
    "boq.positions.bulk_created": "Added {count} position(s)",
    "boq.positions.resource_propagated": "Propagated a resource definition to {count} position(s)",
    "boq.quantity_link.created": "Linked a position quantity to a model",
    "boq.quantity_link.applied": "Updated {applied} position quantities from linked models",
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
    template = _EVENT_DESCRIPTIONS.get(event_name)
    if template is None:
        return humanize_action(event_name)
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


# The activity-log wildcard subscription opens its own session inside the
# handler.  PostgreSQL + asyncpg bridges the separate session cleanly across
# greenlets, so this handler is always registered.
async def _log_boq_activity(event: Event) -> None:
    """Handle all events and log BOQ-related ones to the activity table.

    Uses a separate database session to ensure the log entry is persisted
    even if the calling transaction has unusual lifecycle.  Non-BOQ events
    are silently ignored.
    """
    if not event.name.startswith("boq."):
        return
    if event.name.removeprefix("boq.") in READ_ONLY_ACTIVITY_ACTIONS:
        return

    data = event.data or {}

    # A system-generated event (no acting user) logs ``user_id = None`` →
    # rendered as "System" in the feed. We previously wrote an all-zeros UUID
    # sentinel, but ``user_id`` is a FK to oe_users_user: SQLite ignored the
    # dangling reference (FK enforcement off), PostgreSQL rejects it with a
    # ForeignKeyViolationError. NULL is the portable, correct representation.
    user_id_raw = data.get("user_id")
    user_id: uuid.UUID | None = None
    if user_id_raw:
        try:
            user_id = uuid.UUID(str(user_id_raw))
        except (ValueError, AttributeError):
            user_id = None

    # The BOQ's own deletion is the one event whose parent row is provably
    # gone. ``delete_boq`` removes the row and publishes afterwards, and this
    # handler commits in a session of its own, so there is no ordering in
    # which oe_boq_boq still holds the id: either the delete is committed and
    # the row is gone, or it is not committed and this session cannot see it.
    # ``boq_id`` is a foreign key, so writing it makes PostgreSQL reject the
    # whole entry, and the deletion - the most audit-relevant thing that can
    # happen to a BOQ - never reaches the trail at all. Nothing is lost by
    # dropping it: ``target_id`` carries the same id and has no foreign key,
    # precisely so it can outlive what it names. Same correction as the one
    # made one column over for ``user_id``.
    boq_id = _extract_boq_id(data)
    if event.name == "boq.boq.deleted":
        boq_id = None

    fields = {
        "project_id": _extract_project_id(data),
        "boq_id": boq_id,
        "user_id": user_id,
        "action": event.name.removeprefix("boq."),
        "target_type": _resolve_target(event.name),
        "target_id": _extract_target_id(event.name, data),
        "description": _build_description(event.name, data),
        "changes": data.get("changes", {}),
        "metadata_": {
            "event_id": event.id,
            "source_module": event.source_module,
        },
    }

    async def _write(row: dict) -> None:
        # A fresh instance per attempt: an ORM object that has been through a
        # failed commit is not reusable in a second session.
        async with async_session_factory() as session:
            session.add(BOQActivityLog(**row))
            await session.commit()

    for row in _split_per_boq(event.name, data, fields):
        try:
            await _write(row)
        except IntegrityError:
            # A scope column pointed at a row that is no longer there - the
            # project deleted while the event was still in flight, say. The
            # entry is worth more without its scope than not at all, so write it
            # again unscoped. What was acted on lives in ``target_id`` and
            # survives either way; only the "show me everything under this
            # project" filter loses the row.
            logger.warning(
                "Activity log for event '%s' named a row that no longer exists; writing it unscoped",
                event.name,
            )
            try:
                await _write({**row, "project_id": None, "boq_id": None})
            except Exception:
                logger.exception("Failed to write unscoped activity log for event '%s'", event.name)
        except Exception:
            logger.exception("Failed to write activity log for event '%s'", event.name)


def _split_per_boq(event_name: str, data: dict, fields: dict) -> list[dict]:
    """One activity row per bill a fan-out event touched, or ``fields`` alone.

    ``boq.positions.resource_propagated`` stands for positions that may sit in
    several bills of the project, and its top-level ``boq_id`` is the bill of the
    position that was edited. Logged as one row, a bill whose lines were
    re-priced from another bill would show nothing in its own feed, which is
    filtered by ``boq_id``. So the event is written as one row per bill in
    ``changes.positions_by_boq``, each scoped to that bill and naming its own
    lines.
    """
    if event_name != "boq.positions.resource_propagated":
        return [fields]
    changes = data.get("changes") or {}
    by_boq = changes.get("positions_by_boq")
    if not isinstance(by_boq, dict) or not by_boq:
        return [fields]
    rows: list[dict] = []
    for boq_raw, position_ids in by_boq.items():
        try:
            boq_id = uuid.UUID(str(boq_raw))
        except (ValueError, AttributeError):
            continue
        ids = [str(p) for p in position_ids] if isinstance(position_ids, list) else []
        rows.append(
            {
                **fields,
                "boq_id": boq_id,
                "target_id": boq_id,
                "description": _build_description(event_name, {**data, "count": len(ids)}),
                "changes": {
                    "resource_code_propagation": changes.get("resource_code_propagation", []),
                    "position_ids": ids,
                    "propagated_from": data.get("propagated_from"),
                },
            }
        )
    return rows or [fields]


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_boq_positions`` collection in sync with the live Position
# rows.  Each handler opens its own short-lived session, eager-loads the
# parent BOQ so ``project_id_of`` resolves cleanly, and forwards the row
# to the adapter.  Failures are logged and swallowed - vector indexing is
# best-effort and must never break a normal CRUD path.


async def _index_position(event: Event) -> None:
    """Re-embed a single Position row after create / update.

    Failures (embedding model missing, Qdrant unreachable, LanceDB IO
    error, etc.) are funnelled through :data:`_vector_warn` which
    collapses duplicate ``(operation, error-type)`` pairs to one line
    per 60 s - a long outage produces a handful of lines, not a flood.
    """
    pid_raw = (event.data or {}).get("position_id")
    if not pid_raw:
        return
    try:
        position_id = uuid.UUID(str(pid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            # Only ``row.boq.project_id`` is read; load the parent BOQ but
            # suppress its positions/markups selectin loads so a single
            # position edit does not pull the whole BOQ tree into memory.
            stmt = (
                select(Position)
                .options(
                    selectinload(Position.boq).noload(BOQ.positions),
                    selectinload(Position.boq).noload(BOQ.markups),
                )
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
    except Exception as exc:  # noqa: BLE001 - outage funnel
        _vector_warn.warn("boq.vector.index", str(pid_raw), exc)


async def _delete_position_vector(event: Event) -> None:
    """Remove a deleted Position row from the vector store.

    See :func:`_index_position` for the rationale behind the rate-limited
    warning - deletes use the same embedding backend so they flake in
    the same ways.
    """
    pid_raw = (event.data or {}).get("position_id")
    if not pid_raw:
        return
    try:
        await vector_delete_one(boq_position_adapter, str(pid_raw))
    except Exception as exc:  # noqa: BLE001 - outage funnel
        _vector_warn.warn("boq.vector.delete", str(pid_raw), exc)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_position_created(event: Event) -> None:
    await _index_position(event)


async def _on_position_updated(event: Event) -> None:
    await _index_position(event)


async def _on_position_deleted(event: Event) -> None:
    await _delete_position_vector(event)


def _register_handlers() -> None:
    """Register the BOQ event-bus handlers.

    Vector-index handlers register per-event (create / update / delete /
    duplicate) and the activity-log wildcard handler subscribes to every
    event.  Calling this helper is idempotent - tests can call
    :func:`event_bus.clear` then re-invoke it.
    """
    event_bus.subscribe_once("boq.position.created", _on_position_created)
    event_bus.subscribe_once("boq.position.updated", _on_position_updated)
    event_bus.subscribe_once("boq.position.deleted", _on_position_deleted)
    event_bus.subscribe_once("boq.position.duplicated", _on_position_created)

    event_bus.subscribe_once("*", _log_boq_activity)


_register_handlers()
