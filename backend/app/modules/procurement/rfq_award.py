# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An awarded RFQ becomes a draft purchase order.

``rfq_bidding.service.award_bid`` publishes ``rfq.awarded`` once the award has
committed, and until now nothing listened: the buyer awarded a quote and then
typed the same supplier, lines and amount into a purchase order by hand. This
subscriber drafts that order. It is a draft and nothing more. Approving it is
what commits budget, issuing it is what reaches the supplier, and both stay with
a person, who also sees the vendor gate on issue.

What the draft carries
----------------------
* **Supplier.** The directory contact the quote was entered against, and only
  when that contact resolves and is one the awarding user (or the project
  owner) can see. A bidder id that does not resolve, or a contact from another
  tenant, leaves the vendor empty for the reviewer to pick, and the draft says
  so in its notes. The raw bidder id is never copied into ``vendor_contact_id``.
* **Money.** The awarded quote's own headline in the quote's own currency,
  which is what the supplier will invoice. The award record's figure is the
  same quote restated on the RFQ basis, with any missing items added back for
  the comparison; that number ranked the quotes, it is not what the supplier
  charges, so it is kept in metadata for the audit trail and not ordered.
* **Lines.** The priced scope lines of the awarded quote, in scope order, with
  the supplier's quantity, unit and rate. When those lines fall short of the
  headline the gap is ordered as one balancing line so the order still adds up
  to what was quoted; when they exceed it (an overall discount) or there are
  none, the order is one lump-sum line at the headline. Either way the item
  amounts sum to the order total exactly.
* **Adjustments.** Charges the supplier stated outside the headline (freight,
  installation and the like) are listed in the notes, not ordered: whether the
  supplier invoices them or the buyer sources them elsewhere is the reviewer's
  call.

Idempotency and the award standing
----------------------------------
``metadata.rfq_award_id`` is the key. A second delivery of the same event finds
the draft and stops. The award row is locked while the check and the write run,
so two deliveries racing each other serialise on it.

The draft is written only while the award still stands: the award row exists,
names the RFQ and the quote the event names, the quote is still marked awarded
and the RFQ is in an awarded status. A delivery that arrives after the award
was taken back writes nothing. A re-award (a new award id for the same RFQ)
retires a still-draft order left by the earlier award, and refuses to draft a
second order while the earlier one is past draft, because two live orders for
one RFQ is a double commitment.

The project is always the RFQ's own, read from the database, never the event
payload's.

Failure mode: everything is logged and swallowed. The award is already
committed and must never be affected; the buyer can raise the order by hand.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import Event, _log_failures
from app.database import async_session_factory
from app.modules.procurement.cost_spine import resolve_cost_line_ids
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.repository import PurchaseOrderRepository

logger = logging.getLogger(__name__)

#: ``metadata.origin`` of an order drafted here.
ORIGIN = "rfq_award"

#: RFQ statuses in which an award stands. ``po_issued`` and ``completed`` come
#: after the award in the RFQ lifecycle and keep it.
_AWARD_STANDING_STATUSES = frozenset({"awarded", "po_issued", "completed"})

#: ``oe_procurement_po_item.description`` is String(500).
_DESCRIPTION_MAX = 500
#: ``oe_procurement_po_item.unit`` is String(20).
_UNIT_MAX = 20

_ZERO = Decimal("0")


def _uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _dec(value: object) -> Decimal | None:
    """A Decimal, or ``None`` for a value that is not a finite number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _money(value: Decimal) -> str:
    """A money amount as a plain decimal string, never an exponent."""
    return format(value.quantize(Decimal("0.01")), "f")


def _plain(value: Decimal) -> str:
    """A quantity or rate as a plain decimal string, trailing zeros dropped."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class _Item:
    description: str
    quantity: Decimal
    unit: str | None
    unit_rate: Decimal
    amount: Decimal
    cost_line_id: uuid.UUID | None = None


@dataclass(frozen=True)
class _Vendor:
    """Who the draft is addressed to, and how that was decided."""

    contact_id: uuid.UUID | None
    name: str | None
    #: ``linked``, ``not_in_directory`` or ``not_accessible``.
    link: str


# ── Subscriber ──────────────────────────────────────────────────────────────


