# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project governance end to end on PostgreSQL: decisions, snapshots, binding
documents and change control, staleness, owner change, model change, and the
approval-route subscribers.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.models import (
    GovernanceCheck,
    GovernanceCondition,
    GovernanceDecision,
    ImmutableRecordError,
)
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import (
    World,
    add_revision,
    areas,
    build_world,
    decide,
    documents,
    gate,
    prepare_gate,
)

# Same instant as the fixtures' decide() default, kept local to this file.
TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio

G1 = "strategy_to_brief"


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        yield await build_world(factory)


async def _project_phase(w: World) -> str | None:
    from app.modules.projects.models import Project

    async with w.factory() as s:
        return (await s.get(Project, w.project_id)).phase


async def test_go_makes_documents_binding_and_moves_the_phase_mirror(world: World) -> None:
    g = await prepare_gate(world, G1)
    decision = await decide(world, g.id, "go")
    after = await gate(world, G1)
    assert after.status == "decided" and after.last_outcome == "go"
    doc = (await documents(world))["business_case"]
    assert doc.status == "binding"
    assert doc.bound_revision_id is not None and doc.bound_content_hash == "business_case-hash-1"
    assert await _project_phase(world) == "brief"
    assert decision.snapshot["documents"]
    async with world.factory() as s:
        from app.modules.approval_routes.models import Instance

        inst = await s.get(Instance, decision.approval_instance_id)
        assert inst.status == "approved"


async def test_snapshot_stays_frozen_after_the_document_changes(world: World) -> None:
    g = await prepare_gate(world, G1)
    decision = await decide(world, g.id, "go")
    frozen = {d["doc_type"]: d for d in decision.snapshot["documents"]}["business_case"]
    async with world.factory() as s:
        new_rev = await add_revision(s, world.containers["business_case"], 2, "business_case-hash-2")
        await s.commit()
    async with world.factory() as s:
        stored = await s.get(GovernanceDecision, decision.id)
        again = {d["doc_type"]: d for d in stored.snapshot["documents"]}["business_case"]
    assert again == frozen
    assert again["content_hash"] == "business_case-hash-1"
    doc = (await documents(world))["business_case"]
    assert str(doc.bound_revision_id) != str(new_rev)  # 4: the binding revision stays in force


async def test_go_is_refused_while_a_required_document_is_a_draft_and_a_condition_lifts_it(world: World) -> None:
    async with world.factory() as s:
        svc = GovernanceService(s)
        for a in await svc.repo.list_areas(world.project_id):
            await svc.update_area(
                world.project_id, a.id, changes={"owner_user_id": world.owner}, actor_id=world.manager
            )
        await s.commit()
    g = await gate(world, G1)
    async with world.factory() as s:
        svc = GovernanceService(s)
        await svc.start_preparation(world.project_id, g.id, actor_id=world.owner)
        for a in await svc.repo.list_areas(world.project_id):
            await svc.confirm_check(world.project_id, g.id, a.id, status="ready", rag="", note="", actor_id=world.owner)
        await svc.submit_gate(world.project_id, g.id, actor_id=world.owner)
        await s.commit()
    with pytest.raises(GovernanceError) as exc:
        await decide(world, g.id, "go")
    assert exc.value.code == "required_document_not_approved"
    cond = ev.ProposedCondition(
        area_code="cost_finance",
        document_type="business_case",
        text="Deliver the business case",
        owner_user_id=str(world.owner),
    )
    decision = await decide(world, g.id, "go_with_conditions", conditions=(cond,))
    async with world.factory() as s:
        rows = (
            (await s.execute(select(GovernanceCondition).where(GovernanceCondition.decision_id == decision.id)))
            .scalars()
            .all()
        )
    assert [r.document_type for r in rows] == ["business_case"]


async def test_hold_freezes_and_resume_opens_attempt_two(world: World) -> None:
    from datetime import date

    g = await prepare_gate(world, G1)
    await decide(world, g.id, "hold", hold_resume_date=date(2026, 12, 1))
    held = await gate(world, G1)
    assert held.status == "on_hold" and held.hold_resume_date == "2026-12-01"
    async with world.factory() as s:
        await GovernanceService(s).resume(world.project_id, g.id, actor_id=world.decider)
        await s.commit()
    resumed = await gate(world, G1)
    assert resumed.status == "in_preparation" and resumed.attempt_no == 2
    assert resumed.approval_instance_id is None


