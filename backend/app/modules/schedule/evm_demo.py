# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo history for the schedule: baseline, monthly progress and the earned-value trend.

A demo project is installed with a plan and a snapshot of today, and nothing
that says how it got here: no baseline to compare the plan with, no progress
updates, no data date, so the earned-value curve, the S-curve and the SPI / CPI
trend open empty on a project that has been running for months.

This seeder writes that history from the project's own plan, and only from it.

* The plan is cost-loaded from the project's priced bill, spread over the
  working activities by duration. The bill total is the same anchor the
  reconciliation and the earned-value baseline use, so the cost screens agree.
* The contract baseline is the plan as it stands, frozen at its start.
* One approved progress update per activity per month-end, up to the seed day.
  An activity runs a few days behind its plan, a different few for each, which
  is what real progress looks like and keeps SPI near but not at 1.
* The data date is the seed day and a schedule EVM snapshot is recorded at
  every month-end, by the module's own service, so the trend is what the
  module computes and not what this file asserts.
* The cost-model snapshots are rewritten from the same month-by-month figures:
  planned and earned cost from the plan and the progress, actual cost from
  earned cost over a cost index that stays within a few percent of 1.

Everything is dated from the seed day, so a demo opened a year after it shipped
still has a twelve-month history ending today.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_commercial import bill_total, is_demo_project
from app.modules.costmodel.models import CostSnapshot
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, ProgressUpdate, Schedule, ScheduleBaseline

logger = logging.getLogger(__name__)

__all__ = ["seed_schedule_evm_demo"]

#: Marker on the rows this seeder writes, so a re-run recognises its own work.
SEED_MARK = "schedule-evm-demo"

#: How many months of history to write, at most.
_MAX_STEPS = 12

#: Days an activity runs behind its plan, by position. Small on purpose: the
#: slip is a share of each activity's duration, and the project index should
#: land within a few percent of 1.
_LAG_DAYS = (2, 3, 5, 4)

#: Cost performance index by month, cycled. Within a few percent of 1.
_COST_INDEX = (Decimal("0.99"), Decimal("0.98"), Decimal("0.97"), Decimal("0.98"), Decimal("0.99"), Decimal("1.01"))

_CENT = Decimal("0.01")


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _pct(start: date, end: date, on: date) -> int:
    """Percent of an activity's span elapsed on a day."""
    if on <= start:
        return 0
    if on >= end:
        return 100
    return max(1, min(99, int((on - start).days / max((end - start).days, 1) * 100)))


def _step_days(first: date, today: date) -> list[date]:
    """Month-ends from the first working month up to the seed day, the seed day last."""
    ends: list[date] = []
    cursor = date(first.year, first.month, 1)
    while True:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        month_end = following - timedelta(days=1)
        if month_end >= today:
            break
        ends.append(month_end)
        cursor = following
    ends = ends[-(_MAX_STEPS - 1) :]
    return [*ends, today]


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT, rounding=ROUND_HALF_UP))


