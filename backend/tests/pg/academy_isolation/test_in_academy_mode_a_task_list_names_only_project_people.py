# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a task list names only the project's people.

The task list turns every ``responsible_id`` into the user's full name or
email, whoever they are. The task gate (E2) stops a learner writing another
learner's id there, but a row written before the gate, or by a path around it,
would still print that learner's name. In academy mode a name is resolved only
for a user who is in the task's project; any other id stays unresolved, which
the list already shows as an unknown assignee.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest

from app.modules.tasks.models import Task
from app.modules.tasks.service import TaskService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice Owner")
    bob = await make_user(session, name="Bob Outsider")
    carol = await make_user(session, name="Carol Member")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    tasks = []
    for person in (bob, carol, alice):
        task = Task(
            project_id=project.id,
            task_type="task",
            title=f"For {person.full_name}",
            responsible_id=str(person.id),
            status="open",
            created_by=str(alice.id),
        )
        session.add(task)
        tasks.append(task)
    await session.flush()
    return alice, bob, carol, tasks


async def test_academy_on_an_outsider_on_an_old_task_is_not_named(pg_session, academy) -> None:
    academy(True)
    alice, _bob, carol, tasks = await _setup(pg_session)

    names = await TaskService(pg_session).resolve_assignee_names(tasks)

    assert names == {str(carol.id): "Carol Member", str(alice.id): "Alice Owner"}


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    alice, bob, carol, tasks = await _setup(pg_session)

    names = await TaskService(pg_session).resolve_assignee_names(tasks)

    assert names == {str(bob.id): "Bob Outsider", str(carol.id): "Carol Member", str(alice.id): "Alice Owner"}
