# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Collaboration-locks module - layer 1 of the real-time collab plan.

Provides pessimistic soft locks + presence broadcast for any entity
registered in :data:`schemas.ALLOWED_LOCK_ENTITY_TYPES`.  See
``router.py`` for the public HTTP + WebSocket surface.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Module startup hook invoked by :mod:`app.core.module_loader`.

    * Subscribes the broadcast bridge so lock events fan out over
      the presence WebSocket.
    * Declares the sweeper as a registry process; startup boots it.
    """
    from app.core.processes import process_registry
    from app.core.processes.builtin import register_collab_lock_sweeper
    from app.modules.collaboration_locks.router import (
        register_broadcast_subscribers,
    )

    register_broadcast_subscribers()
    register_collab_lock_sweeper(process_registry)
    logger.info("collaboration_locks: startup complete")
