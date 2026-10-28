# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠WBS rules hold on the projects write paths: duplication and the projects router."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.projects.models import ProjectWBS
from tests._pg import isolated_engine
from tests.pg.design_fixtures import DesignWorld, build_design_world

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        yield await build_design_world(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def _add_raw(w: DesignWorld, *codes: tuple[str, str | None]) -> None:
    """Write nodes straight into the table, past every check, as legacy data would be."""
    async with w.factory() as s:
        ids: dict[str, object] = {}
        for code, parent in codes:
            node = ProjectWBS(project_id=w.project_id, parent_id=ids.get(parent), code=code, name=code, level=0)
            s.add(node)
            await s.flush()
            ids[code] = node.id
        await s.commit()


def _projects(session: AsyncSession):
    from app.config import get_settings
    from app.modules.projects.service import ProjectService

    return ProjectService(session, get_settings())


async def test_duplicating_a_project_with_a_broken_tree_copies_it_as_it_is(world: DesignWorld) -> None:
    """A copy reproduces a tree; it introduces nothing, so legacy violations travel with it (decision 2)."""
    await _add_raw(world, ("1", None), ("2.1", "1"), ("1", None))
    async with world.factory() as s:
        copy = await _projects(s).duplicate_project(world.project_id, world.manager)
        await s.commit()
        codes = (await s.execute(select(ProjectWBS.code).where(ProjectWBS.project_id == copy.id))).scalars().all()
    assert sorted(codes) == ["1", "1", "2.1"]


async def _router_client(w: DesignWorld):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.projects.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(w.manager)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(w.manager),
        "role": "admin",
        "permissions": [],
    }
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://wbs-test")


async def test_a_legacy_broken_tree_stays_editable_through_the_projects_router(world: DesignWorld) -> None:
    """Finding 3: a pinned setup must never make the projects WBS editor unusable."""
    await _add_raw(world, ("1", None), ("1", None), ("9.1", "1"))  # a duplicate and a child off its prefix
    base = f"/api/v1/projects/{world.project_id}/wbs/"
    async with await _router_client(world) as c:
        unrelated = await c.post(base, json={"code": "2", "name": "Site", "level": 0})
        assert unrelated.status_code == 201, unrelated.text
        renamed = await c.patch(f"{base}{unrelated.json()['id']}", json={"name": "Site works"})
        assert renamed.status_code == 200, renamed.text
        third = await c.post(base, json={"code": "1", "name": "Again", "level": 0})
        assert third.status_code == 422, third.text
        assert [v["code"] for v in third.json()["detail"]["violations"]] == ["wbs_code_duplicate"]
        clash = await c.patch(f"{base}{unrelated.json()['id']}", json={"code": "1"})
        assert clash.status_code == 422, clash.text
    async with world.factory() as s:
        codes = (await s.execute(select(ProjectWBS.code).where(ProjectWBS.project_id == world.project_id))).scalars()
        assert sorted(codes) == ["1", "1", "2", "9.1"]


async def test_closing_a_node_closes_its_subtree_and_the_tree_stays_valid(world: DesignWorld) -> None:
    from app.modules.design_management.service import DesignService

    await _add_raw(world, ("1", None), ("1.1", "1"), ("1.1.1", "1.1"), ("2", None))
    async with world.factory() as s:
        svc = DesignService(s)
        rows = {r.code: r for r in await svc.wbs_rows(world.project_id)}
        await svc.close_wbs(world.project_id, rows["1"].id, closed=True, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        closed = {r.code for r in await svc.wbs_rows(world.project_id) if (r.metadata_ or {}).get("closed")}
        assert closed == {"1", "1.1", "1.1.1"}
        assert await svc.wbs_tree_violations(world.project_id) == []


async def _tree(session: AsyncSession, project_id) -> set[tuple[str, str | None]]:
    """``(code, parent code)`` for every node: the hierarchy, independent of ids."""
    rows = (await session.execute(select(ProjectWBS).where(ProjectWBS.project_id == project_id))).scalars().all()
    by_id = {r.id: r.code for r in rows}
    return {(r.code, by_id.get(r.parent_id)) for r in rows}


async def test_a_backup_restores_a_three_level_tree_with_its_hierarchy(world: DesignWorld) -> None:
    """Restore used to build children before their parent had an id, so every child came back at the root."""
    await _add_raw(world, ("1", None), ("1.1", "1"), ("1.1.1", "1.1"), ("1.2", "1"), ("2", None))
    async with world.factory() as s:
        svc = _projects(s)
        backup = await svc.backup_project(world.project_id)
        restored = await svc.restore_project_from_backup(backup, world.manager)
        await s.commit()
        original, copy = await _tree(s, world.project_id), await _tree(s, restored.project_id)
    assert restored.wbs_nodes_created == 5
    assert copy == original == {("1", None), ("1.1", "1"), ("1.1.1", "1.1"), ("1.2", "1"), ("2", None)}


async def test_a_project_without_design_setup_copies_and_restores_its_tree_unchecked(world: DesignWorld) -> None:
    """Scope decision: no design setup, no new refusal; duplicate codes travel as they did before."""
    from app.modules.design_management.models import DesignSetup

    await _add_raw(world, ("1", None), ("1", None), ("2.1", "1"))
    async with world.factory() as s:
        await s.delete(
            (await s.execute(select(DesignSetup).where(DesignSetup.project_id == world.project_id))).scalar_one()
        )
        await s.commit()
    async with world.factory() as s:
        svc = _projects(s)
        copy = await svc.duplicate_project(world.project_id, world.manager)
        restored = await svc.restore_project_from_backup(await svc.backup_project(world.project_id), world.manager)
        await s.commit()
        copied = (await s.execute(select(func.count()).where(ProjectWBS.project_id == copy.id))).scalar_one()
    assert copied == 3
    assert restored.wbs_nodes_created == 3
