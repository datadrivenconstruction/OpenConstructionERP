"""‌⁠‍Finance event subscribers - turn procurement mutation events into
ProjectBudget.committed / actual updates.

Until v2.9.17 ``procurement.po.issued`` and ``procurement.gr.confirmed``
were published into a void: nothing in finance listened, so
``ProjectBudget.committed`` and ``ProjectBudget.actual`` stayed at 0
even when POs totalled millions.  The EVM dashboard's BAC and CPI were
silently divorced from real procurement activity.

The handlers in this module subscribe to those events and adjust the
project's budget rows accordingly:

* ``procurement.po.approved`` → committed += po.amount_total (TOP-30 #10:
  budget is committed when a PO is approved, the moment the spend is
  authorised, since a PO must be approved before it can be issued)
* ``procurement.po.cancelled`` / ``procurement.po.reverted`` →
  committed -= the amount this PO had added (Max-Audit #10: the
  commitment ledger must be reversible so a cancelled or reverted PO
  does not leave a phantom commitment on the budget)
* ``procurement.gr.confirmed`` → committed -= gr.amount, actual += gr.amount

The commitment a PO contributes is idempotent and reversible: each
approved PO stamps a per-PO marker (``committed_from_po:<po_id>``) in the
absorbing ``ProjectBudget.metadata_`` recording the amount it added to
``committed``. A replayed/re-fired ``po.approved`` for the same PO is a
no-op (the marker already exists), and a cancel/revert decrements exactly
the marked amount (and only if it was actually added). This keeps
``committed`` honest under the PO FSM's ``approved -> draft`` /
``approved -> cancelled`` transitions.

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

# ── Published event names (Gap E, Wave 6) ───────────────────────────────────
# Declared here for discoverability; the string is the source of truth at the
# call site in ``service.create_receivable_from_claim``.
#
# Emitted whenever a certified progress claim spawns its receivable invoice.
# Payload: ``project_id``, ``invoice_id``, ``claim_id``, ``amount_total``,
# ``retention_amount``, ``currency_code``. Reporting / BI dashboards subscribe
# to track certified-but-uncollected receivables.
EVENT_RECEIVABLE_FROM_CLAIM = "finance.invoice.created_from_claim"

# Prefix for the per-PO idempotency/reversal marker stored in
# ``ProjectBudget.metadata_``. The full key is ``committed_from_po:<po_id>``
# and the value is the Decimal-string amount this PO added to ``committed``.
# Its presence makes a replayed ``po.approved`` a no-op and lets a
# cancel/revert decrement exactly what was added (Max-Audit #10).
_COMMITTED_FROM_PO_PREFIX = "committed_from_po:"


def _committed_marker_key(po_id_raw: object) -> str | None:
    """Build the ``committed_from_po:<po_id>`` marker key for a PO, or None."""
    po_id = _coerce_uuid(po_id_raw)
    if po_id is None:
        return None
    return f"{_COMMITTED_FROM_PO_PREFIX}{po_id}"


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """‌⁠‍Best-effort string/Decimal coercion - never raises."""
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
    if anything goes wrong - callers must tolerate a None and fall back
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

    Returns None when the project has no budget rows at all - handlers
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


async def _on_po_approved(event: Event) -> None:
    """``procurement.po.approved`` → ProjectBudget.committed += amount_total.

    Approval is the commitment moment (TOP-30 #10): a PO must be approved
    before it can be issued, so committing budget here gives a live committed
    figure the instant the spend is authorised, not when the paperwork is sent.

    Idempotent on the PO id (Max-Audit #10): the absorbing budget records a
    ``committed_from_po:<po_id>`` marker carrying the amount this PO added.
    A replayed or re-fired ``po.approved`` for the same PO (e.g. after an
    ``approved -> draft -> approved`` round-trip) finds the marker and is a
    no-op, so ``committed`` is never inflated twice for one PO.
    """
    data = event.data or {}
    project_id = _coerce_uuid(data.get("project_id"))
    amount = _to_decimal(data.get("amount_total"))
    marker_key = _committed_marker_key(data.get("po_id"))
    if project_id is None or amount == 0:
        return
    try:
        async with async_session_factory() as session:
            wbs_hint = await _resolve_po_wbs(session, data.get("po_id"))
            budget = await _select_budget_row(session, project_id, wbs_hint)
            if budget is None:
                logger.info(
                    "finance: po.approved for project %s - no budget rows, commitment skipped (po_id=%s, amount=%s)",
                    project_id,
                    data.get("po_id"),
                    amount,
                )
                return
            md = dict(getattr(budget, "metadata_", None) or {})
            if marker_key is not None and marker_key in md:
                # This PO already committed against this budget - replayed or
                # re-fired event. Do NOT add a second time.
                logger.info(
                    "finance: po.approved already committed for po=%s on budget %s - skipping (idempotent)",
                    data.get("po_id"),
                    budget.id,
                )
                return
            current = _to_decimal(budget.committed)
            budget.committed = current + amount
            if marker_key is not None:
                md[marker_key] = str(amount)
                budget.metadata_ = md
            await session.commit()
            logger.info(
                "finance: po.approved committed += %s on budget %s (project=%s, po=%s)",
                amount,
                budget.id,
                project_id,
                data.get("po_id"),
            )
    except Exception:
        logger.debug("finance: _on_po_approved failed", exc_info=True)


async def _on_po_decommitted(event: Event) -> None:
    """``procurement.po.cancelled`` / ``procurement.po.reverted`` → committed -= amount.

    Reverses the commitment a PO previously added (Max-Audit #10). When an
    approved PO is cancelled or reverted to draft the authorised spend no
    longer exists, so the budget's ``committed`` slot must shed exactly what
    this PO contributed.

    Decrement strategy: locate the budget that carries this PO's
    ``committed_from_po:<po_id>`` marker, subtract the marked amount, and
    clear the marker so the reversal cannot fire twice and a later
    re-approval can commit cleanly again. If no marker is found (the PO never
    committed, or its commitment was already reversed) this is a safe no-op -
    we never decrement a commitment we did not add.
    """
    data = event.data or {}
    project_id = _coerce_uuid(data.get("project_id"))
    marker_key = _committed_marker_key(data.get("po_id"))
    if project_id is None or marker_key is None:
        return
    try:
        async with async_session_factory() as session:
            # The commitment lives on whichever budget absorbed it; the wbs
            # hint reproduces the same selection used at approval time, but we
            # only act on a budget that actually carries this PO's marker.
            wbs_hint = await _resolve_po_wbs(session, data.get("po_id"))
            budget = await _select_budget_row(session, project_id, wbs_hint)
            if budget is None:
                return
            md = dict(getattr(budget, "metadata_", None) or {})
            if marker_key not in md:
                # No commitment recorded for this PO on this budget - nothing
                # to reverse (never added, or already reversed).
                logger.info(
                    "finance: po decommit for po=%s - no commitment marker on budget %s, skipping",
                    data.get("po_id"),
                    budget.id,
                )
                return
            added = _to_decimal(md.pop(marker_key))
            current = _to_decimal(budget.committed)
            new_committed = current - added
            # Never let committed go negative (defensive against a parallel
            # write having already drained it, e.g. via gr.confirmed).
            if new_committed < 0:
                new_committed = Decimal("0")
            budget.committed = new_committed
            budget.metadata_ = md
            await session.commit()
            logger.info(
                "finance: po %s committed -= %s on budget %s (project=%s, po=%s)",
                event.name,
                added,
                budget.id,
                project_id,
                data.get("po_id"),
            )
    except Exception:
        logger.debug("finance: _on_po_decommitted failed", exc_info=True)


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
                    "finance: gr.confirmed for project %s - no budget rows, actuals skipped (gr_id=%s, amount=%s)",
                    project_id,
                    data.get("gr_id"),
                    amount,
                )
                return
            current_committed = _to_decimal(budget.committed)
            current_actual = _to_decimal(budget.actual)
            new_committed = current_committed - amount
            # Don't let the committed slot go negative - if a GR exceeds the
            # outstanding commitment (because the PO was never issued, or the
            # commitment was already drained by a parallel write), zero it
            # out rather than recording a phantom credit.
            if new_committed < 0:
                new_committed = Decimal("0")
            budget.committed = new_committed
            # Track the goods-receipt-sourced portion of `actual` in metadata.
            # A later invoice payment recomputes `actual` from paid invoices only
            # (see FinanceService.pay_invoice) and would otherwise overwrite this
            # row, silently wiping every procurement actual. Recording the GR
            # portion here lets that recompute add it back instead of losing it.
            # Reassign a fresh dict so SQLAlchemy detects the JSON change.
            md = dict(getattr(budget, "metadata_", None) or {})
            md["actual_from_receipts"] = str(_to_decimal(md.get("actual_from_receipts")) + amount)
            budget.metadata_ = md
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


async def _on_claim_certified(event: Event) -> None:
    """``contracts.claim.certified`` → auto-create a receivable invoice (Gap E).

    A certified progress claim is a collectible amount: the moment it is
    certified an accounts-receivable invoice should exist for it. This handler
    turns the certified claim into a draft receivable invoice (with retainage
    withheld from the gross) via ``FinanceService.create_receivable_from_claim``,
    which is idempotent on the claim id - so an event replay, a double
    certification, or two concurrent calls all converge on a single AR invoice.

    Runs in its own short-lived session (mirrors ``_on_po_approved``) so a write
    failure here never rolls back the upstream contracts transaction. The
    handler swallows the "claim not certified yet" 400 silently because the
    event is the certification itself; any other failure is logged.
    """
    data = event.data or {}
    claim_id = _coerce_uuid(data.get("claim_id"))
    if claim_id is None:
        return
    try:
        from app.modules.finance.service import FinanceService

        async with async_session_factory() as session:
            service = FinanceService(session)
            invoice = await service.create_receivable_from_claim(
                claim_id,
                actor_id=data.get("actor"),
            )
            await session.commit()
            logger.info(
                "finance: claim.certified → receivable invoice %s for claim %s",
                getattr(invoice, "invoice_number", "?"),
                claim_id,
            )
    except Exception:
        logger.exception("finance: _on_claim_certified failed for claim %s", claim_id)


_SUBSCRIPTIONS: list[tuple[str, callable]] = [  # type: ignore[type-arg]
    ("procurement.po.approved", _on_po_approved),
    # Max-Audit #10: a cancelled or reverted PO must shed its commitment so
    # ``committed`` does not carry phantom amounts into the finance dashboard
    # and EVM. Both events route through the same reversal handler.
    ("procurement.po.cancelled", _on_po_decommitted),
    ("procurement.po.reverted", _on_po_decommitted),
    ("procurement.gr.confirmed", _on_gr_confirmed),
    # Gap E (Wave 6): certified progress claim → auto receivable invoice.
    ("contracts.claim.certified", _on_claim_certified),
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
