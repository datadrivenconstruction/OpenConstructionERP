# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A gate only moves the way its lifecycle says, over HTTP against PostgreSQL.

Every test here starts from a move that used to be accepted and left a gate in
a state nothing could leave: a decided gate put back in preparation by an
editor, a reopened gate the phase had already passed, a model change that ran
into its own history, a decision recorded on a route that never closed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.models import GovernanceDecision, GovernanceGate, GovernanceModel
from app.modules.project_governance.permissions import register_governance_permissions
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import (
    World,
    add_role_route,
    add_route,
    build_world,
    client_as,
    decide,
    documents,
    gate,
    prepare_gate,
    project_url,
)

pytestmark = pytest.mark.asyncio

G1 = "strategy_to_brief"
G2 = "brief_to_concept"


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


async def _model(w: World) -> GovernanceModel:
    async with w.factory() as s:
        return (await s.execute(select(GovernanceModel).where(GovernanceModel.project_id == w.project_id))).scalar_one()


async def _post(w: World, user: uuid.UUID, role: str, path: str, json: dict | None = None, **params):
    async with client_as(w, user, role) as c:
        return await c.post(f"{project_url(w)}/{path}", json=json or {}, params=params)


async def _can(w: World, gate_id: uuid.UUID, user: uuid.UUID, role: str) -> dict:
    async with client_as(w, user, role) as c:
        r = await c.get(f"{project_url(w)}/gates/{gate_id}")
    assert r.status_code == 200, r.text
    return r.json()["can"]


# ── the server date is the only date on a write ──


async def test_a_decision_is_judged_on_the_server_date_whatever_the_client_sends(world: World) -> None:
    today = datetime.now(UTC).date()
    g1 = await prepare_gate(world, G1)
    late = ev.ProposedCondition(
        area_code="cost_finance",
        document_type=None,
        text="Funding letter",
        owner_user_id=str(world.owner),
        due_date=today - timedelta(days=1),
    )
    await decide(world, g1.id, "go_with_conditions", conditions=(late,), today=today)
    g2 = await prepare_gate(world, G2)

    r = await _post(world, world.decider, "manager", f"gates/{g2.id}/decide", {"outcome": "go"}, today="2000-01-01")

    assert r.status_code == 422, r.text
    assert "condition_overdue" in {v["code"] for v in r.json()["detail"]["violations"]}
    assert (await gate(world, G2)).status == "in_review"
    # the screen agrees with the endpoint even when it is shown another day
    async with client_as(world, world.decider, "manager") as c:
        can = (await c.get(f"{project_url(world)}/gates/{g2.id}", params={"today": "2000-01-01"})).json()["can"]
    assert can["go"] is False and can["go_reason"] == "condition_overdue"


async def test_escalation_runs_on_the_server_date_whatever_the_client_sends(world: World) -> None:
    today = datetime.now(UTC).date()
    g1 = await prepare_gate(world, G1)
    late = ev.ProposedCondition(
        area_code="cost_finance",
        document_type=None,
        text="Funding letter",
        owner_user_id=str(world.owner),
        due_date=today - timedelta(days=1),
    )
    await decide(world, g1.id, "go_with_conditions", conditions=(late,), today=today)

    r = await _post(world, world.decider, "manager", "conditions/escalate", today="2000-01-01")

    assert r.status_code == 200, r.text
    assert [c["status"] for c in r.json()["items"]] == ["overdue"]


# ── prepare and resume ──


async def test_prepare_does_not_take_a_gate_out_of_a_decision_a_hold_or_a_review(world: World) -> None:
    g = await prepare_gate(world, G1)
    in_review = await _post(world, world.owner, "editor", f"gates/{g.id}/prepare")
    assert (in_review.status_code, _code(in_review)) == (409, "invalid_transition")
    assert (await gate(world, G1)).status == "in_review"

    hold_until = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    held = await _post(
        world,
        world.decider,
        "manager",
        f"gates/{g.id}/decide",
        {"outcome": "hold", "rationale": "Waiting for the land purchase", "hold_resume_date": hold_until},
    )
    assert held.status_code == 201, held.text
    on_hold = await _post(world, world.owner, "editor", f"gates/{g.id}/prepare")
    assert (on_hold.status_code, _code(on_hold)) == (409, "invalid_transition")
    after = await gate(world, G1)
    assert (after.status, after.attempt_no) == ("on_hold", 1)


