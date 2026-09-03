# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Bridge: a register item IS a native ERP record.

The workflow spine is this module's contribution; the record itself
belongs to the platform's own registers, so every other module (cost
control, procurement, reporting, the quote gate, the award record) sees
real data rather than a parallel copy that drifts.

    rfq       → oe_rfq_rfq          (drives compare / quote gate / award)
    rfi       → oe_rfi_rfi          (native RFI register)
    variation → oe_variations_request
    order     → oe_procurement_po
    delay     → workflow-only (no native register on this platform)
    toolbox   → workflow-only

Every creation is best-effort in the sense that a MISSING module never
blocks a raise - but a present module that errors is surfaced, because
silently keeping only half the record is how two registers drift apart.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _money(value: Any) -> Decimal:
    """The figure behind a money field.

    Delegates to the shared parser: this used to strip only "," and "$",
    so "50k", "approx 50,000", "50,000 AUD" and "$50,000 + GST" all
    silently became 0 - and 0 is the value the quote gate tiers off.
    `raise_item` refuses an unreadable money field up front, so reaching
    the zero here now means the field was genuinely empty.
    """
    from app.core.money_text import amount_or_zero

    return amount_or_zero(value)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


async def _next_number(session: AsyncSession, model: Any, column: Any, project_id: uuid.UUID, prefix: str) -> str:
    """``PREFIX-004`` from MAX+1 within the project."""
    rows = (await session.execute(select(column).where(model.project_id == project_id))).scalars().all()
    highest = 0
    for value in rows:
        tail = str(value or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}-{highest + 1:03d}"


async def create_native(
    session: AsyncSession,
    *,
    kind: str,
    project_id: uuid.UUID,
    reference: str,
    title: str,
    fields: dict[str, Any],
    recipient_contact_ids: list[str],
    user_id: str | None,
) -> tuple[str, str] | None:
    """Create the native record for ``kind``. Returns (entity_type, id)."""
    builders = {
        "rfq": lambda: _create_rfq(session, project_id, title, fields, recipient_contact_ids, user_id),
        "rfi": lambda: _create_rfi(session, project_id, title, fields, user_id),
        "variation": lambda: _create_variation(session, project_id, title, fields, recipient_contact_ids),
        "order": lambda: _create_order(session, project_id, title, fields, recipient_contact_ids),
    }
    builder = builders.get(kind)
    if builder is None:
        return None
    try:
        # SAVEPOINT. A clash here (typing the same external PO number twice
        # is routine) used to leave the whole session unusable, so the
        # register item itself was lost at commit and the user got an
        # unexplained 500. Now only this insert rolls back.
        async with session.begin_nested():
            return await builder()
    except ImportError:
        logger.info("Native register for %s is not installed - workflow-only item %s", kind, reference)
        return None
    except Exception:
        logger.exception("Native record creation failed for %s %s", kind, reference)
        return None
    return None


async def _create_rfq(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    fields: dict[str, Any],
    recipient_contact_ids: list[str],
    user_id: str | None,
) -> tuple[str, str]:
    from app.modules.rfq_bidding.models import RFQ

    number = await _next_number(session, RFQ, RFQ.rfq_number, project_id, "RFQ")
    rfq = RFQ(
        project_id=project_id,
        rfq_number=number,
        title=title[:500] or number,
        description=str(fields.get("Materials / scope required") or "")[:10_000],
        scope_of_work=str(fields.get("Package") or "")[:50_000],
        submission_deadline=str(fields.get("Quotes due") or "")[:20] or None,
        currency_code="AUD",
        status="published",
        issued_to_contacts=[str(c) for c in recipient_contact_ids],
        created_by=uuid.UUID(user_id) if user_id else None,
        # THE tier input for the quote gate: the buyer's own estimate. The
        # gate reads it straight off here, so the number typed on the raise
        # form is the number that decides how many quotes are required.
        metadata_={
            "estimated_value": str(_money(fields.get("Estimated value $"))),
            "delivery": {
                "to": fields.get("Delivery to"),
                "site_contact": fields.get("Site contact"),
                "window": fields.get("Delivery window / site hours"),
                "notes": fields.get("Delivery notes / access"),
                "required_by": fields.get("Delivery required by"),
            },
        },
        require_full_scope=False,
    )
    session.add(rfq)
    await session.flush()
    return "rfq", str(rfq.id)


