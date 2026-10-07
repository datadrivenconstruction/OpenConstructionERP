"""Work-order assembly references use established assembly owner/admin access."""

import copy
import uuid

import pytest
from sqlalchemy import inspect, select

from app.modules.assemblies.models import Assembly
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, WorkOrder
from app.modules.schedule.schemas import WorkOrderCreate
from tests.integration.test_schedule_archive_lifecycle import api, published  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.tenant_isolation
@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "role,association",
    [
        ("editor", "own_global"),
        ("editor", "own_other_project"),
        ("editor", "foreign"),
        ("editor", "ownerless"),
        ("editor", "missing"),
        ("editor", "null"),
        ("editor", "omit"),
        ("admin", "foreign"),
        ("admin", "ownerless"),
        ("admin", "missing"),
    ],
)
async def test_work_order_assembly_access_before_mutation(method, role, association):
    async with api(role=role) as (client, session, service, schedule, project, _payload):
        activity = Activity(
            schedule_id=schedule.id, name="Assembly work", start_date="2026-10-01", end_date="2026-10-01"
        )
        own = Assembly(code=f"own-{uuid.uuid4()}", name="Own template", unit="m", owner_id=project.owner_id)
        session.add_all([activity, own])
        await session.flush()
        target_id = own.id
        if association in {"foreign", "ownerless", "own_other_project"}:
            other_project = Project(name="Other assembly project", owner_id=project.owner_id)
            session.add(other_project)
            await session.flush()
            target = Assembly(
                code=f"target-{uuid.uuid4()}",
                name="Target template",
                unit="m",
                owner_id=(project.owner_id if association == "own_other_project" else uuid.uuid4())
                if association != "ownerless"
                else None,
                project_id=other_project.id if association == "own_other_project" else None,
                is_template=True,
            )
            session.add(target)
            await session.flush()
            target_id = target.id
        elif association == "missing":
            target_id = uuid.uuid4()
        elif association == "null":
            target_id = None

        body = {"code": "Changed", "description": "Changed", "planned_cost": "77.50", "metadata": {"new": True}}
        if association != "omit":
            body["assembly_id"] = str(target_id) if target_id else None
        if method == "PATCH":
            work_order = await service.create_work_order(
                WorkOrderCreate(
                    activity_id=activity.id,
                    assembly_id=own.id,
                    code="Original",
                    description="Original",
                    planned_cost="12.25",
                    metadata={"preserved": True},
                )
            )
            before = {a.key: copy.deepcopy(getattr(work_order, a.key)) for a in inspect(WorkOrder).column_attrs}
            endpoint = f"/schedule/work-orders/{work_order.id}"
        else:
            endpoint = f"/schedule/activities/{activity.id}/work-orders/"
        response = await client.request(method, endpoint, json=body)
        valid = association != "missing" and (role == "admin" or association not in {"foreign", "ownerless"})
        assert response.status_code == ((201 if method == "POST" else 200) if valid else 404), response.text
        rows = list((await session.scalars(select(WorkOrder).where(WorkOrder.activity_id == activity.id))).all())
        assert len(rows) == (1 if method == "PATCH" or valid else 0)
        if not valid:
            assert response.json() == {"detail": "Assembly not found"}
            if method == "PATCH":
                await session.refresh(work_order)
                assert {a.key: getattr(work_order, a.key) for a in inspect(WorkOrder).column_attrs} == before
        else:
            await session.refresh(rows[0])
            expected_id = (
                own.id
                if association == "omit" and method == "PATCH"
                else (None if association == "omit" else target_id)
            )
            assert rows[0].assembly_id == expected_id
            assert rows[0].code == "Changed"
            assert rows[0].planned_cost == "77.50"
