# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Periodic poll of the configured invoice mailboxes.

Started from the finance startup hook, one live task per process. A tick that
fails is logged and the loop carries on; the IMAP work runs in a worker thread,
so a slow server never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 120
_FIRST_TICK_SECONDS = 90
_ACTIVE_TASK: asyncio.Task[None] | None = None


async def run_once() -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.finance.invoice_mailbox_service import InvoiceMailboxService

    async with async_session_factory() as session:
        return await InvoiceMailboxService(session).poll_all()


async def _loop(interval: int, first: int) -> None:
    await asyncio.sleep(first)
    while True:
        try:
            counts = await run_once()
            if counts["mailboxes"]:
                logger.info("invoice mailbox poll: %s", counts)
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise
        except Exception:  # noqa: BLE001
            logger.exception("invoice mailbox poll failed")
        await asyncio.sleep(interval)


def register_jobs(interval: int = _INTERVAL_SECONDS, first: int = _FIRST_TICK_SECONDS) -> asyncio.Task[None] | None:
    """Schedule the poll; ``None`` when one already runs or there is no event loop."""
    global _ACTIVE_TASK
    if _ACTIVE_TASK is not None and not _ACTIVE_TASK.done():
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    _ACTIVE_TASK = loop.create_task(_loop(interval, first), name="invoice-mailbox-poll")
    return _ACTIVE_TASK
