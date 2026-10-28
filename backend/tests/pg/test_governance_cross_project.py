# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Ids of another project, callers from outside the project, and who names the decider.

Every request goes over HTTP against PostgreSQL with the real project-access
and permission dependencies. Two projects exist side by side; the second one
must read exactly the same after every refused request.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.models import (
    GovernanceCondition,
    GovernanceDecision,
    GovernanceDocument,
    GovernanceModel,
)
from app.modules.project_governance.permissions import register_governance_permissions
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import (
    World,
    add_revision,
    add_route,
    areas,
    build_world,
    client_as,
    decide,
    documents,
    gate,
    prepare_gate,
    project_url,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

G1 = "strategy_to_brief"
DUE = (date.today() + timedelta(days=30)).isoformat()


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    register_governance_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        yield await build_world(factory)


def _code(response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def _fingerprint(w: World) -> dict:
    """Everything a stray write to this project would change."""
    async with w.factory() as s:
        docs = (
            await s.execute(
                select(GovernanceDocument.doc_type, GovernanceDocument.status, GovernanceDocument.container_id)
                .where(GovernanceDocument.project_id == w.project_id)
                .order_by(GovernanceDocument.doc_type)
            )
        ).all()
        model = (
            await s.execute(select(GovernanceModel).where(GovernanceModel.project_id == w.project_id))
        ).scalar_one()
        conditions = (
            await s.execute(
                select(GovernanceCondition.id, GovernanceCondition.status)
                .where(GovernanceCondition.project_id == w.project_id)
                .order_by(GovernanceCondition.id)
            )
        ).all()
        decisions = (
            await s.execute(
                select(func.count())
                .select_from(GovernanceDecision)
                .where(GovernanceDecision.project_id == w.project_id)
            )
        ).scalar_one()
    area_rows = await areas(w)
    return {
        "documents": [tuple(str(x) for x in row) for row in docs],
        "phase": model.current_phase,
        "routes": (model.decision_route_id, model.change_route_id),
        "owners": sorted((code, str(a.owner_user_id), a.applicable) for code, a in area_rows.items()),
        "gate": (await gate(w, G1)).status,
        "conditions": [tuple(str(x) for x in row) for row in conditions],
        "decisions": decisions,
    }


async def test_a_stranger_cannot_use_any_write_route(world: World) -> None:
    g = await prepare_gate(world, G1, submit=False)
    area = (await areas(world))["scope"]
    doc = (await documents(world))["business_case"]
    before = await _fingerprint(world)
    url = project_url(world)
    calls = [
        ("put", f"{url}/model", {"catalogue_source": "shipped", "catalogue_id": "neutral"}),
        ("patch", f"{url}/model", {"four_eyes": False}),
        ("post", f"{url}/model/change", {"catalogue_source": "shipped", "catalogue_id": "riba_2020", "mapping": {}}),
        ("patch", f"{url}/areas/{area.id}", {"owner_user_id": str(world.outsider)}),
        ("post", f"{url}/gates/{g.id}/prepare", None),
        ("post", f"{url}/gates/{g.id}/submit", None),
        ("post", f"{url}/gates/{g.id}/reopen", {"rationale": "mine now"}),
        ("post", f"{url}/gates/{g.id}/resume", None),
        ("patch", f"{url}/gates/{g.id}", {"target_date": "2027-01-01"}),
        ("put", f"{url}/gates/{g.id}/checks/{area.id}", {"status": "ready"}),
        ("post", f"{url}/gates/{g.id}/checks/{area.id}/not-applicable", {"rationale": "no"}),
        ("post", f"{url}/gates/{g.id}/conditions", {"text": "x", "owner_user_id": str(world.outsider)}),
        ("post", f"{url}/documents", {"area_id": str(area.id), "doc_type": "scope_statement"}),
        ("post", f"{url}/documents/{doc.id}/attach", {"container_id": str(world.containers["business_case"])}),
        ("post", f"{url}/documents/{doc.id}/submit", None),
        ("post", f"{url}/documents/{doc.id}/return", None),
        ("post", f"{url}/documents/{doc.id}/change-requests", {"reason": "x"}),
        ("post", f"{url}/conditions/escalate", None),
        ("post", f"{url}/conditions/{uuid.uuid4()}/clear", {"evidence": "x"}),
        ("post", f"{url}/conditions/{uuid.uuid4()}/waive", {"rationale": "x"}),
    ]
    answers = {}
    # A manager elsewhere: every permission, no access to this project.
    async with client_as(world, world.outsider, "manager") as c:
        for method, path, body in calls:
            r = await c.request(method.upper(), path, json=body)
            answers[f"{method} {path.removeprefix(url)}"] = r.status_code
    assert {k: v for k, v in answers.items() if v != 404} == {}
    assert await _fingerprint(world) == before


async def test_ids_of_another_project_are_refused_on_every_route(world: World) -> None:
    other = await build_world(world.factory)
    await prepare_gate(other, G1, submit=False)
    their_gate = await gate(other, G1)
    their_area = (await areas(other))["scope"]
    their_doc = (await documents(other))["business_case"]
    their_before = await _fingerprint(other)

    g = await gate(world, G1)
    mine = (await documents(world))["business_case"]
    my_area = (await areas(world))["scope"]
    my_before = await _fingerprint(world)
    url = project_url(world)

    not_found = [
        ("patch", f"{url}/areas/{their_area.id}", {"name_override": "taken"}),
        ("put", f"{url}/gates/{g.id}/checks/{their_area.id}", {"status": "ready"}),
        ("post", f"{url}/gates/{g.id}/checks/{their_area.id}/not-applicable", {"rationale": "no"}),
        ("put", f"{url}/gates/{their_gate.id}/checks/{my_area.id}", {"status": "ready"}),
        ("post", f"{url}/gates/{their_gate.id}/prepare", None),
        ("post", f"{url}/gates/{their_gate.id}/submit", None),
        ("post", f"{url}/gates/{their_gate.id}/decide", {"outcome": "go"}),
        ("post", f"{url}/gates/{their_gate.id}/reopen", {"rationale": "x"}),
        ("post", f"{url}/gates/{their_gate.id}/resume", None),
        ("patch", f"{url}/gates/{their_gate.id}", {"target_date": "2027-01-01"}),
        ("post", f"{url}/gates/{their_gate.id}/conditions", {"text": "x"}),
        ("get", f"{url}/gates/{their_gate.id}/decisions", None),
        ("post", f"{url}/documents", {"area_id": str(their_area.id), "doc_type": "scope_statement"}),
        ("post", f"{url}/documents/{their_doc.id}/attach", {"container_id": str(world.containers["business_case"])}),
        ("post", f"{url}/documents/{their_doc.id}/submit", None),
        ("post", f"{url}/documents/{their_doc.id}/return", None),
        ("get", f"{url}/documents/{their_doc.id}/history", None),
        ("post", f"{url}/documents/{their_doc.id}/change-requests", {"reason": "x"}),
    ]
    answers = {}
    # The manager of this project has every permission here and none over there.
    async with client_as(world, world.manager, "manager") as c:
        for method, path, body in not_found:
            r = await c.request(method.upper(), path, json=body)
            answers[f"{method} {path.removeprefix(url)}"] = r.status_code
        foreign_container = await c.post(
            f"{url}/documents/{mine.id}/attach", json={"container_id": str(other.containers["business_case"])}
        )
    assert {k: v for k, v in answers.items() if v != 404} == {}
    assert foreign_container.status_code == 422 and _code(foreign_container) == "container_not_in_project"
    assert await _fingerprint(other) == their_before
    assert await _fingerprint(world) == my_before


async def test_only_a_pinned_route_of_the_project_decides_a_gate(world: World) -> None:
    """Who decides is a governance.manage setting; a route somebody else created never slips in."""
    bare = await build_world(world.factory, routes=False)
    g = await prepare_gate(bare, G1, submit=False)
    url = project_url(bare)
    async with world.factory() as s:
        # A stranger with route rights creates a route visible to every project, naming himself.
        global_route = await add_route(s, None, "phase_gate", world.outsider)  # type: ignore[arg-type]
        # An editor of the project creates a project route before anyone pinned one.
        unpinned = await add_route(s, bare.project_id, "phase_gate", bare.editor)
        own_gate_route = await add_route(s, bare.project_id, "phase_gate", bare.decider)
        own_change_route = await add_route(s, bare.project_id, "frame_change", bare.decider)
        await s.commit()

    async with client_as(bare, bare.owner, "editor") as c:
        no_pin = await c.post(f"{url}/gates/{g.id}/submit")
    assert no_pin.status_code == 422 and _code(no_pin) == "no_decision_route"
    assert (await gate(bare, G1)).status == "in_preparation"
    assert (await gate(bare, G1)).approval_instance_id is None

    async with client_as(bare, bare.manager, "manager") as c:
        refused = {
            "global": await c.patch(f"{url}/model", json={"decision_route_id": str(global_route)}),
            "other project": await c.patch(f"{url}/model", json={"decision_route_id": str(world.gate_route_id)}),
            "wrong kind": await c.patch(f"{url}/model", json={"decision_route_id": str(own_change_route)}),
            "unknown": await c.patch(f"{url}/model", json={"decision_route_id": str(uuid.uuid4())}),
            "change, global": await c.patch(f"{url}/model", json={"change_route_id": str(global_route)}),
        }
        assert {k: (r.status_code, _code(r)) for k, r in refused.items()} == dict.fromkeys(
            refused, (422, "route_not_pinnable")
        )
        still_none = await c.get(f"{url}/model")
        assert still_none.json()["decision_route_id"] is None
    async with client_as(bare, bare.editor, "editor") as c:
        editor_pin = await c.patch(f"{url}/model", json={"decision_route_id": str(unpinned)})
    assert editor_pin.status_code == 403

    async with client_as(bare, bare.manager, "manager") as c:
        pinned = await c.patch(f"{url}/model", json={"decision_route_id": str(own_gate_route)})
    assert pinned.status_code == 200 and pinned.json()["decision_route_id"] == str(own_gate_route)
    async with client_as(bare, bare.owner, "editor") as c:
        submitted = await c.post(f"{url}/gates/{g.id}/submit")
    assert submitted.status_code == 200 and submitted.json()["status"] == "in_review"
    # The stranger named by the global route still decides nothing here.
    async with client_as(bare, world.outsider, "manager") as c:
        stranger = await c.post(f"{url}/gates/{g.id}/decide", json={"outcome": "go"})
    assert stranger.status_code == 404

    async with client_as(bare, bare.manager, "manager") as c:
        unpinned_again = await c.patch(f"{url}/model", json={"decision_route_id": None})
    assert unpinned_again.status_code == 200 and unpinned_again.json()["decision_route_id"] is None


async def test_a_deactivated_pin_stops_deciding(world: World) -> None:
    from app.modules.approval_routes.models import Route

    g = await prepare_gate(world, G1, submit=False)
    async with world.factory() as s:
        (await s.get(Route, world.gate_route_id)).is_active = False
        await s.commit()
    async with client_as(world, world.owner, "editor") as c:
        r = await c.post(f"{project_url(world)}/gates/{g.id}/submit")
    assert r.status_code == 422 and _code(r) == "no_decision_route"


async def test_a_condition_owner_must_be_a_member_and_foreign_conditions_stay_out_of_reach(world: World) -> None:
    other = await build_world(world.factory)
    their_gate = await prepare_gate(other, G1)
    await decide(
        other,
        their_gate.id,
        "go_with_conditions",
        conditions=[
            ev.ProposedCondition(
                area_code=None,
                document_type=None,
                text="Their condition",
                owner_user_id=str(other.owner),
                due_date=date.today() + timedelta(days=30),
            )
        ],
    )
    async with other.factory() as s:
        their_condition = (
            await s.execute(select(GovernanceCondition.id).where(GovernanceCondition.project_id == other.project_id))
        ).scalar_one()
        foreign_revision = await add_revision(s, other.containers["business_case"], 2, "their-hash-2")
        await s.commit()
    their_before = await _fingerprint(other)

    g = await prepare_gate(world, G1)
    url = project_url(world)

    def _body(owner: uuid.UUID) -> dict:
        return {
            "outcome": "go_with_conditions",
            "rationale": "Proceed, one thing open",
            "conditions": [{"text": "Close the open point", "owner_user_id": str(owner), "due_date": DUE}],
        }

    async with client_as(world, world.decider, "manager") as c:
        outsider_owner = await c.post(f"{url}/gates/{g.id}/decide", json=_body(world.outsider))
        assert outsider_owner.status_code == 422 and _code(outsider_owner) == "owner_not_project_member"
        nobody = await c.post(f"{url}/gates/{g.id}/decide", json=_body(uuid.uuid4()))
        assert nobody.status_code == 422 and _code(nobody) == "owner_not_project_member"
    refused = await _fingerprint(world)
    assert refused["gate"] == "in_review" and refused["decisions"] == 0 and refused["conditions"] == []

    async with client_as(world, world.decider, "manager") as c:
        decided = await c.post(f"{url}/gates/{g.id}/decide", json=_body(world.owner))
        assert decided.status_code == 201
        later = await c.post(
            f"{url}/gates/{g.id}/conditions", json={"text": "One more", "owner_user_id": str(world.outsider)}
        )
        assert later.status_code == 422 and _code(later) == "owner_not_project_member"
        member = await c.post(
            f"{url}/gates/{g.id}/conditions", json={"text": "One more", "owner_user_id": str(world.editor)}
        )
        assert member.status_code == 201
        theirs_cleared = await c.post(f"{url}/conditions/{their_condition}/clear", json={"evidence": "done"})
        theirs_waived = await c.post(f"{url}/conditions/{their_condition}/waive", json={"rationale": "not needed"})
    assert (theirs_cleared.status_code, theirs_waived.status_code) == (404, 404)
    assert len((await _fingerprint(world))["conditions"]) == 2

    # The business case is binding now; a revision of the other project's container is no change to it.
    binding = (await documents(world))["business_case"]
    assert binding.status == "binding"
    async with client_as(world, world.owner, "editor") as c:
        cr = await c.post(
            f"{url}/documents/{binding.id}/change-requests",
            json={"reason": "Swap in their file", "proposed_revision_id": str(foreign_revision)},
        )
    assert cr.status_code == 422 and _code(cr) == "no_pending_revision"
    assert await _fingerprint(other) == their_before


async def test_the_condition_owner_check_is_also_in_the_service(world: World) -> None:
    """The seed and other modules call the service directly, so the rule cannot live in the router alone."""
    from app.modules.project_governance.errors import GovernanceError

    g = await prepare_gate(world, G1)
    with pytest.raises(GovernanceError) as exc:
        await decide(
            world,
            g.id,
            "go_with_conditions",
            conditions=[
                ev.ProposedCondition(
                    area_code=None,
                    document_type=None,
                    text="Close it",
                    owner_user_id=str(world.outsider),
                    due_date=date.today() + timedelta(days=30),
                )
            ],
        )
    assert exc.value.code == "owner_not_project_member" and exc.value.status_code == 422
    async with world.factory() as s:
        assert await GovernanceService(s).repo.list_decisions(world.project_id, g.id) == []


async def test_the_screens_read_what_the_caller_may_do(world: World) -> None:
    """Area document types, per-document flags and can.manage on a project without a model."""
    await prepare_gate(world, G1, submit=False)
    url = project_url(world)
    async with client_as(world, world.owner, "editor") as c:
        area_items = {a["code"]: a for a in (await c.get(f"{url}/areas")).json()["items"]}
        as_owner = {d["doc_type"]: d for d in (await c.get(f"{url}/documents")).json()["items"]}
    async with client_as(world, world.editor, "editor") as c:
        as_editor = {d["doc_type"]: d for d in (await c.get(f"{url}/documents")).json()["items"]}
    async with client_as(world, world.editor, "viewer") as c:
        as_viewer = {d["doc_type"]: d for d in (await c.get(f"{url}/documents")).json()["items"]}

    scope_types = {t["code"]: t for t in area_items["scope"]["document_types"]}
    assert set(scope_types) == {"requirements_brief", "scope_statement", "approval_conditions_register"}
    assert scope_types["requirements_brief"]["required_at_gates"] and scope_types["requirements_brief"]["tracked"]
    assert scope_types["scope_statement"]["name"]["key"] == "governance.catalogue.neutral.doc.scope_statement"
    assert all(t["tracked"] for t in scope_types.values()) == (set(scope_types) <= set(as_owner))

    # prepare_gate submitted the business case, so its owner may take it back but not submit again.
    submitted = as_owner["business_case"]
    assert submitted["status"] == "in_review"
    assert (submitted["can"]["return"], submitted["can"]["submit"]) == (True, False)
    assert submitted["can"]["submit_reason"] == "invalid_transition"
    draft = next(d for d in as_owner.values() if d["status"] == "draft")
    assert draft["can"]["attach"] is True and draft["can"]["return_reason"] == "invalid_transition"
    assert draft["can"]["submit"] is bool(draft["container_id"])
    assert as_editor[draft["doc_type"]]["can"]["attach_reason"] == "not_area_owner"
    assert as_viewer[draft["doc_type"]]["can"] == {
        "attach": False,
        "attach_reason": "missing_permission",
        "submit": False,
        "submit_reason": "missing_permission",
        "return": False,
        "return_reason": "missing_permission",
        "change_request": False,
        "change_request_reason": "missing_permission",
    }
    # Nothing is binding yet, so nobody can raise a change request; the owner reads why.
    assert draft["can"]["change_request_reason"] == "document_not_binding"
    assert as_editor[draft["doc_type"]]["can"]["change_request_reason"] == "not_area_owner"
    assert area_items["scope"]["can"] == {"add_document": True, "add_document_reason": None}
    async with client_as(world, world.editor, "editor") as c:
        editor_areas = {a["code"]: a for a in (await c.get(f"{url}/areas")).json()["items"]}
        untracked = next(
            (t["code"] for a in editor_areas.values() for t in a["document_types"] if not t["tracked"]), None
        )
        added = await c.post(
            f"{url}/documents",
            json={"area_id": editor_areas["scope"]["id"], "doc_type": untracked or "scope_statement"},
        )
    assert editor_areas["scope"]["can"] == {"add_document": False, "add_document_reason": "not_area_owner"}
    assert added.status_code == 403 and _code(added) == "not_area_owner"
    # The flag and the write agree.
    async with client_as(world, world.editor, "editor") as c:
        refused = await c.post(f"{url}/documents/{draft['id']}/submit")
    assert refused.status_code == 403 and _code(refused) == "not_area_owner"

    async with world.factory() as s:
        from tests.pg.governance_fixtures import add_project

        empty = await add_project(s, world.manager, [world.editor])
        await s.commit()
    empty_url = f"{project_url(world).rsplit('/', 1)[0]}/{empty}/model"
    async with client_as(world, world.manager, "manager") as c:
        for_manager = await c.get(empty_url)
    async with client_as(world, world.editor, "editor") as c:
        for_editor = await c.get(empty_url)
    assert (for_manager.status_code, _code(for_manager)) == (404, "model_missing")
    assert for_manager.json()["detail"]["can"] == {"manage": True}
    assert (for_editor.status_code, for_editor.json()["detail"]["can"]) == (404, {"manage": False})
