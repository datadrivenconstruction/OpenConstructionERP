"""Work-order BOQ links stay in the owning activity's project."""

import copy
import uuid

import pytest
from sqlalchemy import inspect, select

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, WorkOrder
from app.modules.schedule.schemas import WorkOrderCreate
from app.modules.users.models import User
from tests.integration.test_schedule_archive_lifecycle import api, published  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.tenant_isolation
@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "association", ["same_owner_other_project", "foreign_owner", "missing", "matching", "null", "omit"]
)
async def test_work_order_boq_position_belongs_to_activity_project(method, association):
    async with api() as (client, session, service, schedule, project, _payload):
        activity = Activity(schedule_id=schedule.id, name="Scoped work", start_date="2026-10-01", end_date="2026-10-01")
        own_boq = BOQ(project_id=project.id, name="Own bill")
        session.add_all([activity, own_boq])
        await session.flush()
        own_position = Position(boq_id=own_boq.id, ordinal="1", description="Own work", unit="m")
        session.add(own_position)
        await session.flush()
        position_id = own_position.id
        if association in {"same_owner_other_project", "foreign_owner"}:
            owner_id = project.owner_id
            if association == "foreign_owner":
                owner = User(
                    email=f"work-order-{uuid.uuid4()}@example.test",
                    full_name="Other",
                    hashed_password="x",
                    role="editor",
                )
                session.add(owner)
                await session.flush()
                owner_id = owner.id
            other_project = Project(name="Other bill project", owner_id=owner_id)
            session.add(other_project)
            await session.flush()
            other_boq = BOQ(project_id=other_project.id, name="Other bill")
            session.add(other_boq)
            await session.flush()
            other_position = Position(boq_id=other_boq.id, ordinal="1", description="Other work", unit="m")
            session.add(other_position)
            await session.flush()
            position_id = other_position.id
        elif association == "missing":
            position_id = uuid.uuid4()
        elif association == "null":
            position_id = None

        body = {
            "code": "Changed",
            "description": "Changed description",
            "planned_cost": "77.50",
            "metadata": {"new": True},
        }
        if association != "omit":
            body["boq_position_id"] = str(position_id) if position_id else None
        if method == "PATCH":
            work_order = await service.create_work_order(
                WorkOrderCreate(
                    activity_id=activity.id,
                    code="Original",
                    boq_position_id=own_position.id,
                    description="Original description",
                    planned_cost="12.25",
                    metadata={"preserved": True},
                )
            )
            before = {a.key: copy.deepcopy(getattr(work_order, a.key)) for a in inspect(WorkOrder).column_attrs}
            endpoint = f"/schedule/work-orders/{work_order.id}"
        else:
            endpoint = f"/schedule/activities/{activity.id}/work-orders/"
        response = await client.request(method, endpoint, json=body)
        valid = association in {"matching", "null", "omit"}
        assert response.status_code == ((201 if method == "POST" else 200) if valid else 404), response.text
        rows = list((await session.scalars(select(WorkOrder).where(WorkOrder.activity_id == activity.id))).all())
        assert len(rows) == (1 if method == "PATCH" or valid else 0)
        if not valid:
            assert response.json() == {"detail": "BOQ position not found in this project"}
            if method == "PATCH":
                await session.refresh(work_order)
                assert {a.key: getattr(work_order, a.key) for a in inspect(WorkOrder).column_attrs} == before
        else:
            await session.refresh(rows[0])
            expected_id = (
                own_position.id
                if association == "omit" and method == "PATCH"
                else (None if association in {"null", "omit"} else own_position.id)
            )
            assert rows[0].boq_position_id == expected_id
            assert rows[0].code == "Changed"
            assert rows[0].description == "Changed description"
            assert rows[0].planned_cost == "77.50"
            if method == "PATCH":
                assert rows[0].metadata_ == {"preserved": True, "new": True}
