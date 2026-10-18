# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""5D Cost Model domain events.

The cost-model module talks to the rest of the platform through the global
:data:`app.core.events.event_bus`. Events are addressed by their dot-notation
name (``{module}.{entity}.{action}``); this module is the single place those
names are declared so publishers and subscribers agree on one spelling.

Published events:

* :data:`EVENT_BUDGET_LINE_ACTUAL_POSTED` - emitted by
  :meth:`CostSpineService.post_actual_to_budget_line` whenever a realised cost
  is posted onto a ``BudgetLine.actual_amount`` (Gap B). The payload carries
  ``project_id``, ``budget_line_id``, ``cost_line_id`` (nullable), ``category``,
  ``source_kind``, ``source_ref`` and the posted ``amount`` (base currency,
  Decimal-as-string). Gap D (cost-overrun alerts) and the reporting module
  subscribe to it for eventual-consistency rollups.

The labour-actuals subscriber (Gap A) is bound inside ``service.py`` at import
time; it listens to ``fieldreports.labour.logged`` (owned by the field-reports
module) and is therefore not re-declared here.

The cost-overrun-alert subscriber (Gap D) is likewise bound inside
``service.py`` at import time. It listens to BOTH
:data:`EVENT_BUDGET_LINE_UPDATED` (manual edits + threshold arming) and
:data:`EVENT_BUDGET_LINE_ACTUAL_POSTED` (Gap B / labour postings, which raise
``actual_amount`` without an ``updated`` event), and when a line's actual cost
breaches its armed threshold it creates a ``cost_overrun_alert`` notification
for the project owner (subject to a 24h cooldown). No new published event name
is introduced; the notification itself is the side effect.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Published event names ───────────────────────────────────────────────────

EVENT_BUDGET_LINE_ACTUAL_POSTED = "costmodel.budget_line.actual_posted"

# Existing cost-model events already published by ``service.py`` (declared here
# for discoverability; the strings remain the source of truth at the call site).
EVENT_SNAPSHOT_CREATED = "costmodel.snapshot.created"
EVENT_SNAPSHOT_DELETED = "costmodel.snapshot.deleted"
EVENT_BUDGET_LINE_CREATED = "costmodel.budget_line.created"
EVENT_BUDGET_LINE_UPDATED = "costmodel.budget_line.updated"
EVENT_BUDGET_LINE_DELETED = "costmodel.budget_line.deleted"
EVENT_SPINE_GENERATED = "costmodel.spine.generated"


def register_costmodel_subscribers() -> None:
    """Wire cost-model event subscribers into the global bus.

    The labour-actuals subscriber registers itself at import time in
    ``service.py`` (its binding must live in an allowed source file), so this
    hook is currently a no-op kept for symmetry with the other modules'
    startup wiring and as the home for any future in-module subscribers. It is
    safe to call more than once.
    """
    # Importing the service module ensures the labour-actuals subscriber is
    # bound even if nothing else has imported it yet at startup.
    import app.modules.costmodel.service  # noqa: F401
    from app.core.events import event_bus

    event_bus.subscribe_once("boq.position.updated", _on_bill_position_updated)
    event_bus.subscribe_once("boq.position.deleted", _on_bill_position_deleted)


# ── Cost lines follow the bill ───────────────────────────────────────────────
#
# A cost line generated from a bill position, or carrying a share of one, holds
# the position's money in its estimate. When the position is edited or deleted
# the line is refreshed from what it carries now, instead of waiting for the
# next spine generation. A recalculation or an import fires one event per row
# at commit, so the handlers only queue ids and one worker refreshes them up to
# ``_BATCH_SIZE`` at a time in one session per batch, never a session per row.

#: Position fields whose change can move money onto or off a cost line.
#: ``metadata`` carries the resources a rate is built from.
_MONEY_FIELDS = frozenset({"quantity", "unit_rate", "total", "unit", "metadata"})
_BATCH_SIZE = 200
_POSITION = "position"
_BILL = "bill"

_pending: dict[tuple[str, str], None] = {}
_worker: Any = None


def _touches_money(data: dict[str, Any]) -> bool:
    changes = data.get("changes")
    if not isinstance(changes, dict) or not changes or "propagated_from" in changes:
        return True
    return bool(_MONEY_FIELDS & set(changes))


async def _refresh(items: list[tuple[str, str]]) -> None:
    import uuid

    from app.database import async_session_factory
    from app.modules.costmodel.structure_service import CostStructureService

    positions: set[uuid.UUID] = set()
    bills: set[uuid.UUID] = set()
    for kind, raw in items:
        try:
            (positions if kind == _POSITION else bills).add(uuid.UUID(raw))
        except (ValueError, AttributeError, TypeError):
            continue
    if not positions and not bills:
        return
    async with async_session_factory() as session:
        changed = await CostStructureService(session).recompute_after_bill_change(positions, bills)
        await session.commit()
    if changed:
        logger.debug("Refreshed %d cost line(s) after bill edits", changed)


async def _drain() -> None:
    global _worker
    try:
        while _pending:
            keys = list(_pending)[:_BATCH_SIZE]
            for key in keys:
                _pending.pop(key, None)
            try:
                await _refresh(keys)
            except Exception:
                logger.exception("Cost line refresh after bill edits failed for %d key(s)", len(keys))
    finally:
        _worker = None


def _queue(key: tuple[str, str]) -> None:
    import asyncio

    global _worker
    loop = asyncio.get_running_loop()
    if _worker is not None and _worker.get_loop() is not loop:
        # Left over from a loop that is gone (a finished test's); it can never run here.
        _pending.clear()
        _worker = None
    _pending[key] = None
    if _worker is None or _worker.done():
        _worker = loop.create_task(_drain())


async def _on_bill_position_updated(event: object) -> None:
    data = getattr(event, "data", None) or {}
    position_id = str(data.get("position_id") or "")
    if position_id and _touches_money(data):
        _queue((_POSITION, position_id))


async def _on_bill_position_deleted(event: object) -> None:
    data = getattr(event, "data", None) or {}
    boq_id = str(data.get("boq_id") or "")
    if boq_id:
        _queue((_BILL, boq_id))


async def drain_bill_refresh() -> None:
    """Wait until queued cost line refreshes are done. For tests and shutdown."""
    import asyncio

    while _worker is not None and not _worker.done() and _worker.get_loop() is asyncio.get_running_loop():
        await asyncio.wait({_worker})
