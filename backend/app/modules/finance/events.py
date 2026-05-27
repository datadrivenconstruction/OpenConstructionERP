"""‌⁠‍Finance event subscribers — turn procurement mutation events into
ProjectBudget.committed / actual updates.

Until v2.9.17 ``procurement.po.issued`` and ``procurement.gr.confirmed``
were published into a void: nothing in finance listened, so
``ProjectBudget.committed`` and ``ProjectBudget.actual`` stayed at 0
even when POs totalled millions.  The EVM dashboard's BAC and CPI were
silently divorced from real procurement activity.

The handlers in this module subscribe to those events and adjust the
project's budget rows accordingly:

* ``procurement.po.issued`` → committed += po.amount_total
* ``procurement.gr.confirmed`` → committed -= gr.amount, actual += gr.amount

Each handler opens its own short-lived session via
:data:`async_session_factory` (mirrors the pattern in
``notifications/events.py``) so a write failure inside the subscriber
never rolls back the upstream procurement transaction.

Budget-row selection strategy when a project has multiple budgets:
the handler picks the budget whose ``wbs_id`` matches the PO's first
line item ``wbs_id``; if there's no match (or the PO has no line
items / no wbs_id), it falls back to the oldest budget for the
project (``ORDER BY created_at LIMIT 1``).  That keeps single-budget
projects working unchanged and gives multi-budget projects a stable
WBS-driven mapping without forcing every PO line to declare a budget
explicitly.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.finance.models import ProjectBudget

logger = logging.getLogger(__name__)


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """‌⁠‍Best-effort string/Decimal coercion — never raises."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _coerce_uuid(value: object) -> uuid.UUID | None:
    """‌⁠‍Coerce a string/UUID to UUID, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _resolve_po_wbs(session: AsyncSession, po_id_raw: object) -> str | None:
    """Look up the first line-item ``wbs_id`` for a PO, used to route the
    commitment to the matching ProjectBudget row.

    Returns None if the PO has no items, no wbs_id on its first item, or
    if anything goes wrong — callers must tolerate a None and fall back
    to the project-level "first budget by created_at" rule.
    """
    po_id = _coerce_uuid(po_id_raw)
    if po_id is None:
        return None
    try:
        from app.modules.procurement.models import PurchaseOrderItem

        stmt = (
            select(PurchaseOrderItem.wbs_id)
            .where(PurchaseOrderItem.po_id == po_id)
            .where(PurchaseOrderItem.wbs_id.isnot(None))
            .order_by(PurchaseOrderItem.sort_order)
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception:
        return None


async def _select_budget_row(
    session: AsyncSession,
    project_id: uuid.UUID,
    wbs_id: str | None,
) -> ProjectBudget | None:
    """Pick the ProjectBudget row that should absorb a procurement delta.

    Resolution order:
        1. Exact ``(project_id, wbs_id)`` match if a wbs hint is supplied.
        2. Oldest budget for the project (``ORDER BY created_at LIMIT 1``).

    Returns None when the project has no budget rows at all — handlers
    treat this as a no-op (we can't update what doesn't exist).
    """
    if wbs_id:
        stmt = (
            select(ProjectBudget)
            .where(ProjectBudget.project_id == project_id)
            .where(ProjectBudget.wbs_id == wbs_id)
            .limit(1)
        )
        match = (await session.execute(stmt)).scalar_one_or_none()
        if match is not None:
            return match

    stmt = (
        select(ProjectBudget)
        .where(ProjectBudget.project_id == project_id)
        .order_by(ProjectBudget.created_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _on_po_issued(event: Event) -> None:
    """``procurement.po.issued`` → ProjectBudget.committed += amount_total."""
    data = event.data or {}
    project_id = _coerce_uuid(data.get("project_id"))
    amount = _to_decimal(data.get("amount_total"))
    if project_id is None or amount == 0:
        return
    try:
        async with async_session_factory() as session:
            wbs_hint = await _resolve_po_wbs(session, data.get("po_id"))
            budget = await _select_budget_row(session, project_id, wbs_hint)
            if budget is None:
                logger.info(
                    "finance: po.issued for project %s — no budget rows, commitment skipped (po_id=%s, amount=%s)",
                    project_id,
                    data.get("po_id"),
                    amount,
                )
                return
            current = _to_decimal(budget.committed)
            budget.committed = current + amount
            await session.commit()
            logger.info(
                "finance: po.issued committed += %s on budget %s (project=%s, po=%s)",
                amount,
                budget.id,
                project_id,
                data.get("po_id"),
            )
    except Exception:
        logger.debug("finance: _on_po_issued failed", exc_info=True)


async def _on_gr_confirmed(event: Event) -> None:
    """``procurement.gr.confirmed`` → committed -= amount, actual += amount."""
    data = event.data or {}
    project_id = _coerce_uuid(data.get("project_id"))
    amount = _to_decimal(data.get("amount"))
    if project_id is None or amount == 0:
        return
    try:
        async with async_session_factory() as session:
            wbs_hint = await _resolve_po_wbs(session, data.get("po_id"))
            budget = await _select_budget_row(session, project_id, wbs_hint)
            if budget is None:
                logger.info(
                    "finance: gr.confirmed for project %s — no budget rows, actuals skipped (gr_id=%s, amount=%s)",
                    project_id,
                    data.get("gr_id"),
                    amount,
                )
                return
            current_committed = _to_decimal(budget.committed)
            current_actual = _to_decimal(budget.actual)
            new_committed = current_committed - amount
            # Don't let the committed slot go negative — if a GR exceeds the
            # outstanding commitment (because the PO was never issued, or the
            # commitment was already drained by a parallel write), zero it
            # out rather than recording a phantom credit.
            if new_committed < 0:
                new_committed = Decimal("0")
            budget.committed = new_committed
            budget.actual = current_actual + amount
            await session.commit()
            logger.info(
                "finance: gr.confirmed flipped %s from committed→actual on budget %s (project=%s, gr=%s)",
                amount,
                budget.id,
                project_id,
                data.get("gr_id"),
            )
    except Exception:
        logger.debug("finance: _on_gr_confirmed failed", exc_info=True)


_SUBSCRIPTIONS: list[tuple[str, callable]] = [  # type: ignore[type-arg]
    ("procurement.po.issued", _on_po_issued),
    ("procurement.gr.confirmed", _on_gr_confirmed),
]


def register_finance_subscribers() -> None:
    """Wire every entry of ``_SUBSCRIPTIONS`` into the global event bus.

    Idempotent: subscribing the same handler twice is harmless because
    the EventBus deduplicates on identity.  Called from the module
    ``on_startup`` hook so it runs once after the module loader has
    finished mounting routers.
    """
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Finance: subscribed to %d cross-module event(s)",
        len(_SUBSCRIPTIONS),
    )