async def _create_rfi(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    fields: dict[str, Any],
    user_id: str | None,
) -> tuple[str, str]:
    from app.modules.rfi.models import RFI

    number = await _next_number(session, RFI, RFI.rfi_number, project_id, "RFI")
    rfi = RFI(
        project_id=project_id,
        rfi_number=number,
        subject=title[:500] or number,
        question=str(fields.get("Question") or title or "")[:50_000],
        raised_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
        status="open",
        discipline=str(fields.get("Discipline") or "")[:50] or None,
        date_required=str(fields.get("Response required by") or "")[:20] or None,
        created_by=user_id,
    )
    session.add(rfi)
    await session.flush()
    return "rfi", str(rfi.id)


async def _create_variation(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    fields: dict[str, Any],
    recipient_contact_ids: list[str],
) -> tuple[str, str]:
    from app.modules.variations.models import VariationRequest

    code = await _next_number(session, VariationRequest, VariationRequest.code, project_id, "VO")
    row = VariationRequest(
        project_id=project_id,
        code=code,
        title=title[:500] or code,
        description=str(fields.get("Description of change") or "")[:50_000],
        raised_at=_today(),
        recipient_type="owner",
        recipient_name=(recipient_contact_ids[0] if recipient_contact_ids else "")[:255],
        target_response_date=str(fields.get("Client approval required by") or "")[:40] or None,
        status="issued",
    )
    session.add(row)
    await session.flush()
    return "variation", str(row.id)


async def _create_order(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    fields: dict[str, Any],
    recipient_contact_ids: list[str],
) -> tuple[str, str]:
    from app.modules.procurement.models import PurchaseOrder

    # A PO number typed by the buyer - the one their job-management system
    # issued - wins; ours is the fallback so the record always carries one.
    typed = str(fields.get("Our PO #") or "").strip()
    number = typed or await _next_number(session, PurchaseOrder, PurchaseOrder.po_number, project_id, "PO")
    total = _money(fields.get("Value $"))
    row = PurchaseOrder(
        project_id=project_id,
        po_number=number[:50],
        vendor_contact_id=(recipient_contact_ids[0] if recipient_contact_ids else None),
        po_type="standard",
        issue_date=_today(),
        delivery_date=str(fields.get("ETA") or "")[:40] or None,
        currency_code="AUD",
        amount_subtotal=str(total),
        amount_total=str(total),
    )
    session.add(row)
    await session.flush()
    return "order", str(row.id)


async def delete_native(session: AsyncSession, entity_type: str, entity_id: str) -> bool:
    """Remove the native record a register item created. True if it went.

    Only ever reached from ``service.delete_item``, which has already
    proved the item never left the building - so this row is the RFQ, RFI,
    variation or purchase order that raise published, with nothing hanging
    off it. Leaving it behind was the other half of the "deleted straight
    from the database" problem: the register row disappeared and a junk
    RFQ stayed on the RFQ register for ever.

    A SAVEPOINT and a swallowed failure, deliberately: a sibling module
    that is absent, mid-migration, or protecting its row for a reason we
    cannot see must not take the register deletion down with it.
    """
    models = {
        "rfq": ("app.modules.rfq_bidding.models", "RFQ"),
        "rfi": ("app.modules.rfi.models", "RFI"),
        "variation": ("app.modules.variations.models", "VariationRequest"),
        "order": ("app.modules.procurement.models", "PurchaseOrder"),
    }
    target = models.get(entity_type)
    if target is None:
        return False
    module_path, class_name = target
    try:
        import importlib

        model = getattr(importlib.import_module(module_path), class_name)
        async with session.begin_nested():
            row = await session.get(model, uuid.UUID(str(entity_id)))
            if row is None:
                return False
            await session.delete(row)
            await session.flush()
        return True
    except Exception:  # noqa: BLE001 - the register deletion stands regardless
        logger.warning(
            "Native %s %s could not be removed with its register item",
            entity_type,
            entity_id,
            exc_info=True,
        )
        return False


# ── Reading native state back into the register row ──────────────────────


async def enrich(session: AsyncSession, entity_type: str | None, entity_id: str | None) -> dict[str, Any]:
    """Live native facts for the workspace row: quotes, gate, award, status.

    Read-only and failure-tolerant - the register must render even when a
    sibling module is mid-migration.
    """
    if not entity_type or not entity_id:
        return {}
    try:
        if entity_type == "rfq":
            return await _enrich_rfq(session, entity_id)
        if entity_type == "rfi":
            return await _enrich_rfi(session, entity_id)
        if entity_type == "variation":
            return await _enrich_variation(session, entity_id)
        if entity_type == "order":
            return await _enrich_order(session, entity_id)
    except Exception:  # noqa: BLE001
        logger.debug("Native enrichment failed for %s %s", entity_type, entity_id, exc_info=True)
    return {}


