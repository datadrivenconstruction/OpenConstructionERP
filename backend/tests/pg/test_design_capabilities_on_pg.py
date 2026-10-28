# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``can`` flags against the writes they describe, option listings and the references they feed.

The flags are only worth returning if a button and its request cannot
disagree. So the first test does not assert a list of expected flags: it takes
whatever every row answers and runs each listed move against the real write,
in a session that is thrown away, and compares the two.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.errors import DesignError
from app.modules.design_management.models import (
    DesignApprovalPoint,
    DesignDeliverable,
    DesignPermit,
    DesignRelease,
    DesignReport,
    DesignReview,
    DesignReviewComment,
    DesignRole,
)
from app.modules.design_management.service import Caller, DesignService
from tests._pg import isolated_engine
from tests.pg.design_fixtures import DesignWorld, build_design_world, decide_instance, drawing_with_revision
from tests.pg.governance_fixtures import add_route

pytestmark = pytest.mark.asyncio

_WORDS = "Recorded in the test with enough words to count as a reason."


@pytest_asyncio.fixture
async def world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_design_world(factory)


def _all(world: DesignWorld, **over: bool) -> Caller:
    return Caller(actor_id=world.manager, **({"edit": True, "manage": True, "release": True} | over))


async def _populate(world: DesignWorld) -> dict[str, list[uuid.UUID]]:
    """Rows of every kind, in the states a first screen shows and a few later ones."""
    _d, rev = await drawing_with_revision(world, "ARCH")
    ids: dict[str, list[uuid.UUID]] = {}
    async with world.factory() as s:
        svc = DesignService(s)
        pid, actor = world.project_id, world.editor
        await add_route(s, pid, "design_release", world.approver)
        phase = (await svc.phases(pid))[0]["code"]
        ap = await svc.create_approval_point(pid, {"kind": "owner_approval"}, actor_id=actor)
        dl = await svc.create_deliverable(
            pid, {"title": "Plans", "phase_code": phase, "planned_count": 1}, actor_id=actor
        )
        empty = await svc.create_release(pid, {"revision_ids": []}, actor_id=actor)
        filled = await svc.create_release(pid, {"revision_ids": [str(rev)]}, actor_id=actor)
        planned = await svc.create_review(pid, {"phase_code": phase}, actor_id=actor)
        opened = await svc.create_review(pid, {"phase_code": phase}, actor_id=actor)
        comment = await svc.add_comment(pid, opened.id, {"text": "Check the stair width"}, actor_id=actor)
        answered = await svc.add_comment(pid, opened.id, {"text": "Check the door swing"}, actor_id=actor)
        await svc.comment_transition(pid, answered.id, "answered", actor_id=actor, answer=_WORDS)
        report = await svc.create_report(pid, {"kind_code": "geotechnical", "phase_code": phase}, actor_id=actor)
        moved = await svc.create_report(pid, {"kind_code": "geotechnical", "phase_code": phase}, actor_id=actor)
        for step in ("commissioned", "in_progress", "submitted"):
            await svc.report_transition(pid, moved.id, step, actor_id=actor)
        permit = await svc.create_permit(pid, {"title": "Permit", "profile_code": "neutral"}, actor_id=actor)
        ids = {
            "role": list(world.roles.values()),
            "approval_point": [ap.id],
            "deliverable": [dl.id],
            "release": [empty.id, filled.id],
            "review": [planned.id, opened.id],
            "comment": [comment.id, answered.id],
            "report": [report.id, moved.id],
            "permit": [permit.id],
        }
        await s.commit()
    return ids


_MODEL = {
    "role": DesignRole,
    "approval_point": DesignApprovalPoint,
    "deliverable": DesignDeliverable,
    "release": DesignRelease,
    "review": DesignReview,
    "comment": DesignReviewComment,
    "report": DesignReport,
    "permit": DesignPermit,
}


