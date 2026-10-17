# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittal ↔ approval-routes wiring (feature 06).

When the generic approval engine reaches a terminal decision on a
``submittal`` target it fires ``approval_routes.instance.completed`` (the
chain was fully approved) or ``approval_routes.instance.rejected`` (an
approver rejected a step). These subscribers translate that routed
decision back into the submittal's own FSM so a multi-step sign-off
drives the submittal status instead of a human clicking the legacy
``/approve`` button.

Design notes:

* The subscribers open their own short-lived session via
  :func:`async_session_factory` and gate on PostgreSQL, exactly like the
  wave-5 cross-module subscribers - a cross-session write on SQLite's
  single writer would deadlock the request transaction, and the engine
  publishes detached so the request session is already free.
* They only ever drive transitions the existing submittal FSM permits,
  through the idempotent :meth:`SubmittalService.apply_approval_decision`,
  so a duplicate or out-of-order event can never corrupt state.
* They are fail-soft: any error is logged at debug and swallowed so a
  downstream hiccup never breaks the foreground decision that produced
  the event.
* Projects with **no** configured route never reach here at all - the
  submittal keeps today's direct ``/approve`` / ``/review`` behaviour
  with zero breakage.
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus
from app.database import async_session_factory

logger = logging.getLogger(__name__)


async def _can_open_isolated_session() -> bool:
    """Return True only when a cross-session write is safe (PostgreSQL)."""
    try:
        async with async_session_factory() as probe:
            bind = probe.get_bind()
            dialect = getattr(getattr(bind, "dialect", None), "name", "") or ""
        return dialect == "postgresql"
    except Exception:
        return False


async def _apply(event: Event, *, decision: str) -> None:
    """Shared body for the completed / rejected handlers."""
    data = event.data or {}
    if data.get("target_kind") != "submittal":
        return
    target_raw = data.get("target_id")
    if not target_raw:
        return
    try:
        submittal_id = uuid.UUID(str(target_raw))
    except (ValueError, TypeError):
        return
    if not await _can_open_isolated_session():
        return
    try:
        async with async_session_factory() as session:
            from app.modules.submittals.service import SubmittalService

            svc = SubmittalService(session)
            await svc.apply_approval_decision(
                submittal_id,
                decision=decision,
                decided_by=data.get("decided_by"),
                comment=data.get("comment"),
            )
            await session.commit()
    except Exception:
        logger.debug(
            "submittals: approval %s decision wiring failed for %s",
            decision,
            target_raw,
            exc_info=True,
        )


async def _on_approval_completed(event: Event) -> None:
    """``approval_routes.instance.completed`` → approve the submittal."""
    await _apply(event, decision="approved")


async def _on_approval_rejected(event: Event) -> None:
    """``approval_routes.instance.rejected`` → reject the submittal."""
    await _apply(event, decision="rejected")


def register_submittal_approval_subscribers() -> None:
    """Idempotently wire the submittal approval-decision subscribers."""
    event_bus.subscribe_once("approval_routes.instance.completed", _on_approval_completed)
    event_bus.subscribe_once("approval_routes.instance.rejected", _on_approval_rejected)
    logger.info("Submittals: subscribed to approval-routes terminal decision events")
