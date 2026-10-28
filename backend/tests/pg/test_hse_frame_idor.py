# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may read and write an HSE frame, over HTTP against PostgreSQL.

A stranger to the project answers 404 on every route, exactly like a missing
project. Reading never writes: the frame exists only after an explicit write.
Changing facts needs the edit permission; pinning a catalogue, waiving and
submitting need manage; approving needs the approve permission and a second
person. A child id from another project answers 404 and says nothing about
the row.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.hse_frame.models import HseFrame
from app.modules.hse_frame.permissions import register_hse_frame_permissions
from app.modules.hse_frame.router import router
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, add_project, build_world

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/hse-frame"
READS = ("frame", "catalogue", "items", "roles", "readiness", "summary", "validation", "link-candidates?kind=hse_ptw")


@pytest_asyncio.fixture
async def world():
    register_hse_frame_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, routes=False)


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hse-test") as c:
        yield c


def _p(pid: uuid.UUID, tail: str) -> str:
    return f"{BASE}/projects/{pid}/{tail}"


async def _frames(w: World) -> int:
    async with w.factory() as s:
        stmt = select(func.count()).select_from(HseFrame).where(HseFrame.project_id == w.project_id)
        return (await s.execute(stmt)).scalar_one()


async def test_a_stranger_gets_404_on_reads_and_writes(world: World) -> None:
    async with client_as(world, world.outsider, "manager") as c:
        for path in READS:
            assert (await c.get(_p(world.project_id, path))).status_code == 404, path
        assert (await c.post(_p(world.project_id, "frame"))).status_code == 404
        assert (await c.patch(_p(world.project_id, "frame"), json={"employers_count": 2})).status_code == 404
        item = {"topic": "hse_requirements", "title": "x"}
        assert (await c.post(_p(world.project_id, "items"), json=item)).status_code == 404
    assert await _frames(world) == 0


async def test_reading_never_writes_and_each_write_needs_its_permission(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        got = await c.get(_p(world.project_id, "frame"))
        assert got.status_code == 200, got.text
        assert got.json()["frame"] is None
        for path in READS[1:]:
            await c.get(_p(world.project_id, path))
    assert await _frames(world) == 0

    async with client_as(world, world.editor, "editor") as c:
        made = await c.post(_p(world.project_id, "frame"))
        assert made.status_code == 201, made.text
        patched = await c.patch(_p(world.project_id, "frame"), json={"employers_count": 3})
        assert patched.status_code == 200, patched.text
        # Editors write facts and rows; pinning, waiving and submitting are manager work.
        assert (await c.post(_p(world.project_id, "frame/submit"))).status_code == 403
        assert (await c.post(_p(world.project_id, "frame/apply-templates"))).status_code == 403
        assert (await c.post(_p(world.project_id, "frame/approve"))).status_code == 403
        assert (await c.patch(_p(world.project_id, "frame"), json={"no_such_field": 1})).status_code == 422
    assert await _frames(world) == 1

    async with client_as(world, world.manager, "manager") as c:
        applied = await c.post(_p(world.project_id, "frame/apply-templates"))
        assert applied.status_code == 200, applied.text
        assert applied.json()["created"] > 0


async def test_a_child_of_another_project_answers_404(world: World) -> None:
    async with world.factory() as s:
        other = await add_project(s, world.manager, [])
        await s.commit()
    async with client_as(world, world.manager, "manager") as c:
        assert (await c.post(_p(other, "frame"))).status_code == 201
        made = await c.post(_p(other, "items"), json={"topic": "hse_requirements", "title": "Other project row"})
        assert made.status_code == 201, made.text
        foreign = made.json()["id"]
        assert (await c.post(_p(world.project_id, "frame"))).status_code == 201
        for call in (
            c.get(_p(world.project_id, f"items/{foreign}")),
            c.patch(_p(world.project_id, f"items/{foreign}"), json={"title": "taken"}),
            c.post(_p(world.project_id, f"items/{foreign}/meet"), json={}),
            c.delete(_p(world.project_id, f"items/{foreign}")),
        ):
            assert (await call).status_code == 404
        still = await c.get(_p(other, f"items/{foreign}"))
        assert still.json()["title"] == "Other project row"
