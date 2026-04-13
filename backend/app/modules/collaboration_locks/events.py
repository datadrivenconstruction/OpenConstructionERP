"""Event names for collaboration locks.

The service layer publishes these onto the global event bus; the
presence hub subscribes to them to broadcast over the WebSocket.  Other
modules can also subscribe — e.g. an audit-log module could record who
held a lock on what and for how long.
"""

from __future__ import annotations

COLLAB_LOCK_ACQUIRED = "collab.lock.acquired"
COLLAB_LOCK_HEARTBEAT = "collab.lock.heartbeat"
COLLAB_LOCK_RELEASED = "collab.lock.released"
COLLAB_LOCK_EXPIRED = "collab.lock.expired"


ALL_EVENTS: tuple[str, ...] = (
    COLLAB_LOCK_ACQUIRED,
    COLLAB_LOCK_HEARTBEAT,
    COLLAB_LOCK_RELEASED,
    COLLAB_LOCK_EXPIRED,
)
