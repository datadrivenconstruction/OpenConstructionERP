"""Tasks event handlers — vector indexing subscribers.

Subscribes to ``tasks.task.*`` lifecycle events and keeps the
``oe_tasks`` vector collection in sync with the underlying Task rows so
semantic search and the per-row "Similar tasks" panel always reflect
the latest data.

This module is auto-imported by the module loader when the ``oe_tasks``
module is loaded (see ``module_loader._load_module`` → ``events.py``).
"""

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.tasks.models import Task
from app.modules.tasks.vector_adapter import task_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_tasks`` collection in sync with the live Task rows.  Each
# handler opens its own short-lived session, loads the row and forwards
# it to the adapter.  Failures are logged and swallowed — vector indexing
# is best-effort and must never break a normal CRUD path.


async def _index_task(event: Event) -> None:
    """Re-embed a single Task row after create / update."""
    tid_raw = (event.data or {}).get("task_id")
    if not tid_raw:
        return
    try:
        task_id = uuid.UUID(str(tid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = select(Task).where(Task.id == task_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(task_vector_adapter, str(task_id))
                return
            project_id = (
                str(row.project_id) if row.project_id is not None else None
            )
            await vector_index_one(
                task_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Tasks vector index failed for %s", tid_raw, exc_info=True)


async def _delete_task_vector(event: Event) -> None:
    """Remove a deleted Task row from the vector store."""
    tid_raw = (event.data or {}).get("task_id")
    if not tid_raw:
        return
    try:
        await vector_delete_one(task_vector_adapter, str(tid_raw))
    except Exception:
        logger.debug("Tasks vector delete failed for %s", tid_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_task_created(event: Event) -> None:
    await _index_task(event)


async def _on_task_updated(event: Event) -> None:
    await _index_task(event)


async def _on_task_deleted(event: Event) -> None:
    await _delete_task_vector(event)


event_bus.subscribe("tasks.task.created", _on_task_created)
event_bus.subscribe("tasks.task.updated", _on_task_updated)
event_bus.subscribe("tasks.task.deleted", _on_task_deleted)
