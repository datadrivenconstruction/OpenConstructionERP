# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the finance module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file, and
nothing needs to.
"""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def sync_budget_rows_written_before_18_1(session: AsyncSession) -> int:
    """Bring budget rows 18.0 left with an undrained ``committed`` to the records, once.

    Up to 18.0 a budget row kept the full order value in ``committed`` after
    the order was received or invoiced, and outturn was the larger of committed
    and actual. From 18.1 committed is the open part only and outturn is their
    sum (``finance.variance``), so such a row reads twice its cost: an order of
    100 with its invoice of 100 paid shows 200.

    ``FinanceService.sync_project_budget`` already moves a row to the new shape
    and stamps it ``budget_sync``, but only after a write in its project, so a
    project nobody touches after the upgrade kept the doubled figure on every
    reader: the finance dashboard and Budgets tab, the main dashboard card that
    reads the row columns directly, the Excel export. This runs that sync for
    each project holding an unstamped row that carries money, so every reader
    is right from the first boot.

    Rows with zero committed and actual cannot be inflated and are left to the
    next write, which keeps a boot on a large install to the projects that
    actually need it. After one pass each synced project's rows are stamped, so
    the next boot finds nothing.

    Each project runs in a savepoint: one that fails is logged, rolled back
    alone, and found again on the next boot.

    Args:
        session: An open session. The repair runner commits.

    Returns:
        Number of unstamped rows with money in the projects synced.
    """
    from sqlalchemy import func, or_, select

    from app.modules.finance.models import ProjectBudget
    from app.modules.finance.service import FinanceService

    stamp = ProjectBudget.metadata_["budget_sync"].as_string()
    candidates = (
        await session.execute(
            select(ProjectBudget.project_id, func.count())
            .where(
                or_(stamp.is_(None), stamp != "1"),
                or_(ProjectBudget.committed != Decimal("0"), ProjectBudget.actual != Decimal("0")),
            )
            .group_by(ProjectBudget.project_id)
        )
    ).all()
    if not candidates:
        return 0

    started = time.monotonic()
    service = FinanceService(session)
    synced_rows = 0
    failed: list[uuid.UUID] = []
    for project_id, row_count in candidates:
        try:
            async with session.begin_nested():
                await service.sync_project_budget(project_id)
        except Exception:
            logger.exception("Budget rows of project %s not brought to the 18.1 shape", project_id)
            failed.append(project_id)
            continue
        synced_rows += int(row_count)
    logger.info(
        "Budget rows from before 18.1 synced in %d of %d project(s) in %.1fs",
        len(candidates) - len(failed),
        len(candidates),
        time.monotonic() - started,
    )
    if failed:
        logger.error(
            "Budget rows of %d project(s) still carry the 18.0 committed and read an inflated outturn "
            "until the next boot or the next finance write in them: %s",
            len(failed),
            ", ".join(str(p) for p in failed),
        )
    return synced_rows


async def _run_budget_rows_18_1(session: AsyncSession) -> int:
    return await sync_budget_rows_written_before_18_1(session)


#: Nature ``always_wrong``: under the 18.1 outturn rule (committed plus actual)
#: an 18.0 row's committed, which still held what had since been received or
#: invoiced, was never a correct value. The sync is the same one every finance
#: write already runs, so this only brings its first run forward to the boot.
#: No alembic revision sits behind this: the change was in service code.
FINANCE_BUDGET_ROWS_18_1 = register_data_repair(
    DataRepair(
        repair_id="finance_budget_rows_committed_open_part",
        revision="",
        summary="Sync budget rows written before 18.1 so committed holds only the open part of each order",
        run=_run_budget_rows_18_1,
        nature="always_wrong",
    )
)
