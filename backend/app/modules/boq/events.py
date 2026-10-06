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

import asyncio
import itertools
import logging
import uuid
from collections.abc import Awaitable, Callable, Hashable, Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import raiseload

from app.core.cache import _RateLimitedLogger
from app.core.events import Event, _log_failures, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_many as vector_index_many
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
    "boq.bim_quantity.applied": "Updated {applied} position quantities from a new BIM model version",
    "boq.positions.revision_flagged": "Flagged positions measured on {document_name} (revision {revision_code})",
    "boq.positions.bim_version_flagged": "Flagged positions linked to a changed BIM model version",
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


# The activity-log entries are written in sessions of their own, by the batch
# worker below.  PostgreSQL + asyncpg bridges the separate session cleanly
# across greenlets, so this handler is always registered.
async def _log_boq_activity(event: Event) -> None:
    """Handle all events and log BOQ-related ones to the activity table.

    The entries are queued and written in batches (see ``_BatchQueue``), each
    batch in a database session of its own, so the log entry is persisted even
    if the calling transaction has unusual lifecycle and a burst of events
    shares a few sessions.  Returns once this event's entries are written.
    Non-BOQ events are silently ignored.
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

    rows = _split_per_boq(event.name, data, fields)
    await _activity_queue.submit((next(_activity_keys), (event.name, row)) for row in rows)


async def _write_activity_rows(rows: list[dict]) -> None:
    """Write *rows* in one session and one commit."""
    async with async_session_factory() as session:
        for row in rows:
            # A fresh instance per attempt: an ORM object that has been through a
            # failed commit is not reusable in a second session.
            session.add(BOQActivityLog(**row))
        await session.commit()


async def _write_activity_unscoped(event_name: str, row: dict) -> None:
    """Write *row* again without its scope columns, after a foreign key rejected it.

    A scope column pointed at a row that is no longer there - the project
    deleted while the event was still in flight, say. The entry is worth more
    without its scope than not at all. What was acted on lives in ``target_id``
    and survives either way; only the "show me everything under this project"
    filter loses the row.
    """
    logger.warning(
        "Activity log for event '%s' named a row that no longer exists; writing it unscoped",
        event_name,
    )
    try:
        await _write_activity_rows([{**row, "project_id": None, "boq_id": None}])
    except Exception:
        logger.exception("Failed to write unscoped activity log for event '%s'", event_name)


async def _write_activity_entry(event_name: str, row: dict) -> None:
    """Write one entry on its own, falling back to the unscoped write on a foreign key."""
    try:
        await _write_activity_rows([row])
    except IntegrityError:
        await _write_activity_unscoped(event_name, row)
    except Exception:
        logger.exception("Failed to write activity log for event '%s'", event_name)


async def _write_activity_batch(items: list[tuple[Any, tuple[str, dict]]]) -> None:
    """Write a batch of queued entries in one commit.

    A commit is all or nothing, so one entry whose scope row has gone takes the
    batch with it. The batch is then written again an entry at a time, which
    leaves every other entry as it was and costs the bad one only its scope.
    """
    entries = [entry for _key, entry in items]
    try:
        await _write_activity_rows([row for _name, row in entries])
        return
    except IntegrityError:
        if len(entries) == 1:
            await _write_activity_unscoped(*entries[0])
            return
    except Exception:
        if len(entries) == 1:
            logger.exception("Failed to write activity log for event '%s'", entries[0][0])
            return
    logger.warning("Activity log batch of %d entries was rejected; writing them one by one", len(entries))
    for event_name, row in entries:
        await _write_activity_entry(event_name, row)


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


# ── Batched subscribers ──────────────────────────────────────────────────
#
# An importer that writes a bill row by row defers one ``boq.position.created``
# per row to the request's commit, and the commit fires them all at once, each
# publish as its own task. A subscriber that opened a session per event held as
# many sessions at the same moment as the bill had rows: 1000 for a 1000-row
# GAEB or Excel import, where the pool has 34 and a pool-less engine opens 1000
# server connections. So the handlers below only queue what they were told, and
# one worker per queue works it off ``_BATCH_SIZE`` keys at a time, one session
# per batch. A handler still returns only once its own keys are done, so a
# caller awaiting a publish sees the work finished, as before.

# Keys a worker reads, embeds or writes per batch. One batch holds one session.
_BATCH_SIZE = 200


class _Waiter:
    """One handler call, waiting for the keys it queued to be worked off."""

    __slots__ = ("future", "remaining")

    def __init__(self, future: asyncio.Future[None]) -> None:
        self.future = future
        self.remaining = 0

    def settle(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0 and not self.future.done():
            self.future.set_result(None)


class _BatchQueue:
    """Work queued by key and drained by a single worker task, a batch at a time.

    Keys keep their queue order, and a key queued again while still waiting
    moves to the back with the newer value (or with ``merge(old, new)``), so the
    last thing said about a row is what the worker acts on. The worker starts on
    the first submit and stops when the queue is empty, so an idle process holds
    no task and shutdown has nothing to wait for. It never raises: a failing
    batch is logged and its waiters are released all the same.
    """

    def __init__(
        self,
        name: str,
        process: Callable[[list[tuple[Any, Any]]], Awaitable[None]],
        merge: Callable[[Any, Any], Any] | None = None,
    ) -> None:
        self._name = name
        self._process = process
        self._merge = merge
        self._pending: dict[Hashable, tuple[Any, list[_Waiter]]] = {}
        self._worker: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def submit(self, items: Iterable[tuple[Hashable, Any]]) -> asyncio.Future[None]:
        """Queue *items* and return a future that resolves once all of them are done."""
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # Whatever is left belongs to a loop that is gone (a finished test's);
            # its waiters can never be released on this one.
            self._pending = {}
            self._worker = None
            self._loop = loop
        waiter = _Waiter(loop.create_future())
        for key, value in items:
            queued = self._pending.pop(key, None)
            waiters: list[_Waiter] = []
            if queued is not None:
                previous, waiters = queued
                if self._merge is not None:
                    value = self._merge(previous, value)
            if waiter not in waiters:
                waiters.append(waiter)
                waiter.remaining += 1
            self._pending[key] = (value, waiters)
        if waiter.remaining == 0:
            waiter.future.set_result(None)
        elif self._worker is None or self._worker.done():
            self._worker = _log_failures(self._run(), name=f"boq.{self._name}.batches")
        return waiter.future

    async def idle(self) -> None:
        """Wait until the worker has emptied the queue."""
        while self._worker is not None and not self._worker.done() and self._loop is asyncio.get_running_loop():
            await asyncio.wait({self._worker})

    async def _run(self) -> None:
        try:
            while self._pending:
                keys = list(itertools.islice(self._pending, _BATCH_SIZE))
                batch = [(key, self._pending.pop(key)) for key in keys]
                try:
                    await self._process([(key, value) for key, (value, _waiters) in batch])
                except Exception:
                    logger.exception("BOQ %s batch of %d failed", self._name, len(batch))
                finally:
                    for _key, (_value, waiters) in batch:
                        for waiter in waiters:
                            waiter.settle()
        finally:
            # Cancelled at shutdown: the queued work is dropped, as an interrupted
            # subscriber's always was, and nobody is left waiting on it.
            if self._pending:
                logger.warning("BOQ %s worker stopped with %d keys still queued", self._name, len(self._pending))
            for _value, waiters in self._pending.values():
                for waiter in waiters:
                    waiter.settle()
            self._pending = {}


# ── Vector indexing ──────────────────────────────────────────────────────
#
# Keep the ``oe_boq_positions`` collection in sync with the live Position
# rows. Failures (embedding model missing, Qdrant unreachable, LanceDB IO
# error, etc.) are funnelled through :data:`_vector_warn`, which collapses
# duplicate ``(operation, error-type)`` pairs to one line per 60 s - a long
# outage produces a handful of lines, not a flood. Vector indexing is
# best-effort and must never break a normal CRUD path.

# What the worker does with a queued position id.
_INDEX = "index"  # a new row: batched embedding
_REINDEX = "reindex"  # an edited row: one at a time, skipped when the store is current
_DELETE = "delete"


def _merge_vector_ops(previous: str, new: str) -> str:
    # A row created and then edited before the worker got to it is still new to
    # the store. Anything else: the last word wins, a delete above all.
    if previous == _INDEX and new == _REINDEX:
        return _INDEX
    return new


async def _load_for_index(ids: list[uuid.UUID]) -> tuple[dict[uuid.UUID, Position], dict[uuid.UUID, uuid.UUID]]:
    """Read the rows and the project of each of their bills, in one short session.

    The adapter reads plain columns only, so no relationship is loaded, and the
    session is closed before anything is embedded: it is never held while the
    model works.
    """
    async with async_session_factory() as session:
        stmt = select(Position).options(raiseload("*")).where(Position.id.in_(ids))
        rows = {row.id: row for row in (await session.execute(stmt)).scalars()}
        boq_ids = {row.boq_id for row in rows.values()}
        projects: dict[uuid.UUID, uuid.UUID] = {}
        if boq_ids:
            found = await session.execute(select(BOQ.id, BOQ.project_id).where(BOQ.id.in_(boq_ids)))
            projects = dict(found.all())
        session.expunge_all()
    return rows, projects


async def _index_batch(items: list[tuple[uuid.UUID, str]]) -> None:
    """Index, re-index and remove one batch of positions."""
    deletes = [pid for pid, op in items if op == _DELETE]
    wanted = {pid: op for pid, op in items if op != _DELETE}
    if wanted:
        try:
            rows, projects = await _load_for_index(list(wanted))
        except Exception as exc:  # noqa: BLE001 - outage funnel
            _vector_warn.warn("boq.vector.index", str(next(iter(wanted))), exc)
            wanted = {}
            rows, projects = {}, {}
        new_by_project: dict[str, list[Position]] = {}
        edited: list[tuple[Position, str]] = []
        for pid, op in wanted.items():
            row = rows.get(pid)
            project_id = projects.get(row.boq_id) if row is not None else None
            if row is None or project_id is None:
                # Deleted between the publish and now, alone or with its bill.
                deletes.append(pid)
            elif op == _INDEX:
                new_by_project.setdefault(str(project_id), []).append(row)
            else:
                edited.append((row, str(project_id)))
        # The project is passed explicitly: ``project_id_of`` would load the
        # bill, which ``raiseload`` refuses on purpose.
        for project_id, group in new_by_project.items():
            try:
                await vector_index_many(boq_position_adapter, group, project_id=project_id)
            except Exception as exc:  # noqa: BLE001 - outage funnel
                _vector_warn.warn("boq.vector.index", str(group[0].id), exc)
        for row, project_id in edited:
            try:
                await vector_index_one(boq_position_adapter, row, project_id=project_id)
            except Exception as exc:  # noqa: BLE001 - outage funnel
                _vector_warn.warn("boq.vector.index", str(row.id), exc)
    for pid in deletes:
        try:
            await vector_delete_one(boq_position_adapter, str(pid))
        except Exception as exc:  # noqa: BLE001 - outage funnel
            _vector_warn.warn("boq.vector.delete", str(pid), exc)


_vector_queue = _BatchQueue("vector_index", _index_batch, merge=_merge_vector_ops)
_activity_queue = _BatchQueue("activity_log", _write_activity_batch)
_activity_keys = itertools.count()


async def drain_pending() -> None:
    """Wait until the queued index and activity work is done. For tests and shutdown."""
    await _vector_queue.idle()
    await _activity_queue.idle()


def _position_id(event: Event) -> uuid.UUID | None:
    pid_raw = (event.data or {}).get("position_id")
    if not pid_raw:
        return None
    try:
        return uuid.UUID(str(pid_raw))
    except (ValueError, AttributeError):
        return None


async def _queue_position(event: Event, op: str) -> None:
    position_id = _position_id(event)
    if position_id is not None:
        await _vector_queue.submit([(position_id, op)])


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_position_created(event: Event) -> None:
    await _queue_position(event, _INDEX)


async def _on_position_updated(event: Event) -> None:
    await _queue_position(event, _REINDEX)


async def _on_position_deleted(event: Event) -> None:
    await _queue_position(event, _DELETE)


async def _on_positions_bulk_created(event: Event) -> None:
    """Queue every row a bulk create names under ``position_ids``.

    The same queue as the per-row events, so a bulk create is batched the same
    way and a row named by both is indexed once. An event without ids (an older
    publisher) indexes nothing, as before.
    """
    raw_ids = (event.data or {}).get("position_ids")
    if not isinstance(raw_ids, list):
        return
    ids: list[uuid.UUID] = []
    for raw in raw_ids:
        try:
            ids.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            continue
    if ids:
        await _vector_queue.submit((pid, _INDEX) for pid in ids)


async def _on_revision_flagged(event: Event) -> None:
    # Imported here: change_review pulls in the BOQ service, which this
    # module must not load at import time.
    from app.modules.boq.change_review import handle_revision_flagged

    await handle_revision_flagged(event)


async def _on_bim_version_flagged(event: Event) -> None:
    from app.modules.boq.change_review import handle_bim_version_flagged

    await handle_bim_version_flagged(event)


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
    event_bus.subscribe_once("boq.positions.bulk_created", _on_positions_bulk_created)

    # Change awareness: the core handlers publish which positions a new
    # drawing revision or BIM model version affects; these persist that as
    # review flags the estimator sees in the BOQ editor.
    event_bus.subscribe_once("boq.positions.revision_flagged", _on_revision_flagged)
    event_bus.subscribe_once("boq.positions.bim_version_flagged", _on_bim_version_flagged)

    event_bus.subscribe_once("*", _log_boq_activity)


_register_handlers()