async def _write(svc: DesignService, pid: uuid.UUID, kind: str, row_id: uuid.UUID, action: str, c: Caller) -> None:
    """The write a ``can`` entry stands for: a transition target, or a named action."""
    a = c.actor_id
    if kind == "role":
        await svc.patch_role(pid, row_id, {"state": action}, actor_id=a)
    elif kind == "approval_point" and action == "submit":
        await svc.submit_approval_point(pid, row_id, actor_id=a)
    elif kind == "approval_point" and action == "reopen":
        await svc.reopen_approval_point(pid, row_id, actor_id=a)
    elif kind == "release":
        await svc.release_transition(pid, row_id, action, actor_id=a)
    elif kind == "review" and action == "conclude":
        await svc.conclude_review(pid, row_id, "accepted", actor_id=a)
    elif kind == "review":
        await svc.review_transition(pid, row_id, action, actor_id=a)
    elif kind == "comment":
        await svc.comment_transition(pid, row_id, action, actor_id=a, answer=_WORDS)
    elif kind == "report":
        await svc.report_transition(pid, row_id, action, actor_id=a, rationale=_WORDS)
    elif kind == "permit":
        await svc.permit_transition(pid, row_id, action, actor_id=a, may_manage=c.manage)
    else:
        raise AssertionError((kind, action))


async def _refusal(world: DesignWorld, kind: str, row_id: uuid.UUID, action: str, caller: Caller) -> str | None:
    async with world.factory() as s:  # never committed: every attempt starts from the stored state
        try:
            await _write(DesignService(s), world.project_id, kind, row_id, action, caller)
        except DesignError as exc:
            return exc.code
        return None


async def _can(world: DesignWorld, kind: str, row_id: uuid.UUID, caller: Caller) -> dict[str, Any]:
    async with world.factory() as s:
        return await DesignService(s).capabilities(await s.get(_MODEL[kind], row_id), caller)


#: Named actions whose write this test can run without more input. ``issue`` and ``approve`` of a release
#: and the waiver of a schedule line are pinned by their own tests.
_RUNNABLE = {"submit", "reopen", "conclude"}


async def test_every_flag_agrees_with_the_write_it_describes(world: DesignWorld) -> None:
    ids = await _populate(world)
    caller = _all(world)
    seen: dict[str, set[str]] = {}
    for kind, rows in ids.items():
        for row_id in rows:
            can = await _can(world, kind, row_id, caller)
            assert set(can["transitions"]) <= set(_states(kind)), (kind, can)
            flags = dict(can["transitions"]) | {k: v for k, v in can.items() if k in _RUNNABLE}
            for action, flag in flags.items():
                assert set(flag) == {"allowed", "applies", "reason"}, (kind, action, flag)
                if not flag["applies"]:
                    assert not flag["allowed"], (kind, action, flag)
                    continue
                refused = await _refusal(world, kind, row_id, action, caller)
                assert flag["allowed"] == (refused is None), (kind, action, flag, refused)
                assert flag["reason"] == refused, (kind, action, flag, refused)
                seen.setdefault(kind, set()).add(f"{action}:{flag['reason']}")
    # The population must hold both answers, or the comparison above proves nothing.
    assert "ready:release_empty" in seen["release"] and "ready:None" in seen["release"], seen
    assert "comments_closed:review_comments_open" in seen["review"], seen
    assert "submit:no_approval_route" in seen["approval_point"], seen
    assert "ready:permit_empty" in seen["permit"] and "submitted:permit_empty" in seen["permit"], seen
    assert "accepted:None" in seen["report"] and "commissioned:None" in seen["report"], seen
    assert all(reason.endswith(":None") for reason in seen["role"] | seen["comment"]), seen


def _states(kind: str) -> tuple[str, ...]:
    from app.modules.design_management import fsm

    return {
        "role": fsm.ROLE_STATES,
        "approval_point": (),
        "deliverable": (),
        "release": fsm.RELEASE_STATES,
        "review": fsm.REVIEW_STATES,
        "comment": fsm.COMMENT_STATES,
        "report": fsm.REPORT_STATES,
        "permit": fsm.PERMIT_STATES,
    }[kind]


