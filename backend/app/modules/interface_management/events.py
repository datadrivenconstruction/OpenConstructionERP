# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-management subscribers: approval-route events on an interface agreement.

An interface agreement is routed through the platform approval engine under
target kind ``interface``. approval_routes announces every lifecycle step on the
event bus (``approval_routes.instance.started|completed|rejected|cancelled``);
the handlers here turn the ones aimed at an interface into status-history
entries, and an approval into the move to ``agreed``.

Same constraints as the other modules wired to approval verdicts: each event is
handled in an isolated session of its own (the publisher's request transaction
may still be open), PostgreSQL only (a second writer on SQLite would deadlock
the request), and fail-soft (a failure is logged, never raised into the bus).
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus
from app.database import async_session_factory

logger = logging.getLogger(__name__)

TARGET_KIND = "interface"


async def _can_open_isolated_session() -> bool:
    try:
        async with async_session_factory() as probe:
            dialect = getattr(getattr(probe.get_bind(), "dialect", None), "name", "") or ""
        return dialect == "postgresql"
    except Exception:
        return False


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


async def handle_route_event(data: dict, *, verdict: str, session_factory=None) -> bool:
    """Record one approval-route event on the interface it was aimed at.

    Args:
        data: The approval_routes event payload.
        verdict: ``started``, ``approved``, ``rejected`` or ``cancelled``.
        session_factory: Session factory to use instead of the application's
            (tests pass their own; production leaves it ``None``).

    Returns:
        ``True`` when an entry was written, ``False`` when the event was not
        about an interface, the interface is gone, or handling failed.
    """
    if data.get("target_kind") != TARGET_KIND:
        return False
    interface_id = _uuid(data.get("target_id"))
    instance_id = _uuid(data.get("instance_id"))
    if interface_id is None:
        return False
    factory = session_factory or async_session_factory
    if session_factory is None and not await _can_open_isolated_session():
        return False
    try:
        async with factory() as session:
            from app.modules.interface_management.service import InterfaceManagementService

            actor = _uuid(data.get("decided_by") or data.get("cancelled_by"))
            comment = data.get("comment") if verdict != "cancelled" else data.get("reason")
            if verdict == "started" and instance_id is not None:
                # The started event does not name who started it; the instance does.
                from app.modules.approval_routes.models import Instance

                instance = await session.get(Instance, instance_id)
                actor = instance.started_by if instance is not None else None
            done = await InterfaceManagementService(session).apply_approval_event(
                interface_id,
                verdict=verdict,
                instance_id=instance_id,
                actor_id=actor,
                comment=str(comment) if comment else None,
            )
            await session.commit()
            return done
    except Exception:
        logger.warning("interface_management: route %s wiring failed for %s", verdict, interface_id, exc_info=True)
        return False


async def _on_started(event: Event) -> None:
    await handle_route_event(event.data or {}, verdict="started")


async def _on_completed(event: Event) -> None:
    await handle_route_event(event.data or {}, verdict="approved")


async def _on_rejected(event: Event) -> None:
    await handle_route_event(event.data or {}, verdict="rejected")


async def _on_cancelled(event: Event) -> None:
    await handle_route_event(event.data or {}, verdict="cancelled")


def register_interface_management_subscribers() -> None:
    """Wire the approval-route subscribers; safe to call any number of times."""
    event_bus.subscribe_once("approval_routes.instance.started", _on_started)
    event_bus.subscribe_once("approval_routes.instance.completed", _on_completed)
    event_bus.subscribe_once("approval_routes.instance.rejected", _on_rejected)
    event_bus.subscribe_once("approval_routes.instance.cancelled", _on_cancelled)