async def _enrich_rfq(session: AsyncSession, entity_id: str) -> dict[str, Any]:
    from app.modules.rfq_bidding.models import RFQ, RFQAward
    from app.modules.rfq_bidding.service import RFQService

    rfq = (await session.execute(select(RFQ).where(RFQ.id == uuid.UUID(entity_id)))).scalar_one_or_none()
    if rfq is None:
        return {}
    service = RFQService(session)
    gate = service.quote_gate_status(rfq)
    award = (await session.execute(select(RFQAward).where(RFQAward.rfq_id == rfq.id))).scalar_one_or_none()
    return {
        "native": "rfq",
        "rfq_number": rfq.rfq_number,
        "rfq_status": rfq.status,
        "currency": rfq.currency_code,
        "quote_gate": gate,
        "bids": [
            {
                "id": str(b.id),
                "bidder_contact_id": b.bidder_contact_id,
                "amount": b.bid_amount,
                "currency": b.currency_code,
                "status": b.status,
                "is_awarded": b.is_awarded,
                "notes": b.notes or "",
                "submitted_at": b.submitted_at,
            }
            for b in rfq.bids
        ],
        "award": (
            {
                "bid_id": str(award.bid_id),
                "reason": award.reason,
                "amount": str(award.awarded_amount),
                "currency": award.awarded_currency,
                "is_override": award.is_override,
                "po_number": (award.basis or {}).get("po_number"),
                "quote_gate": (award.basis or {}).get("quote_gate"),
                "awarded_at": award.awarded_at,
            }
            if award
            else None
        ),
    }


async def _enrich_rfi(session: AsyncSession, entity_id: str) -> dict[str, Any]:
    from app.modules.rfi.models import RFI

    rfi = (await session.execute(select(RFI).where(RFI.id == uuid.UUID(entity_id)))).scalar_one_or_none()
    if rfi is None:
        return {}
    return {
        "native": "rfi",
        "rfi_number": rfi.rfi_number,
        "rfi_status": rfi.status,
        "official_response": rfi.official_response,
        "responded_at": rfi.responded_at,
        "cost_impact": bool(rfi.cost_impact),
        "schedule_impact_days": rfi.schedule_impact_days,
    }


async def _enrich_variation(session: AsyncSession, entity_id: str) -> dict[str, Any]:
    from app.modules.variations.models import VariationRequest

    row = (
        await session.execute(select(VariationRequest).where(VariationRequest.id == uuid.UUID(entity_id)))
    ).scalar_one_or_none()
    if row is None:
        return {}
    return {
        "native": "variation",
        "code": row.code,
        "variation_status": row.status,
        "response_summary": row.response_summary,
        "response_received_at": row.response_received_at,
    }


async def _enrich_order(session: AsyncSession, entity_id: str) -> dict[str, Any]:
    from app.modules.procurement.models import PurchaseOrder

    row = (
        await session.execute(select(PurchaseOrder).where(PurchaseOrder.id == uuid.UUID(entity_id)))
    ).scalar_one_or_none()
    if row is None:
        return {}
    return {
        "native": "order",
        "po_number": row.po_number,
        "po_status": getattr(row, "status", None),
        "amount_total": row.amount_total,
        "currency": row.currency_code,
        "delivery_date": row.delivery_date,
    }


async def record_bid(
    session: AsyncSession,
    *,
    rfq_entity_id: str,
    bidder_contact_id: str,
    amount: str,
    lead_time: str = "",
    quote_number: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Record or update one supplier's price against the native RFQ.

    This is the compare panel's typed-price path: the figure a person
    keys in IS a quote for the gate's purposes, exactly as one parsed out
    of a reply is. Otherwise the gate blocks an award over prices that are
    plainly on the screen.
    """
    from app.modules.rfq_bidding.models import RFQ, RFQBid

    rfq = (await session.execute(select(RFQ).where(RFQ.id == uuid.UUID(rfq_entity_id)))).scalar_one_or_none()
    if rfq is None:
        raise ValueError("RFQ not found")
    existing = next((b for b in rfq.bids if str(b.bidder_contact_id) == str(bidder_contact_id)), None)
    meta = {"lead_time": lead_time, "quote_number": quote_number}
    if existing is not None:
        existing.bid_amount = str(_money(amount))
        existing.notes = notes or existing.notes
        existing.metadata_ = {**(existing.metadata_ or {}), **meta}
        bid = existing
    else:
        bid = RFQBid(
            rfq_id=rfq.id,
            bidder_contact_id=str(bidder_contact_id),
            bid_amount=str(_money(amount)),
            currency_code=rfq.currency_code or "AUD",
            submitted_at=_today(),
            status="received",
            notes=notes,
            metadata_=meta,
        )
        rfq.bids.append(bid)
    await session.flush()
    return {"bid_id": str(bid.id), "amount": bid.bid_amount}
