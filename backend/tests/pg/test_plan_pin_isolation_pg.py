# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan pins on PostgreSQL: a user outside a project can neither read nor change its pins."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.documents.models import Document
from app.modules.plan_room.models import PlanPin
from app.modules.plan_room.permissions import register_plan_room_permissions
from app.modules.plan_room.router import router
from app.modules.plan_room.validators import register_plan_room_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

PREFIX = "/v1/plan-room"


@pytest_asyncio.fixture
async def world():
    register_plan_room_permissions()
    register_plan_room_validation_rules()
    async with transactional_session() as session:
        users = []
        for _ in range(2):
            user = User(email=f"pin-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", role="editor")
            session.add(user)
            users.append(user)
        await session.flush()
        owner, outsider = users
        project = Project(name="Pins", owner_id=owner.id)
        session.add(project)
        await session.flush()
        doc = Document(project_id=project.id, name="A-1.pdf")
        session.add(doc)
        await session.flush()
        pin = PlanPin(project_id=project.id, document_id=str(doc.id), page=1, x=0.1, y=0.2, note="mine")
        session.add(pin)
        await session.flush()
        await session.commit()
        yield session, owner, outsider, project, doc, pin


def _client(session, user: User) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user.id), "role": "editor"}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_outsider_sees_and_changes_nothing(world) -> None:
    session, owner, outsider, project, doc, pin = world
    async with _client(session, owner) as mine:
        listed = await mine.get(f"{PREFIX}/pins/", params={"project_id": str(project.id)})
        assert listed.status_code == 200 and listed.json()["total"] == 1

    async with _client(session, outsider) as theirs:
        params = {"project_id": str(project.id)}
        assert (await theirs.get(f"{PREFIX}/pins/", params=params)).status_code == 404
        assert (await theirs.get(f"{PREFIX}/pins/by-target/note/{uuid.uuid4()}", params=params)).status_code == 404
        assert (await theirs.patch(f"{PREFIX}/pins/{pin.id}", json={"x": 0.9})).status_code == 404
        assert (await theirs.delete(f"{PREFIX}/pins/{pin.id}")).status_code == 404
        body = {"project_id": str(project.id), "document_id": str(doc.id), "page": 1, "x": 0.5, "y": 0.5, "note": "x"}
        assert (await theirs.post(f"{PREFIX}/pins/", json=body)).status_code == 404

    await session.refresh(pin)
    assert (pin.x, pin.note) == (0.1, "mine")