async def test_recycle_marks_the_copied_checks_stale_and_keeps_the_decision(world: World) -> None:
    g = await prepare_gate(world, G1)
    await decide(world, g.id, "recycle")
    after = await gate(world, G1)
    assert after.status == "in_preparation" and after.attempt_no == 2
    async with world.factory() as s:
        checks = (
            (
                await s.execute(
                    select(GovernanceCheck).where(GovernanceCheck.gate_id == g.id, GovernanceCheck.attempt_no == 2)
                )
            )
            .scalars()
            .all()
        )
        decisions = (
            (await s.execute(select(GovernanceDecision).where(GovernanceDecision.gate_id == g.id))).scalars().all()
        )
    assert checks and all(c.stale for c in checks)
    assert [d.attempt_no for d in decisions] == [1]


async def test_stop_makes_open_documents_read_only_and_survives_its_own_rejection_event(world: World) -> None:
    g = await prepare_gate(world, G1)
    decision = await decide(world, g.id, "stop")
    # The route rejection the stop itself fired arrives after the commit.
    await gov_events.handle_route_event(
        {"target_kind": "phase_gate", "target_id": str(g.id), "instance_id": str(decision.approval_instance_id)},
        decision="rejected",
        session_factory=world.factory,
    )
    assert (await gate(world, G1)).status == "decided"
    docs = await documents(world)
    assert docs["project_handbook"].read_only is True
    async with world.factory() as s:
        with pytest.raises(GovernanceError) as exc:
            await GovernanceService(s).attach_container(
                world.project_id,
                docs["project_handbook"].id,
                container_id=world.containers["project_handbook"],
                actor_id=world.owner,
            )
    assert exc.value.code == "document_read_only"


async def test_a_route_rejection_outside_a_decision_returns_the_review(world: World) -> None:
    g = await prepare_gate(world, G1)
    current = await gate(world, G1)
    await gov_events.handle_route_event(
        {"target_kind": "phase_gate", "target_id": str(g.id), "instance_id": str(current.approval_instance_id)},
        decision="rejected",
        session_factory=world.factory,
    )
    assert (await gate(world, G1)).status == "in_preparation"


async def test_reopen_keeps_the_decision_and_starts_attempt_two(world: World) -> None:
    g = await prepare_gate(world, G1)
    first = await decide(world, g.id, "go")
    async with world.factory() as s:
        with pytest.raises(GovernanceError):
            await GovernanceService(s).reopen(world.project_id, g.id, rationale=" ", actor_id=world.decider)
    async with world.factory() as s:
        await GovernanceService(s).reopen(world.project_id, g.id, rationale="Cost overrun", actor_id=world.decider)
        await s.commit()
    after = await gate(world, G1)
    assert after.status == "in_preparation" and after.attempt_no == 2
    assert await _project_phase(world) == "strategy"
    async with world.factory() as s:
        kept = await s.get(GovernanceDecision, first.id)
    assert kept.outcome == "go"


async def test_a_binding_document_changes_only_through_an_approved_change_request(world: World) -> None:
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    g = await prepare_gate(world, G1)
    await decide(world, g.id, "go")
    doc = (await documents(world))["business_case"]
    bound = doc.bound_revision_id
    async with world.factory() as s:
        new_rev = await add_revision(s, world.containers["business_case"], 2, "business_case-hash-2")
        await s.commit()
    async with world.factory() as s:
        cr = await GovernanceService(s).create_change_request(
            world.project_id,
            doc.id,
            reason="Updated cost plan",
            impact="",
            proposed_revision_id=None,
            actor_id=world.owner,
        )
        await s.commit()
    assert (await documents(world))["business_case"].bound_revision_id == bound
    async with world.factory() as s:
        routes = ApprovalRouteService(s)
        inst = await routes.get_instance(cr.approval_instance_id)
        step = (await routes.list_steps(inst.route_id))[0]
        await routes.submit_decision(
            inst.id, DecisionSubmit(step_id=step.id, decision="approved"), approver_id=world.decider
        )
        await s.commit()
    await gov_events.handle_route_event(
        {"target_kind": "frame_change", "target_id": str(cr.id), "decided_by": str(world.decider)},
        decision="approved",
        session_factory=world.factory,
    )
    doc = (await documents(world))["business_case"]
    assert doc.bound_revision_id == new_rev
    assert doc.bound_content_hash == "business_case-hash-2"


async def test_a_check_goes_stale_when_its_document_changes_after_confirmation(world: World) -> None:
    g = await prepare_gate(world, G1, submit=False)
    async with world.factory() as s:
        await add_revision(s, world.containers["business_case"], 2, "business_case-hash-2")
        await s.commit()
    async with world.factory() as s:
        detail = await GovernanceService(s).gate_detail(world.project_id, g.id, today=TODAY)
    assert any(b["code"] == "check_stale" and b["area_code"] == "cost_finance" for b in detail["blockers"])