async def test_prepare_does_not_undo_a_decision(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(world, g.id, "go")

    r = await _post(world, world.owner, "editor", f"gates/{g.id}/prepare")

    assert (r.status_code, _code(r)) == (409, "invalid_transition")
    after = await gate(world, G1)
    assert (after.status, after.attempt_no, after.last_outcome) == ("decided", 1, "go")


async def test_resume_is_only_for_a_held_gate(world: World) -> None:
    g = await prepare_gate(world, G1)
    in_review = await _post(world, world.decider, "manager", f"gates/{g.id}/resume")
    assert (in_review.status_code, _code(in_review)) == (409, "gate_not_on_hold")
    assert (await gate(world, G1)).status == "in_review"

    await decide(world, g.id, "go")
    decided = await _post(world, world.decider, "manager", f"gates/{g.id}/resume")
    assert (decided.status_code, _code(decided)) == (409, "gate_not_on_hold")
    after = await gate(world, G1)
    assert (after.status, after.attempt_no) == ("decided", 1)


async def test_a_held_gate_is_resumed_by_its_decider_and_can_be_decided_again(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(
        world,
        g.id,
        "hold",
        hold_resume_date=datetime.now(UTC).date() + timedelta(days=30),
        today=datetime.now(UTC).date(),
    )
    assert (await _can(world, g.id, world.decider, "manager"))["resume"] is True
    stranger = await _can(world, g.id, world.manager, "manager")
    assert stranger["resume"] is False and stranger["resume_reason"] == "decider_not_entitled"

    refused = await _post(world, world.manager, "manager", f"gates/{g.id}/resume")
    assert (refused.status_code, _code(refused)) == (403, "decider_not_entitled")
    resumed = await _post(world, world.decider, "manager", f"gates/{g.id}/resume")
    assert resumed.status_code == 200, resumed.text
    assert (resumed.json()["status"], resumed.json()["attempt_no"]) == ("in_preparation", 2)

    again = await prepare_gate(world, G1)
    decision = await decide(world, again.id, "go")
    assert decision.attempt_no == 2


# ── reopen ──


async def test_reopening_a_passed_gate_takes_the_phase_back_so_it_can_be_submitted_again(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(world, g.id, "go")
    assert (await _model(world)).current_phase == "brief"

    r = await _post(world, world.decider, "manager", f"gates/{g.id}/reopen", {"rationale": "Cost overrun"})

    assert r.status_code == 200, r.text
    assert (await _model(world)).current_phase == "strategy"
    submitted = await _post(world, world.owner, "editor", f"gates/{g.id}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "in_review" and submitted.json()["attempt_no"] == 2


async def test_preparing_the_next_gate_does_not_lock_the_one_before(world: World) -> None:
    """Preparation is open to every editor and has no way back, so it must not block a reopen."""
    g1 = await prepare_gate(world, G1)
    await decide(world, g1.id, "go")
    g2 = await prepare_gate(world, G2, submit=False)
    assert (await gate(world, G2)).status == "in_preparation"
    can = await _can(world, g1.id, world.decider, "manager")
    assert can["reopen"] is True

    r = await _post(world, world.decider, "manager", f"gates/{g1.id}/reopen", {"rationale": "Cost overrun"})

    assert r.status_code == 200, r.text
    assert (await _model(world)).current_phase == "strategy"
    # The prepared gate waits: it cannot be submitted while the project is behind its phase.
    late = await _post(world, world.owner, "editor", f"gates/{g2.id}/submit")
    assert late.status_code == 409, late.text


async def test_a_gate_is_not_reopened_behind_a_later_gate_that_was_started(world: World) -> None:
    g1 = await prepare_gate(world, G1)
    await decide(world, g1.id, "go")
    g2 = await prepare_gate(world, G2)
    can = await _can(world, g1.id, world.decider, "manager")
    assert can["reopen"] is False and can["reopen_reason"] == "later_gate_active"

    r = await _post(world, world.decider, "manager", f"gates/{g1.id}/reopen", {"rationale": "Cost overrun"})

    assert (r.status_code, _code(r)) == (409, "later_gate_active")
    assert (await gate(world, G1)).status == "decided"
    assert (await gate(world, G2)).id == g2.id and (await _model(world)).current_phase == "brief"


async def test_a_gate_the_phase_is_not_at_cannot_be_decided(world: World) -> None:
    """The phase can sit behind a gate in review only through a rewind; the decision has to wait for it."""
    g1 = await prepare_gate(world, G1)
    await decide(world, g1.id, "go")
    g2 = await prepare_gate(world, G2)
    async with world.factory() as s:
        model = (
            await s.execute(select(GovernanceModel).where(GovernanceModel.project_id == world.project_id))
        ).scalar_one()
        model.current_phase = "strategy"
        await s.commit()
    can = await _can(world, g2.id, world.decider, "manager")
    assert can["decide"] is False and can["decide_reason"] == "gate_out_of_order"

    r = await _post(world, world.decider, "manager", f"gates/{g2.id}/decide", {"outcome": "go"})

    assert (r.status_code, _code(r)) == (409, "gate_out_of_order")
    assert (await _model(world)).current_phase == "strategy"


async def test_only_the_decider_or_a_route_approver_reopens(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(world, g.id, "go")
    stranger = await _can(world, g.id, world.manager, "manager")
    assert stranger["reopen"] is False and stranger["reopen_reason"] == "decider_not_entitled"
    assert (await _can(world, g.id, world.decider, "manager"))["reopen"] is True

    r = await _post(world, world.manager, "manager", f"gates/{g.id}/reopen", {"rationale": "I disagree"})

    assert (r.status_code, _code(r)) == (403, "decider_not_entitled")
    assert (await gate(world, G1)).status == "decided"


# ── model change ──


async def _change_model(w: World, catalogue_id: str, mapping: dict[str, str]):
    return await _post(
        w,
        w.manager,
        "manager",
        "model/change",
        {"catalogue_source": "shipped", "catalogue_id": catalogue_id, "mapping": mapping},
    )


async def _hoai_first_phase() -> str:
    from app.modules.project_governance.catalogue import get_catalogue

    return get_catalogue("hoai_lph").phases[0].code


async def test_pinning_the_same_catalogue_again_is_refused(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(world, g.id, "go")

    r = await _change_model(world, "neutral", {"strategy": "strategy", "brief": "brief"})

    assert (r.status_code, _code(r)) == (409, "model_unchanged")
    assert (await gate(world, G1)).historic is False


async def test_going_back_to_a_model_revives_the_gate_it_decided(world: World) -> None:
    g = await prepare_gate(world, G1)
    first = await decide(world, g.id, "go")
    target = await _hoai_first_phase()
    away = await _change_model(world, "hoai_lph", {"strategy": target, "brief": target})
    assert away.status_code == 200, away.text
    assert (await gate(world, G1)).historic is True
    assert (await documents(world))["business_case"].status == "superseded"

    back = await _change_model(world, "neutral", {target: "brief"})

    assert back.status_code == 200, back.text
    async with world.factory() as s:
        rows = list(
            (
                await s.execute(
                    select(GovernanceGate).where(
                        GovernanceGate.project_id == world.project_id, GovernanceGate.code == G1
                    )
                )
            ).scalars()
        )
        kept = await s.get(GovernanceDecision, first.id)
    assert [(r.id, r.historic, r.status) for r in rows] == [(g.id, False, "decided")]
    assert kept.gate_id == g.id and kept.outcome == "go"
    assert (await _model(world)).current_phase == "brief"
    doc = (await documents(world))["business_case"]
    assert doc.status == "binding" and doc.bound_content_hash == "business_case-hash-1"


async def test_a_historic_gate_takes_no_further_moves(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(world, g.id, "stop", rationale="Site not available")
    assert (await _model(world)).stopped is True
    target = await _hoai_first_phase()
    assert (await _change_model(world, "hoai_lph", {"strategy": target})).status_code == 200

    r = await _post(world, world.decider, "manager", f"gates/{g.id}/reopen", {"rationale": "Changed our mind"})

    assert (r.status_code, _code(r)) == (409, "gate_historic")
    assert (await _model(world)).stopped is True


async def test_a_model_change_cancels_the_review_of_a_gate_it_removes(world: World) -> None:
    from app.modules.approval_routes.models import Instance

    g = await prepare_gate(world, G1)
    instance_id = (await gate(world, G1)).approval_instance_id
    assert instance_id is not None
    target = await _hoai_first_phase()

    r = await _change_model(world, "hoai_lph", {"strategy": target})

    assert r.status_code == 200, r.text
    async with world.factory() as s:
        assert (await s.get(Instance, instance_id)).status == "cancelled"
        assert await s.get(GovernanceGate, g.id) is None


# ── capabilities per outcome, and routes that answer in their own words ──


async def test_the_final_approver_who_approved_in_the_approval_screen_can_still_record_the_go(world: World) -> None:
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        routes = ApprovalRouteService(s)
        instance = await routes.get_instance((await gate(world, G1)).approval_instance_id)
        step = (await routes.list_steps(instance.route_id))[0]
        await routes.submit_decision(
            instance.id, DecisionSubmit(step_id=step.id, decision="approved"), approver_id=world.decider
        )
        await s.commit()

    can = await _can(world, g.id, world.decider, "manager")

    assert can["decide"] is True and "decide_reason" not in can
    assert can["go"] is True
    assert can["outcomes"]["go"] == {"allowed": True, "reason": None}
    assert can["outcomes"]["go_with_conditions"] == {"allowed": True, "reason": None}
    for outcome in ("hold", "recycle", "stop"):
        assert can["outcomes"][outcome] == {"allowed": False, "reason": "route_not_pending"}, outcome
    stop = await _post(world, world.decider, "manager", f"gates/{g.id}/decide", {"outcome": "stop", "rationale": "No"})
    assert (stop.status_code, _code(stop)) == (409, "route_not_pending")
    go = await _post(world, world.decider, "manager", f"gates/{g.id}/decide", {"outcome": "go"})
    assert go.status_code == 201, go.text
    # somebody else never gets the dialog, on any outcome
    other = await _can(world, g.id, world.manager, "manager")
    assert other["decide"] is False and not any(o["allowed"] for o in other["outcomes"].values())


async def test_every_outcome_is_open_to_the_entitled_decider_of_a_pending_route(world: World) -> None:
    g = await prepare_gate(world, G1)

    can = await _can(world, g.id, world.decider, "manager")

    assert can["decide"] is True
    assert {k: v["allowed"] for k, v in can["outcomes"].items()} == dict.fromkeys(ev.OUTCOMES, True)
    editor = await _can(world, g.id, world.editor, "editor")
    assert editor["decide"] is False and editor["decide_reason"] == "missing_permission"
    assert {v["reason"] for v in editor["outcomes"].values()} == {"missing_permission"}
    assert (editor["resume"], editor["reopen"], editor["add_condition"]) == (False, False, False)


async def test_a_gate_whose_route_instance_is_gone_still_reads(world: World) -> None:
    g = await prepare_gate(world, G1)
    async with world.factory() as s:
        row = await s.get(GovernanceGate, g.id)
        row.approval_instance_id = uuid.uuid4()
        await s.commit()

    can = await _can(world, g.id, world.decider, "manager")

    assert can["decide"] is False and can["decide_reason"] == "route_not_pending"
    r = await _post(world, world.decider, "manager", f"gates/{g.id}/decide", {"outcome": "go"})
    assert (r.status_code, _code(r)) == (409, "route_not_pending")


async def test_a_go_is_not_recorded_while_the_final_step_still_needs_other_approvers(world: World) -> None:
    """A role-based final step in mode all is not cleared by one approval."""
    from app.modules.approval_routes.models import Instance

    async with world.factory() as s:
        route_id = await add_role_route(s, world.project_id, "phase_gate", "manager", "all")
        await s.commit()
    async with client_as(world, world.manager, "manager") as c:
        pinned = await c.patch(f"{project_url(world)}/model", json={"decision_route_id": str(route_id)})
    assert pinned.status_code == 200, pinned.text
    g = await prepare_gate(world, G1)

    r = await _post(world, world.decider, "manager", f"gates/{g.id}/decide", {"outcome": "go"})

    assert (r.status_code, _code(r)) == (409, "route_needs_more_approvals")
    after = await gate(world, G1)
    assert after.status == "in_review"
    async with world.factory() as s:
        decisions = (
            await s.execute(
                select(func.count()).select_from(GovernanceDecision).where(GovernanceDecision.gate_id == g.id)
            )
        ).scalar_one()
        instance = await s.get(Instance, after.approval_instance_id)
    assert decisions == 0 and instance.status == "pending"
    assert (await _model(world)).current_phase == "strategy"


async def test_a_route_pinned_during_review_does_not_move_the_running_decision(world: World) -> None:
    """Route pins are not frozen in review. The gate under decision keeps the route it started on."""
    from app.modules.approval_routes.models import Instance
    from app.modules.project_governance.service import GovernanceService

    async def _route_of(gate_code: str) -> uuid.UUID:
        row = await gate(world, gate_code)
        async with world.factory() as s:
            return (
                await s.execute(select(Instance.route_id).where(Instance.id == row.approval_instance_id))
            ).scalar_one()

    g1 = await prepare_gate(world, G1)
    running = (await gate(world, G1)).approval_instance_id
    assert await _route_of(G1) == world.gate_route_id

    async with world.factory() as s:
        other = await add_route(s, world.project_id, "phase_gate", world.manager)
        await GovernanceService(s).update_settings(
            world.project_id,
            four_eyes=None,
            decision_route_id=other,
            change_route_id=None,
            fields_set={"decision_route_id"},
            actor_id=world.manager,
        )
        await s.commit()
    assert (await _model(world)).decision_route_id == other

    assert (await gate(world, G1)).approval_instance_id == running
    assert await _route_of(G1) == world.gate_route_id
    # The approver of the new route has no say on the running one; the approver it started with has.
    newcomer = await _post(world, world.manager, "manager", f"gates/{g1.id}/decide", {"outcome": "go"})
    assert newcomer.status_code == 403, newcomer.text
    assert newcomer.json()["detail"]["code"] == "decider_not_entitled"
    started_with = await _post(world, world.decider, "manager", f"gates/{g1.id}/decide", {"outcome": "go"})
    assert started_with.status_code == 201, started_with.text

    # The next gate starts on the route pinned now.
    await prepare_gate(world, G2)
    assert await _route_of(G2) == other
