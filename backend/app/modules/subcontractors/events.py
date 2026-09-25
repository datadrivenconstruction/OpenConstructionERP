# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractors event subscribers - feed cross-module facts into the rating.

When the NCR / HSE / Quality modules publish an event whose payload names a
``subcontractor_id``, this module bumps the corresponding sub's rating
counters for the *current* period and recomputes the weighted overall score.

The subscriber list is intentionally small (NCR, HSE incidents, schedule
slippage). Each handler opens its own short-lived session via
``async_session_factory()`` so a rating-write failure can never roll back the
upstream module's transaction.

Subscribers wired:
    ``ncr.created``                  → ``bump_rating_from_event(kind="ncr")``
    ``safety.incident.created``      → ``bump_rating_from_event(kind="hse")``
    ``schedule.activity.slipped``    → ``bump_rating_from_event(kind="schedule")``
    ``contracts.contract.signed``    → commit a subcontract's value to the budget
    ``contracts.claim.paid``         → pay a subcontractor claim's payable
    ``invoice.paid``                 → draw the subcontract commitment down
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.subcontractors import finance_bridge
from app.modules.subcontractors.models import Subcontractor
from app.modules.subcontractors.service import SubcontractorService

logger = logging.getLogger(__name__)


def _resolve_sub_id(data: dict[str, object]) -> uuid.UUID | None:
    """Pull a subcontractor_id out of an event payload (string or UUID).

    Looks at the top-level ``subcontractor_id`` / ``sub_id`` keys first, then
    falls back to a nested ``metadata`` dict. The previous one-liner had an
    operator-precedence bug - the ``if isinstance(...) else None`` ternary
    bound the *entire* ``or`` chain, so every payload without a dict
    ``metadata`` key resolved to ``None`` and the rating bump was silently
    dropped.
    """
    candidate: object | None = data.get("subcontractor_id") or data.get("sub_id")
    if candidate is None:
        meta = data.get("metadata")
        if isinstance(meta, dict):
            candidate = meta.get("subcontractor_id")
    if candidate is None:
        return None
    if isinstance(candidate, uuid.UUID):
        return candidate
    try:
        return uuid.UUID(str(candidate))
    except (ValueError, TypeError):
        return None


async def _bump(kind: str, event: Event) -> None:
    """Common path: open a session, derive sub_id, bump rating."""
    data = event.data or {}
    sub_id = _resolve_sub_id(data)
    if sub_id is None:
        return
    try:
        async with async_session_factory() as session:
            svc = SubcontractorService(session)
            await svc.bump_rating_from_event(sub_id, kind=kind)
            await session.commit()
    except Exception:
        logger.debug(
            "subcontractors: rating bump for %s/%s failed",
            kind,
            sub_id,
            exc_info=True,
        )


async def _on_ncr_created(event: Event) -> None:
    """``ncr.created`` → +1 NCR for the current month."""
    await _bump("ncr", event)


async def _on_safety_incident_created(event: Event) -> None:
    """``safety.incident.created`` → +1 HSE for the current month."""
    await _bump("hse", event)


async def _on_schedule_slipped(event: Event) -> None:
    """``schedule.activity.slipped`` → +1 schedule-deviation day."""
    await _bump("schedule", event)


async def _on_defect_recorded(event: Event) -> None:
    """``subcontractors.defect.recorded`` → +1 NCR for the current month.

    Forwarded by ``procurement.events._on_supplier_rating_update`` once it has
    resolved the responsible subcontractor from an NCR. Counts as a quality
    (NCR) hit so the next monthly rollup reflects the defect.
    """
    await _bump("ncr", event)


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


# ── Subcontract money ──────────────────────────────────────────────────
#
# A subcontract written in the contracts module (a contract whose counterparty
# is a subcontractor) reaches the budget through these. Unlike the rating bumps
# above, a failure here is money that did not move, so it is left to the bus,
# which logs it at exception level and records it on the publish result.


async def _on_contract_signed(event: Event) -> None:
    """``contracts.contract.signed`` → commit a subcontract's value to the budget."""
    from app.modules.contracts.models import Contract  # noqa: PLC0415

    contract_id = _uuid((event.data or {}).get("contract_id"))
    if contract_id is None:
        return
    async with async_session_factory() as session:
        contract = await session.get(Contract, contract_id)
        if contract is None or contract.counterparty_type != "subcontractor":
            return
        await finance_bridge.commit_subcontract(
            session,
            project_id=contract.project_id,
            source=finance_bridge.contract_source(contract.id),
            amount=contract.total_value,
        )
        await session.commit()