async def test_an_owner_change_resets_that_areas_readiness_only(world: World) -> None:
    g = await prepare_gate(world, G1, submit=False)
    area = (await areas(world))["cost_finance"]
    async with world.factory() as s:
        await GovernanceService(s).update_area(
            world.project_id, area.id, changes={"owner_user_id": world.editor}, actor_id=world.manager
        )
        await s.commit()
    async with world.factory() as s:
        checks = {
            c.area_id: c
            for c in (await s.execute(select(GovernanceCheck).where(GovernanceCheck.gate_id == g.id))).scalars()
        }
    assert checks[area.id].status == "not_assessed" and checks[area.id].confirmed_by is None
    others = [c for aid, c in checks.items() if aid != area.id]
    assert others and all(c.status == "ready" for c in others)


async def test_a_model_change_needs_a_mapping_and_keeps_decided_gates(world: World) -> None:
    from app.modules.project_governance.catalogue import get_catalogue

    g = await prepare_gate(world, G1)
    await decide(world, g.id, "go")
    hoai = get_catalogue("hoai_lph")
    target = hoai.phases[0].code
    async with world.factory() as s:
        with pytest.raises(GovernanceError) as exc:
            await GovernanceService(s).change_model(
                world.project_id,
                source="shipped",
                catalogue_id="hoai_lph",
                version=None,
                mapping={},
                actor_id=world.manager,
                tenant_id=None,
            )
    assert exc.value.code == "phase_mapping_missing"
    async with world.factory() as s:
        await GovernanceService(s).change_model(
            world.project_id,
            source="shipped",
            catalogue_id="hoai_lph",
            version=None,
            mapping={"strategy": target, "brief": target},
            actor_id=world.manager,
            tenant_id=None,
        )
        await s.commit()
    async with world.factory() as s:
        svc = GovernanceService(s)
        all_gates = await svc.repo.list_gates(world.project_id, include_historic=True)
        model = await svc.require_model(world.project_id)
    historic = [x for x in all_gates if x.historic]
    assert [x.code for x in historic] == [G1]
    assert model.catalogue_id == "hoai_lph" and model.current_phase == target
    assert {x.code for x in all_gates if not x.historic} == {gg.code for gg in hoai.gates}


async def test_a_decision_row_refuses_to_be_changed(world: World) -> None:
    g = await prepare_gate(world, G1)
    decision = await decide(world, g.id, "go")
    async with world.factory() as s:
        row = await s.get(GovernanceDecision, decision.id)
        row.rationale = "rewritten"
        with pytest.raises(ImmutableRecordError):
            await s.flush()


async def test_overdue_conditions_escalate_and_block_the_next_gate(world: World) -> None:
    from datetime import date

    g = await prepare_gate(world, G1)
    cond = ev.ProposedCondition(
        area_code="cost_finance",
        document_type=None,
        text="Funding letter",
        owner_user_id=str(world.owner),
        due_date=date(2026, 10, 1),
    )
    await decide(world, g.id, "go_with_conditions", conditions=(cond,))
    async with world.factory() as s:
        late = await GovernanceService(s).escalate_overdue(world.project_id, today=TODAY)
        await s.commit()
    assert [c.status for c in late] == ["overdue"]
    g2 = await gate(world, "brief_to_concept")
    async with world.factory() as s:
        detail = await GovernanceService(s).gate_detail(world.project_id, g2.id, today=TODAY)
    assert any(b["code"] == "condition_overdue" for b in detail["blockers"])
    async with world.factory() as s:
        with pytest.raises(GovernanceError) as exc:
            await GovernanceService(s).waive_condition(
                world.project_id, late[0].id, rationale="", actor_id=world.decider
            )
    assert exc.value.code == "waiver_needs_rationale"


async def test_validation_payload_runs_through_every_rule(world: World) -> None:
    from app.core.validation.engine import ValidationContext
    from app.modules.project_governance.validators import GOVERNANCE_RULES

    async with world.factory() as s:
        payload = await GovernanceService(s).validation_payload(world.project_id, today=TODAY)
    ctx = ValidationContext(data=payload, metadata={"locale": "en"})
    by_rule = {rule.rule_id: await rule().validate(ctx) for rule in GOVERNANCE_RULES}
    assert len(by_rule) == len(GOVERNANCE_RULES) >= 7
    # Every rule read the payload the service built without raising and answered with results.
    assert all(isinstance(results, list) for results in by_rule.values())
    owners = by_rule["project_governance.area_has_owner"]
    assert owners and not any(r.passed for r in owners)  # nobody owns an area yet
