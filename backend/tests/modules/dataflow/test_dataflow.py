"""Dataflow: counts, tenant isolation, missing-module tolerance, cache."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.dataflow import service
from app.modules.dataflow.registry import REGISTRY, CounterSpec
from app.modules.dataflow.router import project_counts
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem


@pytest.fixture(autouse=True)
def _clean_cache():
    service.clear_cache()
    yield
    service.clear_cache()


async def _project(session, owner: uuid.UUID) -> Project:
    p = Project(name="P", owner_id=owner)
    session.add(p)
    await session.flush()
    return p


async def _punch(session, project_id: uuid.UUID, n: int) -> None:
    for i in range(n):
        session.add(
            PunchItem(project_id=project_id, title=f"t{i}", description="", photos=[], metadata_={}, reopen_history=[])
        )
    await session.flush()


def _by_module(result):
    return {m.module: m for m in result.modules}


async def test_counts_are_scoped_to_project(session):
    owner = uuid.uuid4()
    a, b = await _project(session, owner), await _project(session, owner)
    await _punch(session, a.id, 3)
    await _punch(session, b.id, 1)
    res = await service.get_project_counts(session, a.id)
    punch = _by_module(res)["punchlist"]
    assert punch.installed
    assert [(o.object, o.count) for o in punch.objects] == [("punch_item", 3)]
    assert res.project_id == a.id


async def test_other_users_project_is_404(session):
    owner, stranger = uuid.uuid4(), uuid.uuid4()
    p = await _project(session, owner)
    with pytest.raises(HTTPException) as exc:
        await project_counts(p.id, str(stranger), session, None)
    assert exc.value.status_code == 404
    ok = await project_counts(p.id, str(owner), session, None)
    assert ok.project_id == p.id


async def test_unknown_project_is_404(session):
    with pytest.raises(HTTPException) as exc:
        await project_counts(uuid.uuid4(), str(uuid.uuid4()), session, None)
    assert exc.value.status_code == 404


async def test_missing_module_and_table_do_not_fail_response(session, monkeypatch):
    monkeypatch.setitem(REGISTRY, "ghost", [CounterSpec("x", "app.modules.ghost.models:Nope")])
    monkeypatch.setitem(
        REGISTRY, "notable", [CounterSpec("y", "app.modules.punchlist.models:PunchItem", fk="no_such_column")]
    )
    p = await _project(session, uuid.uuid4())
    await _punch(session, p.id, 2)
    mods = _by_module(await service.get_project_counts(session, p.id))
    assert mods["ghost"].installed is False and mods["ghost"].reason == "not_available"
    assert mods["notable"].installed is False
    assert mods["punchlist"].installed and mods["punchlist"].objects[0].count == 2


async def test_query_error_is_isolated_by_savepoint(session, monkeypatch):
    monkeypatch.setitem(REGISTRY, "broken", [CounterSpec("z", "app.modules.punchlist.models:PunchItem")])
    real = service._count_stmt

    def boom(spec, pid):
        if spec.object == "z":
            from sqlalchemy import text

            return text("select count(*) from table_that_does_not_exist")
        return real(spec, pid)

    monkeypatch.setattr(service, "_count_stmt", boom)
    p = await _project(session, uuid.uuid4())
    mods = _by_module(await service.get_project_counts(session, p.id))
    assert mods["broken"].installed is False and mods["broken"].reason == "query_failed"
    assert mods["punchlist"].installed


async def test_cache_hits_within_ttl_and_expires(session, monkeypatch):
    p = await _project(session, uuid.uuid4())
    await _punch(session, p.id, 1)
    first = await service.get_project_counts(session, p.id, "t")
    await _punch(session, p.id, 4)
    assert await service.get_project_counts(session, p.id, "t") is first
    other_tenant = await service.get_project_counts(session, p.id, "other")
    assert _by_module(other_tenant)["punchlist"].objects[0].count == 5
    monkeypatch.setattr(service, "CACHE_TTL_SECONDS", 0.0)
    fresh = await service.get_project_counts(session, p.id, "t")
    assert fresh is not first
    assert _by_module(fresh)["punchlist"].objects[0].count == 5


async def test_registry_models_resolve_or_are_reported(session):
    p = await _project(session, uuid.uuid4())
    res = await service.get_project_counts(session, p.id)
    bad = [m.module for m in res.modules if not m.installed]
    assert bad == [], f"registry entries that do not resolve: {bad}"
