# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits tenant isolation: foreign ids answer 404, editors cannot decide, owners cannot verify themselves."""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.permits import router as permits_router
from app.modules.permits.errors import PermitError
from app.modules.permits.service import PermitService
from tests._pg import isolated_engine
from tests.pg.permits_fixtures import World, build_world, cond, decide, file, requirement

TODAY = date(2026, 10, 11)

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BUILDING = "baugenehmigung"


@pytest_asyncio.fixture
async def pair():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory), await build_world(factory)


async def _granted(w: World) -> tuple:
    rid = await requirement(w, BUILDING)
    aid = await file(w, rid)
    out = await decide(w, aid, "granted_with_conditions", conditions=[cond("1", owner_user_id=w.owner_user)])
    async with w.factory() as s:
        conds = await PermitService(s).repo.conditions_of_permit(w.project_id, out["permit"].id)
    return rid, aid, out["permit"].id, conds[0].id


async def _code(coro) -> tuple[int, str]:
    with pytest.raises(PermitError) as exc:
        await coro
    return exc.value.status_code, exc.value.code


async def test_foreign_ids_answer_404(pair: tuple[World, World]) -> None:
    a, b = pair
    rid, aid, pid, cid = await _granted(b)
    async with a.factory() as s:
        svc = PermitService(s)
        p = a.project_id
        assert await svc.repo.get_requirement(p, rid) is None
        assert (await _code(svc.update_requirement(p, rid, {"title": "x"}, actor_id=a.manager, can_manage=True)))[
            0
        ] == 404
        assert (await _code(svc.create_application(p, {"requirement_id": rid}, actor_id=a.manager)))[0] == 404
        assert (
            await _code(
                svc.record_decision(
                    p, aid, {"outcome": "granted", "decision_date": TODAY}, actor_id=a.manager, today=TODAY
                )
            )
        )[0] == 404
        assert (await _code(svc.transition_permit(p, pid, "suspended", actor_id=a.manager, reason="x")))[0] == 404
        assert (await _code(svc.discharge(p, cid, {"mode": "not_triggered"}, actor_id=a.manager, today=TODAY)))[
            0
        ] == 404
        assert (await _code(svc.set_dependencies(p, rid, [], actor_id=a.manager)))[0] == 404


async def test_soft_link_to_a_foreign_project_is_refused(pair: tuple[World, World]) -> None:
    a, b = pair
    _rid, _aid, pid_b, cid_b = await _granted(b)
    rid_a = await requirement(a, BUILDING)
    async with a.factory() as s:
        svc = PermitService(s)
        status, _ = await _code(
            svc.create_application(
                a.project_id,
                {
                    "requirement_id": rid_a,
                    "kind": "discharge_of_conditions",
                    "parent_permit_id": pid_b,
                    "discharges_condition_ids": [cid_b],
                },
                actor_id=a.manager,
            )
        )
        assert status == 404


def test_editor_cannot_record_a_decision() -> None:
    from app.core.permissions import permission_registry
    from app.modules.permits.permissions import register_permit_permissions

    register_permit_permissions()
    deps = next(r.dependencies for r in permits_router.router.routes if r.path.endswith("/decision"))
    perms = {getattr(d.dependency, "permission", None) for d in deps}
    assert perms == {"permits.manage"}
    assert not permission_registry.role_has_permission("editor", "permits.manage")
    assert permission_registry.role_has_permission("manager", "permits.manage")


async def test_owner_cannot_verify_own_discharge(pair: tuple[World, World]) -> None:
    a, _b = pair
    _rid, _aid, _pid, cid = await _granted(a)
    async with a.factory() as s:
        svc = PermitService(s)
        status, code = await _code(
            svc.discharge(a.project_id, cid, {"mode": "not_triggered"}, actor_id=a.owner_user, today=TODAY)
        )
    assert (status, code) == (403, "verifier_is_owner")