async def test_without_the_edit_permission_every_move_is_forbidden_but_still_applies(world: DesignWorld) -> None:
    ids = await _populate(world)
    viewer = _all(world, edit=False, manage=False, release=False)
    for kind, rows in ids.items():
        for row_id in rows:
            can = await _can(world, kind, row_id, viewer)
            for target, flag in can["transitions"].items():
                assert (flag["allowed"], flag["reason"]) == (False, "forbidden"), (kind, target, flag)
    release = await _can(world, "release", ids["release"][1], viewer)
    assert (release["issue"]["allowed"], release["issue"]["reason"]) == (False, "forbidden")
    report = await _can(world, "report", ids["report"][0], viewer)
    assert report["edit_gate_fields"] == {"allowed": False, "applies": True, "reason": "manage_required"}


async def test_a_schedule_line_offers_the_waiver_and_no_typed_state(world: DesignWorld) -> None:
    ids = await _populate(world)
    line = ids["deliverable"][0]
    can = await _can(world, "deliverable", line, _all(world))
    assert can == {
        "transitions": {},
        "waive": {"allowed": True, "applies": True, "reason": None},
        "unwaive": {"allowed": False, "applies": False, "reason": None},
    }
    async with world.factory() as s:
        await DesignService(s).patch_deliverable(
            world.project_id, line, {"waived": True, "waived_rationale": _WORDS}, actor_id=world.editor
        )
        await s.commit()
    can = await _can(world, "deliverable", line, _all(world))
    assert (can["waive"]["applies"], can["unwaive"]["allowed"]) == (False, True)


async def test_a_permit_decision_is_a_managers_to_type_until_a_review_cycle_decides(world: DesignWorld) -> None:
    """Without a cycle a manager records the authority's answer; with one the state is read, so it does not apply."""
    from app.modules.review_authority.models import ReviewCycle

    async with world.factory() as s:
        svc = DesignService(s)
        permit = await svc.create_permit(
            world.project_id, {"title": "Permit", "profile_code": "neutral"}, actor_id=world.editor
        )
        permit.status = "under_review"
        await s.commit()
    manager = await _can(world, "permit", permit.id, _all(world))
    editor = await _can(world, "permit", permit.id, _all(world, manage=False))
    for target in ("approved", "partially_approved", "refused", "remarks"):
        assert manager["transitions"][target] == {"allowed": True, "applies": True, "reason": None}, target
        assert editor["transitions"][target] == {"allowed": False, "applies": True, "reason": "manage_required"}
        assert await _refusal(world, "permit", permit.id, target, _all(world, manage=False)) == "manage_required"
    assert manager["transitions"]["withdrawn"]["allowed"] and editor["transitions"]["withdrawn"]["allowed"]

    async with world.factory() as s:
        cycle = ReviewCycle(project_id=world.project_id, authority_name="Building authority", status="under_review")
        s.add(cycle)
        await s.flush()
        (await s.get(DesignPermit, permit.id)).review_cycle_id = cycle.id
        await s.commit()
    linked = (await _can(world, "permit", permit.id, _all(world)))["transitions"]
    assert linked["approved"] == {"allowed": False, "applies": False, "reason": "permit_state_read_from_cycle"}
    assert linked["partially_approved"] == {"allowed": True, "applies": True, "reason": None}, "always a person's"
    assert await _refusal(world, "permit", permit.id, "approved", _all(world)) == "permit_state_read_from_cycle"


async def test_a_rejected_approval_point_is_reopened_and_nothing_else_is(world: DesignWorld) -> None:
    async with world.factory() as s:
        await add_route(s, world.project_id, "design_approval_point", world.approver)
        svc = DesignService(s)
        ap = await svc.create_approval_point(world.project_id, {"kind": "owner_approval"}, actor_id=world.editor)
        with pytest.raises(DesignError) as early:
            await svc.reopen_approval_point(world.project_id, ap.id, actor_id=world.editor)
        assert (early.value.code, early.value.status_code) == ("approval_point_not_rejected", 409)
        sent = await svc.submit_approval_point(world.project_id, ap.id, actor_id=world.editor)
        await decide_instance(s, sent.approval_instance_id, world.approver, "rejected")
        assert await svc.catch_up_approvals(world.project_id) == 1
        await s.commit()
    rejected = await _can(world, "approval_point", ap.id, _all(world))
    assert rejected["reopen"] == {"allowed": True, "applies": True, "reason": None}
    assert rejected["submit"]["allowed"], "a rejected point may also go straight back to the route"
    async with world.factory() as s:
        svc = DesignService(s)
        row = await svc.reopen_approval_point(world.project_id, ap.id, actor_id=world.editor)
        assert (row.status, row.approval_instance_id, row.decided_by, row.decided_at) == ("open", None, None, None)
        await svc.patch_approval_point(world.project_id, ap.id, {"title": "Reworked"}, actor_id=world.editor)
        await s.commit()
    reopened = await _can(world, "approval_point", ap.id, _all(world))
    assert (reopened["reopen"]["applies"], reopened["submit"]["allowed"]) == (False, True)


