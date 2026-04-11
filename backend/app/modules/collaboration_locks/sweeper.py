"""Background task that prunes expired locks.

Runs every :data:`SWEEP_INTERVAL_SECONDS` for the lifetime of the
process.  On shutdown the task is cancelled cooperatively so the
FastAPI process can exit cleanly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.database import async_session_factory
from app.modules.collaboration_locks.events import COLLAB_LOCK_EXPIRED
from app.modules.collaboration_locks.repository import CollabLockRepository

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS: int = 30

_task: asyncio.Task[None] | None = None


async def _sweep_once() -> int:
    """Delete every expired lock in a short-lived session.

    Returns the number of rows removed.  Publishes a ``collab.lock.expired``
    event for every row so subscribers (presence hub, audit log) can react.
    """
    now = datetime.now(UTC)
    from sqlalchemy import and_, select

    from app.core.events import event_bus
    from app.modules.collaboration_locks.models import CollabLock

    try:
        async with async_session_factory() as session:
            # Read first so we can publish events after delete.
            stmt = select(CollabLock).where(
                and_(CollabLock.expires_at <= now)
            )
            result = await session.execute(stmt)
            stale_rows = list(result.scalars().all())
            if not stale_rows:
                return 0

            snapshots = [
                {
                    "lock_id": str(row.id),
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id),
                    "user_id": str(row.user_id),
                }
                for row in stale_rows
            ]

            repo = CollabLockRepository(session)
            removed = await repo.delete_expired(now)
            await session.commit()
    except Exception:
        logger.exception("collab lock sweeper failed")
        return 0

    for snap in snapshots:
        try:
            await event_bus.publish(
                COLLAB_LOCK_EXPIRED,
                snap,
                source_module="collaboration_locks",
            )
        except Exception:
            logger.debug("sweeper event publish failed", exc_info=True)

    return removed


async def _sweeper_loop() -> None:
    """Main loop. Safe to cancel."""
    logger.info(
        "collab lock sweeper started (interval=%ss)", SWEEP_INTERVAL_SECONDS
    )
    try:
        while True:
            try:
                removed = await _sweep_once()
                if removed:
                    logger.debug("collab lock sweeper removed %d row(s)", removed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("collab lock sweeper iteration failed")
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("collab lock sweeper stopped")
        raise


def start_sweeper() -> None:
    """Spawn the sweeper task.  Idempotent: calling it twice is a no-op."""
    global _task
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("no running loop — sweeper will be started by on_startup")
        return
    _task = loop.create_task(_sweeper_loop(), name="collab_lock_sweeper")


def stop_sweeper() -> None:
    """Cancel the sweeper on shutdown."""
    global _task
    if _task is None:
        return
    _task.cancel()
    _task = None