async def on_rfq_awarded(event: Event) -> None:
    """Schedule the draft as a detached task.

    The publisher defers ``rfq.awarded`` until its transaction has committed
    (``publish_after_commit``), so the award is visible to the session the
    draft opens. Detaching keeps the draft off the publish path, and
    ``_log_failures`` reports a crash at WARNING instead of losing it.
    """
    _log_failures(draft_po_from_rfq_award(event), name="procurement.draft_po_from_rfq_award")


async def draft_po_from_rfq_award(event: Event) -> uuid.UUID | None:
    """Draft the purchase order for an RFQ award, in a session of its own.

    Returns:
        The id of the draft for this award (new or already there), or ``None``
        when none was written. The subscriber ignores it; tests read it.
    """
    data = event.data or {}
    award_id = _uuid(data.get("award_id"))
    rfq_id = _uuid(data.get("rfq_id"))
    bid_id = _uuid(data.get("bid_id"))
    if award_id is None or rfq_id is None or bid_id is None:
        logger.warning(
            "rfq.awarded without usable award/rfq/bid ids: %r",
            {k: data.get(k) for k in ("award_id", "rfq_id", "bid_id")},
        )
        return None
    actor_id = _uuid(data.get("actor_id"))
    try:
        async with async_session_factory() as session:
            return await _draft(session, award_id=award_id, rfq_id=rfq_id, bid_id=bid_id, actor_id=actor_id)
    except Exception:
        logger.exception(
            "Draft purchase order for RFQ award %s (rfq=%s) failed; the award itself is unaffected",
            award_id,
            rfq_id,
        )
        return None