# ── option listings and the references they feed ──


async def test_options_list_what_the_write_accepts_and_nothing_of_another_project(world: DesignWorld) -> None:
    from app.modules.contacts.models import Contact
    from app.modules.file_distribution.models import FileDistributionList
    from app.modules.project_governance.public import project_gates
    from app.modules.review_authority.models import ReviewCycle
    from tests.pg.governance_fixtures import add_project

    tenant, stranger = str(world.manager), str(world.outsider)
    async with world.factory() as s:
        other = await add_project(s, world.outsider, [])
        s.add_all(
            [
                Contact(contact_type="company", company_name="Own architects", tenant_id=tenant, created_by=tenant),
                Contact(contact_type="company", company_name="Foreign firm", tenant_id=stranger, created_by=stranger),
                FileDistributionList(owner_id=world.manager, project_id=world.project_id, name="Project list"),
                FileDistributionList(owner_id=world.manager, project_id=None, name="My own list"),
                FileDistributionList(owner_id=world.outsider, project_id=None, name="Somebody's list"),
                FileDistributionList(owner_id=world.outsider, project_id=other, name="Other project list"),
                ReviewCycle(project_id=world.project_id, authority_name="Building authority", status="submitted"),
                ReviewCycle(project_id=other, authority_name="Other authority", status="submitted"),
            ]
        )
        await s.commit()

    async def labels(kind: str) -> list[str]:
        async with world.factory() as s:
            out = await DesignService(s).options(world.project_id, kind, actor_id=world.manager, tenant_id=tenant)
        assert out["kind"] == kind and out["available"] is True and out["reason"] is None, out
        assert all(set(i) >= {"id", "label", "code"} and i["id"] and i["label"] for i in out["items"]), out
        return [i["label"] for i in out["items"]]

    assert await labels("contacts") == ["Own architects"]
    assert sorted(await labels("recipient_lists")) == ["My own list", "Project list"]
    assert await labels("review_cycles") == ["Building authority"]
    assert await labels("authority_submissions") == []
    async with world.factory() as s:
        svc = DesignService(s)
        gates = await svc.options(world.project_id, "governance_gates", actor_id=world.manager, tenant_id=tenant)
        assert [i["id"] for i in gates["items"]] == [str(g.id) for g in await project_gates(s, world.project_id)]
        assert gates["items"], "the neutral model has gates"
        nodes = await svc.options(world.project_id, "wbs_nodes", actor_id=world.manager, tenant_id=tenant)
        assert nodes["available"] is True
        packages = await svc.options(world.project_id, "contract_packages", actor_id=world.manager, tenant_id=tenant)
        assert packages == {
            "kind": "contract_packages",
            "available": False,
            "reason": "source_not_installed",
            "items": [],
        }
        forms = await svc.options(world.project_id, "forms", actor_id=world.manager, tenant_id=tenant)
        assert (forms["available"], forms["reason"], forms["items"]) == (False, "scheme_has_no_form_list", [])
        with pytest.raises(DesignError) as unknown:
            await svc.options(world.project_id, "users", actor_id=world.manager, tenant_id=tenant)
        assert unknown.value.code == "option_kind_unknown"
        await svc.change_scheme(
            world.project_id, actor_id=world.manager, tenant_id=tenant, source="shipped", scheme_id="de_planschluessel"
        )
        forms = await svc.options(world.project_id, "forms", actor_id=world.manager, tenant_id=tenant)
        scheme = await svc.scheme(await svc.get_setup(world.project_id))
        assert [i["id"] for i in forms["items"]] == [e.code for e in scheme.field("form").code_list]


