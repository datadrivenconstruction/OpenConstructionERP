# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Background jobs for the file_trash module.

This module ships two entry points:

* :func:`register_jobs` — registers a 24-hour periodic task with the
  process-wide asyncio scheduler. ``app.main`` calls this once at
  startup. The function is idempotent — calling it twice silently
  no-ops on the second call.
* :func:`run_purge_once` — single-shot wrapper around
  :func:`purge_expired_trash` that opens its own short-lived session
  so it can be invoked from a Celery worker or a one-off CLI command
  without an outer SQLAlchemy context.

The 24-hour cadence matches the rest of the maintenance schedulers in
``app/main.py`` (KPI recalculation, reports). The first tick fires one
hour after process start so a brand-new install doesn't immediately
hammer the trash table.

Wiring point (already done in ``app/main.py``):

    from app.modules.file_trash.jobs import register_jobs
    register_jobs()  # called from the same startup block that wires
                     # KPI auto-recalculation, reports schedules etc.
"""

from __future__ import annotations

import asyncio
import logging

from app.database import async_session_factory
from app.modules.file_trash.service import purge_expired_trash

logger = logging.getLogger(__name__)

# Once-per-process guard so a hot-reload (or a duplicate ``register_jobs``
# call from a test harness) doesn't end up running two parallel purge
# loops against the same database.
_REGISTERED: bool = False

# Scheduler cadence — 24h is plenty given retention windows are
# measured in days and the cron is purely a clean-up safety net.
_DEFAULT_INTERVAL_SECONDS: int = 24 * 60 * 60

# First-tick delay so newly booted processes don't kick off a heavy
# scan during the same window as schema migrations + cache warm-ups.
_DEFAULT_FIRST_TICK_DELAY_SECONDS: int = 60 * 60  # 1 h


async def run_purge_once() -> int:
    """Open a short-lived session and run one purge pass.

    Returns the number of rows purged so the caller can log a
    summary line. Swallows DB-side errors (logs + returns 0) so a
    transient failure can't crash the scheduler loop.
    """
    try:
        async with async_session_factory() as session:
            count = await purge_expired_trash(session)
            await session.commit()
            return count
    except Exception:  # noqa: BLE001 — scheduler must never crash the loop
        logger.exception("file_trash.purge_expired_trash failed; will retry next tick")
        return 0


async def _scheduler_loop(
    interval_seconds: int,
    first_tick_delay_seconds: int,
) -> None:
    """Forever loop: wait → purge → wait → purge → …

    Logged at INFO when rows are purged, DEBUG when the tick is a
    no-op. Long-running enough that a single missed tick costs at
    most 24 h of stale trash — not a correctness issue.
    """
    await asyncio.sleep(first_tick_delay_seconds)
    while True:
        try:
            purged = await run_purge_once()
            if purged:
                logger.info(
                    "file_trash scheduler: purged %d expired trash row(s)",
                    purged,
                )
            else:
                logger.debug("file_trash scheduler: no expired rows")
        except asyncio.CancelledError:  # pragma: no cover — process shutdown
            raise
        except Exception:  # noqa: BLE001
            logger.exception("file_trash scheduler tick failed")
        await asyncio.sleep(interval_seconds)


def register_jobs(
    *,
    interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
    first_tick_delay_seconds: int = _DEFAULT_FIRST_TICK_DELAY_SECONDS,
) -> asyncio.Task[None] | None:
    """Schedule the periodic retention-purge job.

    Idempotent: the second call returns ``None`` and leaves the
    already-running task alone.

    Returns the created asyncio task on first call so callers /
    tests can ``cancel()`` it during teardown. Returns ``None`` on
    subsequent calls.
    """
    global _REGISTERED
    if _REGISTERED:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop yet — the scheduler is purely informative
        # in environments (e.g. sync tests) that haven't bound one.
        logger.debug(
            "file_trash.register_jobs: no running event loop; scheduler not started",
        )
        return None
    task = loop.create_task(
        _scheduler_loop(interval_seconds, first_tick_delay_seconds),
    )
    _REGISTERED = True
    logger.info(
        "file_trash scheduler registered (every %d s; first tick in %d s)",
        interval_seconds,
        first_tick_delay_seconds,
    )
    return task
