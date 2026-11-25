"""Integration: BIM elements -> quantity map -> BOQ -> schedule -> 5D, and a quantity change ripples through.

Worked example: two new walls of 12.5 and 7.5 m2 map to one auto-created BOQ
position of 20 m2 at 10 EUR/m2 (200 EUR). A schedule is generated from the
bill and a 5D cost model from the same bill. The estimator then raises the
quantity to 60 m2: the wall work goes from 16 to 48 hours for a gang of three,
one working day to two, and
the cost model's estimate goes from 200 to 600 EUR.

The bill's events are delivered after commit to handlers that open their own
session; inside this test's rolled-back transaction they are invoked directly
on the test session, and the subscription itself is asserted.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests._pg import transactional_session

START = "2026-05-04"  # a Monday


async def _project(session):  # noqa: ANN001, ANN202
    from app.modules.bim_hub.models import BIMElement, BIMModel, BIMQuantityMap
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(id=uuid.uuid4(), email=f"c-{uuid.uuid4().hex[:8]}@chain.io", hashed_password="x", full_name="C")
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Chain", description="", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Bill", description="", status="draft", is_locked=False)
    model = BIMModel(project_id=project.id, name="house.rvt", status="ready")
    session.add_all([boq, model])
    await session.flush()
    for phase, area in (("Existing", 30.0), ("New", 12.5), ("New", 7.5)):
        session.add(
            BIMElement(
                model_id=model.id,
                stable_id=uuid.uuid4().hex,
                element_type="Walls",
                properties={"category": "Walls", "phase created": phase},
                quantities={"area": area},
            )
        )
    session.add(
        BIMQuantityMap(
            project_id=project.id,
            name="New walls",
            element_type_filter="Wall*",
            property_filter={"phase created": "New"},
            quantity_source="area",
            multiplier="1",
            waste_factor_pct="0",
            unit="m2",
            boq_target={"auto_create": True, "unit_rate": "10"},
            is_active=True,
        )
    )
    await session.flush()
    return project, boq, model


async def _estimate(session, project_id: uuid.UUID) -> Decimal:  # noqa: ANN001
    from app.modules.costmodel.models import CostLine

    rows = (
        (await session.execute(select(CostLine.estimate_amount).where(CostLine.project_id == project_id)))
        .scalars()
        .all()
    )
    return sum((Decimal(str(r)) for r in rows), Decimal(0))


@pytest.mark.asyncio
async def test_a_quantity_change_moves_the_schedule_and_the_cost_model() -> None:
    from app.core.events import event_bus
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest
    from app.modules.bim_hub.service import BIMHubService
    from app.modules.boq.models import Position
    from app.modules.boq.schemas import PositionUpdate
    from app.modules.boq.service import BOQService
    from app.modules.costmodel.service import CostSpineService
    from app.modules.costmodel.structure_service import CostStructureService
    from app.modules.schedule import events as schedule_events
    from app.modules.schedule.boq_followup import follow_position_quantity
    from app.modules.schedule.models import Activity
    from app.modules.schedule.schemas import ScheduleCreate
    from app.modules.schedule.service import ScheduleService

    async with transactional_session() as session:
        project, boq, model = await _project(session)
        project_id, boq_id = project.id, boq.id

        # BIM -> quantity map -> BOQ position.
        bim = BIMHubService(session)
        preview = await bim.apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id))
        applied = await bim.apply_quantity_maps(
            QuantityMapApplyRequest(model_id=model.id, dry_run=False, preview_fingerprint=preview.preview_fingerprint)
        )
        assert applied.positions_created == 1
        [position] = (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all()
        assert Decimal(position.quantity) == Decimal("20")
        position_id = position.id

        # BOQ -> schedule, BOQ -> 5D cost model.
        schedule_service = ScheduleService(session)
        schedule = await schedule_service.create_schedule(
            ScheduleCreate(project_id=project.id, name="Plan", start_date=START)
        )
        schedule_id = schedule.id
        await schedule_service.generate_from_boq(schedule_id, boq_id, start_date=date.fromisoformat(START))
        await CostSpineService(session).generate_from_boq(project_id, boq_id)
        assert await _estimate(session, project_id) == Decimal("200")

        session.expire_all()
        acts = (await session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars().all()
        [task] = [a for a in acts if str(position_id) in [str(p) for p in (a.boq_position_ids or [])]]
        days_before, end_before, task_id = task.duration_days, task.end_date, task.id

        # The estimator triples the quantity.
        await BOQService(session).update_position(position_id, PositionUpdate(quantity=60))
        await session.flush()

        handlers = event_bus._handlers.get("boq.position.updated", [])  # noqa: SLF001
        assert schedule_events._on_bill_position_updated in handlers
        changed = await follow_position_quantity(session, position_id, "20")
        await CostStructureService(session).recompute_after_bill_change({position_id}, set())

        session.expire_all()
        task = await session.get(Activity, task_id)
        assert changed == [task_id]
        # 48 crew hours for a gang of three on an 8-hour day: two days, as a
        # fresh generation at 60 m2 would plan it.
        assert days_before == 1
        assert task.duration_days == 2
        assert task.end_date > end_before
        assert await _estimate(session, project_id) == Decimal("600")
