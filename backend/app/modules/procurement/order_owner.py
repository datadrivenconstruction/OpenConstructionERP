# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who places the orders for a project: OCERP or an external purchasing system (issue #516).

A project without a settings row orders in OCERP, which is how every project
behaved before the setting existed. With ``external``:

* new requisitions are created with ``order_owner = external``, so they are
  reconciled from the external system's reports instead of converted into a
  purchase order here;
* the award subscribers (tender, bid management, RFQ) draft no purchase order,
  because the external system raises the order for that decision and a local
  draft would be a second order for it.

Standalone purchase orders raised by hand are not affected: the setting is
about requisitions and automatic drafts, not about forbidding a buyer to type
an order.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.models import ProcurementProjectSettings

OCERP = "ocerp"
EXTERNAL = "external"
ORDER_OWNERS: frozenset[str] = frozenset({OCERP, EXTERNAL})

OrderOwner = Literal["ocerp", "external"]


async def load_settings(session: AsyncSession, project_id: uuid.UUID) -> ProcurementProjectSettings | None:
    """The project's settings row, or None when the project never saved one."""
    return (
        await session.execute(
            select(ProcurementProjectSettings).where(ProcurementProjectSettings.project_id == project_id)
        )
    ).scalar_one_or_none()


async def order_owner_for_project(session: AsyncSession, project_id: uuid.UUID) -> str:
    """``ocerp`` or ``external`` for a project; ``ocerp`` when nothing is configured."""
    row = await load_settings(session, project_id)
    owner = (row.order_owner if row is not None else "") or OCERP
    return owner if owner in ORDER_OWNERS else OCERP


def effective_owner(raw: str | None) -> str:
    """A requisition's stored owner as it is read: null and unknown values are ``ocerp``."""
    return raw if raw in ORDER_OWNERS else OCERP
