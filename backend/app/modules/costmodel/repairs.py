# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the cost model module.

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


async def _run_cost_structure_backfill(session: AsyncSession) -> int:
    """Nest the flat account lists of earlier releases and recompute every level.

    The decision of what to touch lives in
    :func:`app.modules.costmodel.structure_backfill.plan_structure_backfill`,
    shared with the revision, so an install that runs alembic and one that
    heals at boot end with the same tree. Imported inside the function so that
    importing this module costs only the registration.
    """
    from sqlalchemy import select, update

    from app.modules.costmodel.models import ControlAccount
    from app.modules.costmodel.structure_backfill import AccountRow, plan_structure_backfill

    rows = (
        await session.execute(
            select(
                ControlAccount.id,
                ControlAccount.project_id,
                ControlAccount.parent_id,
                ControlAccount.code,
                ControlAccount.name,
                ControlAccount.title,
                ControlAccount.level,
                ControlAccount.classification_standard,
            )
        )
    ).all()
    plan = plan_structure_backfill(
        AccountRow(
            id=r.id,
            project_id=r.project_id,
            parent_id=r.parent_id,
            code=r.code or "",
            name=r.name or "",
            title=r.title or "",
            level=int(r.level or 0),
            standard=r.classification_standard or "",
        )
        for r in rows
    )
    for account_id, values in plan.items():
        await session.execute(
            update(ControlAccount)
            .where(ControlAccount.id == account_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
    if plan:
        logger.info("Nested or re-levelled %d cost account(s) of an earlier flat cost structure.", len(plan))
    return len(plan)


#: Nature ``always_wrong``: a flat account list whose codes nest is the shape the
#: spine generator wrote before 18.7, not a structure anyone chose, and a level
#: that disagrees with the parent chain was never right. The planner only nests
#: groups nobody has shaped yet, so a deliberate top-level account is left
#: alone on every boot. ``v92_costmodel_cost_structure`` makes the same change
#: where alembic runs; this registration is how an ordinary install, which heals
#: its schema at boot and stamps head, gets it.
COSTMODEL_STRUCTURE_BACKFILL = register_data_repair(
    DataRepair(
        repair_id="costmodel_structure_backfill",
        revision="v92_costmodel_cost_structure",
        summary="Nest the flat cost account lists of earlier releases by code and recompute account levels",
        run=_run_cost_structure_backfill,
        nature="always_wrong",
    )
)