async def test_a_gate_or_contact_from_elsewhere_is_not_stored(world: DesignWorld) -> None:
    """Both were written as given before: an id of another project or tenant stayed on the row."""
    from app.modules.contacts.models import Contact
    from app.modules.project_governance.public import project_gates

    tenant, stranger = str(world.manager), str(world.outsider)
    async with world.factory() as s:
        own = Contact(contact_type="company", company_name="Own architects", tenant_id=tenant, created_by=tenant)
        foreign = Contact(contact_type="company", company_name="Foreign", tenant_id=stranger, created_by=stranger)
        s.add_all([own, foreign])
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        gate = (await project_gates(s, world.project_id))[0]
        role = {"party_kind": "specialist", "title": "Fire"}
        for refused in (
            svc.create_role(
                world.project_id, role | {"contact_id": str(foreign.id)}, actor_id=world.editor, tenant_id=tenant
            ),
            svc.create_role(world.project_id, role | {"contact_id": str(own.id)}, actor_id=world.editor),
            svc.patch_role(
                world.project_id,
                world.roles["ARCH"],
                {"contact_id": str(foreign.id)},
                actor_id=world.editor,
                tenant_id=tenant,
            ),
        ):
            with pytest.raises(DesignError) as err:
                await refused
            assert (err.value.code, err.value.status_code) == ("contact_not_found", 404)
        with pytest.raises(DesignError) as no_gate:
            await svc.create_approval_point(
                world.project_id,
                {"kind": "owner_approval", "governance_gate_id": str(uuid.uuid4())},
                actor_id=world.editor,
            )
        assert (no_gate.value.code, no_gate.value.status_code) == ("governance_gate_not_found", 404)
        made = await svc.create_role(
            world.project_id, role | {"contact_id": str(own.id)}, actor_id=world.editor, tenant_id=tenant
        )
        assert made.contact_id == own.id
        ap = await svc.create_approval_point(
            world.project_id, {"kind": "owner_approval", "governance_gate_id": str(gate.id)}, actor_id=world.editor
        )
        assert ap.governance_gate_id == gate.id
        with pytest.raises(DesignError) as patched:
            await svc.patch_approval_point(
                world.project_id, ap.id, {"governance_gate_id": str(uuid.uuid4())}, actor_id=world.editor
            )
        assert patched.value.code == "governance_gate_not_found"


async def test_a_role_in_use_names_what_still_points_at_it(world: DesignWorld) -> None:
    async with world.factory() as s:
        svc = DesignService(s)
        phase = (await svc.phases(world.project_id))[0]["code"]
        line = await svc.create_deliverable(
            world.project_id,
            {"code": "DL-9", "title": "Concept plans", "phase_code": phase, "role_id": str(world.roles["ARCH"])},
            actor_id=world.editor,
        )
        with pytest.raises(DesignError) as used:
            await svc.delete_role(world.project_id, world.roles["ARCH"], actor_id=world.editor)
    assert used.value.code == "role_in_use"
    assert used.value.violations == [
        {"code": "role_in_use", "kind": "deliverable", "id": str(line.id), "label": "DL-9 Concept plans", "ref": "DL-9"}
    ]


async def test_numbering_schemes_are_listed_by_the_governance_catalogue_listing(world: DesignWorld) -> None:
    """The scheme picker reads GET /v1/project-governance/catalogues?kind=drawing_numbering; this is its store call."""
    from app.modules.design_management.catalogue import NUMBERING_KIND, REPORTS_KIND
    from app.modules.project_governance.catalogue_store import CatalogueStore

    assert NUMBERING_KIND == "drawing_numbering"
    async with world.factory() as s:
        store = CatalogueStore(s)
        schemes = await store.list_available(str(world.manager), kind=NUMBERING_KIND, country_code="DE")
        reports = await store.list_available(str(world.manager), kind=REPORTS_KIND)
    ids = {i["id"] for i in schemes}
    assert {"iso19650_generic", "simple_sequential", "de_planschluessel"} <= ids, ids
    assert reports, "the reports catalogue is listed the same way"
