# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan room cross-module subscribers.

A pin mirrors the status of the record it points at, and goes away with it. The records never call
into plan_room; they publish their own events and this module listens.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)

# event name -> (record kind, payload key holding the record id, new status or payload key for it)
_STATUS_EVENTS: dict[str, tuple[str, str, str]] = {
    "punchlist.item.status_changed": ("punch", "item_id", "@to_status"),
    "rfi.updated": ("rfi", "rfi_id", "@status"),
    "rfi.responded": ("rfi", "rfi_id", "responded"),
    "rfi.closed": ("rfi", "rfi_id", "closed"),
    "ncr.status_changed": ("ncr", "ncr_id", "@to_status"),
    "inspection.completed.passed": ("inspection", "inspection_id", "completed"),
    "inspection.completed.failed": ("inspection", "inspection_id", "completed"),
}
_DELETE_EVENTS: dict[str, tuple[str, str]] = {
    "punchlist.item.deleted": ("punch", "item_id"),
    "rfi.deleted": ("rfi", "rfi_id"),
}


def _status_handler(kind: str, id_key: str, status_spec: str) -> Callable[[Event], Awaitable[None]]:
    async def handler(event: Event) -> None:
        data = event.data or {}
        target_id = data.get(id_key)
        new_status = data.get(status_spec[1:]) if status_spec.startswith("@") else status_spec
        if not target_id or not new_status:
            return
        try:
            from app.database import async_session_factory
            from app.modules.plan_room.pin_service import PinService

            async with async_session_factory() as session:
                if await PinService(session).mirror_status(kind, str(target_id), str(new_status)):
                    await session.commit()
        except Exception:  # noqa: BLE001 - mirroring is best effort, the record is already saved
            logger.debug("plan_room: status mirror failed for %s %s", kind, target_id, exc_info=True)

    return handler


def _delete_handler(kind: str, id_key: str) -> Callable[[Event], Awaitable[None]]:
    async def handler(event: Event) -> None:
        target_id = (event.data or {}).get(id_key)
        if not target_id:
            return
        try:
            from app.database import async_session_factory
            from app.modules.plan_room.pin_service import PinService

            async with async_session_factory() as session:
                if await PinService(session).drop_for_target(kind, str(target_id)):
                    await session.commit()
        except Exception:  # noqa: BLE001
            logger.debug("plan_room: pin cleanup failed for %s %s", kind, target_id, exc_info=True)

    return handler


# Built once so a second register call finds the same handler objects and subscribes nothing new.
_HANDLERS: dict[str, Callable[[Event], Awaitable[None]]] = {
    **{name: _status_handler(*spec) for name, spec in _STATUS_EVENTS.items()},
    **{name: _delete_handler(*spec) for name, spec in _DELETE_EVENTS.items()},
}


def register_subscribers() -> None:
    """Subscribe the status mirrors and the cleanup handlers (idempotent)."""
    for name, handler in _HANDLERS.items():
        event_bus.subscribe_once(name, handler)


register_subscribers()
