# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may see and change the engineering brief, over HTTP against PostgreSQL.

A stranger from another tenant sees 404 on every project route, a project member with the editor role reads
but cannot approve, and the approver cannot be the submitter.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.engineering_brief.permissions import register_engineering_brief_permissions
from app.modules.engineering_brief.router import router
from tests._pg import isolated_engine
from tests.pg.engineering_brief_fixtures import build_world
from tests.pg.governance_fixtures import World

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/engineering_brief"


@pytest_asyncio.fixture
async def world():
    register_engineering_brief_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://brief-test") as c:
        yield c


async def test_a_stranger_from_another_tenant_sees_404_everywhere(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.outsider, "manager") as c:
        responses = [
            await c.get(f"{p}/brief"),
            await c.get(f"{p}/requirements"),
            await c.get(f"{p}/concept"),
            await c.get(f"{p}/programme"),
            await c.get(f"{p}/milestones"),
            await c.get(f"{p}/studies"),
            await c.get(f"{p}/specification"),
            await c.post(f"{p}/specification/issue", json={}),
            await c.get(f"{p}/readiness?gate_code=none"),
            await c.post(f"{p}/brief/submit"),
            await c.post(f"{p}/milestones/publish"),
        ]
    assert [r.status_code for r in responses] == [404] * len(responses)


async def test_a_project_member_reads_the_brief(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.editor, "editor") as c:
        r = await c.get(f"{p}/brief")
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


async def test_an_editor_cannot_publish_or_approve(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.editor, "editor") as c:
        approve = await c.post(f"{p}/brief/approve")
        publish = await c.post(f"{p}/milestones/publish")
    assert approve.status_code == 403
    assert publish.status_code == 403
