"""Collaboration-locks module — layer 1 of the real-time collab plan.

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
    * Spawns the sweeper background task.
    """
    from app.modules.collaboration_locks.router import (
        register_broadcast_subscribers,
    )
    from app.modules.collaboration_locks.sweeper import start_sweeper

    register_broadcast_subscribers()
    start_sweeper()
    logger.info("collaboration_locks: startup complete")
