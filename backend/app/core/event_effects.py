# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run-once ledger for event side effects (``oe_event_effect``).

A subscriber that writes a business record from an event (a purchase order or
a contract from an award) checks for an earlier record and then inserts. Two
deliveries of one event in flight at the same time both pass the check and
both insert. :func:`claim_effect` closes that window: it inserts
``(event_key, effect)`` under a unique constraint in the subscriber's own
transaction, so exactly one delivery wins, and a delivery whose transaction
rolls back releases its claim and leaves the retry free to run.

The key names the business fact, not the bus message (``bid_award:<award id>``),
so an alias event carrying the same key cannot fire the effect a second time,
and a re-award (a new award row) gets a new key.
"""

from __future__ import annotations

import logging

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

logger = logging.getLogger(__name__)

EFFECT_PURCHASE_ORDER = "procurement.purchase_order"
EFFECT_CONTRACT = "contracts.contract"


class EventEffect(Base):
    """One side effect that has run for one business event."""

    __tablename__ = "oe_event_effect"
    __table_args__ = (UniqueConstraint("event_key", "effect", name="uq_oe_event_effect_key_effect"),)

    event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    effect: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    event_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


def bid_award_key(award_id: object) -> str:
    """Key of a bid_management award (one per ``BidAward`` row)."""
    return f"bid_award:{award_id}"


def tender_award_key(package_id: object, bid_id: object) -> str:
    """Key of a tendering award; a tender package is awarded once."""
    return f"tender_award:{package_id}:{bid_id}"


def rfq_award_key(award_id: object) -> str:
    """Key of an RFQ award (one per ``RFQAward`` row)."""
    return f"rfq_award:{award_id}"


async def claim_effect(
    session: AsyncSession,
    event_key: str,
    effect: str = "",
    *,
    event_name: str | None = None,
) -> EventEffect | None:
    """Claim ``(event_key, effect)`` in the caller's transaction.

    Returns the claim row, or ``None`` when another delivery already holds it.
    The caller commits the claim together with the record it writes; set
    ``record_id`` on the returned row to link the two.
    """
    existing = (
        await session.execute(
            select(EventEffect.id).where(EventEffect.event_key == event_key, EventEffect.effect == effect)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = EventEffect(event_key=event_key[:200], effect=effect, event_name=event_name)
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        logger.info("event effect %s already ran for %s (concurrent delivery)", effect, event_key)
        return None
    return row


#: Metadata keys that name the award an auto-drafted record came from.
_PO_AWARD_KEYS = ("rfq_award_id", "bid_package_id", "tender_package_id")
_CONTRACT_AWARD_KEYS = ("bid_package_id", "tender_package_id")


def group_award_duplicates(
    rows: list[tuple[str, str, str | None, dict | None]], keys: tuple[str, ...]
) -> list[dict[str, object]]:
    """Group ``(id, project_id, status, metadata)`` rows by award key; keep keys held by 2+ standing rows."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    for record_id, project_id, status, metadata in rows:
        if status in ("cancelled", "terminated"):
            continue
        md = metadata if isinstance(metadata, dict) else {}
        for key in keys:
            value = md.get(key)
            if value:
                groups.setdefault((str(project_id), key, str(value)), []).append(str(record_id))
                break
    return [
        {"project_id": p, "award_key": k, "award_value": v, "record_ids": sorted(ids)}
        for (p, k, v), ids in sorted(groups.items())
        if len(ids) > 1
    ]


async def find_award_duplicates(session: AsyncSession) -> dict[str, list[dict[str, object]]]:
    """Read-only: purchase orders and contracts that more than one delivery drafted for one award."""
    from app.modules.contracts.models import Contract  # noqa: PLC0415
    from app.modules.procurement.models import PurchaseOrder  # noqa: PLC0415

    pos = (
        await session.execute(
            select(PurchaseOrder.id, PurchaseOrder.project_id, PurchaseOrder.status, PurchaseOrder.metadata_)
        )
    ).all()
    contracts = (
        await session.execute(select(Contract.id, Contract.project_id, Contract.status, Contract.metadata_))
    ).all()
    return {
        "purchase_orders": group_award_duplicates([tuple(r) for r in pos], _PO_AWARD_KEYS),
        "contracts": group_award_duplicates([tuple(r) for r in contracts], _CONTRACT_AWARD_KEYS),
    }
