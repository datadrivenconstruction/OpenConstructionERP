# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CDE event subscribers.

Auto-imported by the module loader when ``oe_cde`` loads (see
``module_loader._load_module`` -> ``events.py``).

``cde.container.published`` is re-emitted by the core
``cde.container.promoted`` handler once a container crosses Gate B. This
module is its in-app consumer: it tells the owners of records linked to the
container's documents that the version under their work has changed. The
logic lives in :mod:`app.modules.cde.published_notice`; this file only binds
it to the bus and gives it its own session, opened after the publisher has
committed.

``cde.revision.published`` is the same news for every revision added after
that. A container crosses Gate B once and the state machine has no way back,
so without it the owners would hear about the first published revision and
never about the next one, which is the one that makes their quantities stale.
``CDEService.create_revision`` publishes it, after the commit, when the
container it adds to is already published. The notice is idempotent per
container revision, so the two events can never tell anyone twice about the
same one.
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_container_published(event: Event) -> None:
    """``cde.container.published`` / ``cde.revision.published`` -> notify owners."""
    data = event.data or {}
    raw_id = data.get("container_id")
    try:
        container_id = uuid.UUID(str(raw_id))
    except (ValueError, AttributeError, TypeError):
        logger.debug("cde.container.published without a usable container_id: %r", raw_id)
        return

    try:
        from app.database import async_session_factory
        from app.modules.cde.published_notice import notify_linked_record_owners

        async with async_session_factory() as session:
            await notify_linked_record_owners(
                session,
                container_id,
                promoted_by=data.get("promoted_by") or data.get("user_id"),
            )
            await session.commit()
    except Exception:
        logger.exception("Error handling cde.container.published for %s", container_id)


event_bus.subscribe_once("cde.container.published", _on_container_published)
event_bus.subscribe_once("cde.revision.published", _on_container_published)
