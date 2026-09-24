# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement event handlers - auto-create PO from awarded tender / bid.

Subscribes to BOTH award events emitted by the two sister tendering
modules and creates a draft Purchase Order pre-populated from the winner:

* ``tendering.package.awarded`` (oe_tendering) - see
  :func:`_create_po_from_award`.
* ``bid_management.package.awarded`` (oe_bid_management) - see
  :func:`_create_po_from_bid_award`.

Both close the long-standing workflow gap where an award updated the BOQ
unit rates but left procurement empty, forcing the PM to retype the
supplier and every line item by hand.

Module is auto-imported by the module loader when ``oe_procurement`` is
loaded (see ``module_loader._load_module`` → ``events.py``).

Idempotency & reconciliation
----------------------------
Each generated PO carries deterministic keys in ``metadata``:

* tender awards write ``tender_package_id``;
* bid_management awards write ``bid_package_id`` AND, when the bid
  package is linked to a tendering package (``BidPackage.tender_id``),
  the same ``tender_package_id`` value the tender path would use.

Before creating a PO each handler scans existing project POs and
short-circuits if any of these keys already match. Because the two paths
share the ``tender_package_id`` key whenever a bid package is linked to a
tender, a project that runs BOTH modules for the same logical award never
ends up with two purchase orders - whichever fires first wins, the second
is an idempotent skip. Re-firing the same event (bus retry, manual
replay) is likewise a no-op.

Failure mode
------------
Errors are logged and swallowed - the award itself must never be blocked
because procurement wiring choked. The PO can always be created manually
from the UI.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, _log_failures, event_bus
from app.database import async_session_factory
from app.modules.bid_management.award_selection import select_awarded_submission
from app.modules.bid_management.models import (
    Bidder,
    BidPackage,
    BidSubmissionLine,
)
from app.modules.procurement.cost_spine import resolve_cost_line_ids
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.repository import (
    POItemRepository,
    PurchaseOrderRepository,
)
from app.modules.tendering.models import TenderBid, TenderPackage

logger = logging.getLogger(__name__)


