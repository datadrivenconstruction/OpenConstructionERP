# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How much of each BOQ resource the requisitions already hold (issue #516).

A requisition reserves quantity only once it is submitted: a draft holds
nothing, and a withdrawn, rejected or cancelled requisition gives its quantity
back. Quantities are summed per BOQ position and resource, in the unit the
source states. Two units are two figures: kilograms are never added to tonnes
as if they were the same, so the result is keyed by unit as well.

The BOQ is never rewritten by this, and a requisition is never rewritten by a
BOQ edit: when the demand later shrinks, the remaining quantity simply reads
negative.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.models import (
    MaterialRequisition,
    MaterialRequisitionItem,
    MaterialRequisitionItemSource,
)

#: Statuses whose sources count as covered. ``draft`` reserves nothing, and
#: ``rejected``, ``cancelled`` (and a withdrawn requisition, which is a draft
#: again) hold nothing.
COVERING_STATUSES: frozenset[str] = frozenset({"submitted", "approved", "ordered", "received", "consumed"})

_ZERO = Decimal("0")

#: ``{(boq_position_id, resource_key): {unit: quantity}}``
Coverage = dict[tuple[str, str], dict[str, Decimal]]


def unit_key(raw: str | None) -> str:
    """The unit as compared: trimmed and lower-cased."""
    return str(raw or "").strip().lower()


def _qty(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return value if value.is_finite() else _ZERO


async def covered_by_source(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    exclude_requisition_id: uuid.UUID | None = None,
) -> Coverage:
    """Sum source quantities of the project's covering requisitions per BOQ resource and unit.

    ``exclude_requisition_id`` leaves one requisition out, so it can be judged
    against what the others hold.
    """
    stmt = (
        select(
            MaterialRequisitionItemSource.boq_position_id,
            MaterialRequisitionItemSource.resource_key,
            MaterialRequisitionItemSource.unit,
            MaterialRequisitionItemSource.quantity,
        )
        .join(MaterialRequisitionItem, MaterialRequisitionItem.id == MaterialRequisitionItemSource.item_id)
        .join(MaterialRequisition, MaterialRequisition.id == MaterialRequisitionItem.requisition_id)
        .where(
            MaterialRequisition.project_id == project_id,
            MaterialRequisition.status.in_(COVERING_STATUSES),
            MaterialRequisitionItemSource.boq_position_id.is_not(None),
            MaterialRequisitionItemSource.resource_key.is_not(None),
        )
    )
    if exclude_requisition_id is not None:
        stmt = stmt.where(MaterialRequisition.id != exclude_requisition_id)
    covered: Coverage = {}
    for position_id, resource_key, unit, quantity in (await session.execute(stmt)).all():
        per_unit = covered.setdefault((str(position_id), str(resource_key)), {})
        key = unit_key(unit)
        per_unit[key] = per_unit.get(key, _ZERO) + _qty(quantity)
    return covered


def covered_in_unit(covered: Coverage, position_id: str, resource_key: str, unit: str | None) -> Decimal:
    """What is covered for one resource in one unit; other units are not added in."""
    return covered.get((str(position_id), str(resource_key)), {}).get(unit_key(unit), _ZERO)


async def boq_demand(session: AsyncSession, project_id: uuid.UUID) -> dict[tuple[str, str], tuple[Decimal, str]]:
    """The BOQ demand per ``(position, resource key)`` as ``(gross quantity, unit)``.

    Read from the same buy list a requisition is raised from, so the figure a
    source was written from and the figure it is judged against agree.
    """
    from app.modules.resource_summary.service import ResourceSummaryService

    buy_list, _ = await ResourceSummaryService(session).generate_buy_list(project_id)
    return {
        (source.position_id, source.resource_key): (source.quantity, source.unit)
        for item in buy_list.items
        for source in item.sources
    }
