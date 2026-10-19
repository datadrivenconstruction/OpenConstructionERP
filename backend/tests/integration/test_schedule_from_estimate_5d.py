"""Integration: a schedule generated from the estimate is cost- and resource-loaded.

Before this, generating from a bill wrote ``cost_planned = None`` and
``resources = []`` on every task, so a fresh plan had BAC 0, an empty S-curve
and nothing for resource levelling to level. These tests build real bills
against PostgreSQL and call the service the endpoints call. Design:
``docs/design/schedule_from_estimate.md``.
"""

from __future__ import annotations

import math
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.schedule.evm_math import EvmCostRow, compute_evm_summary
from app.modules.schedule.models import Activity
from app.modules.schedule.schemas import ScheduleCreate
from app.modules.schedule.service import ScheduleService
from app.modules.schedule.service_4d import ScheduleDashboardService
from tests._pg import transactional_session

START = "2026-05-04"  # a Monday


async def _setup(session):  # noqa: ANN001, ANN202
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"est-{uuid.uuid4().hex[:8]}@schedule-5d.io",
        hashed_password="x",
        full_name="Planner",
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name="5D QA", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    service = ScheduleService(session)
    schedule = await service.create_schedule(ScheduleCreate(project_id=project.id, name="Plan", start_date=START))
    boq = BOQ(project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    return service, schedule.id, boq.id


class _Bill:
    def __init__(self, session, boq_id: uuid.UUID) -> None:  # noqa: ANN001
        self.session = session
        self.boq_id = boq_id
        self.order = 0

    async def add(
        self,
        parent: uuid.UUID | None,
        ordinal: str,
        description: str,
        unit: str = "",
        qty: str = "0",
        rate: str = "0",
        total: str | None = None,
        meta: dict | None = None,
    ) -> uuid.UUID:
        from app.modules.boq.models import Position

        self.order += 1
        pos = Position(
            boq_id=self.boq_id,
            parent_id=parent,
            ordinal=ordinal,
            description=description,
            unit=unit,
            quantity=qty,
            unit_rate=rate,
            total=total if total is not None else str(Decimal(qty) * Decimal(rate)),
            metadata_=meta or {},
            sort_order=self.order,
        )
        self.session.add(pos)
        await self.session.flush()
        return pos.id


def _labour(hours: float) -> dict:
    return {"type": "labor", "unit": "hr", "quantity": hours, "name": "Worker"}


def _machine(hours: float) -> dict:
    return {"type": "equipment", "unit": "machine hours", "quantity": hours, "name": "Excavator"}


async def _bill(session, boq_id: uuid.UUID) -> dict[str, uuid.UUID]:  # noqa: ANN001
    bill = _Bill(session, boq_id)
    earth = await bill.add(None, "01", "Earthworks")
    ids = {
        # Labour 0.05 h/m3, machine 0.2 h/m3: the excavator bounds the work.
        "dig": await bill.add(
            earth, "01.001", "Excavation", "m3", "800", "12.37", meta={"resources": [_labour(0.05), _machine(0.2)]}
        ),
        "fill": await bill.add(earth, "01.002", "Backfill", "m3", "150", "9.10", meta={"labor_hours": 0.4}),
    }
    finishes = await bill.add(None, "02", "Finishes")
    ids["plaster"] = await bill.add(finishes, "02.001", "Plaster", "m2", "320", "18.333")
    # Priced with no quantity: nothing to build, so it is left out of the plan
    # and its money is missing from the schedule.
    ids["orphan"] = await bill.add(finishes, "02.002", "Fence allowance", "m", "0", "0", total="250.50")
    return ids


async def _tasks(service: ScheduleService, schedule_id: uuid.UUID) -> list[Activity]:
    service.session.expire_all()
    rows, _ = await service.list_activities_for_schedule(schedule_id, limit=10_000)
    return rows


@pytest.mark.asyncio
async def test_generation_cost_loads_every_task_with_its_position_total() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        await _bill(session, boq_id)
        await service.generate_from_boq(schedule_id, boq_id)
        rows = await _tasks(service, schedule_id)

        tasks = [a for a in rows if a.activity_type == "task"]
        assert len(tasks) == 3
        by_name = {a.name: a for a in tasks}
        assert by_name["Excavation"].cost_planned == Decimal("9896.00")
        assert by_name["Backfill"].cost_planned == Decimal("1365.00")
        # 320 x 18.333 = 5866.56, exactly, not through a float.
        assert by_name["Plaster"].cost_planned == Decimal("5866.56")
        # Summaries and milestones carry no money: BAC is a plain sum and a
        # rolled-up summary would count its children twice.
        assert all(a.cost_planned is None for a in rows if a.activity_type != "task")
        assert sum(a.cost_planned for a in tasks) == Decimal("17127.56")


@pytest.mark.asyncio
async def test_s_curve_and_evm_show_the_bill_total_on_a_fresh_plan() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        await _bill(session, boq_id)
        await service.generate_from_boq(schedule_id, boq_id)
        rows = await _tasks(service, schedule_id)
        last_end = max(date.fromisoformat(a.end_date) for a in rows)

        dashboard = await ScheduleDashboardService(session).dashboard(schedule_id, last_end)
        assert dashboard.has_cost_data
        assert dashboard.s_curve_data, "a cost-loaded plan has an S-curve"
        last = dashboard.s_curve_data[-1]
        assert Decimal(str(last["planned_value"])) > 0
        if last["date"] == last_end.isoformat():
            # Sampled on the last day, the curve has earned the whole bill.
            assert Decimal(str(last["planned_value"])) == Decimal("17127.56")

        summary = compute_evm_summary(
            [EvmCostRow(a.start_date, a.end_date, a.cost_planned, a.cost_actual, a.progress_pct) for a in rows],
            last_end,
        )
        assert summary.budget_at_completion == Decimal("17127.56")
        assert summary.planned_value == Decimal("17127.56")


@pytest.mark.asyncio
async def test_tasks_carry_labour_and_machine_resources_for_levelling() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        await _bill(session, boq_id)
        await service.generate_from_boq(schedule_id, boq_id)
        by_name = {a.name: a for a in await _tasks(service, schedule_id)}

        dig = by_name["Excavation"]
        kinds = {r["type"]: r for r in dig.resources}
        assert kinds["labor"]["name"] == "Labour"
        assert kinds["labor"]["count"] >= 1
        assert kinds["labor"]["hours"] == pytest.approx(40.0)
        assert kinds["equipment"]["name"] == "Machines"
        assert kinds["equipment"]["hours"] == pytest.approx(160.0)
        assert dig.metadata_["machine_hours_total"] == pytest.approx(160.0)
        # Levelling reads {name: count} off these rows.
        required = {r["name"]: int(r.get("count", 1)) for r in dig.resources}
        assert set(required) == {"Labour", "Machines"}

        fill = by_name["Backfill"]
        assert [r["type"] for r in fill.resources] == ["labor"]
        assert fill.metadata_["labor_hours_total"] == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_machine_hours_set_the_duration_when_they_outlast_the_labour() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        await _bill(session, boq_id)
        await service.generate_from_boq(schedule_id, boq_id)
        dig = {a.name: a for a in await _tasks(service, schedule_id)}["Excavation"]

        assert dig.metadata_["duration_source"] == "machine_hours"
        # 160 machine hours, one machine, 8 h a day, plus 10 % mobilisation,
        # to calendar days and back onto the five-day week: 23 working days.
        # The labour alone (40 h) would be about six.
        expected = math.ceil(round(160 / 8 * 1.1 * 7 / 5) * 5 / 7)
        assert expected == 23
        assert dig.duration_days == expected
        assert dig.metadata_["norm_days"] == expected
        assert dig.metadata_["confidence"]["band"] in {"high", "medium"}
        assert "duration_machine_hours" in dig.metadata_["confidence"]["reasons"]


@pytest.mark.asyncio
async def test_preview_reports_confidence_cost_and_the_checks() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        ids = await _bill(session, boq_id)
        preview = await service.preview_generation(schedule_id, boq_id)

        cost = preview["cost"]
        assert cost["currency"] == "EUR"
        assert Decimal(cost["boq_total"]) == Decimal("17378.06")
        assert Decimal(cost["planned_total"]) == Decimal("17127.56")
        assert cost["unscheduled_positions"] == 1

        confidence = preview["confidence"]
        assert 0 < confidence["score"] < 1
        assert sum(confidence["counts"].values()) == 3
        # The plaster has no norm: a guess from the unit table, listed for review.
        assert [row["position_id"] for row in confidence["low"]] == [str(ids["plaster"])]

        validation = preview["validation"]
        assert set(validation["rule_sets"]) >= {"schedule_quality", "schedule_5d"}
        fired = {f["rule_id"] for f in validation["findings"]}
        assert "schedule_5d.cost_reconciliation" in fired
        coverage = [f for f in validation["findings"] if f["rule_id"] == "schedule_5d.boq_coverage"]
        assert [f["position_id"] for f in coverage] == [str(ids["orphan"])]
        assert coverage[0]["ordinal"] == "02.002"
        # Errors come first.
        assert validation["findings"][0]["severity"] == "error"


@pytest.mark.asyncio
async def test_confirmed_generation_records_confidence_cost_and_check_counts() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        await _bill(session, boq_id)
        await service.generate_from_boq(schedule_id, boq_id)
        session.expire_all()
        schedule = await service.get_schedule(schedule_id)
        recorded = schedule.metadata_["boq_generation"]

        assert recorded["confidence"]["counts"]["low"] == 1
        assert Decimal(recorded["cost"]["planned_total"]) == Decimal("17127.56")
        assert recorded["validation"]["errors"] >= 1
        assert "findings" not in recorded["validation"]


@pytest.mark.asyncio
async def test_a_bill_fully_scheduled_reconciles() -> None:
    async with transactional_session() as session:
        service, schedule_id, boq_id = await _setup(session)
        bill = _Bill(session, boq_id)
        section = await bill.add(None, "01", "Structure")
        await bill.add(section, "01.001", "Concrete", "m3", "40", "150", meta={"labor_hours": 2, "workers_per_unit": 4})
        preview = await service.preview_generation(schedule_id, boq_id)

        fired = {f["rule_id"] for f in preview["validation"]["findings"]}
        assert "schedule_5d.cost_reconciliation" not in fired
        assert "schedule_5d.boq_coverage" not in fired
        assert preview["cost"]["unscheduled_positions"] == 0
        assert preview["confidence"]["band"] == "high"
