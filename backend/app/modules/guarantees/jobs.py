# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ guarantees job: expiry alerts at 60/30/14 days, auto-extension, lapsing.

Started from the module startup hook. One live task per process; a reload or a
cancelled task starts a fresh one. The same work runs on demand through
``POST /api/v1/guarantees/alerts/run``.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 24 * 3600
_FIRST_TICK_SECONDS = 900
_ACTIVE_TASK: asyncio.Task[None] | None = None


async def run_once() -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.guarantees.service import GuaranteesService

    async with async_session_factory() as session:
        counts = await GuaranteesService(session).run_daily()
        await session.commit()
    return counts


async def _loop(interval: int, first: int) -> None:
    await asyncio.sleep(first)
    while True:
        try:
            counts = await run_once()
            logger.info("guarantees daily job: %s", counts)
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise
        except Exception:  # noqa: BLE001
            logger.exception("guarantees daily job failed")
        await asyncio.sleep(interval)


def register_jobs(interval: int = _INTERVAL_SECONDS, first: int = _FIRST_TICK_SECONDS) -> asyncio.Task[None] | None:
    """Schedule the daily job; returns the task, or ``None`` when one already runs or no loop exists."""
    global _ACTIVE_TASK
    if _ACTIVE_TASK is not None and not _ACTIVE_TASK.done():
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    _ACTIVE_TASK = loop.create_task(_loop(interval, first))
    return _ACTIVE_TASK
