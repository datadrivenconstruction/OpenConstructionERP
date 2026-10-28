# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may see and change the project handbook and the data room, over HTTP against PostgreSQL.

A stranger from another tenant sees 404 on every project route, a project member with the editor role reads
and writes text but cannot approve, and the approver cannot be the submitter.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_handbook.permissions import register_project_handbook_permissions
from app.modules.project_handbook.router import router
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World
from tests.pg.project_handbook_fixtures import build_world

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/project_handbook"


@pytest_asyncio.fixture
async def world():
    register_project_handbook_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, governance=True)


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str, permissions: list[str] | None = None):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": permissions or [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://handbook-test") as c:
        yield c


async def test_a_stranger_from_another_tenant_sees_404_everywhere(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.outsider, "manager") as c:
        responses = [
            await c.get(f"{p}/handbook"),
            await c.get(f"{p}/chapters/principles"),
            await c.get(f"{p}/chapters/principles/versions"),
            await c.get(f"{p}/findings"),
            await c.get(f"{p}/validation"),
            await c.get(f"{p}/export"),
            await c.get(f"{p}/data-room"),
            await c.patch(f"{p}/chapters/principles", json={"content": "x"}),
            await c.post(f"{p}/chapters/principles/submit"),
            await c.post(f"{p}/chapters/principles/approve"),
            await c.post(f"{p}/data-room/materialise"),
            await c.post(f"{p}/handbook/sync"),
        ]
    assert [r.status_code for r in responses] == [404] * len(responses)


async def test_a_project_member_reads_the_handbook_with_what_they_may_do(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.editor, "editor") as c:
        r = await c.get(f"{p}/handbook")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["chapters"] == 15
    first = body["chapters"][0]
    assert first["can"]["approve"]["allowed"] is False
    assert first["can"]["edit"]["allowed"] is True


async def test_an_editor_cannot_approve_or_materialise(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.editor, "editor") as c:
        approve = await c.post(f"{p}/chapters/principles/approve")
        materialise = await c.post(f"{p}/data-room/materialise")
    assert approve.status_code == 403
    assert materialise.status_code == 403


async def test_the_flow_over_http_ends_in_a_pdf_and_a_materialised_data_room(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.owner, "manager") as c:
        saved = await c.patch(f"{p}/chapters/principles", json={"content": "Ziele des Projekts."})
        assert saved.status_code == 200
        submitted = await c.post(f"{p}/chapters/principles/submit")
        assert submitted.json()["status"] == "in_review"
        same = await c.post(f"{p}/chapters/principles/approve")
        assert same.status_code == 403
        assert same.json()["detail"]["code"] == "approver_is_submitter"
    async with client_as(world, world.decider, "manager") as c:
        approved = await c.post(f"{p}/chapters/principles/approve")
        assert approved.status_code == 200
        assert approved.json()["approved_version"] == 1
        pdf = await c.get(f"{p}/export", headers={"Accept-Language": "de"})
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")
        assert pdf.headers["content-disposition"].endswith('project_handbook.pdf"')
        done = await c.post(f"{p}/data-room/materialise")
        assert done.status_code == 200
        assert done.json()["folders"] == 185
        tree = await c.get(f"{p}/data-room")
        assert len(tree.json()["folders"]) == 185


async def test_a_missing_handbook_answers_with_its_own_code(world: World) -> None:
    other = await build_world(world.factory, governance=False, handbook=False)
    async with client_as(other, other.manager, "manager") as c:
        r = await c.get(f"{BASE}/projects/{other.project_id}/handbook")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "handbook_missing"
