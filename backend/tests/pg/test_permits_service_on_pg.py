# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits service on real PostgreSQL: route to roadmap, decisions, conditions, discharge, variation, races."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.permits.errors import PermitError
from app.modules.permits.service import PermitService
from tests._pg import isolated_engine
from tests.pg.permits_fixtures import (
    World,
    application,
    build_world,
    cond,
    decide,
    file,
    move,
    requirement,
    state,
)

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio

BUILDING = "baugenehmigung"


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _conditions(w: World, permit_id) -> dict[str, object]:
    async with w.factory() as s:
        rows = await PermitService(s).repo.conditions_of_permit(w.project_id, permit_id)
        return {c.number: c for c in rows}


async def test_route_proposals_are_not_written_until_accepted(world: World) -> None:
    async with world.factory() as s:
        svc = PermitService(s)
        proposal = await svc.propose(world.project_id)
        codes = [p["permit_type_code"] for p in proposal["proposals"]]
        assert BUILDING in codes
        assert await svc.repo.list_requirements(world.project_id) == []
        made = await svc.accept_proposals(world.project_id, [BUILDING], actor_id=world.manager)
        await s.commit()
    assert [r.permit_type_code for r in made] == [BUILDING]


async def test_grant_with_conditions_builds_the_register(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    out = await decide(
        world,
        aid,
        "granted_with_conditions",
        conditions=[cond("1", "suspensive", owner_user_id=world.owner_user), cond("2", trigger="ongoing")],
    )
    permit = out["permit"]
    assert permit is not None and permit.status == "in_force"
    conds = await _conditions(world, permit.id)
    assert set(conds) == {"1", "2"} and all(c.status == "open" for c in conds.values())
    assert await state(world, rid) == "granted"


async def test_partial_grant_creates_a_follow_up_requirement(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    with pytest.raises(PermitError) as exc:
        await decide(world, aid, "partially_granted")
    assert exc.value.code == "partial_grant_needs_scope"
    out = await decide(world, aid, "partially_granted", scope_note="Basement and ground floor only")
    follow = out["follow_up_requirement"]
    assert follow is not None and follow.follow_up_of_id == rid and out["permit"].scope == "partial"


async def test_refusal_then_second_attempt(world: World) -> None:
    rid = await requirement(world, BUILDING)
    first = await file(world, rid)
    out = await decide(world, first, "refused")
    assert out["permit"] is None and out["next"] == ["resubmit", "appeal_note"]
    assert await state(world, rid) == "refused"
    second = await file(world, rid)
    async with world.factory() as s:
        app = await PermitService(s).repo.get_application(world.project_id, second)
    assert app.attempt == 2
    await decide(world, second, "granted")
    assert await state(world, rid) == "granted"


async def test_self_certified_discharge_is_four_eyes(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    out = await decide(world, aid, "granted_with_conditions", conditions=[cond("1", owner_user_id=world.owner_user)])
    c = (await _conditions(world, out["permit"].id))["1"]
    async with world.factory() as s:
        svc = PermitService(s)
        await svc.add_evidence(
            world.project_id,
            c.id,
            {"kind": "photo", "note": "Fence photographed"},
            actor_id=world.owner_user,
            can_manage=False,
        )
        await svc.submit_evidence(world.project_id, c.id, actor_id=world.owner_user, can_manage=False)
        await s.commit()
    async with world.factory() as s:
        with pytest.raises(PermitError) as exc:
            await PermitService(s).discharge(
                world.project_id, c.id, {"mode": "self_certified"}, actor_id=world.owner_user, today=TODAY
            )
        assert exc.value.code == "verifier_is_owner"
    async with world.factory() as s:
        row = await PermitService(s).discharge(
            world.project_id, c.id, {"mode": "self_certified"}, actor_id=world.verifier, today=TODAY
        )
        await s.commit()
    assert row.decided_by == world.owner_user and row.verifier_user_id == world.verifier
    assert len(row.evidence_snapshot) == 1
    assert (await _conditions(world, out["permit"].id))["1"].status == "discharged"


async def test_one_discharge_application_covers_three_conditions(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    out = await decide(
        world,
        aid,
        "granted_with_conditions",
        conditions=[cond(n, "suspensive", requires_authority_approval=True) for n in ("1", "2", "3")],
    )
    pid = out["permit"].id
    ids = [c.id for c in (await _conditions(world, pid)).values()]
    dis = await application(
        world, rid, kind="discharge_of_conditions", parent_permit_id=pid, discharges_condition_ids=ids
    )
    await move(world, dis, "preparing")
    await move(world, dis, "submitted", TODAY - timedelta(days=20))
    assert {c.status for c in (await _conditions(world, pid)).values()} == {"discharge_applied"}
    res = await decide(world, dis, "granted", discharged_condition_ids=ids[:2])
    assert res["permit"] is None
    statuses = sorted(c.status for c in (await _conditions(world, pid)).values())
    assert statuses == ["discharged", "discharged", "open"]


async def test_variation_supersedes_the_parent_and_carries_conditions(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    out = await decide(world, aid, "granted_with_conditions", conditions=[cond("1"), cond("2")])
    parent = out["permit"]
    var = await application(world, rid, kind="variation", parent_permit_id=parent.id)
    await move(world, var, "preparing")
    await move(world, var, "submitted", TODAY - timedelta(days=15))
    res = await decide(world, var, "granted_with_conditions", conditions=[cond("3")], removed_condition_numbers=["2"])
    child = res["permit"]
    async with world.factory() as s:
        old = await PermitService(s).repo.get_permit(world.project_id, parent.id)
    assert old.status == "superseded" and old.superseded_by_id == child.id
    assert {c.status for c in (await _conditions(world, parent.id)).values()} == {"superseded"}
    carried = await _conditions(world, child.id)
    assert set(carried) == {"1", "3"} and carried["1"].original_id is not None


async def test_deemed_outcome_is_only_a_proposal(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid, TODAY - timedelta(days=400))
    async with world.factory() as s:
        status = await PermitService(s).deemed_status(world.project_id, aid, TODAY)
        app = await PermitService(s).repo.get_application(world.project_id, aid)
    assert app.status != "decided"
    if status["proposal"] is None:
        with pytest.raises(PermitError) as exc:
            await decide(world, aid, "deemed_granted")
        assert exc.value.code == "deemed_not_available"
    else:
        out = await decide(world, aid, "deemed_granted", conditions=[], conditions_pending=True)
        assert out["decision"].deemed is True


async def test_two_concurrent_decisions_one_wins_one_409(world: World) -> None:
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    results = await asyncio.gather(decide(world, aid, "granted"), decide(world, aid, "refused"), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(errors) == 1, results
    assert isinstance(errors[0], PermitError) and errors[0].status_code == 409


# ── programme rule 26: a project that does not use gates is worked to the end ──


async def test_a_project_without_gates_is_walked_from_the_roadmap_to_a_ready_start(world: World) -> None:
    """No phase model, no gate, no frame document: nothing in permits waits for one.

    The roadmap is never ``agreed`` here (that state only mirrors a binding frame document
    and only adds the change request duty), so structural changes stay free, the authority's
    decision is recorded by hand, the condition is discharged four-eyes and the start of
    works reads ready.
    """
    from app.modules.project_governance import public

    p = world.project_id
    async with world.factory() as s:
        assert await public.project_gates(s, p) == ()
        view = await PermitService(s).roadmap_view(p)
    assert view["gates_in_use"] is False and view["state"] == "draft"

    rid = await requirement(world, BUILDING, needed_by_date=TODAY)
    aid = await file(world, rid)
    out = await decide(
        world, aid, "granted_with_conditions", conditions=[cond("1", "suspensive", owner_user_id=world.owner_user)]
    )
    c = (await _conditions(world, out["permit"].id))["1"]
    async with world.factory() as s:
        before = await PermitService(s).readiness(p, "start", TODAY)
    assert before["status"] == "not_ready"
    async with world.factory() as s:
        svc = PermitService(s)
        await svc.add_evidence(
            p, c.id, {"kind": "photo", "note": "Checked calculations"}, actor_id=world.owner_user, can_manage=False
        )
        await svc.submit_evidence(p, c.id, actor_id=world.owner_user, can_manage=False)
        await svc.discharge(p, c.id, {"mode": "self_certified"}, actor_id=world.verifier, today=TODAY)
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        after = await svc.readiness(p, "start", TODAY)
        view = await svc.roadmap_view(p)
    assert after["status"] == "ready", after
    assert view["state"] == "draft" and view["gates_in_use"] is False


async def test_a_project_with_a_phase_model_says_its_gates_are_in_use(world: World) -> None:
    from app.modules.project_governance.service import GovernanceService

    async with world.factory() as s:
        await GovernanceService(s).set_model(
            world.project_id,
            source="shipped",
            catalogue_id="neutral",
            version=None,
            four_eyes=True,
            actor_id=world.manager,
            tenant_id=str(world.manager),
        )
        await s.commit()
    async with world.factory() as s:
        view = await PermitService(s).roadmap_view(world.project_id)
    assert view["gates_in_use"] is True