async def _draft(
    session: AsyncSession,
    *,
    award_id: uuid.UUID,
    rfq_id: uuid.UUID,
    bid_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> uuid.UUID | None:
    from app.modules.rfq_bidding.models import RFQ, RFQAward, RFQBid  # noqa: PLC0415

    # Lock the award first: a redelivery racing this one waits here and then
    # finds the draft this one wrote.
    award = (
        await session.execute(select(RFQAward).where(RFQAward.id == award_id).with_for_update())
    ).scalar_one_or_none()
    if award is None:
        logger.info("rfq.awarded: award %s no longer exists; no purchase order drafted", award_id)
        return None
    if award.rfq_id != rfq_id or award.bid_id != bid_id:
        logger.warning(
            "rfq.awarded: award %s is for rfq=%s bid=%s, the event names rfq=%s bid=%s; nothing drafted",
            award_id,
            award.rfq_id,
            award.bid_id,
            rfq_id,
            bid_id,
        )
        return None

    # Read the RFQ with its scope and every quote's lines and adjustments in
    # this statement, and over whatever the session already holds: everything
    # below reads these collections, and a lazy load from here would fail.
    rfq = (
        await session.execute(
            select(RFQ)
            .where(RFQ.id == rfq_id)
            .options(
                selectinload(RFQ.lines),
                selectinload(RFQ.bids).selectinload(RFQBid.lines),
                selectinload(RFQ.bids).selectinload(RFQBid.adjustments),
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if rfq is None or rfq.status not in _AWARD_STANDING_STATUSES:
        logger.info(
            "rfq.awarded: RFQ %s is %s, the award no longer stands; nothing drafted",
            rfq_id,
            None if rfq is None else rfq.status,
        )
        return None
    bid = next((b for b in rfq.bids if b.id == bid_id), None)
    if bid is None or not bid.is_awarded:
        logger.info("rfq.awarded: quote %s is no longer the awarded one on RFQ %s; nothing drafted", bid_id, rfq_id)
        return None

    project_id = rfq.project_id
    rfq_key = str(rfq_id)
    award_key = str(award_id)

    orders = (
        (await session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id))).scalars().all()
    )
    earlier: list[PurchaseOrder] = []
    for po in orders:
        if po.status == "cancelled":
            continue
        md = po.metadata_ if isinstance(po.metadata_, dict) else {}
        if md.get("rfq_award_id") == award_key:
            logger.info("rfq.awarded: PO %s already drafted for award %s (idempotent skip)", po.po_number, award_id)
            return po.id
        if md.get("origin") == ORIGIN and md.get("rfq_id") == rfq_key:
            earlier.append(po)

    for po in earlier:
        if po.status != "draft":
            logger.warning(
                "rfq.awarded: RFQ %s was re-awarded but order %s from the earlier award is %s; "
                "cancel it before a new order is drafted",
                rfq_id,
                po.po_number,
                po.status,
            )
            return None
    for po in earlier:
        if not await _retire_superseded_draft(session, po, rfq_number=rfq.rfq_number):
            return None

    headline = _dec(bid.bid_amount)
    if headline is not None and headline <= _ZERO:
        headline = None
    currency = (bid.currency_code or rfq.currency_code or "").strip()
    items, pricing = _order_lines(rfq, bid, headline)
    if not items:
        logger.warning("rfq.awarded: quote %s on RFQ %s has no readable amount; nothing drafted", bid_id, rfq_id)
        return None
    await _link_cost_lines(session, project_id, items)
    subtotal = sum((item.amount for item in items), _ZERO)

    vendor = await _resolve_vendor(session, bid.bidder_contact_id, actor_id=actor_id, project_id=project_id)
    notes = _notes(rfq, bid, pricing=pricing, vendor=vendor, headline=headline, subtotal=subtotal, currency=currency)

    po_number = await PurchaseOrderRepository(session).next_po_number(project_id)
    po = PurchaseOrder(
        project_id=project_id,
        vendor_contact_id=str(vendor.contact_id) if vendor.contact_id else None,
        po_number=po_number,
        po_type="standard",
        issue_date=None,
        delivery_date=None,
        currency_code=currency,
        amount_subtotal=_money(subtotal),
        tax_amount="0",
        amount_total=_money(subtotal),
        status="draft",
        payment_terms=None,
        notes=notes[:5000],
        created_by=None,
        metadata_={
            "origin": ORIGIN,
            "rfq_id": rfq_key,
            "rfq_number": rfq.rfq_number,
            "rfq_title": rfq.title,
            "rfq_award_id": award_key,
            "rfq_bid_id": str(bid_id),
            "supplier_name": vendor.name,
            "vendor_link": vendor.link,
            "pricing": pricing,
            "quoted_amount": _money(headline) if headline is not None else None,
            "quoted_currency": currency,
            # The figure the ranking used, on the RFQ basis. Audit only.
            "award_basis_amount": _money(basis) if (basis := _dec(award.awarded_amount)) is not None else None,
            "award_basis_currency": award.awarded_currency,
            "award_is_override": bool(award.is_override),
            "awarded_by": str(award.awarded_by) if award.awarded_by else None,
        },
    )
    session.add(po)
    await session.flush()
    for idx, item in enumerate(items):
        session.add(
            PurchaseOrderItem(
                po_id=po.id,
                description=item.description[:_DESCRIPTION_MAX],
                quantity=_plain(item.quantity),
                unit=(item.unit or "")[:_UNIT_MAX] or None,
                unit_rate=_plain(item.unit_rate),
                amount=_money(item.amount),
                cost_line_id=item.cost_line_id,
                sort_order=idx,
            )
        )
    await session.commit()
    logger.info(
        "Draft PO %s from RFQ %s award %s: %d line(s), %s %s, vendor=%s",
        po_number,
        rfq.rfq_number,
        award_id,
        len(items),
        _money(subtotal),
        currency,
        vendor.link,
    )
    return po.id


async def _retire_superseded_draft(session: AsyncSession, po: PurchaseOrder, *, rfq_number: str) -> bool:
    """Cancel a draft left by an earlier award of the same RFQ.

    Goes through the service so the cancellation is recorded and audited like
    any other. Returns ``False`` when the service refuses (another record holds
    the order), in which case nothing new is drafted either.
    """
    from app.modules.procurement.service import ProcurementService  # noqa: PLC0415

    try:
        await ProcurementService(session).cancel_po(
            po.id,
            reason=f"Superseded: {rfq_number} was re-awarded",
        )
    except HTTPException as exc:
        logger.warning(
            "rfq.awarded: could not retire draft %s left by an earlier award (%s); nothing new drafted",
            po.po_number,
            exc.detail,
        )
        return False
    return True


# ── Lines ───────────────────────────────────────────────────────────────────


def _scope_label(code: str | None, description: str) -> str:
    code = (code or "").strip()
    description = (description or "").strip()
    return f"{code} {description}".strip() if code else description


def _item_from_bid_line(bid_line: Any, scope_line: Any | None) -> _Item | None:
    """One order line from one priced line of the awarded quote."""
    amount = _dec(bid_line.amount) or _ZERO
    quantity = _dec(bid_line.quantity) or _ZERO
    rate = _dec(bid_line.unit_rate) or _ZERO
    if amount <= _ZERO and quantity > _ZERO and rate > _ZERO:
        amount = quantity * rate
    if amount <= _ZERO:
        return None
    if quantity <= _ZERO:
        scope_qty = _dec(scope_line.quantity) if scope_line is not None else None
        quantity = scope_qty if scope_qty is not None and scope_qty > _ZERO else Decimal("1")
    if rate <= _ZERO:
        rate = amount / quantity
    unit = (bid_line.unit or "").strip() or (scope_line.unit if scope_line is not None else None)
    if scope_line is not None:
        description = _scope_label(scope_line.code, scope_line.description)
    else:
        description = (bid_line.description or "").strip() or "Additional item priced by the supplier"
    return _Item(
        description=description,
        quantity=quantity,
        unit=unit,
        unit_rate=rate,
        amount=amount.quantize(Decimal("0.01")),
        cost_line_id=scope_line.cost_line_id if scope_line is not None else None,
    )


def _order_lines(rfq: Any, bid: Any, headline: Decimal | None) -> tuple[list[_Item], str]:
    """The order lines for the awarded quote, and how they were arrived at.

    Returns ``(items, pricing)`` where ``pricing`` is ``itemised``,
    ``itemised_with_balance`` or ``lump_sum``. The item amounts always sum to
    the quoted headline when there is one.
    """
    scope = sorted(rfq.lines, key=lambda line: line.line_no)
    scope_by_id = {line.id: line for line in scope}
    priced = [bl for bl in bid.lines if not bl.is_excluded]

    items: list[_Item] = []
    for line in scope:
        for bid_line in priced:
            if bid_line.rfq_line_id == line.id:
                item = _item_from_bid_line(bid_line, line)
                if item is not None:
                    items.append(item)
    for bid_line in priced:
        if bid_line.rfq_line_id is None or bid_line.rfq_line_id not in scope_by_id:
            item = _item_from_bid_line(bid_line, None)
            if item is not None:
                items.append(item)

    lines_total = sum((item.amount for item in items), _ZERO)
    if headline is None:
        return items, "itemised"
    headline = headline.quantize(Decimal("0.01"))
    if items and lines_total == headline:
        return items, "itemised"
    if items and lines_total < headline:
        gap = headline - lines_total
        items.append(
            _Item(
                description="Quoted total not itemised against the priced lines",
                quantity=Decimal("1"),
                unit=None,
                unit_rate=gap,
                amount=gap,
            )
        )
        return items, "itemised_with_balance"
    label = _scope_label(rfq.rfq_number, rfq.title or "")
    return [
        _Item(
            description=f"{label}: awarded quote, lump sum",
            quantity=Decimal("1"),
            unit=None,
            unit_rate=headline,
            amount=headline,
        )
    ], "lump_sum"


async def _link_cost_lines(session: AsyncSession, project_id: uuid.UUID, items: list[_Item]) -> None:
    """Keep each scope line's cost-line link when it belongs to this project.

    One bad link must not lose the order, nor the links of the other lines,
    so a refusal of the batch is retried line by line.
    """
    if not any(item.cost_line_id for item in items):
        return

    def _ref(item: _Item) -> tuple[str | None, None]:
        return (str(item.cost_line_id) if item.cost_line_id else None, None)

    try:
        resolved = await resolve_cost_line_ids(session, project_id, [_ref(item) for item in items])
    except HTTPException:
        resolved = []
        for item in items:
            try:
                [one] = await resolve_cost_line_ids(session, project_id, [_ref(item)])
            except HTTPException:
                one = None
            resolved.append(one)
    for idx, cost_line_id in enumerate(resolved):
        if items[idx].cost_line_id != cost_line_id:
            items[idx] = _Item(
                description=items[idx].description,
                quantity=items[idx].quantity,
                unit=items[idx].unit,
                unit_rate=items[idx].unit_rate,
                amount=items[idx].amount,
                cost_line_id=cost_line_id,
            )


# ── Supplier ────────────────────────────────────────────────────────────────


async def _resolve_vendor(
    session: AsyncSession,
    bidder_contact_id: str | None,
    *,
    actor_id: uuid.UUID | None,
    project_id: uuid.UUID,
) -> _Vendor:
    """The directory contact the quote was entered against, if the order may name it.

    The contact must be visible to the user who awarded the RFQ or to the
    project owner, by the same rule the contacts register applies (tenant, or
    the legacy ``created_by`` for rows from before tenants), with admins
    seeing everything. The order list resolves vendor names without a tenant
    filter, so linking a contact from another tenant would show its name to
    this project.
    """
    raw = (bidder_contact_id or "").strip()
    contact_uuid = _uuid(raw)
    if contact_uuid is None:
        # Not an id at all: a supplier typed in by name on the quote. It is the
        # RFQ's own data, so it names the supplier, but there is no contact.
        return _Vendor(None, raw or None, "not_in_directory")

    from app.core.party_names import contact_display_name  # noqa: PLC0415
    from app.modules.contacts.models import Contact  # noqa: PLC0415

    contact = await session.get(Contact, contact_uuid)
    if contact is None:
        return _Vendor(None, None, "not_in_directory")
    if not await _may_see_contact(session, contact, actor_id=actor_id, project_id=project_id):
        logger.warning(
            "rfq.awarded: contact %s on the awarded quote is outside the awarding user's tenant; "
            "the draft order is left without a vendor",
            contact_uuid,
        )
        return _Vendor(None, None, "not_accessible")
    name = contact_display_name(contact.company_name, contact.legal_name, contact.first_name, contact.last_name)
    return _Vendor(contact.id, name or None, "linked")


async def _may_see_contact(
    session: AsyncSession,
    contact: Any,
    *,
    actor_id: uuid.UUID | None,
    project_id: uuid.UUID,
) -> bool:
    from app.modules.projects.models import Project  # noqa: PLC0415
    from app.modules.users.models import User  # noqa: PLC0415

    viewers: set[str] = set()
    if actor_id is not None:
        actor = await session.get(User, actor_id)
        if actor is not None and getattr(actor, "role", "") == "admin":
            return True
        viewers.add(str(actor_id))
    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner_id is not None:
        viewers.add(str(owner_id))

    tenant = getattr(contact, "tenant_id", None)
    if tenant is not None:
        return str(tenant) in viewers
    created_by = getattr(contact, "created_by", None)
    return created_by is not None and str(created_by) in viewers


# ── Notes ───────────────────────────────────────────────────────────────────


def _notes(
    rfq: Any,
    bid: Any,
    *,
    pricing: str,
    vendor: _Vendor,
    headline: Decimal | None,
    subtotal: Decimal,
    currency: str,
) -> str:
    """What the reviewer needs to know before approving the draft."""
    label = _scope_label(rfq.rfq_number, rfq.title or "")
    parts = [f"Drafted from the award of {label}. Review the supplier, lines and terms before approving."]
    if pricing == "itemised_with_balance":
        parts.append(
            "The priced lines of the quote add up to less than its total, so the difference is ordered as one "
            "balancing line."
        )
    elif pricing == "lump_sum":
        if any(not bl.is_excluded for bl in bid.lines):
            parts.append(
                "The priced lines of the quote add up to more than its total (an overall discount), so the "
                "order is one line at the quoted total."
            )
        else:
            parts.append("The quote was given as a single total, so the order is one line at that total.")
    if vendor.link == "not_in_directory":
        parts.append("The awarded supplier is not a directory contact. Pick the vendor before approving.")
    elif vendor.link == "not_accessible":
        parts.append(
            "The awarded supplier's contact is not available in this workspace. Pick the vendor before approving."
        )
    extras = [adj for adj in bid.adjustments if not adj.included_in_bid and adj.source == "bidder"]
    if extras:
        listed = "; ".join(
            f"{adj.kind}{f' ({adj.description})' if adj.description else ''} {_money(_dec(adj.amount) or _ZERO)} "
            f"{adj.currency_code}"
            for adj in extras
        )
        parts.append(f"Charges the supplier stated outside the quoted total, not included in this order: {listed}.")
    if headline is None:
        parts.append(
            f"The quote had no readable total; the order is the sum of its priced lines, {_money(subtotal)} {currency}."
        )
    return " ".join(parts)
