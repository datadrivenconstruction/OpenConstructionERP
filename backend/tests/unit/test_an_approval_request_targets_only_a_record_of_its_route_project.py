# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An approval request may only target a record of its route's project.

A request stores its target as ``entity_type`` + ``entity_id`` strings, and
submit used to check only access to the route's own project. An editor of
project A could file a request on A's route against a bill of project B and
approve it, writing "bill X approved" into the trail of a record they cannot
see. Submit now resolves the record through a registry and requires it to
exist, to match the route's type and to belong to the route's project; a
template route (no project) accepts only records of a project the caller can
access.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.enterprise_workflows.schemas import ApprovalRequestCreate, WorkflowCreate
from app.modules.enterprise_workflows.service import WorkflowService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

_STEPS = [{"name": "s1", "action_type": "approve", "role": "editor"}]


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, role: str = "editor") -> uuid.UUID:
    from app.modules.users.models import User

    user = User(email=f"ew-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="U", role=role)
    session.add(user)
    await session.flush()
    return user.id


async def _project_with_bill(session: AsyncSession, owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    project = Project(name="P", owner_id=owner_id)
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    return project.id, boq.id


async def _route(service: WorkflowService, user_id: uuid.UUID, project_id: uuid.UUID | None, entity_type: str = "boq"):
    return await service.create_workflow(
        WorkflowCreate(project_id=project_id, entity_type=entity_type, name="route", steps=_STEPS),
        user_id=str(user_id),
    )


async def _submit(service: WorkflowService, wf_id: uuid.UUID, user_id: uuid.UUID, entity_id, entity_type="boq"):
    return await service.submit_request(
        ApprovalRequestCreate(workflow_id=wf_id, entity_type=entity_type, entity_id=str(entity_id)),
        user_id=str(user_id),
    )


async def test_a_record_of_the_route_project_is_accepted(session: AsyncSession) -> None:
    editor = await _user(session)
    project_a, bill_a = await _project_with_bill(session, editor)
    service = WorkflowService(session)
    wf = await _route(service, editor, project_a)

    req = await _submit(service, wf.id, editor, bill_a)

    assert req.status == "pending"


async def test_a_record_of_another_project_is_refused_as_not_found(session: AsyncSession) -> None:
    editor = await _user(session)
    stranger = await _user(session)
    project_a, _ = await _project_with_bill(session, editor)
    _, bill_b = await _project_with_bill(session, stranger)
    service = WorkflowService(session)
    wf = await _route(service, editor, project_a)

    with pytest.raises(HTTPException) as exc:
        await _submit(service, wf.id, editor, bill_b)

    assert exc.value.status_code == 404


async def test_a_record_that_does_not_exist_is_refused(session: AsyncSession) -> None:
    editor = await _user(session)
    project_a, _ = await _project_with_bill(session, editor)
    service = WorkflowService(session)
    wf = await _route(service, editor, project_a)

    with pytest.raises(HTTPException) as exc:
        await _submit(service, wf.id, editor, uuid.uuid4())

    assert exc.value.status_code == 404


async def test_a_type_other_than_the_route_type_is_refused(session: AsyncSession) -> None:
    editor = await _user(session)
    project_a, bill_a = await _project_with_bill(session, editor)
    service = WorkflowService(session)
    wf = await _route(service, editor, project_a, entity_type="invoice")

    with pytest.raises(HTTPException) as exc:
        await _submit(service, wf.id, editor, bill_a, entity_type="boq")

    assert exc.value.status_code == 400


async def test_an_unregistered_type_is_refused(session: AsyncSession) -> None:
    editor = await _user(session)
    project_a, bill_a = await _project_with_bill(session, editor)
    service = WorkflowService(session)
    wf = await _route(service, editor, project_a, entity_type="unicorn")

    with pytest.raises(HTTPException) as exc:
        await _submit(service, wf.id, editor, bill_a, entity_type="unicorn")

    assert exc.value.status_code == 400


async def test_a_template_route_refuses_a_record_the_caller_cannot_access(session: AsyncSession) -> None:
    editor = await _user(session)
    stranger = await _user(session)
    _, bill_b = await _project_with_bill(session, stranger)
    service = WorkflowService(session)
    wf = await _route(service, editor, None)

    with pytest.raises(HTTPException) as exc:
        await _submit(service, wf.id, editor, bill_b)

    assert exc.value.status_code == 404


async def test_a_template_route_accepts_a_record_of_the_callers_own_project(session: AsyncSession) -> None:
    editor = await _user(session)
    _, bill_a = await _project_with_bill(session, editor)
    service = WorkflowService(session)
    wf = await _route(service, editor, None)

    req = await _submit(service, wf.id, editor, bill_a)

    assert req.status == "pending"