async def _seed_project(session: AsyncSession, project: Project, today: date) -> dict[str, int]:
    schedule = (
        (await session.execute(select(Schedule).where(Schedule.project_id == project.id).order_by(Schedule.created_at)))
        .scalars()
        .first()
    )
    if schedule is None:
        return {}
    if (
        await session.execute(select(ScheduleBaseline.id).where(ScheduleBaseline.project_id == project.id).limit(1))
    ).scalar_one_or_none() is not None:
        return {}

    activities = list(
        (
            await session.execute(
                select(Activity).where(Activity.schedule_id == schedule.id).order_by(Activity.sort_order)
            )
        )
        .scalars()
        .all()
    )
    work = [a for a in activities if a.activity_type != "summary" and _day(a.start_date) and _day(a.end_date)]
    if not work:
        return {}
    first_start = min(_day(a.start_date) for a in work)  # type: ignore[type-var]
    if first_start >= today:
        return {}

    bac = await bill_total(session, project.id)
    if bac <= 0:
        return {}

    # Cost-load the plan by duration, keeping anything the plan already carries.
    weights = {a.id: max((_day(a.end_date) - _day(a.start_date)).days, 1) for a in work}  # type: ignore[operator]
    total_weight = sum(weights.values())
    for act in work:
        if act.cost_planned is None:
            act.cost_planned = (bac * weights[act.id] / total_weight).quantize(_CENT, rounding=ROUND_HALF_UP)
    await session.flush()

    # The baseline is the plan frozen as it stands, before any progress is booked.
    baseline_date = (_day(schedule.start_date) or first_start).isoformat()
    session.add(
        ScheduleBaseline(
            schedule_id=schedule.id,
            project_id=project.id,
            name="Contract baseline",
            baseline_date=baseline_date,
            snapshot_data={
                "activities": [
                    {
                        "id": str(a.id),
                        "wbs_code": a.wbs_code,
                        "name": a.name,
                        "start_date": a.start_date,
                        "end_date": a.end_date,
                        "duration_days": a.duration_days,
                        "cost_planned": str(a.cost_planned) if a.cost_planned is not None else None,
                    }
                    for a in activities
                ],
                "relationships": [],
            },
            is_active=True,
            metadata_={"seed": SEED_MARK},
        )
    )

    from app.modules.schedule.evm_snapshot_service import ScheduleEvmSnapshotService

    evm = ScheduleEvmSnapshotService(session)
    steps = _step_days(max(first_start, today - timedelta(days=366)), today)

    # Series is rewritten, not appended to: a generic cost series seeded earlier belongs to another
    # project's story and cannot sit beside this one in the same periods.
    await session.execute(delete(CostSnapshot).where(CostSnapshot.project_id == project.id))

    updates = 0
    snapshots = 0
    cost_rows = 0
    for index, on in enumerate(steps):
        planned_cost = Decimal("0")
        earned_cost = Decimal("0")
        for position, act in enumerate(work):
            start, end = _day(act.start_date), _day(act.end_date)
            assert start is not None and end is not None
            lag = timedelta(days=_LAG_DAYS[position % len(_LAG_DAYS)])
            planned = _pct(start, end, on)
            actual = _pct(start, end, on - lag)
            cost = act.cost_planned or Decimal("0")
            planned_cost += cost * planned / 100
            earned_cost += cost * actual / 100
            act.progress_pct = str(actual)
            act.status = "completed" if actual >= 100 else "in_progress" if actual > 0 else "planned"
            if actual > 0:
                session.add(
                    ProgressUpdate(
                        project_id=project.id,
                        activity_id=act.id,
                        update_date=on.isoformat(),
                        progress_pct=str(actual),
                        actual_start=start.isoformat(),
                        actual_finish=end.isoformat() if actual >= 100 else None,
                        remaining_duration=str(max(0, int((100 - actual) / 100 * max((end - start).days, 1)))),
                        notes="Monthly progress update",
                        status="approved",
                        metadata_={"seed": SEED_MARK},
                    )
                )
                updates += 1
        await session.flush()
        await evm.record_snapshot(schedule.id, on.isoformat())
        snapshots += 1

        cpi = _COST_INDEX[index % len(_COST_INDEX)]
        actual_cost = earned_cost / cpi
        spi = earned_cost / planned_cost if planned_cost else Decimal("1")
        session.add(
            CostSnapshot(
                project_id=project.id,
                period=f"{on.year:04d}-{on.month:02d}",
                planned_cost=_money(planned_cost),
                earned_value=_money(earned_cost),
                actual_cost=_money(actual_cost),
                forecast_eac=_money(bac / cpi),
                spi=str(spi.quantize(_CENT, rounding=ROUND_HALF_UP)),
                cpi=str(cpi),
                notes="Month-end status",
                metadata_={"seed": SEED_MARK},
            )
        )
        cost_rows += 1

    schedule.data_date = today.isoformat()
    await session.flush()
    return {"baselines": 1, "progress_updates": updates, "evm_snapshots": snapshots, "cost_snapshots": cost_rows}


async def seed_schedule_evm_demo(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[str, int]:
    """Write the schedule history of each demo project that has none.

    Self-guards per project on an existing baseline, and touches demo projects
    only: a baseline and a trail of approved progress state what a job did, and
    inventing them inside somebody's live project is a data incident.
    """
    if not project_ids:
        return {}
    projects = (
        await session.execute(select(Project).where(Project.id.in_(list(dict.fromkeys(project_ids)))))
    ).scalars()
    today = date.today()
    totals: dict[str, int] = {}
    for project in projects.all():
        if not is_demo_project(project.metadata_):
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, project, today)
        except Exception:
            logger.warning("schedule evm demo seed skipped for %s (non-fatal)", project.id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return totals
