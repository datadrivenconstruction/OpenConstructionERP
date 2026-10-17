# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI ↔ approval-routes wiring (feature 06).

When the generic approval engine reaches a terminal decision on an
``rfi`` target it fires ``approval_routes.instance.completed`` (the chain
was fully approved) or ``approval_routes.instance.rejected``. These
subscribers translate that routed decision into the RFI's own FSM,
conservatively (the RFI FSM and the approval FSM are orthogonal): an
approved sign-off only re-affirms an already-recorded answer, and a
rejection reopens an answered RFI. See
:meth:`RFIService.apply_approval_decision` for the exact mapping.

The subscribers open their own short-lived session, gate on PostgreSQL,
and are fail-soft - exactly like the submittals and wave-5 cross-module
subscribers. Projects with no configured route never reach here, so the
RFI keeps today's direct respond / close behaviour with zero breakage.
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
    if data.get("target_kind") != "rfi":
        return
    target_raw = data.get("target_id")
    if not target_raw:
        return
    try:
        rfi_id = uuid.UUID(str(target_raw))
    except (ValueError, TypeError):
        return
    if not await _can_open_isolated_session():
        return
    try:
        async with async_session_factory() as session:
            from app.modules.rfi.service import RFIService

            svc = RFIService(session)
            await svc.apply_approval_decision(
                rfi_id,
                decision=decision,
                decided_by=data.get("decided_by"),
                comment=data.get("comment"),
            )
            await session.commit()
    except Exception:
        logger.debug(
            "rfi: approval %s decision wiring failed for %s",
            decision,
            target_raw,
            exc_info=True,
        )


async def _on_approval_completed(event: Event) -> None:
    """``approval_routes.instance.completed`` → re-affirm the RFI answer."""
    await _apply(event, decision="approved")


async def _on_approval_rejected(event: Event) -> None:
    """``approval_routes.instance.rejected`` → reopen the RFI."""
    await _apply(event, decision="rejected")


def register_rfi_approval_subscribers() -> None:
    """Idempotently wire the RFI approval-decision subscribers."""
    event_bus.subscribe_once("approval_routes.instance.completed", _on_approval_completed)
    event_bus.subscribe_once("approval_routes.instance.rejected", _on_approval_rejected)
    logger.info("RFI: subscribed to approval-routes terminal decision events")
