# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Timeline bridge subscriber - persist significant events to the audit store.

The in-memory event bus (:mod:`app.core.events`) loses everything on restart.
This bridge subscribes a single wildcard handler that, for each *significant*
cross-module domain event (see :mod:`app.modules.timeline.mapping`), writes one
:class:`app.core.audit_log.ActivityLog` row so the unified project timeline
survives a process restart.

The handler is best-effort. Bursts share bounded sessions, but never share a
session across different request contexts. Each event still owns its commit
and rollback boundary. Registration is idempotent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.audit_log import log_activity
from app.core.event_batches import ContextBatchQueue, run_session_batch
from app.core.events import event_bus
from app.database import async_session_factory
from app.modules.timeline import mapping

if TYPE_CHECKING:
    from app.core.events import Event

logger = logging.getLogger(__name__)

_SUBSCRIBED_FLAG = "_timeline_subscribers_registered"


async def _record_event(event: Event) -> None:
    """Persist a significant event as one ActivityLog row (best-effort).

    Wrapped end-to-end in try/except: a malformed event, a mapping miss, or a
    DB hiccup is logged at WARNING and swallowed so the publishing workflow is
    never affected.
    """
    try:
        if not mapping.is_significant(event.name):
            return
        mapped = mapping.map_event(event.name, event.data or {})
        if mapped is None:
            return

        # A row with neither a parent project nor an entity id cannot be
        # returned by any timeline query - see mapping.is_routable. Writing it
        # would cost an insert and then read as coverage forever, so drop it
        # here and say why at WARNING rather than accumulating silent rows.
        if not mapping.is_routable(mapped):
            logger.warning(
                "timeline: dropping %s - payload carries no project id and no entity id, "
                "so the row could never appear on a timeline",
                event.name,
            )
            return

        metadata = {
            **mapped.get("metadata", {}),
            "_via": "event_bus",
            "event_id": event.id,
        }

        await _timeline_queue.submit({**mapped, "metadata": metadata})
    except Exception:  # noqa: BLE001 - best-effort, never break the publisher
        logger.warning(
            "timeline: failed to record event %s",
            getattr(event, "name", "<unknown>"),
            exc_info=True,
        )


async def _write_timeline_batch(rows: list[dict]) -> None:
    async def record(session, row) -> None:
        await log_activity(
            session,
            actor_id=row["actor_id"],
            action=row["action"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            module=row["module"],
            parent_entity_type=row["parent_entity_type"],
            parent_entity_id=row["parent_entity_id"],
            metadata=row["metadata"],
        )

    await run_session_batch("timeline", rows, async_session_factory, record)


_timeline_queue = ContextBatchQueue("timeline", _write_timeline_batch)


def register_timeline_subscribers() -> None:
    """Subscribe the wildcard bridge handler to the event bus (idempotent)."""
    if getattr(event_bus, _SUBSCRIBED_FLAG, False):
        return
    event_bus.subscribe_once("*", _record_event)
    try:
        setattr(event_bus, _SUBSCRIBED_FLAG, True)
    except (AttributeError, TypeError):
        pass
    logger.info("timeline: wildcard bridge subscriber registered")
