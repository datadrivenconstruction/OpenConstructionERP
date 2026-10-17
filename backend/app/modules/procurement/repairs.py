# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the procurement module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file, and
nothing needs to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _run_requisition_delivery_date(session: AsyncSession) -> int:
    """Replace the stored ordering deadline with the order's delivery date.

    Requisitions without an order lose the value; requisitions with one take
    the order's ``delivery_date``. Both statements touch only rows that differ,
    so a clean database reports zero. Imported inside the function so that
    importing this module costs only the registration.
    """
    from sqlalchemy import func, select, update

    from app.modules.procurement.models import MaterialRequisition, PurchaseOrder

    cleared = await session.execute(
        update(MaterialRequisition)
        .where(MaterialRequisition.po_id.is_(None), MaterialRequisition.estimated_delivery_date.is_not(None))
        .values(estimated_delivery_date=None)
        .execution_options(synchronize_session=False)
    )
    order_date = (
        select(PurchaseOrder.delivery_date).where(PurchaseOrder.id == MaterialRequisition.po_id).scalar_subquery()
    )
    synced = await session.execute(
        update(MaterialRequisition)
        .where(
            MaterialRequisition.po_id.is_not(None),
            func.coalesce(MaterialRequisition.estimated_delivery_date, "") != func.coalesce(order_date, ""),
        )
        .values(estimated_delivery_date=order_date)
        .execution_options(synchronize_session=False)
    )
    changed = (cleared.rowcount or 0) + (synced.rowcount or 0)
    if changed:
        logger.info("Corrected the delivery date of %d material requisition(s) (issue #516).", changed)
    return changed


#: Nature ``always_wrong``: until 18.6.x ``estimated_delivery_date`` held the
#: required date minus the lead time, which is the latest day to order and was
#: never a delivery forecast. No reader was ever entitled to it as an arrival
#: date, so it is overwritten in place. ``v91_requisition_line_supplier_dates``
#: makes the same correction where alembic runs; this registration is how an
#: ordinary install, which heals its schema at boot and stamps head, gets it.
PROCUREMENT_REQUISITION_DELIVERY_DATE = register_data_repair(
    DataRepair(
        repair_id="procurement_requisition_delivery_date_from_order",
        revision="v91_requisition_line_supplier_dates",
        summary="Replace the requisition ordering deadline stored as a delivery date with the order's delivery date",
        run=_run_requisition_delivery_date,
        nature="always_wrong",
    )
)
