# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approved change orders and variations on the schedule of values.

An approved change order, or a completed variation order, moves
``Contract.total_value`` (G702 line 3) through the wave-5 subscribers. It used
to move nothing else, so the schedule of values the claims are billed against
drifted away from the contract sum with every approval, and the change was
work nobody could bill.

:func:`post_source_to_sov` is called by those subscribers on the path that
moves the money, in the same transaction: it adds one pooled SoV line for the
change and one :class:`~app.modules.contracts.models.SovAdjustment` recording
it. The adjustment carries the same idempotency key the contract's posted
sources use (``change_order:<id>``, or ``variation_order:<id>`` for a
variation and the change order that mirrors it), so a replayed event or the
second half of a mirrored pair posts nothing.

Changes approved before the poster existed moved the contract sum and no line.
They are not repaired at boot: rows injected into billable lines need a person
to agree. :func:`plan_reconcile` lists them with the amounts it would post,
and :func:`apply_reconcile` posts exactly the list a person confirmed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import Contract, ContractLine, SovAdjustment

logger = logging.getLogger(__name__)

#: Only a live contract takes new lines from a change. A draft's lines are
#: frozen as the original schedule when it is signed, and a closed one takes no
#: change at all; the reconcile picks a draft's changes up once it is active.
POSTABLE_CONTRACT_STATUSES: frozenset[str] = frozenset({"active"})

SOURCE_CHANGE_ORDER = "change_order"
SOURCE_VARIATION_ORDER = "variation_order"


def source_key(kind: str, source_id: object) -> str:
    """The posting identity, in the shape the contract's posted sources use."""
    return f"{kind}:{source_id}"


async def posted_source_keys(session: AsyncSession, contract_id: uuid.UUID) -> set[str]:
    """Every source key that already has an adjustment on this contract."""
    rows = await session.execute(select(SovAdjustment.source_key).where(SovAdjustment.contract_id == contract_id))
    return {str(key) for key in rows.scalars().all()}


async def post_source_to_sov(
    session: AsyncSession,
    contract: Contract,
    *,
    key: str,
    kind: str,
    source_id: uuid.UUID | None,
    code: str,
    title: str,
    amount: Decimal,
    currency: str,
    approved_on: date | None,
) -> SovAdjustment | None:
    """Add the pooled SoV line and adjustment for one approved change.

    ``kind`` names the record that carried the money, which is what the line's
    origin says; ``key`` may name the variation a change order mirrors. Does
    nothing, and returns ``None``, for a contract that is not active, for a
    zero amount, and for a key already posted on this contract. Flushes and
    leaves the commit to the caller, so the line moves with the contract sum.
    """
    if contract.status not in POSTABLE_CONTRACT_STATUSES or amount == 0:
        return None
    if key in await posted_source_keys(session, contract.id):
        return None
    last = await session.execute(
        select(func.max(ContractLine.order_index)).where(ContractLine.contract_id == contract.id)
    )
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code=(code or "")[:80],
        description=title or code or "",
        quantity=Decimal("1"),
        unit_rate=amount,
        total_value=amount,
        order_index=int(last.scalar() or 0) + 1,
        origin="variation" if kind == SOURCE_VARIATION_ORDER else "change_order",
        source_key=key,
        # Added after signing from nothing, which is what zero says here.
        original_value=Decimal("0"),
        metadata_={},
    )
    session.add(line)
    await session.flush()
    adjustment = SovAdjustment(
        id=uuid.uuid4(),
        contract_id=contract.id,
        contract_line_id=line.id,
        source_key=key,
        source_kind=kind,
        source_id=source_id,
        source_code=(code or "")[:80],
        delta_value=amount,
        delta_quantity=Decimal("0"),
        created_line=True,
        approved_on=approved_on,
        currency=(currency or contract.currency or "")[:3],
        metadata_={},
    )
    session.add(adjustment)
    await session.flush()
    return adjustment


# ── Reconcile: changes approved before the poster existed ───────────────


@dataclass(frozen=True, slots=True)
class ReconcileItem:
    """One change the contract sum carries and the schedule of values does not."""

    key: str
    kind: str
    source_id: uuid.UUID
    code: str
    title: str
    amount: Decimal
    currency: str
    approved_on: date | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.key,
            "source_kind": self.kind,
            "source_id": str(self.source_id),
            "source_code": self.code,
            "title": self.title,
            "amount": str(self.amount),
            "currency": self.currency,
            "approved_on": self.approved_on.isoformat() if self.approved_on else None,
        }


