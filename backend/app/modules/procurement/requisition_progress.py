# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requested, ordered, received and outstanding per requisition line (issue #516).

The figures are read from the documents that carry them, not from counters:

* **ordered** is the sum of the purchase order lines that name the requisition
  line (``oe_procurement_po_item.requisition_item_id``) on orders that are not
  cancelled, plus the external order lines reported for it that are not
  cancelled. Several orders per line, part quantities and one order holding
  lines of several requisitions all fall out of that sum.
* **received** is the sum of confirmed goods receipt lines against those order
  lines, plus what the external system reported as received.

Every figure is restated in the requisition line's unit with
:func:`app.core.unit_conversion.convert_between`. An order line in a unit that
cannot be restated is listed with ``unit_mismatch`` and left out of the sums,
because adding kilograms to tonnes as if they were the same would be a wrong
number presented as a right one.

The stored ``quantity_ordered`` / ``quantity_received`` columns on the line are
a cache that :func:`refresh_requisitions` rewrites whenever this module's
inputs change through the requisition workflow (conversion, order release,
external report). Readers use :func:`load_progress`, which is always live.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sql_numeric import numeric_value
from app.core.unit_conversion import convert_between
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    MaterialRequisition,
    MaterialRequisitionItem,
    PurchaseOrder,
    PurchaseOrderItem,
    RequisitionExternalOrderLine,
)

_ZERO = Decimal("0")


def dec(raw: object) -> Decimal:
    """A finite Decimal, or zero for anything that is not one."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return value if value.is_finite() else _ZERO


def fmt(value: Decimal) -> str:
    """A Decimal as plain text without exponent, keeping the scale its arithmetic gave it.

    The scale is kept so a line requested as ``71.4000`` still reads
    ``71.4000`` outstanding, as it always has; :func:`in_line_unit` trims a
    converted figure instead, where the conversion is what made the digits.
    """
    return format(value, "f")


def in_line_unit(quantity: Decimal, from_unit: str | None, line_unit: str | None) -> Decimal | None:
    """``quantity`` restated in the requisition line's unit, or None when it cannot be."""
    converted = convert_between(quantity, from_unit, line_unit)
    if converted is None or not converted.is_finite():
        return None
    if (from_unit or "").strip().lower() != (line_unit or "").strip().lower():
        # 3250 kg is 3.25 t, not 3.250000000 t.
        converted = converted.normalize()
    return converted


@dataclass
class POLineProgress:
    """One purchase order line converted from a requisition line."""

    po_item_id: uuid.UUID
    po_id: uuid.UUID
    po_number: str | None
    po_status: str | None
    quantity: Decimal
    unit: str | None
    received: Decimal
    po_delivery_date: str | None
    supplier_confirmed_delivery_date: str | None
    unit_mismatch: bool = False


@dataclass
class LineProgress:
    """What has been ordered and received for one requisition line, in its unit."""

    requested: Decimal
    ordered: Decimal = _ZERO
    received: Decimal = _ZERO
    po_lines: list[POLineProgress] = field(default_factory=list)
    external_lines: list[RequisitionExternalOrderLine] = field(default_factory=list)
    external_mismatch: set[uuid.UUID] = field(default_factory=set)

    @property
    def to_order(self) -> Decimal:
        return max(self.requested - self.ordered, _ZERO)

    @property
    def outstanding(self) -> Decimal:
        """Requested minus received, not clamped: below zero means more arrived than was asked for."""
        return self.requested - self.received

    @property
    def over_ordered(self) -> bool:
        return self.ordered > self.requested


