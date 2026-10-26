# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report demo seed: three closed month ends per demo project.

Every closed period is computed by the real close from the project's own contracts,
change orders, cost reports and claims at that month end; nothing is typed in here.
What the seed decides is the project manager's estimate at completion on three of the
projects, the input a WIP meeting really revises:

* the first is re-estimated upwards, so less work is earned than billed: over-billed;
* the second is re-estimated downwards, so more is earned than billed: under-billed;
* the third keeps the cost report forecast for two months, then a cost overrun of four
  percent of contract value lands in the last month: a fading job.

Demo estate only, and skipped per project once any WIP period exists.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wip_report import logic
from app.modules.wip_report.models import WipPeriod
from app.modules.wip_report.service import WipReportService

logger = logging.getLogger(__name__)

_NOTE = {
    "over": "Estimate revised upwards after the design changes review.",
    "under": "Estimate revised downwards after the trade packages were let below budget.",
    "fade": "Ground conditions overrun booked at the month-end review.",
}


def _back(today: date, months: int) -> str:
    index = today.year * 12 + today.month - 1 - months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _eac_for(role: str, row: dict) -> Decimal | None:
    contract, billed, ctd = row["contract_value"], row["billed_to_date"], row["cost_to_date"]
    if contract <= 0 or billed <= 0 or ctd <= 0:
        return None
    billed_share = billed / contract
    if role == "over":
        target = billed_share / Decimal("1.08")
    elif role == "under":
        target = min(Decimal("0.97"), billed_share * Decimal("1.15"))
        if target <= billed_share:
            return None
    else:
        return None
    return logic.q2(ctd / target) if target > 0 else None


async def seed_wip_report_demo(
    session: AsyncSession, project_ids: Iterable[uuid.UUID], *, today: date | None = None
) -> dict[str, int]:
    """Close the last three month ends on every demo project with a contract and a cost report."""
    from app.core.demo_commercial import is_demo_project
    from app.modules.projects.models import Project

    totals = {"projects": 0, "periods": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    anchor = today or date.today()
    projects = (
        await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)).order_by(Project.name))
    ).all()
    seeded = set(
        (await session.execute(select(WipPeriod.project_id).where(WipPeriod.project_id.in_(ids)).distinct()))
        .scalars()
        .all()
    )
    service = WipReportService(session)
    roles = ["over", "under", "fade"]
    periods = [_back(anchor, 3), _back(anchor, 2), _back(anchor, 1)]
    for project_id, metadata in projects:
        if project_id in seeded or not is_demo_project(metadata):
            continue
        try:
            async with session.begin_nested():
                live = await service.row(project_id, logic.month_end(periods[-1]))
                if live["contract_value"] <= 0 or live["cost_to_date"] <= 0:
                    continue
                role = None
                if roles:
                    candidate = roles[0]
                    if candidate == "fade" or _eac_for(candidate, live) is not None:
                        role = roles.pop(0)
                if role in ("over", "under"):
                    eac = _eac_for(role, live)
                    await service.set_forecast(project_id, eac, _NOTE[role], None)
                for i, period in enumerate(periods):
                    if role == "fade" and i == len(periods) - 1:
                        overrun = live["contract_value"] * Decimal("0.04")
                        base = live["estimated_cost"] if live["estimated_cost"] > 0 else live["cost_to_date"]
                        await service.set_forecast(project_id, logic.q2(base + overrun), _NOTE["fade"], None)
                    await service.close_period(project_id, period, None, "Month-end close")
                    totals["periods"] += 1
                totals["projects"] += 1
        except Exception:
            logger.warning("WIP demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
    return totals


__all__ = ["seed_wip_report_demo"]
