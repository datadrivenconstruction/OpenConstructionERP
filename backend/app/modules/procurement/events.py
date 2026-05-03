"""Procurement event handlers — auto-create PO from awarded tender.

Subscribes to ``tendering.package.awarded`` and creates a draft Purchase
Order pre-populated from the winning bid's line items, supplier
identity, and total. Closes the long-standing workflow gap where a
tender award updated the BOQ unit rates (via :func:`apply_winner`) but
left procurement empty — the PM had to retype the supplier and every
line item by hand.

Module is auto-imported by the module loader when ``oe_procurement`` is
loaded (see ``module_loader._load_module`` → ``events.py``).

Idempotency
-----------
Each generated PO carries ``metadata.tender_package_id``. Before creating
a new PO the handler queries for any existing row with the same value and
short-circuits if found. This makes re-firing the event (event bus retry,
manual replay during testing) safe.

Failure mode
------------
Errors are logged and swallowed — the tender award itself must never be
blocked because procurement wiring choked. The PO can always be created
manually from the UI.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
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


async def _on_tender_awarded(event: Event) -> None:
    """Schedule the auto-PO creation as a detached task.

    The publisher (``tendering.service.apply_winner``) calls
    ``event_bus.publish`` while still holding its request transaction. On
    SQLite the request session is the only writer allowed, so opening a
    second async session inside this handler synchronously would deadlock
    the database (single-writer lock). Detaching via ``create_task`` lets
    the publishing transaction commit and close before we open ours.
    """
    asyncio.create_task(_create_po_from_award(event))


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
                await session.execute(
                    select(TenderPackage).where(TenderPackage.id == package_id)
                )
            ).scalar_one_or_none()
            bid = (
                await session.execute(
                    select(TenderBid).where(TenderBid.id == bid_id)
                )
            ).scalar_one_or_none()

            if package is None or bid is None:
                logger.warning(
                    "tender.awarded handler: package=%s or bid=%s not found",
                    package_id, bid_id,
                )
                return

            # Idempotency — search for any existing PO created from this
            # tender package. JSON path query works on both PG (JSON_EXTRACT)
            # and SQLite (JSON1 extension).
            po_repo = PurchaseOrderRepository(session)
            existing_pos = (
                await session.execute(
                    select(PurchaseOrder)
                    .where(PurchaseOrder.project_id == package.project_id)
                )
            ).scalars().all()
            for po in existing_pos:
                md = po.metadata_ if isinstance(po.metadata_, dict) else {}
                if md.get("tender_package_id") == str(package_id):
                    logger.info(
                        "tender.awarded: PO %s already exists for package %s "
                        "(idempotent skip)",
                        po.po_number, package_id,
                    )
                    return

            # Build line items from bid.line_items. The bid carries dicts
            # with description / unit / quantity / unit_rate / position_id.
            line_items_raw = bid.line_items if isinstance(bid.line_items, list) else []
            po_items: list[PurchaseOrderItem] = []
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

            # Fall back to bid.total_amount if line items don't sum to it
            # (suppliers occasionally include lump sums above the lines).
            bid_total = _to_decimal(bid.total_amount)
            subtotal = running_subtotal if running_subtotal > 0 else bid_total

            # Use the existing repository to assign a project-scoped
            # auto-incremented PO number — keeps the format consistent
            # with manually-created POs.
            po_number = await po_repo.next_po_number(package.project_id)

            po = PurchaseOrder(
                project_id=package.project_id,
                vendor_contact_id=None,  # bid is a free-text supplier; no FK
                po_number=po_number,
                po_type="standard",
                issue_date=None,
                delivery_date=None,
                currency_code=bid.currency or "EUR",
                amount_subtotal=str(subtotal),
                tax_amount="0",
                amount_total=str(subtotal),
                status="draft",
                payment_terms=None,
                notes=(
                    f"Auto-created from awarded tender: {package.name} "
                    f"— bid by {bid.company_name}"
                )[:5000],
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
                "Auto-PO created from tender award: po=%s package=%s bid=%s "
                "items=%d subtotal=%s %s",
                po.po_number, package_id, bid_id,
                len(po_items), subtotal, bid.currency or "EUR",
            )
    except Exception:
        logger.exception(
            "tender.awarded auto-PO failed for package=%s bid=%s "
            "— tender award itself was unaffected",
            package_id, bid_id,
        )


# Register subscriber at module import — module_loader picks this up
# automatically when ``oe_procurement`` is loaded.
event_bus.subscribe("tendering.package.awarded", _on_tender_awarded)
