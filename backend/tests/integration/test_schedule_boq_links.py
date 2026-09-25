"""Integration: linking BOQ positions to a schedule activity by hand.

The activity edit panel lets a planner attach positions to an activity they
created themselves. The ids live in a JSON list with no foreign key, so the
service has to be the one that keeps a link inside the schedule's own project,
and the panel needs a route to take a link off again.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.schedule import router as schedule_router
from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate, LinkPositionRequest, ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session


async def _position(session, project_id: uuid.UUID) -> uuid.UUID:  # noqa: ANN001
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name=f"BOQ {uuid.uuid4().hex[:6]}")
    session.add(boq)
    await session.flush()
    pos = Position(
        boq_id=boq.id,
        ordinal="01.001",
        description="Strip foundation",
        unit="m3",
        quantity="12",
        unit_rate="100",
        total="1200",
    )
    session.add(pos)
    await session.flush()
    return pos.id


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_activity_links_only_positions_of_its_own_project() -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        project_id = uuid.uuid4()
        schedule = await service.create_schedule(ScheduleCreate(project_id=project_id, name="Links QA"))
        schedule_id = schedule.id
        activity = await service.create_activity(
            ActivityCreate(schedule_id=schedule_id, name="Foundations", start_date="2026-05-04", end_date="2026-05-08")
        )
        activity_id = activity.id
        own = await _position(session, project_id)
        foreign = await _position(session, uuid.uuid4())

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        common = {"_user_id": uuid.uuid4(), "payload": {"role": "admin"}, "session": session, "service": service}
        try:
            linked = await schedule_router.link_boq_position(
                activity_id=activity_id, body=LinkPositionRequest(boq_position_id=own), **common
            )
            assert linked.boq_position_ids == [str(own)]

            with pytest.raises(HTTPException) as exc:
                await schedule_router.link_boq_position(
                    activity_id=activity_id, body=LinkPositionRequest(boq_position_id=foreign), **common
                )
            assert exc.value.status_code == 404

            with pytest.raises(HTTPException) as exc:
                await service.update_activity(activity_id, ActivityUpdate(boq_position_ids=[own, foreign]))
            assert exc.value.status_code == 404

            with pytest.raises(HTTPException) as exc:
                await service.create_activity(
                    ActivityCreate(
                        schedule_id=schedule_id,
                        name="Other",
                        start_date="2026-05-04",
                        end_date="2026-05-04",
                        boq_position_ids=[foreign],
                    )
                )
            assert exc.value.status_code == 404

            unlinked = await schedule_router.unlink_boq_position(activity_id=activity_id, boq_position_id=own, **common)
            assert unlinked.boq_position_ids == []
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]
