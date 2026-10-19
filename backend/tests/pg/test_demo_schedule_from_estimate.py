# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regenerating a demo project's schedule from its bill gives a cost-loaded plan.

The demo is what people are shown first. Its bill carries labour and machine
rows on every position, but their hours are synthetic (``demo_provenance.
productivity_verified = false``), so the plan must say so through its
confidence rather than read as a plan built on real norms. Design:
``docs/design/schedule_from_estimate.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.demo_projects import install_demo_project
from app.modules.boq.models import BOQ
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.service import ScheduleService
from app.modules.schedule.service_4d import ScheduleDashboardService

pytestmark = pytest.mark.asyncio

_DEMO = "residential-berlin"


async def test_a_regenerated_demo_plan_is_cost_loaded_and_honest_about_its_norms(pg_session) -> None:
    result = await install_demo_project(pg_session, _DEMO)
    await pg_session.flush()
    project_id = result["project_id"]
    boq = (await pg_session.execute(select(BOQ).where(BOQ.project_id == project_id))).scalars().first()
    schedule = (await pg_session.execute(select(Schedule).where(Schedule.project_id == project_id))).scalars().first()
    assert boq is not None and schedule is not None, "the demo seeded no bill or no schedule"

    # Read the ids before expire_all: an expired attribute would lazy-load
    # outside the async context.
    schedule_id, boq_id = schedule.id, boq.id
    service = ScheduleService(pg_session)
    preview = await service.preview_generation(schedule_id, boq_id)
    await service.generate_from_boq(schedule_id, boq_id, replace=True)
    pg_session.expire_all()
    rows = list((await pg_session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars())
    tasks = [a for a in rows if a.activity_type == "task"]
    assert tasks

    # Every task is cost-loaded and the plan holds the bill's priced total.
    assert all(a.cost_planned is not None for a in tasks)
    planned = sum((a.cost_planned for a in tasks), Decimal("0"))
    assert planned == Decimal(preview["cost"]["planned_total"])
    if preview["cost"]["unscheduled_positions"] == 0:
        assert planned == Decimal(preview["cost"]["boq_total"])

    # Every task carries a labour row for levelling, and machine rows where
    # the bill has them.
    assert all(
        any(r.get("type") == "labor" for r in a.resources)
        for a in tasks
        if a.metadata_.get("duration_source") != "spans_works"
    )
    assert any(any(r.get("type") == "equipment" for r in a.resources) for a in tasks)

    # Synthetic norms keep the plan out of the high band.
    assert preview["confidence"]["band"] != "high"
    reasons = {reason for a in tasks for reason in a.metadata_["confidence"]["reasons"]}
    assert "unverified_norm" in reasons

    # The S-curve and EVM have something to show the moment the plan exists.
    last_end = max(date.fromisoformat(a.end_date) for a in rows)
    dashboard = await ScheduleDashboardService(pg_session).dashboard(schedule_id, last_end)
    assert dashboard.has_cost_data
    assert dashboard.s_curve_data and Decimal(str(dashboard.s_curve_data[-1]["planned_value"])) > 0

    print(  # noqa: T201 - read in the lane log as the demo's numbers
        f"\n[demo {_DEMO}] tasks={len(tasks)} planned={planned} boq={preview['cost']['boq_total']} "
        f"confidence={preview['confidence']['score']} {preview['confidence']['band']} "
        f"counts={preview['confidence']['counts']} sources="
        f"{sorted({a.metadata_['duration_source'] for a in tasks})} "
        f"checks=errors {preview['validation']['errors']} warnings {preview['validation']['warnings']} "
        f"rules={sorted({f['rule_id'] for f in preview['validation']['findings']})}"
    )
