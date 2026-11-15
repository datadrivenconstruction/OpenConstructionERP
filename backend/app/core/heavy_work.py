# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One heavy data load at a time in this process.

A cost-database import peaks at about +1.2 GB and the core has to run on a
3 GB server, so two of them, or one beside the first-run demo seed, must not
overlap. Every bulk loader takes :func:`heavy_slot` around its heavy part; a
second caller waits its turn instead of doubling the peak.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None
_holder: str | None = None


def _get_lock() -> asyncio.Lock:
    # One lock per event loop: tests start a fresh loop per test, and an
    # asyncio.Lock is bound to the loop it was first awaited on.
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


def current_holder() -> str | None:
    """Name of the load holding the slot, or None when it is free."""
    return _holder


@contextlib.asynccontextmanager
async def heavy_slot(name: str) -> AsyncIterator[None]:
    """Hold the process-wide heavy-load slot for the body of the ``async with``.

    Args:
        name: What is loading, for the log line a waiting caller writes.
    """
    global _holder
    lock = _get_lock()
    if lock.locked():
        logger.info("%s waits for %s to finish (one heavy load at a time)", name, _holder or "another load")
    async with lock:
        _holder = name
        try:
            yield
        finally:
            _holder = None


__all__ = ["current_holder", "heavy_slot"]
