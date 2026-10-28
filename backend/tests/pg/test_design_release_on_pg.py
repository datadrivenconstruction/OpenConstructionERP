# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Releases against PostgreSQL: the approval route, the purpose that is sent, who receives what.

Four-eyes through approval_routes ``design_release`` (decision 14), rule 13
checked against the purpose a transmittal really carries, only current
revisions, distribution lists of this project or the actor's own, recipients
that resolve to a person, and two releases issued at once.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.errors import DesignError
from app.modules.design_management.models import DesignRelease
from app.modules.design_management.service import DesignService
from tests._pg import isolated_engine
from tests.pg.design_fixtures import (
    DesignWorld,
    approved_release,
    build_design_world,
    decide_instance,
    drawing_with_revision,
    new_revision,
)
from tests.pg.governance_fixtures import add_route

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        yield await build_design_world(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def _rule(w: DesignWorld, role: str = "ARCH", **data: object) -> None:
    async with w.factory() as s:
        await DesignService(s).create_dist_rule(
            w.project_id, {"recipient_role_id": str(w.roles[role]), **data}, actor_id=w.manager
        )
        await s.commit()


async def _decide(w: DesignWorld, instance_id: uuid.UUID, approver: uuid.UUID, decision: str = "approved") -> None:
    async with w.factory() as s:
        await decide_instance(s, instance_id, approver, decision)
        await s.commit()


async def _release(w: DesignWorld, release_id: uuid.UUID) -> DesignRelease:
    async with w.factory() as s:
        return await s.get(DesignRelease, release_id)


async def test_a_release_needs_an_approval_route_and_someone_else_to_approve_it(world: DesignWorld) -> None:
    """Finding 4: B rewrites A's draft, marks it ready and can neither approve nor issue it alone."""
    _d, rev_a = await drawing_with_revision(world, "ARCH")
    _d, rev_s = await drawing_with_revision(world, "STRU")
    await _rule(world)
    both = {"revision_ids": [str(rev_a), str(rev_s)]}
    async with world.factory() as s:
        svc = DesignService(s)
        rel = await svc.create_release(world.project_id, {"revision_ids": [str(rev_a)]}, actor_id=world.editor)
        with pytest.raises(DesignError) as no_route:
            await svc.release_transition(world.project_id, rel.id, "ready", actor_id=world.editor)
        assert no_route.value.code == "no_approval_route"
        await add_route(s, world.project_id, "design_release", world.approver)
        # The route's own approver rewrites the draft and marks it ready.
        await svc.patch_release(world.project_id, rel.id, both, actor_id=world.approver)
        ready = await svc.release_transition(world.project_id, rel.id, "ready", actor_id=world.approver)
        assert (ready.approval_status, ready.content_changed_by) == ("pending", world.approver)
        can = await svc.release_can(ready, actor_id=world.approver, may_release=True)
        assert can["issue"] == {"allowed": False, "applies": True, "reason": "release_not_approved"}
        assert can["approve"] == {"allowed": False, "applies": True, "reason": "release_four_eyes"}
        assert (await svc.release_can(ready, actor_id=world.manager, may_release=True))["approve"]["allowed"]
        for actor in (world.manager, world.approver, world.editor):
            with pytest.raises(DesignError) as early:
                await svc.issue_release(world.project_id, rel.id, actor_id=actor)
            assert (early.value.code, early.value.status_code) == ("release_not_approved", 409)
        own_instance = ready.approval_instance_id
        await s.commit()
    # The route lets its approver approve; it was that person's own content, so it does not count.
    await _decide(world, own_instance, world.approver)
    async with world.factory() as s:
        svc = DesignService(s)
        assert await svc.catch_up_approvals(world.project_id) == 1
        row = await s.get(DesignRelease, rel.id)
        assert (row.status, row.approval_status, row.approved_by) == ("draft", "rejected", None)
        again = await svc.release_transition(world.project_id, rel.id, "ready", actor_id=world.manager)
        assert again.content_changed_by == world.manager
        instance_id = again.approval_instance_id
        await s.commit()
    await _decide(world, instance_id, world.approver)
    async with world.factory() as s:
        svc = DesignService(s)
        assert await svc.catch_up_approvals(world.project_id) == 1
        assert await svc.catch_up_approvals(world.project_id) == 0, "a verdict is applied once"
        row = await s.get(DesignRelease, rel.id)
        assert (row.approval_status, row.approved_by) == ("approved", world.approver)
        with pytest.raises(DesignError) as no_permission:
            await svc.issue_release(world.project_id, rel.id, actor_id=world.manager, may_release=False)
        assert (no_permission.value.code, no_permission.value.status_code) == ("forbidden", 403)
        issued = await svc.issue_release(world.project_id, rel.id, actor_id=world.manager)
        await s.commit()
    assert issued.status == "issued" and len(issued.transmittal_ids) == 1


async def test_reopening_or_a_cancelled_route_drops_the_approval(world: DesignWorld) -> None:
    from app.modules.approval_routes.service import ApprovalRouteService

    _d, rev = await drawing_with_revision(world, "ARCH")
    await _rule(world)
    rel_id = await approved_release(world, [rev])
    async with world.factory() as s:
        svc = DesignService(s)
        draft = await svc.release_transition(world.project_id, rel_id, "draft", actor_id=world.editor)
        assert (draft.approval_status, draft.approved_by, draft.approval_instance_id) == ("none", None, None)
        ready = await svc.release_transition(world.project_id, rel_id, "ready", actor_id=world.editor)
        await ApprovalRouteService(s).cancel_instance(ready.approval_instance_id, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        assert await DesignService(s).catch_up_approvals(world.project_id) == 1
        await s.commit()
    row = await _release(world, rel_id)
    assert (row.status, row.approval_status, row.approval_instance_id) == ("draft", "none", None)


async def test_an_editor_the_route_does_not_name_cannot_approve(world: DesignWorld) -> None:
    """Spec 8.3: only whoever the route entitles decides."""
    from fastapi import HTTPException

    _d, rev = await drawing_with_revision(world, "ARCH")
    async with world.factory() as s:
        await add_route(s, world.project_id, "design_release", world.approver)
        svc = DesignService(s)
        rel = await svc.create_release(world.project_id, {"revision_ids": [str(rev)]}, actor_id=world.manager)
        ready = await svc.release_transition(world.project_id, rel.id, "ready", actor_id=world.manager)
        instance_id = ready.approval_instance_id
        await s.commit()
    with pytest.raises(HTTPException) as refused:
        await _decide(world, instance_id, world.editor)
    assert refused.value.status_code == 403
    assert (await _release(world, rel.id)).approval_status == "pending"


async def test_a_transmittal_carries_the_release_purpose_and_a_rule_only_narrows(world: DesignWorld) -> None:
    """Finding 5: a for_construction rule neither upgrades an information release nor is sent as one."""
    from app.modules.transmittals.models import Transmittal

    _d, shared = await drawing_with_revision(world, "ARCH", suitability="S2")
    await _rule(world, "ARCH", purpose="for_construction")
    rel_id = await approved_release(world, [shared], purpose="for_information")
    async with world.factory() as s:
        with pytest.raises(DesignError) as nobody:
            await DesignService(s).issue_release(world.project_id, rel_id, actor_id=world.manager)
    assert nobody.value.code == "release_no_recipients"
    await _rule(world, "STRU")
    async with world.factory() as s:
        issued = await DesignService(s).issue_release(world.project_id, rel_id, actor_id=world.manager)
        await s.commit()
    assert [p["recipient_key"] for p in issued.issue_plan] == [f"role:{world.roles['STRU']}"]
    async with world.factory() as s:
        sent = (await s.execute(select(Transmittal).where(Transmittal.project_id == world.project_id))).scalars().all()
    assert [t.purpose_code for t in sent] == ["for_information"]
    # ...and the other way round: a shared revision cannot leave for construction through any rule.
    async with world.factory() as s:
        svc = DesignService(s)
        rel = await svc.create_release(
            world.project_id, {"revision_ids": [str(shared)], "purpose": "for_construction"}, actor_id=world.editor
        )
        with pytest.raises(DesignError) as unpublished:
            await svc.release_transition(world.project_id, rel.id, "ready", actor_id=world.editor)
    assert unpublished.value.code == "release_needs_published"


async def test_a_release_pins_only_the_current_revision(world: DesignWorld) -> None:
    """Finding 6: a superseded revision has no suitability of its own to check rule 13 against."""
    from app.modules.cde.models import DocumentContainer
    from app.modules.design_management.models import DesignDrawing

    drawing_id, old = await drawing_with_revision(world, "ARCH", suitability="S0")
    current = await new_revision(world, drawing_id, 2)
    async with world.factory() as s:
        d = await s.get(DesignDrawing, drawing_id)
        (await s.get(DocumentContainer, d.container_id)).suitability_code = "A4"
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        with pytest.raises(DesignError) as stale:
            await svc.create_release(world.project_id, {"revision_ids": [str(old)]}, actor_id=world.editor)
        assert (stale.value.code, stale.value.status_code) == ("revision_not_current", 422)
        assert [(v["code"], v["revision_id"]) for v in stale.value.violations] == [("revision_not_current", str(old))]
        rel = await svc.create_release(world.project_id, {"revision_ids": [str(current)]}, actor_id=world.editor)
        assert rel.revision_ids == [str(current)]


async def test_a_release_whose_revision_was_superseded_after_approval_is_not_issued(world: DesignWorld) -> None:
    drawing_id, rev = await drawing_with_revision(world, "ARCH")
    await _rule(world)
    rel_id = await approved_release(world, [rev])
    await new_revision(world, drawing_id, 2)
    async with world.factory() as s:
        with pytest.raises(DesignError) as stale:
            await DesignService(s).issue_release(world.project_id, rel_id, actor_id=world.manager)
    assert stale.value.code == "revision_not_current"


async def _list(w: DesignWorld, owner: uuid.UUID, *, project: bool, members: int = 1) -> uuid.UUID:
    from app.modules.file_distribution.models import FileDistributionList, FileDistributionMember

    async with w.factory() as s:
        lst = FileDistributionList(name=f"list {uuid.uuid4().hex[:6]}", owner_id=owner)
        lst.project_id = w.project_id if project else None
        s.add(lst)
        await s.flush()
        for i in range(members):
            s.add(FileDistributionMember(list_id=lst.id, email=f"person{i}@example.test", display_name=f"Person {i}"))
        await s.commit()
        return lst.id


async def test_only_a_list_of_this_project_or_the_actors_own_enters_the_matrix(world: DesignWorld) -> None:
    """Finding 7: another user's personal list is 404, as if it did not exist."""
    other = await build_design_world(world.factory)
    cases = [
        (await _list(world, world.outsider, project=False), None, "distribution_list_not_found"),
        (await _list(other, other.manager, project=True), None, "distribution_list_not_found"),
        (await _list(world, world.manager, project=False), world.manager, None),
        (await _list(world, world.editor, project=True), world.manager, None),
    ]
    async with world.factory() as s:
        svc = DesignService(s)
        for list_id, _actor, refused in cases:
            data = {"recipient_list_id": str(list_id)}
            if refused is None:
                row = await svc.create_dist_rule(world.project_id, data, actor_id=world.manager)
                assert row.recipient_list_id == list_id
                continue
            with pytest.raises(DesignError) as err:
                await svc.create_dist_rule(world.project_id, data, actor_id=world.manager)
            assert (err.value.code, err.value.status_code) == (refused, 404)
        foreign = cases[0][0]
        rule = await svc.create_dist_rule(
            world.project_id, {"recipient_role_id": str(world.roles["ARCH"])}, actor_id=world.manager
        )
        with pytest.raises(DesignError) as patched:
            await svc.patch_dist_rule(
                world.project_id,
                rule.id,
                {"recipient_list_id": str(foreign), "recipient_role_id": None},
                actor_id=world.manager,
            )
        assert patched.value.code == "distribution_list_not_found"


async def test_a_recipient_without_a_person_stops_the_issue(world: DesignWorld) -> None:
    """Finding 15: an empty list would have produced a transmittal to nobody."""
    from app.modules.transmittals.models import Transmittal

    _d, rev = await drawing_with_revision(world, "ARCH")
    empty = await _list(world, world.manager, project=True, members=0)
    async with world.factory() as s:
        await DesignService(s).create_dist_rule(
            world.project_id, {"recipient_list_id": str(empty)}, actor_id=world.manager
        )
        await s.commit()
    await _rule(world)
    rel_id = await approved_release(world, [rev])
    async with world.factory() as s:
        with pytest.raises(DesignError) as err:
            await DesignService(s).issue_release(world.project_id, rel_id, actor_id=world.manager)
        assert (err.value.code, err.value.status_code) == ("release_recipient_empty", 422)
        assert [(v["code"], v["recipient"]) for v in err.value.violations] == [
            ("release_recipient_empty", f"list:{empty}")
        ]
    async with world.factory() as s:
        sent = (await s.execute(select(Transmittal).where(Transmittal.project_id == world.project_id))).scalars().all()
    assert sent == []
    assert (await _release(world, rel_id)).status == "ready"


async def test_a_recipient_whose_revisions_are_all_excluded_is_recorded_not_sent(world: DesignWorld) -> None:
    """Finding 20: the plan keeps who got nothing and why."""
    _d, rev = await drawing_with_revision(world, "ARCH", suitability="S2")
    await _rule(world, "ARCH")
    await _rule(world, "STRU", min_suitability="A1")
    rel_id = await approved_release(world, [rev])
    async with world.factory() as s:
        issued = await DesignService(s).issue_release(world.project_id, rel_id, actor_id=world.manager)
        await s.commit()
    plan = {p["recipient_key"]: p for p in issued.issue_plan}
    held_back = plan[f"role:{world.roles['STRU']}"]
    assert held_back["transmittal_id"] is None and held_back["revision_ids"] == []
    assert held_back["excluded"] == [{"revision_id": str(rev), "reason": "below_min_suitability"}]
    assert plan[f"role:{world.roles['ARCH']}"]["transmittal_id"] == issued.transmittal_ids[0]
    assert len(issued.transmittal_ids) == 1


async def test_a_role_in_use_cannot_be_deleted(world: DesignWorld) -> None:
    """Finding 15: every reference is named, not only drawings."""
    await _rule(world, "STRU")
    async with world.factory() as s:
        svc = DesignService(s)
        phase = (await svc.phases(world.project_id))[0]["code"]
        await svc.create_deliverable(
            world.project_id, {"phase_code": phase, "role_id": str(world.roles["STRU"])}, actor_id=world.manager
        )
        await svc.create_approval_point(
            world.project_id,
            {"kind": "owner_approval", "approver_role_id": str(world.roles["STRU"])},
            actor_id=world.manager,
        )
        await svc.update_setup(
            world.project_id, {"lead_designer_role_id": str(world.roles["STRU"])}, actor_id=world.manager
        )
        with pytest.raises(DesignError) as used:
            await svc.delete_role(world.project_id, world.roles["STRU"], actor_id=world.manager)
        assert (used.value.code, used.value.status_code) == ("role_in_use", 409)
        assert {v["kind"] for v in used.value.violations} == {
            "distribution_rule",
            "deliverable",
            "approval_point",
            "setup",
        }
        spare = await svc.create_role(
            world.project_id, {"code": "SPARE", "party_kind": "specialist"}, actor_id=world.manager
        )
        await svc.delete_role(world.project_id, spare.id, actor_id=world.manager)


async def test_two_releases_issued_at_once_end_issued_or_refused_never_broken(world: DesignWorld) -> None:
    """Finding 18: a transmittal number collision rolls the session back under the issue."""
    await _rule(world)
    releases = []
    for _ in range(2):
        _d, rev = await drawing_with_revision(world, "ARCH")
        releases.append(await approved_release(world, [rev]))

    async def issue(release_id: uuid.UUID) -> str:
        async with world.factory() as s:
            try:
                await DesignService(s).issue_release(world.project_id, release_id, actor_id=world.manager)
            except DesignError as exc:
                await s.rollback()
                return exc.code
            await s.commit()
            return "issued"

    outcomes = await asyncio.gather(*(issue(r) for r in releases))
    assert set(outcomes) <= {"issued", "concurrent_issue"}, outcomes
    assert "issued" in outcomes
    for release_id, outcome in zip(releases, outcomes, strict=True):
        row = await _release(world, release_id)
        assert row.status == ("issued" if outcome == "issued" else "ready")
        assert len(row.transmittal_ids) == (1 if outcome == "issued" else 0)
