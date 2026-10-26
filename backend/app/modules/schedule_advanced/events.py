# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced event handlers - takt / line-of-balance.

Subscribes to the ``schedule_advanced.takt.*`` event family published by
:class:`~app.modules.schedule_advanced.service.TaktScheduleService` and
keeps lightweight, side-effect-free bookkeeping in place (structured log
lines for observability). These handlers are intentionally non-blocking
and never open a second DB session - they run inside the detached event
task scheduled by ``event_bus.publish_detached``.

This module is auto-imported by the module loader when ``oe_schedule_advanced``
is loaded (see ``module_loader._load_module`` → ``events.py``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_takt_schedule_created(event: Event) -> None:
    """Log takt schedule creation for observability / downstream hooks."""
    data = event.data or {}
    logger.info(
        "takt schedule created: id=%s master=%s locations=%s",
        data.get("takt_schedule_id"),
        data.get("master_schedule_id"),
        data.get("location_count"),
    )


async def _on_takt_activities_imported(event: Event) -> None:
    """Log a bulk activity import into a takt schedule."""
    data = event.data or {}
    logger.info(
        "takt activities imported: takt=%s count=%s",
        data.get("takt_schedule_id"),
        data.get("count"),
    )


async def _on_takt_cycle_updated(event: Event) -> None:
    """Record a line-of-balance recomputation.

    The takt timeline shifting is a signal other modules (e.g. KPI
    rollups) may want to react to; for now we emit a structured log line
    so the makespan / violation movement is observable in production.
    """
    data = event.data or {}
    logger.info(
        "takt cycle updated: takt=%s makespan=%s violations=%s",
        data.get("takt_schedule_id"),
        data.get("makespan_days"),
        data.get("violation_count"),
    )


# ── Constraint links: the record that clears a constraint resolved ─────────
#
# An answered RFI, an approved submittal, an issued PO or a confirmed delivery
# makes the linked constraint clearable. The constraint is stamped and its
# owner notified; clearing stays a person's decision.

_LINK_EVENTS: dict[str, tuple[str, str]] = {
    "rfi.responded": ("rfi", "rfi_id"),
    "rfi.closed": ("rfi", "rfi_id"),
    "submittal.approved": ("submittal", "submittal_id"),
    "procurement.po.issued": ("purchase_order", "po_id"),
    "procurement.gr.confirmed": ("goods_receipt", "gr_id"),
}


async def mark_linked_constraints_resolved(session: Any, linked_type: str, linked_id: uuid.UUID) -> list[Any]:
    """Stamp open constraints linked to ``linked_id`` as resolvable and notify their owners."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.schedule_advanced.models import Constraint  # noqa: PLC0415

    rows = list(
        (
            await session.execute(
                select(Constraint).where(
                    Constraint.linked_type == linked_type,
                    Constraint.linked_id == linked_id,
                    Constraint.status.in_(("open", "in_progress", "escalated")),
                    Constraint.link_resolved_at.is_(None),
                )
            )
        ).scalars()
    )
    if not rows:
        return []
    from app.modules.notifications.service import NotificationService  # noqa: PLC0415

    notifier = NotificationService(session)
    now = datetime.now(UTC)
    for c in rows:
        c.link_resolved_at = now
        if c.owner_user_id:
            await notifier.create(
                c.owner_user_id,
                "lps_constraint_resolvable",
                "notifications.lps.constraint_resolvable_title",
                entity_type="schedule_advanced_constraint",
                entity_id=str(c.id),
                body_key="notifications.lps.constraint_resolvable_body",
                body_context={"description": c.description, "linked_type": linked_type},
                action_url="/schedule-advanced?tab=constraints",
            )
    await session.flush()
    return rows


async def _on_linked_record_resolved(event: Event) -> None:
    spec = _LINK_EVENTS.get(event.name)
    data = event.data or {}
    if spec is None or not data.get(spec[1]):
        return
    try:
        linked_id = uuid.UUID(str(data[spec[1]]))
    except ValueError:
        return
    from app.database import async_session_factory  # noqa: PLC0415

    try:
        async with async_session_factory() as session:
            await mark_linked_constraints_resolved(session, spec[0], linked_id)
            await session.commit()
    except Exception:
        logger.debug("schedule_advanced: linked constraint update for %s failed", event.name, exc_info=True)


def _register_handlers() -> None:
    """Wire takt handlers into the event bus.

    Idempotent in practice - the bus dedups by callable identity, and the
    module loader imports this module exactly once per process.
    """
    event_bus.subscribe_once("schedule_advanced.takt.schedule.created", _on_takt_schedule_created)
    event_bus.subscribe_once("schedule_advanced.takt.activities_imported", _on_takt_activities_imported)
    event_bus.subscribe_once("schedule_advanced.takt.cycle_updated", _on_takt_cycle_updated)
    for name in _LINK_EVENTS:
        event_bus.subscribe_once(name, _on_linked_record_resolved)


_register_handlers()


__all__: list[str] = [
    "_on_linked_record_resolved",
    "_on_takt_activities_imported",
    "_on_takt_cycle_updated",
    "_on_takt_schedule_created",
    "_register_handlers",
    "mark_linked_constraints_resolved",
]