def _to_decimal(value: object) -> Decimal:
    """Coerce a JSON-loaded numeric/string into Decimal, defaulting to 0."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


async def _find_existing_po(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    keys: dict[str, str | None],
) -> PurchaseOrder | None:
    """Return the first project PO whose metadata matches any reconciliation key.

    ``keys`` maps a metadata field name to the value that identifies an
    auto-created PO for this logical award (e.g.
    ``{"bid_package_id": "...", "tender_package_id": "..."}``). A match on
    *any* non-empty key short-circuits creation, which is what makes the
    tender and bid_management paths converge on a single PO when they both
    reference the same tendering package.

    A cancelled PO does not count. Withdrawing an award is refused while its
    PO stands, so the way to re-award is to cancel that PO first, and the
    re-award must then raise a PO for the new supplier rather than find the
    cancelled one and skip.

    Args:
        session: Active async session.
        project_id: Project to scope the scan to.
        keys: Metadata field -> expected value pairs; ``None`` values are
            ignored so callers can pass an absent ``tender_package_id``.

    Returns:
        The matching :class:`PurchaseOrder`, or ``None`` if none exists.
    """
    wanted = {field: value for field, value in keys.items() if value}
    if not wanted:
        return None
    rows = (await session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id))).scalars().all()
    for po in rows:
        if po.status == "cancelled":
            continue
        md = po.metadata_ if isinstance(po.metadata_, dict) else {}
        for field, value in wanted.items():
            if md.get(field) == value:
                return po
    return None


async def _on_tender_awarded(event: Event) -> None:
    """Schedule the auto-PO creation as a detached task.

    The publisher (``tendering.service.apply_winner``) calls
    ``event_bus.publish`` while still holding its request transaction. On
    SQLite the request session is the only writer allowed, so opening a
    second async session inside this handler synchronously would deadlock
    the database (single-writer lock). Detaching via ``create_task`` lets
    the publishing transaction commit and close before we open ours.

    Failures inside the detached coroutine are surfaced via
    :func:`app.core.events._log_failures` so they hit the logs at WARNING
    (previously silent).
    """
    _log_failures(
        _create_po_from_award(event),
        name="procurement.auto_po_from_tender_award",
    )


async def _create_po_from_award(event: Event) -> None:
    """Create a draft PO from a winning tender bid.

    Pulls the package + bid in a fresh async session (the publishing
    session has already committed), maps the bid's line items to PO
    items, and persists. ``metadata.tender_package_id`` is the
    idempotency key.
    """
    data = event.data or {}
    package_id_raw = data.get("package_id")
    bid_id_raw = data.get("bid_id")
    if not package_id_raw or not bid_id_raw:
        return

    try:
        package_id = uuid.UUID(str(package_id_raw))
        bid_id = uuid.UUID(str(bid_id_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            package = (
                await session.execute(select(TenderPackage).where(TenderPackage.id == package_id))
            ).scalar_one_or_none()
            bid = (await session.execute(select(TenderBid).where(TenderBid.id == bid_id))).scalar_one_or_none()

            if package is None or bid is None:
                logger.warning(
                    "tender.awarded handler: package=%s or bid=%s not found",
                    package_id,
                    bid_id,
                )
                return

            # Idempotency + cross-module reconciliation. Skip if a PO
            # already exists for this tender package (re-fire / replay) OR
            # if a *bid_management* award for a bid package linked to this
            # tender already produced one. Both paths stamp the shared
            # ``tender_package_id`` key, so a single metadata scan covers
            # the symmetric case; we additionally resolve any linked bid
            # package id so the reverse direction (bid keyed only on
            # ``bid_package_id`` because it carried no tender link) is also
            # caught.
            po_repo = PurchaseOrderRepository(session)
            linked_bid_package_id = (
                await session.execute(select(BidPackage.id).where(BidPackage.tender_id == package_id))
            ).scalar_one_or_none()
            existing = await _find_existing_po(
                session,
                package.project_id,
                keys={
                    "tender_package_id": str(package_id),
                    "bid_package_id": str(linked_bid_package_id) if linked_bid_package_id else None,
                },
            )
            if existing is not None:
                logger.info(
                    "tender.awarded: PO %s already exists for package %s (idempotent skip)",
                    existing.po_number,
                    package_id,
                )
                return

            # Build line items from bid.line_items. The bid carries dicts
            # with description / unit / quantity / unit_rate / position_id.
            line_items_raw = bid.line_items if isinstance(bid.line_items, list) else []
            po_items: list[PurchaseOrderItem] = []
            position_refs: list[tuple[str | None, str | None]] = []
            running_subtotal = Decimal("0")
            for idx, line in enumerate(line_items_raw):
                if not isinstance(line, dict):
                    continue
                qty = _to_decimal(line.get("quantity"))
                rate = _to_decimal(line.get("unit_rate"))
                amount = qty * rate
                running_subtotal += amount
                desc = str(line.get("description") or "(no description)")[:500]
                unit = str(line.get("unit") or "")[:20] or None
                pos_id = line.get("position_id")
                wbs_id = str(pos_id)[:36] if pos_id else None
                position_refs.append((None, str(pos_id) if pos_id else None))
                po_items.append(
                    PurchaseOrderItem(
                        description=desc,
                        quantity=str(qty),
                        unit=unit,
                        unit_rate=str(rate),
                        amount=str(amount),
                        wbs_id=wbs_id,
                        cost_category=None,
                        sort_order=idx,
                    )
                )

            # An award is the largest single commitment the system makes, and
            # the bid line already names the position it was priced against, so
            # the money link is derivable here exactly as it is for an order a
            # buyer types. Without this the whole package lands on the project
            # total and nowhere in the breakdown.
            #
            # Best effort on purpose. Resolution raises when a position has
            # moved out of the project, and failing to record an award because
            # one line points at stale scope would lose the commitment itself,
            # which is far worse than losing its attribution.
            if any(ref[1] for ref in position_refs):
                try:
                    resolved = await resolve_cost_line_ids(session, package.project_id, position_refs)
                except HTTPException as exc:
                    logger.warning(
                        "tender.awarded: cost spine resolution failed for package %s (%s); "
                        "the order is recorded without its money link",
                        package_id,
                        exc.detail,
                    )
                else:
                    for item, cost_line_id in zip(po_items, resolved, strict=False):
                        item.cost_line_id = cost_line_id

            # Fall back to bid.total_amount if line items don't sum to it
            # (suppliers occasionally include lump sums above the lines).
            bid_total = _to_decimal(bid.total_amount)
            subtotal = running_subtotal if running_subtotal > 0 else bid_total

            # Use the existing repository to assign a project-scoped
            # auto-incremented PO number - keeps the format consistent
            # with manually-created POs.
            po_number = await po_repo.next_po_number(package.project_id)

            po = PurchaseOrder(
                project_id=package.project_id,
                vendor_contact_id=None,  # bid is a free-text supplier; no FK
                po_number=po_number,
                po_type="standard",
                issue_date=None,
                delivery_date=None,
                currency_code=bid.currency or "",
                amount_subtotal=str(subtotal),
                tax_amount="0",
                amount_total=str(subtotal),
                status="draft",
                payment_terms=None,
                notes=(f"Auto-created from awarded tender: {package.name} - bid by {bid.company_name}")[:5000],
                created_by=None,
                metadata_={
                    "tender_package_id": str(package_id),
                    "tender_bid_id": str(bid_id),
                    "tender_package_name": package.name,
                    "supplier_name": bid.company_name,
                    "supplier_contact_email": bid.contact_email,
                    "boq_id": str(package.boq_id) if package.boq_id else None,
                    "origin": "tender_award",
                },
            )
            po = await po_repo.create(po)

            # Persist line items
            item_repo = POItemRepository(session)
            for item in po_items:
                item.po_id = po.id
                await item_repo.create(item)

            await session.commit()
            logger.info(
                "Auto-PO created from tender award: po=%s package=%s bid=%s items=%d subtotal=%s %s",
                po.po_number,
                package_id,
                bid_id,
                len(po_items),
                subtotal,
                bid.currency or "",
            )
    except Exception:
        logger.exception(
            "tender.awarded auto-PO failed for package=%s bid=%s - tender award itself was unaffected",
            package_id,
            bid_id,
        )


async def _on_bid_management_awarded(event: Event) -> None:
    """Schedule auto-PO creation from a bid_management award (detached).

    Mirrors :func:`_on_tender_awarded`. ``bid_management.service.award_package``
    publishes ``bid_management.package.awarded`` via ``publish_detached``
    while its request transaction is still open, so we detach here too:
    opening a second async session synchronously would contend with the
    publishing writer. Detaching lets the award transaction commit before
    we read the winning submission and write the PO.
    """
    _log_failures(
        _create_po_from_bid_award(event),
        name="procurement.auto_po_from_bid_award",
    )


async def _create_po_from_bid_award(event: Event) -> None:
    """Create a draft PO from a bid_management package award.

    The award event carries only identifiers (``package_id``,
    ``project_id``, ``awarded_bidder_id``, ``awarded_amount``,
    ``currency``); the supplier is the winning :class:`Bidder` and the
    line items come from that bidder's valid :class:`BidSubmission` and
    its :class:`BidSubmissionLine` rows. ``metadata.bid_package_id`` is the
    primary idempotency key; when the bid package is linked to a tendering
    package we also stamp ``tender_package_id`` so this PO reconciles with
    one a tender award would create for the same logical award.
    """
    data = event.data or {}
    package_id_raw = data.get("package_id")
    bidder_id_raw = data.get("awarded_bidder_id")
    if not package_id_raw or not bidder_id_raw:
        return

    try:
        package_id = uuid.UUID(str(package_id_raw))
        bidder_id = uuid.UUID(str(bidder_id_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            package = (
                await session.execute(select(BidPackage).where(BidPackage.id == package_id))
            ).scalar_one_or_none()
            bidder = (await session.execute(select(Bidder).where(Bidder.id == bidder_id))).scalar_one_or_none()

            if package is None or bidder is None:
                logger.warning(
                    "bid_management.awarded handler: package=%s or bidder=%s not found",
                    package_id,
                    bidder_id,
                )
                return

            # Idempotency + reconciliation. Skip if a PO already exists for
            # this bid package OR for the tendering package it is linked to
            # (the tender award path may have fired first).
            po_repo = PurchaseOrderRepository(session)
            tender_package_id = str(package.tender_id) if package.tender_id else None
            existing = await _find_existing_po(
                session,
                package.project_id,
                keys={
                    "bid_package_id": str(package_id),
                    "tender_package_id": tender_package_id,
                },
            )
            if existing is not None:
                logger.info(
                    "bid_management.awarded: PO %s already exists for package %s (idempotent skip)",
                    existing.po_number,
                    package_id,
                )
                return

            # Resolve the winning bidder's submission. A bidder may hold more
            # than one, so which row an award refers to is a decision rather
            # than an accident of query order. It is made once, in
            # ``select_awarded_submission``, so that this handler and the
            # contract subscriber cannot drift apart again. The rule it applies
            # is the one this handler already applied: newest valid, falling
            # back to newest, because the award itself already vetted it.
            winning_submission = await select_awarded_submission(session, bidder_id=bidder_id)

            # Map the priced submission lines to PO items, joining each line
            # back to its package line for description/unit/quantity.
            po_items: list[PurchaseOrderItem] = []
            running_subtotal = Decimal("0")
            if winning_submission is not None:
                sub_lines = (
                    (
                        await session.execute(
                            select(BidSubmissionLine).where(BidSubmissionLine.submission_id == winning_submission.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                line_meta = await _bid_line_lookup(session, package_id)
                for idx, line in enumerate(sub_lines):
                    meta = line_meta.get(line.line_item_id, {})
                    qty = _to_decimal(line.quantity_priced) or _to_decimal(meta.get("quantity"))
                    rate = _to_decimal(line.unit_price)
                    amount = _to_decimal(line.total_price)
                    if amount == 0:
                        amount = qty * rate
                    running_subtotal += amount
                    desc = str(meta.get("description") or meta.get("code") or "(no description)")[:500]
                    unit = (str(meta.get("unit") or "")[:20]) or None
                    po_items.append(
                        PurchaseOrderItem(
                            description=desc,
                            quantity=str(qty),
                            unit=unit,
                            unit_rate=str(rate),
                            amount=str(amount),
                            wbs_id=None,
                            cost_category=None,
                            sort_order=idx,
                        )
                    )

            # Award amount is the authoritative committed total; fall back to
            # the submission envelope total if the award amount is missing.
            award_amount = _to_decimal(data.get("awarded_amount"))
            submission_total = (
                _to_decimal(winning_submission.total_amount) if winning_submission is not None else Decimal("0")
            )
            if award_amount > 0:
                subtotal = award_amount
            elif running_subtotal > 0:
                subtotal = running_subtotal
            else:
                subtotal = submission_total

            currency = (
                str(data.get("currency") or "")
                or (winning_submission.currency if winning_submission is not None else "")
                or package.currency
                or ""
            )

            po_number = await po_repo.next_po_number(package.project_id)

            po = PurchaseOrder(
                project_id=package.project_id,
                vendor_contact_id=None,  # bidder is a denormalised snapshot; no FK
                po_number=po_number,
                po_type="standard",
                issue_date=None,
                delivery_date=None,
                currency_code=currency,
                amount_subtotal=str(subtotal),
                tax_amount="0",
                amount_total=str(subtotal),
                status="draft",
                payment_terms=None,
                notes=(
                    f"Auto-created from awarded bid package: {package.title or package.code} "
                    f"- bid by {bidder.company_name}"
                )[:5000],
                created_by=None,
                metadata_={
                    "bid_package_id": str(package_id),
                    "bid_package_code": package.code,
                    "bid_award_bidder_id": str(bidder_id),
                    "tender_package_id": tender_package_id,
                    "supplier_name": bidder.company_name,
                    "supplier_contact_email": bidder.contact_email,
                    "origin": "bid_management_award",
                },
            )
            po = await po_repo.create(po)

            item_repo = POItemRepository(session)
            for item in po_items:
                item.po_id = po.id
                await item_repo.create(item)

            await session.commit()
            logger.info(
                "Auto-PO created from bid_management award: po=%s package=%s bidder=%s items=%d subtotal=%s %s",
                po.po_number,
                package_id,
                bidder_id,
                len(po_items),
                subtotal,
                currency,
            )
    except Exception:
        logger.exception(
            "bid_management.awarded auto-PO failed for package=%s bidder=%s - the award itself was unaffected",
            package_id,
            bidder_id,
        )


async def _bid_line_lookup(session: AsyncSession, package_id: uuid.UUID) -> dict[uuid.UUID, dict[str, object]]:
    """Map a package's line-item ids to their scope description/unit/quantity.

    Submission lines reference ``line_item_id`` (the package line) but carry
    no human description of their own, so we resolve it here once to label
    each generated PO item.
    """
    from app.modules.bid_management.models import BidPackageLineItem

    rows = (
        (await session.execute(select(BidPackageLineItem).where(BidPackageLineItem.package_id == package_id)))
        .scalars()
        .all()
    )
    return {
        row.id: {
            "code": row.code,
            "description": row.description,
            "unit": row.unit,
            "quantity": row.quantity,
        }
        for row in rows
    }


async def _on_supplier_rating_update(event: Event) -> None:
    """``procurement.supplier_rating_update`` → flag the vendor on a defect.

    Published by ``qms/events.py::_on_ncr_raised_fanout`` whenever an NCR
    is raised. When the payload carries a ``supplier_id`` (the responsible
    subcontractor), this marks that subcontractor ``under_review`` on its
    metadata - a non-destructive flag the scorecard UI surfaces and the next
    monthly rollup folds into the quality score via the NCR count. The flag
    records the triggering NCR id, severity and timestamp so the buyer can
    see *why* a vendor is under review without spelunking the event bus.

    The defect signal is also forwarded to the subcontractors module as
    ``subcontractors.defect.recorded`` so its event subscriber can accumulate
    the NCR count onto the current period's rating basis (the same low-latency
    path the monthly compute reads).

    When no ``supplier_id`` is present (today's qms payload links the NCR to
    an inspection but does not resolve the responsible sub) the hand-off is
    logged so it stays observable; nothing to flag without a vendor. The
    handler never raises - an NCR must never fail because the rating
    projection choked.
    """
    data = event.data or {}
    ncr_id = data.get("ncr_id") or ""
    project_id = data.get("project_id") or ""
    severity = data.get("severity") or ""
    supplier_id = data.get("supplier_id") or ""

    if not supplier_id:
        logger.info(
            "procurement.supplier_rating_update: no supplier_id on NCR %s (project=%s severity=%s) - nothing to flag",
            ncr_id,
            project_id,
            severity,
        )
        return

    try:
        sub_uuid = uuid.UUID(str(supplier_id))
    except (ValueError, TypeError):
        logger.warning(
            "procurement.supplier_rating_update: supplier_id %r is not a UUID",
            supplier_id,
        )
        return

    from datetime import UTC, datetime

    from app.modules.subcontractors.models import Subcontractor

    try:
        async with async_session_factory() as session:
            sub = await session.get(Subcontractor, sub_uuid)
            if sub is None:
                logger.info(
                    "procurement.supplier_rating_update: supplier %s not a known subcontractor - skipping",
                    supplier_id,
                )
                return
            meta = dict(sub.metadata_ or {})
            meta["under_review"] = True
            meta["under_review_reason"] = {
                "trigger": "ncr",
                "ncr_id": str(ncr_id),
                "project_id": str(project_id),
                "severity": str(severity),
                "at": datetime.now(UTC).isoformat(),
            }
            sub.metadata_ = meta
            session.add(sub)
            await session.commit()
        # Forward the defect so the subcontractors rating projection can
        # accumulate the NCR count onto the current period's basis.
        event_bus.publish_detached(
            "subcontractors.defect.recorded",
            {
                "subcontractor_id": str(sub_uuid),
                "ncr_id": str(ncr_id),
                "project_id": str(project_id),
                "severity": str(severity),
            },
            source_module="procurement",
        )
        logger.info(
            "procurement.supplier_rating_update: flagged subcontractor %s under_review from NCR %s (severity=%s)",
            supplier_id,
            ncr_id,
            severity,
        )
    except Exception:  # noqa: BLE001 - never fail the NCR over a projection
        logger.warning(
            "procurement.supplier_rating_update: failed to flag supplier %s",
            supplier_id,
            exc_info=True,
        )


# ── Published events (declared for discoverability) ───────────────────────────
#
# Events this module PUBLISHES (see procurement/service.py):
#   * procurement.po.created            - new PO row inserted
#   * procurement.po.updated            - PO fields changed
#   * procurement.po.approved           - PO transitioned to 'approved'
#   * procurement.po.issued             - PO transitioned to 'issued'
#   * procurement.po.cancelled          - PO voided out of a committed state;
#                                         finance decrements ``committed`` by
#                                         exactly what this PO committed
#   * procurement.po.reverted           - PO taken back to draft, same effect
#   * procurement.po.deleted            - a never-issued draft PO removed
#   * procurement.gr.created            - new goods receipt inserted
#   * procurement.gr.confirmed          - goods receipt confirmed
#   * procurement.po.retainage_released - withheld retainage released (Gap F)
#
# ``procurement.po.retainage_released`` payload:
#   { po_id, project_id, po_number, release_amount, currency_code,
#     released_by, release_reason, retainage_released_total }
# No subscriber is wired yet - retainage release does not re-post to the cost
# spine (the actual cost already landed on the BudgetLine when the PO/GR was
# posted; releasing retainage is a payment-timing event, not a new cost). A
# future Wave 6 item may subscribe to feed a cash-flow / payment-schedule view.
PUBLISHED_EVENTS = (
    "procurement.po.created",
    "procurement.po.updated",
    "procurement.po.approved",
    "procurement.po.issued",
    "procurement.po.cancelled",
    "procurement.po.reverted",
    "procurement.po.deleted",
    "procurement.gr.created",
    "procurement.gr.confirmed",
    "procurement.po.retainage_released",
)


# Register subscribers at module import - module_loader picks this up
# automatically when ``oe_procurement`` is loaded.
event_bus.subscribe_once("tendering.package.awarded", _on_tender_awarded)
event_bus.subscribe_once("bid_management.package.awarded", _on_bid_management_awarded)
event_bus.subscribe_once(
    "procurement.supplier_rating_update",
    _on_supplier_rating_update,
)