def _day(value: object) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _unpaid_ids(md: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Change order and variation ids the currency guard stopped: no money moved."""
    changes: set[str] = set()
    variations: set[str] = set()
    for entry in md.get("skipped_currency_mismatch") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("change_order_id"):
            changes.add(str(entry["change_order_id"]))
        if entry.get("variation_id"):
            variations.add(str(entry["variation_id"]))
    return changes, variations


async def plan_reconcile(session: AsyncSession, contract: Contract) -> list[ReconcileItem]:
    """The changes that moved this contract's sum and have no SoV line yet.

    Read from the ids the subscribers recorded as applied, less those the
    currency guard stopped, and less every key that already has an adjustment.
    A change order that mirrors a variation is keyed on the variation, as it
    was when it posted. Amounts are the change's own recorded figure, the
    same one the subscriber added to the contract sum.
    """
    from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415
    from app.modules.variations.models import VariationOrder  # noqa: PLC0415

    md = dict(contract.metadata_ or {})
    unpaid_changes, unpaid_variations = _unpaid_ids(md)
    change_ids = [
        cid for raw in md.get("change_order_ids") or [] if str(raw) not in unpaid_changes and (cid := _uuid(raw))
    ]
    variation_ids = [
        vid for raw in md.get("variation_ids") or [] if str(raw) not in unpaid_variations and (vid := _uuid(raw))
    ]
    posted = await posted_source_keys(session, contract.id)
    items: dict[str, ReconcileItem] = {}

    if change_ids:
        rows = await session.execute(select(ChangeOrder).where(ChangeOrder.id.in_(change_ids)))
        for order in rows.scalars().all():
            mirrored = (order.metadata_ or {}).get("variation_order_id")
            key = (
                source_key(SOURCE_VARIATION_ORDER, mirrored) if mirrored else source_key(SOURCE_CHANGE_ORDER, order.id)
            )
            items[key] = ReconcileItem(
                key=key,
                kind=SOURCE_CHANGE_ORDER,
                source_id=order.id,
                code=order.code or "",
                title=order.title or "",
                amount=_money(order.cost_impact),
                currency=order.currency or contract.currency or "",
                approved_on=_day(order.approved_at),
            )
    if variation_ids:
        rows = await session.execute(select(VariationOrder).where(VariationOrder.id.in_(variation_ids)))
        for variation in rows.scalars().all():
            key = source_key(SOURCE_VARIATION_ORDER, variation.id)
            items.setdefault(
                key,
                ReconcileItem(
                    key=key,
                    kind=SOURCE_VARIATION_ORDER,
                    source_id=variation.id,
                    code=variation.code or "",
                    title=variation.title or "",
                    amount=_money(variation.final_cost_impact),
                    currency=variation.currency or contract.currency or "",
                    approved_on=_day(variation.implementation_completed_at),
                ),
            )
    return [item for key, item in sorted(items.items()) if key not in posted and item.amount != 0]


async def scheduled_total(session: AsyncSession, contract_id: uuid.UUID) -> Decimal:
    """The schedule of values on a contract, roll-up rows left out (G703 column C)."""
    rows = (await session.execute(select(ContractLine).where(ContractLine.contract_id == contract_id))).scalars().all()
    parents = {ln.parent_line_id for ln in rows if ln.parent_line_id is not None}
    return sum((_money(ln.total_value) for ln in rows if ln.id not in parents), Decimal("0"))


async def reconcile_preview(session: AsyncSession, contract: Contract) -> dict[str, Any]:
    """What the reconcile would post, and where it leaves the schedule."""
    items = await plan_reconcile(session, contract)
    scheduled = await scheduled_total(session, contract.id)
    adding = sum((item.amount for item in items), Decimal("0"))
    return {
        "contract_id": str(contract.id),
        "contract_status": contract.status,
        "can_apply": contract.status in POSTABLE_CONTRACT_STATUSES and bool(items),
        "currency": contract.currency or "",
        "contract_sum": str(_money(contract.total_value)),
        "scheduled_total": str(scheduled),
        "scheduled_total_after": str(scheduled + adding),
        "items": [item.as_dict() for item in items],
    }


class ReconcileMismatchError(Exception):
    """The confirmed list is not what the reconcile would post now."""


async def apply_reconcile(session: AsyncSession, contract: Contract, confirmed_keys: list[str]) -> list[SovAdjustment]:
    """Post exactly the changes a person confirmed from the preview.

    The confirmed keys must equal the preview as it stands now. Anything else
    means the preview the person read is out of date (another approval, or a
    reconcile by someone else), and nothing is posted.

    Raises:
        ReconcileMismatchError: the confirmed list differs from the plan.
    """
    items = await plan_reconcile(session, contract)
    if sorted(set(confirmed_keys)) != sorted(item.key for item in items):
        raise ReconcileMismatchError
    posted: list[SovAdjustment] = []
    for item in items:
        adjustment = await post_source_to_sov(
            session,
            contract,
            key=item.key,
            kind=item.kind,
            source_id=item.source_id,
            code=item.code,
            title=item.title,
            amount=item.amount,
            currency=item.currency,
            approved_on=item.approved_on,
        )
        if adjustment is not None:
            adjustment.metadata_ = {"reconciled_at": datetime.now(UTC).isoformat()}
            posted.append(adjustment)
    await session.flush()
    return posted
