# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: collaboration locks stay project scoped, academy or not (regression for E4).

A lock names its holder, so reading or planting one on another learner's row
would leak who is editing what. The lock router already resolves every entity
to its project and runs ``verify_project_access`` before acquire, heartbeat and
the entity read. Nothing was changed for the academy; this file pins that the
gate holds with the flag on and off alike, and that the owner of the row still
locks it, so a gate that refused everyone would fail here too.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.collaboration_locks.router import acquire_lock, get_entity_lock, heartbeat_lock
from app.modules.collaboration_locks.schemas import CollabLockAcquire, CollabLockHeartbeat
from app.modules.collaboration_locks.service import CollabLockService
from app.modules.tasks.models import Task
from tests.pg.academy_isolation.rows import make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _task_of(session, owner) -> Task:
    project = await make_project(session, owner)
    task = Task(project_id=project.id, task_type="task", title="Formwork", created_by=str(owner.id))
    session.add(task)
    await session.flush()
    return task


@pytest.mark.parametrize("academy_on", [True, False], ids=["academy_on", "academy_off"])
async def test_a_learner_cannot_read_or_take_a_lock_in_another_learners_project(
    pg_session, academy, events, academy_on: bool
) -> None:
    academy(academy_on)
    alice = await make_user(pg_session, name="Alice")
    bob = await make_user(pg_session, name="Bob")
    task = await _task_of(pg_session, alice)
    service = CollabLockService(pg_session)

    with pytest.raises(HTTPException) as planted:
        await acquire_lock(CollabLockAcquire(entity_type="task", entity_id=task.id), str(bob.id), service)
    assert planted.value.status_code == 404

    held = await acquire_lock(CollabLockAcquire(entity_type="task", entity_id=task.id), str(alice.id), service)
    assert str(held.user_id) == str(alice.id)

    with pytest.raises(HTTPException) as read:
        await get_entity_lock(str(bob.id), entity_type="task", entity_id=str(task.id), service=service)
    assert read.value.status_code == 404
    with pytest.raises(HTTPException) as renewed:
        await heartbeat_lock(held.id, CollabLockHeartbeat(), str(bob.id), service)
    assert renewed.value.status_code == 404

    seen = await get_entity_lock(str(alice.id), entity_type="task", entity_id=str(task.id), service=service)
    assert seen is not None and seen.id == held.id