async def load_progress(
    session: AsyncSession,
    items: Iterable[MaterialRequisitionItem],
    *,
    exclude_po_ids: Iterable[uuid.UUID] = (),
) -> dict[uuid.UUID, LineProgress]:
    """Live ordered and received figures for requisition lines, keyed by line id.

    ``exclude_po_ids`` leaves orders out of the sums as if they were cancelled,
    for the moment just before an order is cancelled or deleted.
    """
    lines = {item.id: item for item in items}
    out = {item_id: LineProgress(requested=dec(item.quantity_requested)) for item_id, item in lines.items()}
    if not lines:
        return out
    excluded = set(exclude_po_ids)
    po_rows = (
        await session.execute(
            select(
                PurchaseOrderItem.id,
                PurchaseOrderItem.po_id,
                PurchaseOrderItem.quantity,
                PurchaseOrderItem.unit,
                PurchaseOrderItem.requisition_item_id,
                PurchaseOrder.po_number,
                PurchaseOrder.status,
                PurchaseOrder.delivery_date,
                PurchaseOrder.supplier_confirmed_delivery_date,
            )
            .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
            .where(PurchaseOrderItem.requisition_item_id.in_(list(lines)))
            .order_by(PurchaseOrder.created_at, PurchaseOrderItem.sort_order)
        )
    ).all()
    received_by_po_item: dict[uuid.UUID, Decimal] = {}
    po_item_ids = [row.id for row in po_rows]
    if po_item_ids:
        received_rows = (
            await session.execute(
                select(
                    GoodsReceiptItem.po_item_id,
                    func.coalesce(func.sum(numeric_value(GoodsReceiptItem.quantity_received)), 0),
                )
                .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.receipt_id)
                .where(GoodsReceipt.status == "confirmed", GoodsReceiptItem.po_item_id.in_(po_item_ids))
                .group_by(GoodsReceiptItem.po_item_id)
            )
        ).all()
        received_by_po_item = {row[0]: dec(row[1]) for row in received_rows}

    for row in po_rows:
        progress = out[row.requisition_item_id]
        line_unit = lines[row.requisition_item_id].unit
        quantity = dec(row.quantity)
        received = received_by_po_item.get(row.id, _ZERO)
        ordered_here = in_line_unit(quantity, row.unit, line_unit)
        received_here = in_line_unit(received, row.unit, line_unit)
        mismatch = ordered_here is None or received_here is None
        progress.po_lines.append(
            POLineProgress(
                po_item_id=row.id,
                po_id=row.po_id,
                po_number=row.po_number,
                po_status=row.status,
                quantity=quantity,
                unit=row.unit,
                received=received,
                po_delivery_date=row.delivery_date,
                supplier_confirmed_delivery_date=row.supplier_confirmed_delivery_date,
                unit_mismatch=mismatch,
            )
        )
        if row.status == "cancelled" or row.po_id in excluded or mismatch:
            continue
        progress.ordered += ordered_here or _ZERO
        progress.received += received_here or _ZERO

    external = (
        (
            await session.execute(
                select(RequisitionExternalOrderLine)
                .where(RequisitionExternalOrderLine.requisition_item_id.in_(list(lines)))
                .order_by(
                    RequisitionExternalOrderLine.external_system,
                    RequisitionExternalOrderLine.external_order_number,
                    RequisitionExternalOrderLine.external_line_ref,
                )
            )
        )
        .scalars()
        .all()
    )
    for ext in external:
        progress = out[ext.requisition_item_id]
        progress.external_lines.append(ext)
        line_unit = lines[ext.requisition_item_id].unit
        ordered_here = in_line_unit(dec(ext.quantity_ordered), ext.unit, line_unit)
        received_here = in_line_unit(dec(ext.quantity_received), ext.unit, line_unit)
        if ordered_here is None or received_here is None:
            progress.external_mismatch.add(ext.id)
            continue
        if ext.status == "cancelled":
            continue
        progress.ordered += ordered_here
        progress.received += received_here
    return out


def order_progress(progress: dict[uuid.UUID, LineProgress]) -> str:
    """``none``, ``partial`` or ``full`` for a requisition's lines taken together."""
    if not progress:
        return "none"
    if all(p.to_order == _ZERO and p.requested > _ZERO for p in progress.values()):
        return "full"
    if any(p.ordered > _ZERO for p in progress.values()):
        return "partial"
    return "none"


async def refresh_requisitions(
    session: AsyncSession,
    reqs: Iterable[MaterialRequisition],
    *,
    exclude_po_ids: Iterable[uuid.UUID] = (),
) -> dict[uuid.UUID, tuple[str, str]]:
    """Rewrite the cached line figures and move ``approved`` <-> ``ordered`` to match.

    A requisition whose lines are all fully on live orders is ``ordered``; one
    with anything left to order is ``approved``, so it can be ordered further.
    Only those two statuses move: a received, consumed or cancelled requisition
    keeps its status. ``po_id`` follows the newest live order, or is cleared.

    Returns:
        ``{requisition id: (previous status, new status)}`` for every
        requisition whose status changed. The caller records those.
    """
    excluded = set(exclude_po_ids)
    changed: dict[uuid.UUID, tuple[str, str]] = {}
    for req in reqs:
        progress = await load_progress(session, req.items, exclude_po_ids=excluded)
        for item in req.items:
            line = progress[item.id]
            item.quantity_ordered = fmt(line.ordered)
            item.quantity_received = fmt(line.received)
        live = [
            po_line
            for line in progress.values()
            for po_line in line.po_lines
            if po_line.po_status != "cancelled" and po_line.po_id not in excluded
        ]
        req.po_id = live[-1].po_id if live else None
        if not live:
            req.estimated_delivery_date = None
        if req.status in ("approved", "ordered"):
            target = "ordered" if order_progress(progress) == "full" else "approved"
            if target != req.status:
                changed[req.id] = (req.status, target)
                req.status = target
    return changed
