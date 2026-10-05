# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a task cannot be assigned outside its project (gate E2).

``responsible_id`` and ``persons_involved`` are user ids taken from the request
body, and a new responsible user gets ``task.assigned``, which the
notifications module turns into a notification. Nothing checked that the user
belongs to the task's project, so on an academy box one learner could assign a
task to another and push it into their "my tasks" and their inbox. In academy
mode create, update and the bulk assign refuse a person outside the project
with 422 ``user_not_in_project``.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.core.bulk_ops import BulkAssignRequest
from app.modules.tasks.models import Task
from app.modules.tasks.router import batch_assign_tasks
from app.modules.tasks.schemas import TaskCreate, TaskUpdate
from app.modules.tasks.service import TaskService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

ASSIGNED = "task.assigned"


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return project, alice, bob, carol


async def _task_count(session, project) -> int:
    return (await session.execute(select(func.count(Task.id)).where(Task.project_id == project.id))).scalar_one()


def _assigned(events) -> list[str]:
    return [data["responsible_id"] for name, data in events if name == ASSIGNED]


def _refused(caught) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT


async def test_responsible_outside_project_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol = await _setup(pg_session)
    service = TaskService(pg_session)

    with pytest.raises(HTTPException) as caught:
        await service.create_task(
            TaskCreate(project_id=project.id, task_type="task", title="Pour slab", responsible_id=str(bob.id)),
            user_id=str(alice.id),
        )
    _refused(caught)
    assert await _task_count(pg_session, project) == 0

    task = await service.create_task(
        TaskCreate(project_id=project.id, task_type="task", title="Pour slab"), user_id=str(alice.id)
    )
    with pytest.raises(HTTPException) as on_update:
        await service.update_task(task.id, TaskUpdate(responsible_id=str(bob.id)), current_user_id=str(alice.id))
    _refused(on_update)

    with pytest.raises(HTTPException) as on_batch:
        await batch_assign_tasks(
            body=BulkAssignRequest(ids=[task.id], assignee_id=str(bob.id)), user_id=str(alice.id), session=pg_session
        )
    _refused(on_batch)
    await pg_session.refresh(task)
    assert task.responsible_id is None
    assert _assigned(events) == []


async def test_persons_involved_outside_project_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, carol = await _setup(pg_session)
    service = TaskService(pg_session)

    with pytest.raises(HTTPException) as caught:
        await service.create_task(
            TaskCreate(
                project_id=project.id, task_type="task", title="Survey", persons_involved=[str(carol.id), str(bob.id)]
            ),
            user_id=str(alice.id),
        )
    _refused(caught)

    task = await service.create_task(
        TaskCreate(project_id=project.id, task_type="task", title="Survey", persons_involved=[str(carol.id)]),
        user_id=str(alice.id),
    )
    with pytest.raises(HTTPException) as on_update:
        await service.update_task(
            task.id, TaskUpdate(persons_involved=[str(carol.id), str(bob.id)]), current_user_id=str(alice.id)
        )
    _refused(on_update)


async def test_academy_on_a_project_member_can_still_be_assigned(pg_session, academy, events) -> None:
    academy(True)
    project, alice, _bob, carol = await _setup(pg_session)
    service = TaskService(pg_session)

    task = await service.create_task(
        TaskCreate(
            project_id=project.id,
            task_type="task",
            title="Check rebar",
            responsible_id=str(carol.id),
            persons_involved=[str(alice.id), str(carol.id)],
        ),
        user_id=str(alice.id),
    )
    assert str(task.responsible_id) == str(carol.id)
    await service.update_task(task.id, TaskUpdate(responsible_id=str(alice.id)), current_user_id=str(alice.id))
    result = await batch_assign_tasks(
        body=BulkAssignRequest(ids=[task.id], assignee_id=str(carol.id)), user_id=str(alice.id), session=pg_session
    )
    assert result["updated"] == 1
    assert _assigned(events) == [str(carol.id), str(alice.id)]


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, _carol = await _setup(pg_session)
    service = TaskService(pg_session)

    task = await service.create_task(
        TaskCreate(
            project_id=project.id,
            task_type="task",
            title="Pour slab",
            responsible_id=str(bob.id),
            persons_involved=[str(bob.id)],
        ),
        user_id=str(alice.id),
    )
    assert str(task.responsible_id) == str(bob.id)
    other = await service.create_task(
        TaskCreate(project_id=project.id, task_type="task", title="Strip"), user_id=str(alice.id)
    )
    await service.update_task(other.id, TaskUpdate(responsible_id=str(bob.id)), current_user_id=str(alice.id))
    result = await batch_assign_tasks(
        body=BulkAssignRequest(ids=[task.id, other.id], assignee_id=str(bob.id)),
        user_id=str(alice.id),
        session=pg_session,
    )
    assert result["updated"] == 2
    assert _assigned(events) == [str(bob.id), str(bob.id)]