async def _on_claim_paid(event: Event) -> None:
    """``contracts.claim.paid`` → pay a subcontractor claim's payable through finance.

    Marking a subcontractor's claim paid used to stop at the claim: its invoice
    stayed a draft, so the money never reached actual and never came off the
    commitment. A client claim is not touched; what the client paid us is
    booked on the receivable by whoever records the receipt.
    """
    from app.modules.contracts.models import Contract, ProgressClaim  # noqa: PLC0415
    from app.modules.finance.service import FinanceService  # noqa: PLC0415

    data = event.data or {}
    claim_id = _uuid(data.get("claim_id"))
    if claim_id is None:
        return
    async with async_session_factory() as session:
        claim = await session.get(ProgressClaim, claim_id)
        if claim is None:
            return
        contract = await session.get(Contract, claim.contract_id)
        if contract is None or contract.counterparty_type != "subcontractor":
            return
        actor = data.get("actor") or None
        invoice = await FinanceService(session).create_receivable_from_claim(claim_id, actor_id=actor)
        await finance_bridge.settle_payable(session, invoice.id, actor_id=actor)
        await session.commit()


async def _on_invoice_paid(event: Event) -> None:
    """``invoice.paid`` → draw a subcontract's commitment down by the paid gross.

    Covers a subcontractor's payable paid from the finance screens. A payment
    made through this module or a paid claim has drawn it down already, and the
    per-invoice marker makes this a no-op then.
    """
    from app.modules.finance.models import Invoice  # noqa: PLC0415

    invoice_id = _uuid((event.data or {}).get("invoice_id"))
    if invoice_id is None:
        return
    async with async_session_factory() as session:
        invoice = await session.get(Invoice, invoice_id)
        if invoice is None:
            return
        await finance_bridge.draw_down_for_invoice(session, invoice)
        await session.commit()


_SUBSCRIPTIONS: list[tuple[str, object]] = [
    ("ncr.created", _on_ncr_created),
    ("safety.incident.created", _on_safety_incident_created),
    ("schedule.activity.slipped", _on_schedule_slipped),
    ("subcontractors.defect.recorded", _on_defect_recorded),
    ("contracts.contract.signed", _on_contract_signed),
    ("contracts.claim.paid", _on_claim_paid),
    ("invoice.paid", _on_invoice_paid),
]


async def compute_all_monthly_ratings(period: str | None = None) -> int:
    """Recompute the monthly rating rollup for every active subcontractor.

    Designed to be driven by a monthly cron / scheduler entry (the same way
    the audit-prune sweep is). ``period`` defaults to the current ``YYYY-MM``.
    Opens one short-lived session, iterates the active subcontractors, and
    calls :meth:`SubcontractorService.compute_monthly_rating` for each so the
    period's authoritative figures (and the ``subcontractors.rating.updated``
    event) land even if no live event fired that month.

    Returns the number of subcontractors processed. Per-sub failures are
    swallowed (logged) so one bad row cannot abort the whole sweep.
    """
    period_str = period or datetime.now(UTC).strftime("%Y-%m")
    processed = 0
    async with async_session_factory() as session:
        rows = (
            (await session.execute(select(Subcontractor.id).where(Subcontractor.is_active.is_(True)))).scalars().all()
        )
        svc = SubcontractorService(session)
        for sub_id in rows:
            try:
                await svc.compute_monthly_rating(sub_id, period_str)
                await session.commit()
                processed += 1
            except Exception:
                await session.rollback()
                logger.debug(
                    "subcontractors: monthly rating compute failed for %s",
                    sub_id,
                    exc_info=True,
                )
    logger.info(
        "Subcontractors: computed monthly ratings for %d subcontractor(s) (%s)",
        processed,
        period_str,
    )
    return processed


def register_subcontractor_rating_subscribers() -> None:
    """Wire NCR/HSE/Schedule events into the rating engine.

    Idempotent - re-registering does not stack duplicate handlers. Plain
    ``subscribe`` appends blindly, so a second call (module reload, or the eager
    import below combined with a loader-driven call) would double-bind every
    handler and make each event fire the rating bump twice.
    """
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)  # type: ignore[arg-type]
    logger.info(
        "Subcontractors: subscribed to %d rating-driving event(s)",
        len(_SUBSCRIPTIONS),
    )


# Eagerly register on import - module_loader picks this up when the
# subcontractors module is loaded (same pattern as procurement.events).
register_subcontractor_rating_subscribers()
