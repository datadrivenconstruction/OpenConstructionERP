# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The defects of the second review, each pinned on PostgreSQL.

The committed figure against a contract header that carries its changes, the
reconciliation with the cost model, recompute targets, anti-splitting, schedule
re-pinning, pinned routes, who may decide (assignees, deputies, four eyes),
abort and transfer, routes edited or reassigned behind the matrix, award
drafts, the overdue sweep, gate evidence and the demo seed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.commitment_release.errors import CommitmentError
from app.modules.commitment_release.events import handle_route_event
from app.modules.commitment_release.models import CommitmentItem, CommitmentLink, CommitmentMatrix, ReleaseDecision
from app.modules.commitment_release.service import CommitmentService
from tests._pg import isolated_engine
from tests.pg.commitment_fixtures import (
    World,
    add_contract,
    add_cost_line,
    add_project,
    build_world,
    decide,
    item,
    link,
    released_item,
    request,
    state,
)

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio
D = Decimal


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _committed(w: World, item_id: uuid.UUID) -> Decimal:
    async with w.factory() as s:
        svc = CommitmentService(s)
        matrix = await svc.require_matrix(w.project_id)
        project = await svc._project(w.project_id)
        _figs, committed, _why = await svc.committed_for_items(
            matrix, project, await svc.schedule_for(matrix), on_date=TODAY
        )
    return committed.get(item_id) or D("0")


async def _variation(w: World, amount: str, status: str, contract_id: uuid.UUID | None = None) -> uuid.UUID:
    from app.modules.variations.models import VariationOrder

    async with w.factory() as s:
        vo = VariationOrder(
            project_id=w.project_id,
            code=f"VO-{uuid.uuid4().hex[:6]}",
            title="Revised facade",
            final_cost_impact=D(amount),
            currency="EUR",
            status=status,
            affected_contract_id=contract_id,
        )
        s.add(vo)
        await s.commit()
        return vo.id


async def _header_takes(w: World, contract_id: uuid.UUID, variation_id: uuid.UUID, new_value: str) -> None:
    """What the platform's contract subscriber does when a variation completes: bump the header, mark the source."""
    from app.modules.contracts.models import Contract

    async with w.factory() as s:
        contract = await s.get(Contract, contract_id)
        contract.total_value = D(new_value)
        contract.metadata_ = {**(contract.metadata_ or {}), "variation_ids": [str(variation_id)]}
        await s.commit()


async def _release_row(w: World, release_id: uuid.UUID) -> ReleaseDecision:
    async with w.factory() as s:
        return await s.get(ReleaseDecision, release_id)


async def _decide(w: World, item_id: uuid.UUID, actor: uuid.UUID, decision: str = "approved", comment: str = ""):
    async with w.factory() as s:
        row = await CommitmentService(s).decide_release(
            w.project_id,
            item_id,
            decision=decision,
            comment=comment,
            conditions="",
            valid_until=None,
            actor_id=actor,
            caller_role="manager",
            today=TODAY,
        )
        await s.commit()
        return row


# ── findings 1 and 2: the committed figure ─────────────────────────────────


async def test_a_change_is_counted_once_before_and_after_it_moves_the_contract_header(world: World) -> None:
    iid = await released_item(world, "45000")
    cid = await add_contract(world, "40000")
    await link(world, iid, "contract", cid)
    vo = await _variation(world, "5000", "completed", cid)
    await link(world, iid, "variation_order", vo)
    # Not yet in the header: the contract and the change, each once.
    assert await _committed(world, iid) == D("45000")
    await _header_takes(world, cid, vo, "45000")
    # In the header now: the header alone. The old netting gave 40000, a plain sum 50000.
    assert await _committed(world, iid) == D("45000")


async def test_a_variation_counts_only_when_completed(world: World) -> None:
    iid = await released_item(world, "10000")
    vo = await _variation(world, "5000", "issued")
    await link(world, iid, "variation_order", vo)
    assert await _committed(world, iid) == D("0")
    from app.modules.variations.models import VariationOrder

    async with world.factory() as s:
        (await s.get(VariationOrder, vo)).status = "completed"
        await s.commit()
    assert await _committed(world, iid) == D("5000")


async def test_the_matrix_and_the_cost_model_differ_by_changes_that_moved_the_header_without_a_line(
    world: World,
) -> None:
    """The matrix reads the contract header; the cost model reads contract lines by cost line. A
    change that moved the header and added no line is in the first and not in the second, and that
    is the whole difference."""
    from app.modules.costmodel.repository import CostSpineRepository

    line = await add_cost_line(world, "CL-1")
    iid = await released_item(world, "45000")
    cid = await add_contract(world, "40000", cost_line_id=line)
    await link(world, iid, "contract", cid)
    vo = await _variation(world, "5000", "completed", cid)
    await _header_takes(world, cid, vo, "45000")
    async with world.factory() as s:
        by_line = await CostSpineRepository(s).committed_by_cost_line(world.project_id)
    cost_model = sum(by_line.values(), D("0"))
    matrix = await _committed(world, iid)
    assert (matrix, cost_model) == (D("45000"), D("40000"))
    assert matrix - cost_model == D("5000")


# ── finding 6: recompute may reach every recomputed state ──────────────────


async def test_linking_a_completed_contract_closes_a_released_item_and_unlinking_reopens_it(world: World) -> None:
    iid = await released_item(world, "40000")
    cid = await add_contract(world, "40000", status="completed")
    await link(world, iid, "contract", cid)
    assert (await state(world, iid)).status == "closed"
    async with world.factory() as s:
        lk = (await s.execute(select(CommitmentLink).where(CommitmentLink.item_id == iid))).scalar_one()
        await CommitmentService(s).remove_link(world.project_id, iid, lk.id, actor_id=world.requester)
        await s.commit()
    assert (await state(world, iid)).status == "released"


# ── finding 7: anti-splitting ──────────────────────────────────────────────


async def test_a_pending_request_of_the_split_group_counts_and_the_group_is_frozen(world: World) -> None:
    a = await item(world, code="SP-A", amount="30000", split_group="lot-7")
    b = await item(world, code="SP-B", amount="30000", split_group="lot-7")
    first = await request(world, a, "30000")
    assert first.required_tier == "project_manager"
    second = await request(world, b, "30000")
    # 30000 pending on A plus 30000 here is over the project manager's 50000.
    assert second.required_tier == "sponsor"
    async with world.factory() as s:
        with pytest.raises(CommitmentError) as exc:
            await CommitmentService(s).update_item(
                world.project_id, b, {"split_group": "other"}, actor_id=world.requester
            )
    assert (exc.value.code, exc.value.status_code) == ("field_frozen", 409)


# ── finding 8: re-pinning the schedule ─────────────────────────────────────


async def test_a_schedule_in_another_currency_is_refused_once_releases_exist(world: World) -> None:
    await released_item(world, "10000")
    async with world.factory() as s:
        with pytest.raises(CommitmentError) as exc:
            await CommitmentService(s).set_matrix(
                world.project_id, actor_id=world.manager, tenant_id=str(world.manager), schedule_id="us_federal_owner"
            )
    assert exc.value.code == "schedule_currency_mismatch"


# ── finding 9: a pinned route is the manager's ─────────────────────────────


async def _route(w: World, approver: uuid.UUID, project: bool = True) -> uuid.UUID:
    from app.modules.approval_routes.schemas import RouteCreate, StepCreate
    from app.modules.approval_routes.service import ApprovalRouteService

    async with w.factory() as s:
        route = await ApprovalRouteService(s).create_route(
            RouteCreate(
                project_id=w.project_id if project else None,
                name=f"hand built {uuid.uuid4().hex[:6]}",
                target_kind="commitment_release",
                steps=[StepCreate(ordinal=1, approver_user_id=approver, mode="any")],
            ),
            created_by=w.manager,
        )
        await s.commit()
        return route.id


async def _pin(w: World, tier: str, route_id: uuid.UUID) -> None:
    async with w.factory() as s:
        await CommitmentService(s).pin_tier_route(w.project_id, tier, route_id, actor_id=w.manager)
        await s.commit()


async def _matrix(w: World) -> CommitmentMatrix:
    async with w.factory() as s:
        return (
            await s.execute(select(CommitmentMatrix).where(CommitmentMatrix.project_id == w.project_id))
        ).scalar_one()


async def test_a_pinned_route_survives_new_assignments_and_a_forced_regeneration(world: World) -> None:
    route_id = await _route(world, world.sponsor)
    await _pin(world, "project_manager", route_id)
    async with world.factory() as s:
        svc = CommitmentService(s)
        await svc.put_assignments(
            world.project_id,
            [{"project_role": "owner_pm", "user_id": world.board}],
            actor_id=world.manager,
            today=TODAY,
        )
        report = await svc.generate_routes(world.project_id, actor_id=world.manager, today=TODAY, force=True)
        await s.commit()
    assert report["project_manager"] == "pinned"
    assert (await _matrix(world)).tier_routes["project_manager"] == str(route_id)


async def test_a_route_of_no_project_cannot_be_pinned(world: World) -> None:
    route_id = await _route(world, world.sponsor, project=False)
    with pytest.raises(CommitmentError) as exc:
        await _pin(world, "project_manager", route_id)
    assert exc.value.code == "route_must_belong_to_project"


# ── finding 13 and four eyes: who decides ──────────────────────────────────


async def test_every_assignee_of_an_any_tier_and_a_deputy_can_decide(world: World) -> None:
    async with world.factory() as s:
        await CommitmentService(s).put_assignments(
            world.project_id,
            [
                {"project_role": "owner_pm", "user_id": world.pm, "deputy_user_id": world.sponsor},
                {"project_role": "owner_pm", "user_id": world.board},
                {"project_role": "owner_sponsor", "user_id": world.sponsor},
                {"project_role": "owner_board_member", "user_id": world.board},
            ],
            actor_id=world.manager,
            today=TODAY,
        )
        await s.commit()
    # The second assignee, who has no step of their own on the route.
    first = await item(world, code="ANY-1", amount="10000")
    await request(world, first, "10000")
    row = await _decide(world, first, world.board)
    assert (row.outcome, row.decided_by, row.on_behalf_of) == ("released", world.board, None)
    # The deputy of the first assignee decides in that assignee's name.
    second = await item(world, code="ANY-2", amount="10000")
    await request(world, second, "10000")
    row = await _decide(world, second, world.sponsor)
    assert (row.outcome, row.decided_by, row.on_behalf_of) == ("released", world.sponsor, world.pm)
    assert (await state(world, second)).status == "released"


async def test_an_outsider_and_whoever_confirmed_a_precondition_cannot_decide(world: World) -> None:
    iid = await item(world, amount="10000")
    async with world.factory() as s:
        svc = CommitmentService(s)
        pre = await svc.add_precondition(
            world.project_id, iid, kind="manual", ref_id=None, text="Brief signed", actor_id=world.requester
        )
        await svc.confirm_precondition(
            world.project_id, iid, pre.id, met=True, evidence_ref="minute 4", actor_id=world.pm, manage=True
        )
        await s.commit()
    with pytest.raises(CommitmentError) as exc:
        # The only holder of the tier confirmed the evidence, so nobody is left to decide.
        await request(world, iid, "10000")
    assert exc.value.code == "four_eyes_no_approver"

    other = await item(world, code="CR-2", amount="10000")
    await request(world, other, "10000")
    for actor, code in ((world.outsider, "not_entitled_decider"), (world.requester, "four_eyes_violation")):
        with pytest.raises(CommitmentError) as exc:
            await _decide(world, other, actor)
        assert (exc.value.code, exc.value.status_code) == (code, 403)
    with pytest.raises(CommitmentError) as exc:
        await _decide(world, other, world.pm, decision="rejected")
    assert exc.value.code == "rationale_required"
    assert (await state(world, other)).status == "release_requested"


async def test_the_owner_and_the_gate_fields_are_frozen_for_an_editor_and_after_planned(world: World) -> None:
    iid = await item(world, amount="10000")
    async with world.factory() as s:
        with pytest.raises(CommitmentError) as exc:
            await CommitmentService(s).update_item(
                world.project_id, iid, {"owner_user_id": world.pm}, actor_id=world.requester
            )
    assert exc.value.code == "manage_required"
    await decide(world, await request(world, iid, "10000"), world.pm)
    async with world.factory() as s:
        with pytest.raises(CommitmentError) as exc:
            await CommitmentService(s).update_item(
                world.project_id,
                iid,
                {"deferred": True, "deferred_reason": "later"},
                actor_id=world.manager,
                manage=True,
            )
    assert exc.value.code == "field_frozen"


# ── finding 12: a verdict that waited behind a withdrawal ──────────────────


async def test_a_verdict_does_not_undo_a_withdrawal_it_read_before(world: World) -> None:
    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        svc = CommitmentService(s)
        seen = await svc.repo.get_release(d.id)
        assert seen.outcome == "pending"
        async with world.factory() as other:
            await CommitmentService(other).withdraw_release(
                world.project_id, iid, actor_id=world.requester, reason="wrong item"
            )
            await other.commit()
        applied = await svc.apply_route_verdict(
            d.id, instance_id=d.approval_instance_id, verdict="approved", decided_by=str(world.pm)
        )
        await s.commit()
    assert applied is False
    assert (await _release_row(world, d.id)).outcome == "withdrawn"
    assert (await state(world, iid)).status == "planned"


# ── finding 14: abort and transfer ─────────────────────────────────────────


async def _terms(w: World, item_id: uuid.UUID, charge: str) -> None:
    async with w.factory() as s:
        await CommitmentService(s).put_abort_terms(
            w.project_id,
            item_id,
            {"basis_code": "custom", "other_charge_estimate": charge, "source_note": "test"},
            actor_id=w.manager,
            manage=True,
            tenant_id=str(w.manager),
        )
        await s.commit()


async def _abort(w: World, item_id: uuid.UUID):
    async with w.factory() as s:
        row = await CommitmentService(s).request_abort(
            w.project_id, item_id, reason="Scheme cancelled", actor_id=w.requester, today=TODAY
        )
        await s.commit()
        return row


async def test_an_abort_is_decided_on_the_tier_of_its_residual_loss_and_ends_the_item(world: World) -> None:
    iid = await released_item(world, "40000")
    cid = await add_contract(world, "40000")
    await link(world, iid, "contract", cid)
    with pytest.raises(CommitmentError) as exc:
        await _abort(world, iid)
    assert exc.value.code == "abort_exposure_unknown"
    await _terms(world, iid, "10000")
    row = await _abort(world, iid)
    assert (row.purpose, row.required_tier, row.requested_amount) == ("abort", "sponsor", D("10000"))
    assert (await state(world, iid)).status == "release_requested"
    row = await _decide(world, iid, world.sponsor)
    assert row.outcome == "aborted"
    assert (await state(world, iid)).status == "aborted"


async def test_a_transfer_moves_the_links_and_ends_the_item_for_a_manager_only(world: World) -> None:
    src = await released_item(world, "40000")
    cid = await add_contract(world, "40000")
    await link(world, src, "contract", cid)
    dst = await item(world, code="CR-T", amount="40000")

    async def transfer(manage: bool):
        async with world.factory() as s:
            await CommitmentService(s).transfer_item(
                world.project_id,
                src,
                target_project_id=world.project_id,
                target_item_id=dst,
                reason="Package merged",
                actor_id=world.manager,
                manage=manage,
            )
            await s.commit()

    with pytest.raises(CommitmentError) as exc:
        await transfer(False)
    assert exc.value.code == "manage_required"
    await transfer(True)
    source = await state(world, src)
    assert (source.status, source.transferred_to_item_id) == ("transferred", dst)
    async with world.factory() as s:
        owners = (
            (await s.execute(select(CommitmentLink.item_id).where(CommitmentLink.target_id == cid))).scalars().all()
        )
    assert owners == [dst]


# ── findings 25 to 27: approval routes behind the matrix ───────────────────


async def test_a_step_is_handed_off_only_by_its_approver_or_a_manager_and_never_to_the_requester(
    world: World,
) -> None:
    from app.modules.approval_routes.service import ApprovalRouteService

    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        svc = ApprovalRouteService(s)
        with pytest.raises(HTTPException) as exc:
            await svc.reassign_current_step(
                d.approval_instance_id, to_user_id=world.board, actor_id=world.requester, caller_role="editor"
            )
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            await svc.reassign_current_step(
                d.approval_instance_id, to_user_id=world.requester, actor_id=world.manager, manage=True
            )
        assert exc.value.status_code == 422
        handed = await svc.reassign_current_step(
            d.approval_instance_id, to_user_id=world.board, actor_id=world.pm, caller_role="manager"
        )
        assert handed.current_assignee_user_id == world.board


async def test_an_approval_by_someone_who_does_not_hold_the_tier_releases_nothing(world: World) -> None:
    from app.modules.approval_routes.service import ApprovalRouteService

    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        # A manager of routes hands the project manager's step to the sponsor's colleague on the board.
        await ApprovalRouteService(s).reassign_current_step(
            d.approval_instance_id, to_user_id=world.board, actor_id=world.manager, manage=True
        )
        await s.commit()
    assert await decide(world, d, world.board) == "approved"
    row = await _release_row(world, d.id)
    assert (row.outcome, row.rationale) == ("rejected", "decider_not_tier_holder")
    assert (await state(world, iid)).status == "planned"


async def test_a_generated_route_edited_behind_the_matrix_is_refused_until_a_manager_pins_it(world: World) -> None:
    from app.modules.approval_routes.models import Step

    route_id = uuid.UUID((await _matrix(world)).tier_routes["project_manager"])
    async with world.factory() as s:
        step = (await s.execute(select(Step).where(Step.route_id == route_id))).scalar_one()
        step.approver_user_id = None
        step.approver_role = "editor"
        await s.commit()
    iid = await item(world, amount="10000")
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "10000")
    assert (exc.value.code, exc.value.status_code) == ("route_changed_since_accepted", 409)
    await _pin(world, "project_manager", route_id)
    assert (await request(world, iid, "10000")).outcome == "pending"


async def test_a_cancel_in_approval_routes_names_who_cancelled(world: World, monkeypatch) -> None:
    import app.modules.approval_routes.service as routes_service

    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(routes_service, "_safe_publish", lambda name, data: published.append((name, data)))
    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        await routes_service.ApprovalRouteService(s).cancel_instance(
            d.approval_instance_id, actor_id=world.manager, reason="superseded"
        )
        await s.commit()
    name, data = published[-1]
    assert name == "approval_routes.instance.cancelled"
    assert data["cancelled_by"] == str(world.manager)
    await handle_route_event(data, verdict="cancelled", session_factory=world.factory)
    row = await _release_row(world, d.id)
    assert (row.outcome, row.decided_by) == ("withdrawn", world.manager)


# ── finding 15: what an award drafted follows the award ────────────────────


async def test_a_contract_drafted_from_an_award_is_linked_to_the_item_of_the_award(world: World) -> None:
    from app.modules.bid_management.models import BidPackage

    iid = await released_item(world, "40000")
    async with world.factory() as s:
        pkg = BidPackage(
            project_id=world.project_id, code=f"BP-{uuid.uuid4().hex[:6]}", currency="EUR", status="awarded"
        )
        s.add(pkg)
        await s.commit()
        pkg_id = pkg.id
    await link(world, iid, "bid_package", pkg_id)
    cid = await add_contract(world, "30000", meta={"bid_package_id": str(pkg_id)})
    stranger = await add_contract(world, "30000", meta={"bid_package_id": str(uuid.uuid4())})
    async with world.factory() as s:
        assert await CommitmentService(s).adopt_award_drafts(world.project_id) == 1
        await s.commit()
    async with world.factory() as s:
        assert await CommitmentService(s).adopt_award_drafts(world.project_id) == 0
        linked = (
            (await s.execute(select(CommitmentLink.target_id).where(CommitmentLink.kind == "contract"))).scalars().all()
        )
    assert linked == [cid]
    assert stranger not in linked
    assert (await state(world, iid)).status == "committed"


# ── finding 17: the overdue escalation ─────────────────────────────────────


async def test_an_overdue_decision_is_escalated_once_per_date(world: World) -> None:
    from app.core.audit_log import ActivityLog
    from app.modules.commitment_release.sweep import sweep_once

    iid = await item(world, amount="10000", latest_decision_date_fixed="2026-10-01")
    await item(world, code="CR-OK", amount="10000", latest_decision_date_fixed="2026-12-01")
    first = await sweep_once(world.factory, today=TODAY)
    second = await sweep_once(world.factory, today=TODAY)
    assert (first["escalations"], first["failures"]) == (1, 0)
    assert (second["escalations"], second["failures"]) == (0, 0)
    async with world.factory() as s:
        rows = (
            (await s.execute(select(ActivityLog).where(ActivityLog.action == "decision_overdue_escalated")))
            .scalars()
            .all()
        )
    assert [r.entity_id for r in rows] == [str(iid)]
    assert str(world.requester) in rows[0].metadata_["notified"]
    assert str(world.pm) in rows[0].metadata_["notified"]


# ── gate evidence ──────────────────────────────────────────────────────────


async def test_items_naming_an_area_the_project_does_not_have_read_as_unknown_not_as_nothing(world: World) -> None:
    from app.modules.commitment_release.evidence import items_released_by_gate
    from app.modules.project_governance.evidence import GateAttempt

    await item(world, code="CR-G1", amount="10000", gate_code="G1", governance_area_code="ghost")
    attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code="G1", attempt_no=1)
    async with world.factory() as s:
        elsewhere = await items_released_by_gate(s, world.project_id, attempt, SimpleNamespace(code="cost"))
        own = await items_released_by_gate(s, world.project_id, attempt, SimpleNamespace(code="ghost"))
        other_gate = await items_released_by_gate(
            s,
            world.project_id,
            GateAttempt(gate_id=uuid.uuid4(), gate_code="G2", attempt_no=1),
            SimpleNamespace(code="cost"),
        )
    assert [(e.state, e.detail) for e in elsewhere] == [("unknown", "CR-G1")]
    assert [(e.state, e.detail) for e in own] == [("not_met", "CR-G1")]
    assert other_gate == []


# ── findings 18 to 20: the demo seed ───────────────────────────────────────


async def test_the_demo_seed_shows_a_released_item_a_decided_tranche_and_a_pending_one(world: World) -> None:
    from app.modules.commitment_release import seed
    from app.modules.contracts.models import Contract

    async with world.factory() as s:
        pid = await add_project(s, world.manager, [world.requester])
        s.add(
            Contract(
                project_id=pid,
                code="SC-DEMO",
                title="Structure",
                counterparty_type="subcontractor",
                total_value=D("1200000"),
                currency="EUR",
                status="active",
                metadata_={},
            )
        )
        await s.flush()
        counts = await seed._seed_project(s, pid)
        await s.commit()
    assert counts == {"items": 4, "links": 1, "releases": 3, "scenarios": 1, "releases_skipped_no_rate": 0}
    async with world.factory() as s:
        items = {
            i.code: i
            for i in (await s.execute(select(CommitmentItem).where(CommitmentItem.project_id == pid))).scalars()
        }
        releases = (
            (
                await s.execute(
                    select(ReleaseDecision)
                    .where(ReleaseDecision.project_id == pid)
                    .order_by(ReleaseDecision.created_at)
                )
            )
            .scalars()
            .all()
        )
        exposure = await CommitmentService(s).exposure(pid, as_of=TODAY)
    assert {c: i.status for c, i in items.items()} == {
        "CR-001": "committed",
        "CR-002": "planned",
        "CR-003": "release_requested",
        "CR-004": "planned",
    }
    assert [r.outcome for r in releases] == ["released", "released", "pending"]
    assert all(r.decided_at is None or r.created_at < r.decided_at for r in releases)
    assert {i.currency for i in items.values()} == {"EUR"}
    by_code = {row["code"]: row for row in exposure["items"]}
    # Nothing is bound on the facade item: no loss, and no gain from a salvage estimate either.
    assert D(by_code["CR-002"]["residual_loss"]) == D("0")
    assert D(by_code["CR-001"]["residual_loss"]) == D("40000")


# ── the governance read port ───────────────────────────────────────────────


async def test_gates_areas_and_documents_come_from_the_governance_port(world: World) -> None:
    from app.modules.project_governance.public import project_areas, project_documents, project_gates
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
        gates = await project_gates(s, world.project_id)
        areas = await project_areas(s, world.project_id)
        documents = await project_documents(s, world.project_id)
        refs = await CommitmentService(s).references(world.project_id)
    assert gates
    assert areas
    assert documents
    assert refs["has_model"] is True
    assert [g["code"] for g in refs["gates"]] == [g.code for g in gates]
    assert [g["name"] for g in refs["gates"]] == [g.label for g in gates]
    assert {g["status"] for g in refs["gates"]} == {g.status for g in gates}
    assert [a["code"] for a in refs["areas"]] == [a.code for a in areas]
    assert [(d["id"], d["doc_type"], d["area_code"]) for d in refs["frame_documents"]] == [
        (str(d.id), d.code, d.area_code) for d in documents
    ]

    gate, area = gates[0].code, areas[0].code
    for fields, code in (
        ({"gate_code": gate, "governance_area_code": "no-such-area"}, "governance_area_unknown"),
        ({"gate_code": "no-such-gate", "governance_area_code": area}, "gate_unknown"),
    ):
        with pytest.raises(CommitmentError) as exc:
            await item(world, code="CR-X", amount="10000", **fields)
        assert exc.value.code == code
    await item(world, code="CR-OK", amount="10000", gate_code=gate, governance_area_code=area)

    async with world.factory() as s:
        svc = CommitmentService(s)
        # Nothing is decided and nothing is binding yet, and an id the project does not own is not met.
        assert await svc.linked_state(world.project_id, "gate_decided", gate) == "open"
        doc_kind = "frame_document_binding"
        assert await svc.linked_state(world.project_id, doc_kind, str(documents[0].id)) == "open"
        assert await svc.linked_state(world.project_id, doc_kind, str(uuid.uuid4())) == "open"
        assert await svc.linked_state(world.project_id, doc_kind, "not-a-uuid") == "open"


async def test_a_handed_over_item_names_its_successor_only_to_a_reader_of_the_receiving_project(
    world: World,
) -> None:
    async with world.factory() as s:
        other = await add_project(s, world.manager, [])
        await CommitmentService(s).set_matrix(
            other, actor_id=world.manager, tenant_id=str(world.manager), schedule_id="neutral"
        )
        target = await CommitmentService(s).create_item(
            other,
            {
                "code": "CR-T",
                "title": "Receiving item",
                "commitment_type": "design",
                "planned_source": "manual",
                "planned_manual_amount": "10000",
                "currency": "EUR",
            },
            actor_id=world.manager,
        )
        await s.commit()
    iid = await item(world, code="CR-S", amount="10000")
    async with world.factory() as s:
        await CommitmentService(s).transfer_item(
            world.project_id,
            iid,
            target_project_id=other,
            target_item_id=target.id,
            reason="Package moved",
            actor_id=world.manager,
            manage=True,
        )
        await s.commit()

    async def successor(actor: uuid.UUID) -> dict:
        async with world.factory() as s:
            data = await CommitmentService(s).item_views(world.project_id, today=TODAY, item_ids=[iid], actor_id=actor)
        return data["items"][0]["transferred_to"]

    seen = await successor(world.manager)
    assert seen == {
        "project_id": str(other),
        "item_id": str(target.id),
        "same_project": False,
        "can_open": True,
        "project_name": seen["project_name"],
        "code": "CR-T",
        "title": "Receiving item",
    }
    assert seen["project_name"]
    hidden = await successor(world.requester)
    assert (hidden["project_id"], hidden["item_id"], hidden["can_open"]) == (str(other), str(target.id), False)
    assert (hidden["project_name"], hidden["code"], hidden["title"]) == (None, None, None)


# ── abort parameters, external reference, assignment without an approver ───────────────────


async def test_abort_terms_refuse_a_parameter_the_chosen_basis_does_not_have(world: World) -> None:
    from app.modules.commitment_release.catalogue import ABORT_BASIS_KIND
    from app.modules.commitment_release.models import AbortTerms
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    bases = list(get_catalogue_kind(ABORT_BASIS_KIND).shipped())
    fee = next(b.id for b in bases if b.method == "fee_on_unperformed")
    presumed = next(b.id for b in bases if b.method == "price_less_saved_costs")
    iid = await item(world, amount="10000")

    async def put(data: dict) -> None:
        async with world.factory() as s:
            await CommitmentService(s).put_abort_terms(
                world.project_id, iid, data, actor_id=world.manager, manage=True, tenant_id=str(world.manager)
            )
            await s.commit()

    await put({"basis_code": fee, "parameters": {"fee_pct": "0.1"}})
    for data, code in (
        # The form changed the basis and still sends the old basis's value.
        ({"basis_code": presumed, "parameters": {"fee_pct": "0.1"}}, "abort_parameter_not_in_basis"),
        # A caller that changes only the basis leaves the stored value behind: refused as well.
        ({"basis_code": presumed}, "abort_parameter_not_in_basis"),
        ({"basis_code": None, "parameters": {"fee_pct": "0.1"}}, "abort_parameter_not_in_basis"),
        ({"basis_code": fee, "parameters": {"fee_pct": "10"}}, "abort_parameter_invalid"),
    ):
        with pytest.raises(CommitmentError) as exc:
            await put(data)
        assert (exc.value.code, exc.value.status_code) == (code, 422), data
    async with world.factory() as s:
        row = (await s.execute(select(AbortTerms).where(AbortTerms.item_id == iid))).scalar_one()
    assert (row.basis_code, row.parameters) == (fee, {"fee_pct": "0.1"})

    await put({"basis_code": presumed, "parameters": {}})
    async with world.factory() as s:
        row = (await s.execute(select(AbortTerms).where(AbortTerms.item_id == iid))).scalar_one()
    assert (row.basis_code, row.parameters) == (presumed, {})


async def test_an_external_reference_on_an_amount_a_tier_decides_is_refused(world: World) -> None:
    iid = await item(world, amount="400000")
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "400000", external_approval_ref="Board minute 12")
    assert (exc.value.code, exc.value.status_code) == ("external_approval_not_required", 422)
    assert (await state(world, iid)).status == "planned"
    d = await request(world, iid, "400000")
    assert d.external_approval_ref == ""

    # Above every tier the reference is what makes the request possible.
    big = await item(world, code="CR-BIG", amount="9000000")
    with pytest.raises(CommitmentError) as exc:
        await request(world, big, "9000000")
    assert exc.value.code == "external_approval_required"
    d = await request(world, big, "9000000", external_approval_ref="Board minute 12")
    assert d.external_approval_ref == "Board minute 12"


async def test_a_deputy_or_a_period_without_an_approver_is_refused_by_name(world: World) -> None:
    from app.modules.commitment_release.models import AuthorityAssignment

    async def put(rows: list[dict]) -> None:
        async with world.factory() as s:
            await CommitmentService(s).put_assignments(world.project_id, rows, actor_id=world.manager, today=TODAY)
            await s.commit()

    for row in (
        {"project_role": "owner_sponsor", "user_id": None, "deputy_user_id": world.sponsor},
        {"project_role": "owner_sponsor", "valid_to": "2027-01-31"},
    ):
        with pytest.raises(CommitmentError) as exc:
            await put([{"project_role": "owner_pm", "user_id": world.pm}, row])
        assert (exc.value.code, exc.value.status_code) == ("assignment_needs_approver", 422)
        assert exc.value.detail == "owner_sponsor"
    async with world.factory() as s:
        rows = (
            (await s.execute(select(AuthorityAssignment).where(AuthorityAssignment.project_id == world.project_id)))
            .scalars()
            .all()
        )
    # Nothing was replaced by the refused writes.
    assert {r.project_role for r in rows} == {"owner_pm", "owner_sponsor", "owner_board_member"}


# ── second review, round 2 ──────────────────────────────────────────────────────────────────


async def test_an_abort_above_every_tier_needs_the_outside_reference_like_a_release(world: World) -> None:
    iid = await item(world, amount="9000000")
    cid = await add_contract(world, "9000000")
    async with world.factory() as s:
        await CommitmentService(s).add_link(world.project_id, iid, "contract", cid, actor_id=world.manager, manage=True)
        await s.commit()
    await _terms(world, iid, "8000000")

    async def abort(ref: str):
        async with world.factory() as s:
            d = await CommitmentService(s).request_abort(
                world.project_id,
                iid,
                reason="Scheme cancelled",
                actor_id=world.requester,
                today=TODAY,
                external_approval_ref=ref,
            )
            await s.commit()
            return d

    with pytest.raises(CommitmentError) as exc:
        await abort("")
    assert exc.value.code == "external_approval_required"
    d = await abort("Board minute 12")
    assert (d.purpose, d.escalate_outside, d.external_approval_ref) == ("abort", True, "Board minute 12")

    small = await item(world, code="CR-SM", amount="10000")
    await _terms(world, small, "1000")
    async with world.factory() as s:
        with pytest.raises(CommitmentError) as exc:
            await CommitmentService(s).request_abort(
                world.project_id,
                small,
                reason="Scheme cancelled",
                actor_id=world.requester,
                today=TODAY,
                external_approval_ref="Board minute 12",
            )
    assert exc.value.code == "external_approval_not_required"


async def test_a_role_step_is_offered_only_to_somebody_who_has_the_role(world: World) -> None:
    from app.modules.approval_routes.models import Step
    from tests.pg.governance_fixtures import add_user

    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        viewer = await add_user(s, "viewer")
        instance_route = (
            (await s.execute(select(CommitmentMatrix).where(CommitmentMatrix.project_id == world.project_id)))
            .scalar_one()
            .tier_routes["project_manager"]
        )
        step = (await s.execute(select(Step).where(Step.route_id == uuid.UUID(str(instance_route))))).scalar_one()
        step.approver_user_id = None
        step.approver_role = "manager"
        await s.commit()

    async def check(actor: uuid.UUID, role: str | None) -> str | None:
        async with world.factory() as s:
            svc = CommitmentService(s)
            row = await s.get(ReleaseDecision, d.id)
            return (await svc._decide_check(await s.get(CommitmentItem, iid), row, actor, TODAY, role))[0]

    # The stored role answers a read that carries none; the role of the request wins when given.
    assert await check(viewer, None) == "not_entitled_decider"
    assert await check(viewer, "viewer") == "not_entitled_decider"
    assert await check(world.pm, None) is None
    assert await check(world.pm, "manager") is None


async def test_every_approver_of_a_tier_adds_conditions_and_the_earliest_date_stands(world: World) -> None:
    from app.modules.approval_routes.models import Step

    iid = await item(world, amount="10000")
    d = await request(world, iid, "10000")
    async with world.factory() as s:
        route_id = uuid.UUID(
            str(
                (await s.execute(select(CommitmentMatrix).where(CommitmentMatrix.project_id == world.project_id)))
                .scalar_one()
                .tier_routes["project_manager"]
            )
        )
        s.add(Step(route_id=route_id, ordinal=2, approver_user_id=world.sponsor, mode="all"))
        await s.commit()

    async def approve(actor: uuid.UUID, conditions: str, until: str | None):
        async with world.factory() as s:
            row = await CommitmentService(s).decide_release(
                world.project_id,
                iid,
                decision="approved",
                comment="",
                conditions=conditions,
                valid_until=until,
                actor_id=actor,
                caller_role="manager",
                today=TODAY,
            )
            await s.commit()
            return row

    first = await approve(world.pm, "Report first", "2027-06-30")
    assert (first.outcome, first.conditions, first.valid_until) == ("pending", "Report first", "2027-06-30")
    second = await approve(world.sponsor, "Cap the fee", "2027-03-31")
    assert second.conditions == "Report first\nCap the fee"
    assert second.valid_until == "2027-03-31"
    # The last step closed the request; what it closed as is the tier holder rule's business, not this test's.
    assert second.outcome != "pending"
    stored = await _release_row(world, d.id)
    # Both approvers' conditions and the earlier of their two dates are what the database keeps.
    assert (stored.conditions, stored.valid_until) == ("Report first\nCap the fee", "2027-03-31")


async def test_an_abort_basis_of_another_tenant_is_unknown_to_this_one(world: World) -> None:
    from app.modules.commitment_release.catalogue import ABORT_BASIS_KIND
    from app.modules.project_governance.catalogue_store import CatalogueStore

    theirs = str(world.outsider)
    async with world.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            theirs,
            code="own_terms",
            name="Own terms",
            based_on_source="shipped",
            based_on_id="custom",
            based_on_version=None,
            actor_id=world.outsider,
            kind=ABORT_BASIS_KIND,
        )
        await store.publish(theirs, row.id, actor_id=world.outsider)
        await s.commit()
        basis_id = str(row.id)
    iid = await item(world, amount="10000")
    data = {"basis_code": basis_id, "basis_source": "tenant", "other_charge_estimate": "100"}

    async def put(tenant_id: str | None):
        async with world.factory() as s:
            row = await CommitmentService(s).put_abort_terms(
                world.project_id, iid, dict(data), actor_id=world.manager, manage=True, tenant_id=tenant_id
            )
            await s.commit()
            return row

    for tenant in (str(world.manager), None):
        with pytest.raises(CommitmentError) as exc:
            await put(tenant)
        assert (exc.value.code, exc.value.status_code) == ("abort_basis_unknown", 422)
    assert (await put(theirs)).basis_code == basis_id


async def test_an_item_already_told_about_its_date_costs_the_sweep_no_project_rebuild(
    world: World, monkeypatch
) -> None:
    iid = await item(world, code="CR-LATE", amount="10000", latest_decision_date_fixed="2026-10-01")
    async with world.factory() as s:
        svc = CommitmentService(s)
        due = dict(await svc.overdue_items(world.project_id, today=TODAY))[iid]
        assert await svc.escalate_overdue(world.project_id, iid, today=TODAY, due=due) is True
        await s.commit()

    calls = []
    real = CommitmentService.overdue_items

    async def counting(self, project_id, *, today):
        calls.append(project_id)
        return await real(self, project_id, today=today)

    monkeypatch.setattr(CommitmentService, "overdue_items", counting)
    async with world.factory() as s:
        assert await CommitmentService(s).escalate_overdue(world.project_id, iid, today=TODAY, due=due) is False
    assert calls == []
    # A date handed in that is not the item's is not believed: the item is read again.
    async with world.factory() as s:
        assert (
            await CommitmentService(s).escalate_overdue(world.project_id, iid, today=TODAY, due="1999-01-01") is False
        )
    assert calls == [world.project_id]


async def test_a_new_matrix_pins_what_the_active_pack_names_before_the_modules_own_default(
    world: World, monkeypatch
) -> None:
    """The pack is asked first; without an opinion the module's default applies, and a named schedule wins."""
    from app.modules.commitment_release.catalogue import AUTHORITY_SCHEDULE_KIND
    from app.modules.project_governance import public
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    shipped = sorted(s.id for s in get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).shipped())
    other = next(i for i in shipped if i != "neutral")
    version = get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).get_shipped(other).version
    asked: list[tuple[str, str | None]] = []

    def pack_says(kind, country_code=None, subdivision_code=None):
        asked.append((kind, country_code))
        return public.CataloguePin("shipped", other, version)

    async def new_matrix(**kw):
        async with world.factory() as s:
            pid = await add_project(s, world.manager, [])
            m = await CommitmentService(s).set_matrix(pid, actor_id=world.manager, tenant_id=str(world.manager), **kw)
            await s.commit()
            return m.schedule_source, m.schedule_id, m.schedule_version

    assert (await new_matrix())[1] == "neutral"
    monkeypatch.setattr(public, "default_catalogue_pin", pack_says)
    assert await new_matrix() == ("shipped", other, version)
    assert asked == [(AUTHORITY_SCHEDULE_KIND, None)]
    assert (await new_matrix(schedule_id="neutral"))[1] == "neutral"
    assert len(asked) == 1


async def test_the_host_area_never_answers_a_gate_with_nothing(world: World) -> None:
    """On the area that hosts commitment release an empty list would read as covered."""
    from app.modules.commitment_release.evidence import items_released_by_gate
    from app.modules.project_governance.evidence import GateAttempt
    from app.modules.project_governance.public import host_for, project_areas, project_gates
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
        host = await host_for(s, world.project_id, "commitment_release")
        gate = (await project_gates(s, world.project_id))[0].code
        elsewhere = next(a.code for a in await project_areas(s, world.project_id) if a.code != host.area_code)
        attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code=gate, attempt_no=1)
        on_host = await items_released_by_gate(s, world.project_id, attempt, SimpleNamespace(code=host.area_code))
        other = await items_released_by_gate(s, world.project_id, attempt, SimpleNamespace(code=elsewhere))
    assert [(e.state, e.label_key) for e in on_host] == [("unknown", "commitment.evidence.no_items_for_gate")]
    assert other == []

    await item(world, code="CR-H", amount="10000", gate_code=gate, governance_area_code=host.area_code)
    async with world.factory() as s:
        on_host = await items_released_by_gate(s, world.project_id, attempt, SimpleNamespace(code=host.area_code))
    assert [(e.state, e.detail) for e in on_host] == [("not_met", "CR-H")]


async def test_a_change_is_linked_only_on_the_item_that_holds_its_contract(world: World) -> None:
    """A release decided on a separate change item covers nothing once the contract header carries the change."""
    works = await item(world, code="CR-W", amount="40000", ctype="works")
    change = await item(world, code="CR-C", amount="5000", ctype="change")
    cid = await add_contract(world, "40000")
    await link(world, works, "contract", cid)
    vo = await _variation(world, "5000", "completed", cid)
    with pytest.raises(CommitmentError) as exc:
        await link(world, change, "variation_order", vo)
    assert (exc.value.code, exc.value.status_code) == ("change_belongs_to_contract_item", 422)
    await link(world, works, "variation_order", vo)

    # The other order: the change is linked first, then its contract may only join the same item.
    other = await add_contract(world, "20000")
    late = await _variation(world, "1000", "completed", other)
    await link(world, change, "variation_order", late)
    with pytest.raises(CommitmentError) as exc:
        await link(world, works, "contract", other)
    assert (exc.value.code, exc.value.status_code) == ("change_belongs_to_contract_item", 422)
    await link(world, change, "contract", other)

    # A change that names no contract is free to sit on its own item.
    loose = await _variation(world, "700", "completed")
    await link(world, change, "variation_order", loose)
    async with world.factory() as s:
        rows = (await s.execute(select(CommitmentLink.item_id, CommitmentLink.target_id))).all()
    assert {(i, d) for i, d in rows} == {(works, cid), (works, vo), (change, late), (change, other), (change, loose)}


# ── the demo before construction, and what procurement asks ────────────────────────────────


async def test_the_demo_of_a_project_before_construction_releases_nothing_of_the_main_works(world: World) -> None:
    from app.modules.commitment_release import public, seed
    from app.modules.project_governance.public import host_for, phases_enabling, project_gates
    from app.modules.project_governance.service import GovernanceService

    async with world.factory() as s:
        pid = await add_project(s, world.manager, [world.requester])
        await GovernanceService(s).set_model(
            pid,
            source="shipped",
            catalogue_id="neutral",
            version=None,
            four_eyes=True,
            actor_id=world.manager,
            tenant_id=str(world.manager),
        )
        await s.flush()
        counts = await seed._seed_project(s, pid)
        await s.commit()
    assert counts == {"items": 5, "links": 0, "releases": 3, "scenarios": 1, "releases_skipped_no_rate": 0}
    today = datetime.now(UTC).date()
    async with world.factory() as s:
        phases = set(await phases_enabling(s, pid, "construction_start"))
        gate = next(g for g in await project_gates(s, pid) if g.to_phase in phases)
        host = await host_for(s, pid, "commitment_release")
        views = {v["code"]: v for v in (await CommitmentService(s).item_views(pid, today=today))["items"]}
        releases = (await s.execute(select(ReleaseDecision).where(ReleaseDecision.project_id == pid))).scalars().all()
        links = (await s.execute(select(CommitmentLink).where(CommitmentLink.project_id == pid))).scalars().all()
        exposure = {r["code"]: r for r in (await CommitmentService(s).exposure(pid, as_of=today))["items"]}
        options = {o.code: o for o in await public.item_options(s, pid)}
        states = {code: await public.release_state(s, pid, uuid.UUID(v["id"])) for code, v in views.items()}
        stranger = await public.release_state(s, world.project_id, uuid.UUID(views["CR-002"]["id"]))
    assert gate.status != "decided"
    assert {c: v["status"] for c, v in views.items()} == {
        "CR-001": "planned",
        "CR-002": "released",
        "CR-003": "release_requested",
        "CR-004": "planned",
        "CR-005": "planned",
    }
    assert links == []
    # Exactly one item is past its decision date, and the works package is due at the award.
    assert [c for c, v in views.items() if v["decision_overdue"]] == ["CR-004"]
    assert views["CR-004"]["latest_decision_date"] == (today - timedelta(days=5)).isoformat()
    assert views["CR-001"]["latest_decision_date"] == (today + timedelta(days=165)).isoformat()
    assert (views["CR-004"]["gate_code"], views["CR-004"]["governance_area_code"]) == (gate.code, host.area_code)
    assert views["CR-001"]["gate_code"] is None
    # Every decided release lies in the past, and each released item says what stopping would cost.
    decided = [r for r in releases if r.outcome == "released"]
    assert len(decided) == 2
    assert all(r.decided_at.date() < today for r in decided)
    assert [r.outcome for r in releases].count("pending") == 1
    # Released, and nothing is bound yet: no contract or order is linked, so stopping today loses
    # nothing. The terms are entered and start to count with the first linked document.
    for code in ("CR-002", "CR-003"):
        assert D(exposure[code]["residual_loss"]) == D("0")
        assert "nothing_committed" in [line["code"] for line in exposure[code]["lines"]]
    # What procurement reads: the reservation is the released item with a lead time, the design has none.
    assert (options["CR-002"].released, options["CR-002"].lead_time_days) == (True, 120)
    # CR-002 is the transformer order that is not placed yet. Its release note says the slot is held
    # free of charge, no stage of its cancellation terms has begun, and without the plant register
    # it reads its own 120 days and no date it could be overdue against.
    slot = views["CR-002"]
    assert slot["title"] == seed.DEMO_SLOT_ITEM_TITLE
    assert (slot["lead_time_in_force_days"], slot["lead_time_source"], slot["plant_item_id"]) == (120, "item", None)
    assert (slot["latest_decision_date"], slot["date_basis"], slot["decision_overdue"]) == (None, "none", False)
    note = next(r.tranche_note for r in releases if str(r.item_id) == slot["id"])
    assert "held free of charge" in note and "not signed" in note
    async with world.factory() as s:
        terms = (await CommitmentService(s).repo.list_abort_terms(pid, [uuid.UUID(slot["id"])]))[0]
    stages = [(e["milestone"], e["from_date"]) for e in terms.cancellation_schedule]
    assert [m for m, _d in stages] == ["order_signed", "manufacturing_started"]
    assert [d for _m, d in stages] == [
        (today + timedelta(days=seed.DEMO_ORDER_SIGNED_DAYS)).isoformat(),
        (today + timedelta(days=seed.DEMO_MANUFACTURING_STARTED_DAYS)).isoformat(),
    ]
    assert all(d > today.isoformat() for _m, d in stages)
    assert options["CR-002"].released_on == today - timedelta(days=30)
    assert options["CR-003"].lead_time_days is None
    with_lead = [o.code for o in options.values() if o.released and o.lead_time_days]
    assert with_lead == ["CR-002"]
    assert {c: (st.found, st.released) for c, st in states.items()} == {
        c: (True, o.released) for c, o in options.items()
    }
    assert (stranger.found, stranger.released) == (False, False)


async def test_the_demo_reads_its_gate_and_area_from_the_phase_model_and_names_nothing_without_one(
    world: World,
) -> None:
    """The story of a project past its start gate names the procurement gate; the lookup is tested on its own."""
    from app.modules.commitment_release import seed
    from app.modules.project_governance.public import host_for, phases_enabling, project_gates
    from app.modules.project_governance.service import GovernanceService

    async with world.factory() as s:
        assert await seed._readiness_fields(s, world.project_id) == {}
        assert await seed._undecided_start_gate(s, world.project_id) is None
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
        fields = await seed._readiness_fields(s, world.project_id)
        start_gate = await seed._undecided_start_gate(s, world.project_id)
        host = await host_for(s, world.project_id, "commitment_release")
        gates = await project_gates(s, world.project_id)
        procurement = set(await phases_enabling(s, world.project_id, "procurement"))
        start = set(await phases_enabling(s, world.project_id, "construction_start"))
    assert fields == {
        "gate_code": next(g.code for g in gates if g.to_phase in procurement),
        "governance_area_code": host.area_code,
    }
    assert start_gate == next(g.code for g in gates if g.to_phase in start)


async def test_the_abort_preview_names_the_tier_and_the_reference_the_request_will_ask_for(world: World) -> None:
    """The form reads what the request will require instead of learning it from a refused click."""
    big = await item(world, code="CR-PB", amount="9000000")
    cid = await add_contract(world, "9000000")
    await link(world, big, "contract", cid)
    small = await item(world, code="CR-PS", amount="10000")

    async def preview(item_id: uuid.UUID) -> dict:
        async with world.factory() as s:
            return await CommitmentService(s).preview_abort(world.project_id, item_id, today=TODAY)

    async def refusal(item_id: uuid.UUID, ref: str) -> str | None:
        async with world.factory() as s:
            try:
                await CommitmentService(s).request_abort(
                    world.project_id,
                    item_id,
                    reason="Scheme cancelled",
                    actor_id=world.requester,
                    today=TODAY,
                    external_approval_ref=ref,
                )
            except CommitmentError as exc:
                return exc.code
            return None

    # Money is bound and no terms say what stopping costs: the preview refuses exactly as the request does.
    with pytest.raises(CommitmentError) as exc:
        await preview(big)
    assert exc.value.code == "abort_exposure_unknown"
    assert await refusal(big, "") == "abort_exposure_unknown"

    nothing = await preview(small)
    assert (D(nothing["residual_loss"]), nothing["external_approval_required"]) == (D("0"), False)
    assert nothing["required_tier"] is not None
    assert await refusal(small, "Board minute 12") == "external_approval_not_required"

    await _terms(world, big, "8000000")
    above = await preview(big)
    # The preview and the request agree on whether the outside reference is needed.
    assert await refusal(big, "") == ("external_approval_required" if above["external_approval_required"] else None)
    async with world.factory() as s:
        assert (await s.execute(select(ReleaseDecision))).scalars().all() == []


# ── a release past its validity date ───────────────────────────────────────────────────────


async def test_a_release_past_its_date_keeps_what_is_bound_and_authorises_nothing_new(world: World) -> None:
    from app.modules.commitment_release.validators import ReleaseInDate
    from tests.pg.commitment_fixtures import set_enforcement

    iid = await released_item(world, "40000")
    cid = await add_contract(world, "30000")
    await link(world, iid, "contract", cid)
    await set_enforcement(world, "block")

    async def check(kind: str, document_id: uuid.UUID | None, amount: str) -> dict:
        async with world.factory() as s:
            return await CommitmentService(s).check_document(
                world.project_id, kind=kind, document_id=document_id, new_amount=amount, currency="EUR"
            )

    async def view() -> dict:
        async with world.factory() as s:
            svc = CommitmentService(s)
            return (await svc.item_views(world.project_id, today=TODAY, item_ids=[iid], actor_id=world.manager))[
                "items"
            ][0]

    # In date: the contract may grow to the release.
    assert (await check("contract", cid, "40000"))["result"] == "ok"
    before = await view()
    assert (before["release_expired"], before["can"]["commit_new"]) == (False, {"allowed": True, "reason": None})

    async with world.factory() as s:
        row = (await s.execute(select(ReleaseDecision).where(ReleaseDecision.item_id == iid))).scalar_one()
        row.valid_until = "2020-01-31"
        await s.commit()

    after = await view()
    async with world.factory() as s:
        totals = (await CommitmentService(s).item_views(world.project_id, today=TODAY))["totals"]
    # The totals row serves the in-force sum, so nobody adds the lapsed 10,000 as available.
    assert (D(totals["released"]), D(totals["released_in_force"]), D(totals["released_lapsed"])) == (
        D("40000"),
        D("30000"),
        D("10000"),
    )
    # What is bound stays released and committed: no new state, no re-release demanded.
    assert after["status"] == before["status"]
    assert (D(after["released"]), D(after["committed"]), D(after["released_in_force"])) == (
        D("40000"),
        D("30000"),
        D("30000"),
    )
    assert after["release_expired"] is True
    assert D(after["released_lapsed"]) == D("10000")
    assert after["expired_release_dates"] == ["2020-01-31"]
    assert after["can"]["commit_new"] == {"allowed": False, "reason": "release_expired"}
    # The bound contract as it stands is still covered; growing it is new money and is refused by name.
    assert (await check("contract", cid, "30000"))["result"] == "ok"
    grown = await check("contract", cid, "40000")
    assert (grown["result"], grown["reasons"][0]["code"]) == ("block", "release_expired")
    # Beyond what was ever released the reason is the old one, not the date.
    beyond = await check("contract", cid, "90000")
    assert beyond["reasons"][0]["code"] == "commitment_not_released"

    # The validation rule warns on the item and does not fail it as an error.
    async with world.factory() as s:
        payload = await CommitmentService(s).validation_payload(world.project_id, today=TODAY)
    from app.core.validation.engine import ValidationContext

    results = await ReleaseInDate().validate(ValidationContext(data=payload, metadata={"locale": "en"}))
    assert [(r.passed, r.element_ref, str(r.severity.value)) for r in results] == [(False, "CR-G", "warning")]
    assert "2020-01-31" in results[0].message

    # A renewed release for the rest goes the usual route and is judged on what is in force.
    d = await request(world, iid, "10000")
    assert D(str(d.cumulative_after)) == D("40000")
    await decide(world, d, world.pm)
    renewed = await view()
    assert D(renewed["released_in_force"]) == D("40000")
    assert renewed["can"]["commit_new"] == {"allowed": True, "reason": None}
    # The renewal clears the warning; the lapsed 10,000 of the old release stay on record.
    assert (renewed["release_expired"], D(renewed["released"]), D(renewed["released_lapsed"])) == (
        False,
        D("50000"),
        D("10000"),
    )
    assert (await check("contract", cid, "40000"))["result"] == "ok"


# ── outstanding, not blocking: a decision date that has passed ─────────────────────────────


async def test_an_item_past_its_decision_date_is_its_own_warning_evidence_item(world: World) -> None:
    from app.modules.commitment_release import evidence
    from app.modules.project_governance.evidence import EVIDENCE_STATES, GateAttempt, evidence_link_href

    late = await item(
        world,
        code="CR-L",
        amount="10000",
        gate_code="G1",
        governance_area_code="ghost",
        latest_decision_date_fixed="2020-01-15",
    )
    await item(
        world,
        code="CR-F",
        amount="10000",
        gate_code="G1",
        governance_area_code="ghost",
        latest_decision_date_fixed="2999-01-15",
    )
    attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code="G1", attempt_no=1)

    async def read() -> list[tuple[str, str, str | None]]:
        async with world.factory() as s:
            got = await evidence.items_released_by_gate(s, world.project_id, attempt, SimpleNamespace(code="ghost"))
        return [(e.code, e.state, e.detail) for e in got]

    # The warning names one item by its id, so the code is the same on every read and after a rename.
    assert evidence.WARNING_STATE in EVIDENCE_STATES
    assert await read() == [
        (f"commitment_decision_overdue:G1:{late}", evidence.WARNING_STATE, "CR-L 2020-01-15"),
        ("commitments_released:G1:ghost", "not_met", "CR-F, CR-L"),
    ]
    # Released, the item is no longer outstanding and the warning is gone.
    d = await request(world, late, "10000")
    await decide(world, d, world.pm)
    assert await read() == [("commitments_released:G1:ghost", "not_met", "CR-F")]

    # Every evidence item of this module opens the matrix of the project.
    evidence.register_gate_evidence()
    assert evidence_link_href("commitment_matrix", str(world.project_id), world.project_id) == (
        f"/projects/{world.project_id}/commitments"
    )


# ── the plant item link (plant register rule 12: one lead time per plant item) ─────────────


def _plant_register(monkeypatch, known: dict) -> None:
    """Stand in for ``plant_register.reads`` with the contract of its ``plant_item_dates``."""
    import sys
    import types

    async def plant_item_dates(session, project_id, plant_item_id, *, today=None):
        owner, dates = known.get(plant_item_id, (None, None))
        return dates if owner == project_id else None

    reads = types.ModuleType("app.modules.plant_register.reads")
    reads.plant_item_dates = plant_item_dates
    monkeypatch.setitem(sys.modules, "app.modules.plant_register.reads", reads)


async def _item_view(world: World, iid: uuid.UUID) -> dict:
    async with world.factory() as s:
        return (await CommitmentService(s).item_views(world.project_id, today=TODAY, item_ids=[iid]))["items"][0]


async def test_a_linked_plant_item_gives_the_lead_time_and_the_order_date(world: World, monkeypatch) -> None:
    from datetime import date as day

    from app.modules.commitment_release.public import item_options

    plant_id = uuid.uuid4()
    dates = SimpleNamespace(
        plant_item_id=plant_id,
        code="PL-07",
        need_date=day(2027, 8, 1),
        latest_order_date=day(2027, 2, 1),
        lead_time_days=84,
        long_lead=True,
    )
    _plant_register(monkeypatch, {plant_id: (world.project_id, dates)})
    iid = await item(
        world,
        code="CR-P",
        amount="10000",
        ctype="supplies",
        plant_item_id=plant_id,
        lead_time_days=30,
        decision_buffer_days=10,
        latest_decision_date_fixed="2027-06-30",
    )
    v = await _item_view(world, iid)
    assert (v["plant_item_id"], v["plant_item_code"]) == (str(plant_id), "PL-07")
    # The register's figures, not the 30 days and the fixed date typed on the row.
    assert (v["lead_time_in_force_days"], v["lead_time_source"]) == (84, "plant_item")
    assert (v["latest_decision_date"], v["date_basis"]) == ("2027-01-22", "plant_item")
    assert v["lead_time_days"] == 30
    async with world.factory() as s:
        assert [o.lead_time_days for o in await item_options(s, world.project_id) if o.id == iid] == [84]

    # The register no longer knows the item: the row falls back to its own figures and says so.
    _plant_register(monkeypatch, {})
    v = await _item_view(world, iid)
    assert (v["plant_item_code"], v["lead_time_in_force_days"], v["lead_time_source"]) == (None, 30, "item")
    assert (v["latest_decision_date"], v["date_basis"]) == ("2027-06-30", "fixed")


async def test_a_plant_item_of_another_project_or_an_unknown_one_is_refused(world: World, monkeypatch) -> None:
    foreign, unknown = uuid.uuid4(), uuid.uuid4()
    _plant_register(monkeypatch, {foreign: (uuid.uuid4(), SimpleNamespace(code="PL-X"))})
    for plant_id in (foreign, unknown):
        with pytest.raises(CommitmentError) as exc:
            await item(world, code=f"CR-{plant_id.hex[:4]}", amount="10000", plant_item_id=plant_id)
        assert (exc.value.code, exc.value.status_code) == ("plant_item_not_found", 404)
    iid = await item(world, code="CR-Q", amount="10000")
    async with world.factory() as s:
        with pytest.raises(CommitmentError) as exc:
            await CommitmentService(s).update_item(
                world.project_id, iid, {"plant_item_id": foreign}, actor_id=world.requester
            )
    assert exc.value.code == "plant_item_not_found"


async def test_without_the_plant_register_an_item_keeps_its_own_lead_time(world: World, monkeypatch) -> None:
    import sys

    # ``None`` in sys.modules makes the import fail, as on an install without the module.
    monkeypatch.setitem(sys.modules, "app.modules.plant_register.reads", None)
    iid = await item(world, code="CR-N", amount="10000", lead_time_days=30, latest_decision_date_fixed="2027-06-30")
    v = await _item_view(world, iid)
    assert (v["lead_time_in_force_days"], v["lead_time_source"], v["plant_item_id"]) == (30, "item", None)
    assert (v["latest_decision_date"], v["date_basis"]) == ("2027-06-30", "fixed")
    # A link cannot be stored when nothing can answer for it.
    with pytest.raises(CommitmentError) as exc:
        await item(world, code="CR-O", amount="10000", plant_item_id=uuid.uuid4())
    assert exc.value.code == "plant_item_not_found"


# ── the demo seed and currencies: nothing is requested that is known to be refused ─────────


async def _seeded(world: World, caplog, *, currency: str, contract_currency: str) -> tuple[uuid.UUID, dict, list]:
    """A German demo project in ``currency`` with one subcontract, seeded; its counts and loud log records."""
    import logging

    from app.modules.commitment_release import seed
    from app.modules.contracts.models import Contract
    from app.modules.projects.models import Project

    async with world.factory() as s:
        pid = await add_project(s, world.manager, [world.requester])
        project = await s.get(Project, pid)
        project.country_code, project.currency = "DE", currency
        s.add(
            Contract(
                project_id=pid,
                code="SC-DEMO",
                title="Structure",
                counterparty_type="subcontractor",
                total_value=D("1200000"),
                currency=contract_currency,
                status="active",
                metadata_={},
            )
        )
        await s.flush()
        with caplog.at_level(logging.INFO):
            counts = await seed._seed_project(s, pid)
        await s.commit()
    loud = [
        (r.name, r.getMessage())
        for r in caplog.records
        if r.levelno > logging.INFO and r.name.startswith(("app.modules.commitment_release", "app.modules.approval"))
    ]
    return pid, counts, loud


async def _pinned(world: World, pid: uuid.UUID) -> str:
    async with world.factory() as s:
        return (
            (await s.execute(select(CommitmentMatrix).where(CommitmentMatrix.project_id == pid)))
            .scalar_one()
            .schedule_id
        )


async def test_the_demo_seed_keeps_the_national_schedule_on_a_project_in_its_currency(world: World, caplog) -> None:
    pid, counts, loud = await _seeded(world, caplog, currency="EUR", contract_currency="EUR")
    assert await _pinned(world, pid) == "de_public_owner"
    assert (counts["releases"], counts["releases_skipped_no_rate"]) == (3, 0)
    assert loud == []


async def test_the_demo_seed_pins_the_neutral_schedule_on_a_project_in_another_currency(world: World, caplog) -> None:
    pid, counts, loud = await _seeded(world, caplog, currency="CHF", contract_currency="CHF")
    assert await _pinned(world, pid) == "neutral"
    assert (counts["releases"], counts["releases_skipped_no_rate"]) == (3, 0)
    assert loud == []


async def test_the_demo_seed_does_not_request_a_release_it_has_no_rate_for(world: World, caplog, monkeypatch) -> None:
    from app.modules.commitment_release import fx

    async def no_rate_set(*_args, **_kwargs):
        return None

    # A dated rate set left in the shared database by another test would convert USD; this one is about the project.
    monkeypatch.setattr(fx, "_rate_set_quote", no_rate_set)
    # The fixture project knows a rate for GBP only: a subcontract in USD cannot be converted.
    pid, counts, loud = await _seeded(world, caplog, currency="EUR", contract_currency="USD")
    assert await _pinned(world, pid) == "de_public_owner"
    assert (counts["releases"], counts["releases_skipped_no_rate"], counts["links"]) == (2, 1, 0)
    async with world.factory() as s:
        works = (
            await s.execute(
                select(CommitmentItem).where(CommitmentItem.project_id == pid, CommitmentItem.code == "CR-001")
            )
        ).scalar_one()
        asked = (await s.execute(select(ReleaseDecision).where(ReleaseDecision.item_id == works.id))).scalars().all()
    assert (works.status, asked) == ("planned", [])
    assert loud == []


# ── a plant item link that dangles, and the demo link ──────────────────────────────────────


async def test_a_link_to_a_plant_item_the_register_lost_is_a_warning_finding(world: World, monkeypatch) -> None:
    from app.core.validation.engine import ValidationContext
    from app.modules.commitment_release.validators import PlantItemInRegister

    plant_id = uuid.uuid4()
    dates = SimpleNamespace(code="PL-07", need_date=None, latest_order_date=None, lead_time_days=84, status="cancelled")
    _plant_register(monkeypatch, {plant_id: (world.project_id, dates)})
    iid = await item(world, code="CR-P", amount="10000", plant_item_id=plant_id, lead_time_days=30)
    await item(world, code="CR-U", amount="10000")

    async def findings() -> list[tuple[bool, str, str]]:
        async with world.factory() as s:
            payload = await CommitmentService(s).validation_payload(world.project_id, today=TODAY)
        results = await PlantItemInRegister().validate(ValidationContext(data=payload, metadata={"locale": "en"}))
        return [(r.passed, r.element_ref, str(r.severity.value)) for r in results]

    v = await _item_view(world, iid)
    # A cancelled plant item is shown as cancelled and still gives its dates.
    assert (v["plant_item_missing"], v["plant_item_status"], v["plant_item_cancelled"]) == (False, "cancelled", True)
    assert (v["lead_time_in_force_days"], v["lead_time_source"]) == (84, "plant_item")
    # Only the linked item is judged; the unlinked one is not a finding at all.
    assert await findings() == [(True, "CR-P", "warning")]

    _plant_register(monkeypatch, {})
    v = await _item_view(world, iid)
    assert (v["plant_item_missing"], v["plant_item_cancelled"], v["lead_time_source"]) == (True, False, "item")
    assert await findings() == [(False, "CR-P", "warning")]


async def test_the_demo_link_points_a_commitment_item_at_its_plant_item_once(world: World, monkeypatch) -> None:
    import sys

    from app.modules.commitment_release import seed
    from app.modules.projects.models import Project

    plant_id = uuid.uuid4()
    _plant_register(monkeypatch, {})
    reads = sys.modules["app.modules.plant_register.reads"]
    iid = await item(world, code="CR-002", amount="10000", title=seed.DEMO_SLOT_ITEM_TITLE)

    async def link_now() -> dict[str, str]:
        async with world.factory() as s:
            out = await seed.link_demo_plant_items(s, world.project_id, links={"CR-002": "PL-001", "CR-404": "PL-001"})
            await s.commit()
            return out

    # Not a demo project: nothing is touched.
    assert await link_now() == {}
    async with world.factory() as s:
        project = await s.get(Project, world.project_id)
        project.metadata_ = {**(project.metadata_ or {}), "demo_id": "demo-test"}
        await s.commit()
    # A plant register without the lookup by code answers as unavailable.
    assert await link_now() == {"CR-002": "plant_register_unavailable", "CR-404": "plant_register_unavailable"}

    async def plant_item_id_by_code(session, project_id, code):
        return plant_id if (project_id, code) == (world.project_id, "PL-001") else None

    reads.plant_item_id_by_code = plant_item_id_by_code
    assert await link_now() == {"CR-002": "linked", "CR-404": "no_commitment_item"}
    assert (await state(world, iid)).plant_item_id == plant_id
    assert (await link_now())["CR-002"] == "already_linked"


# ── the plant items a form may pick from ───────────────────────────────────────────────────


async def test_references_list_the_plant_items_of_this_project_only(world: World, monkeypatch) -> None:
    import sys

    async def refs() -> dict:
        async with world.factory() as s:
            return (await CommitmentService(s).references(world.project_id))["plant_items"]

    # No plant register installed: nothing to link to, and the answer says so.
    monkeypatch.setitem(sys.modules, "app.modules.plant_register.reads", None)
    assert await refs() == {"available": False, "items": []}

    mine, theirs = uuid.uuid4(), uuid.uuid4()
    other_project = uuid.uuid4()
    register = {
        world.project_id: [
            SimpleNamespace(id=mine, code="PL-002", title="Switchgear", status="identified"),
            SimpleNamespace(id=uuid.uuid4(), code="PL-001", title="Transformer", status="cancelled"),
        ],
        other_project: [SimpleNamespace(id=theirs, code="PL-900", title="Foreign", status="identified")],
    }
    asked: list[uuid.UUID] = []

    async def plant_item_options(session, project_id):
        asked.append(project_id)
        return register.get(project_id, [])

    _plant_register(monkeypatch, {})
    sys.modules["app.modules.plant_register.reads"].plant_item_options = plant_item_options
    got = await refs()
    assert got["available"] is True
    # By code, every status served as the register names it, and only this project was asked for.
    assert [(r["code"], r["name"], r["status"]) for r in got["items"]] == [
        ("PL-001", "Transformer", "cancelled"),
        ("PL-002", "Switchgear", "identified"),
    ]
    assert got["items"][1]["id"] == str(mine)
    assert asked == [world.project_id]
    assert str(theirs) not in {r["id"] for r in got["items"]}


async def test_a_matrix_read_asks_the_plant_register_once_for_all_linked_items(world: World, monkeypatch) -> None:
    import sys

    a, b = uuid.uuid4(), uuid.uuid4()
    dates = {
        a: SimpleNamespace(code="PL-A", need_date=None, latest_order_date=None, lead_time_days=70, status="ordered"),
        b: SimpleNamespace(code="PL-B", need_date=None, latest_order_date=None, lead_time_days=21, status="ordered"),
    }
    _plant_register(monkeypatch, {k: (world.project_id, v) for k, v in dates.items()})
    for code, plant_id in (("CR-A", a), ("CR-B", b)):
        await item(world, code=code, amount="10000", plant_item_id=plant_id)
    await item(world, code="CR-C", amount="10000", lead_time_days=5)
    calls: list[list[uuid.UUID]] = []

    async def plant_items_dates(session, project_id, plant_item_ids, *, today=None):
        calls.append(list(plant_item_ids))
        return {i: dates[i] for i in plant_item_ids if i in dates and project_id == world.project_id}

    sys.modules["app.modules.plant_register.reads"].plant_items_dates = plant_items_dates
    async with world.factory() as s:
        views = (await CommitmentService(s).item_views(world.project_id, today=TODAY))["items"]
    assert {v["code"]: (v["lead_time_in_force_days"], v["lead_time_source"]) for v in views} == {
        "CR-A": (70, "plant_item"),
        "CR-B": (21, "plant_item"),
        "CR-C": (5, "item"),
    }
    assert len(calls) == 1 and sorted(calls[0], key=str) == sorted([a, b], key=str)


async def test_the_demo_link_is_not_made_where_the_item_is_another_thing(world: World, monkeypatch) -> None:
    import sys

    from app.modules.commitment_release import seed
    from app.modules.projects.models import Project

    _plant_register(monkeypatch, {})
    plant_id = uuid.uuid4()

    async def plant_item_id_by_code(session, project_id, code):
        return plant_id

    sys.modules["app.modules.plant_register.reads"].plant_item_id_by_code = plant_item_id_by_code
    # The construction story: the same code is the facade units, which no plant item is.
    iid = await item(world, code="CR-002", amount="10000", title="Long-lead facade units")
    async with world.factory() as s:
        project = await s.get(Project, world.project_id)
        project.metadata_ = {**(project.metadata_ or {}), "demo_id": "demo-test"}
        await s.commit()
    async with world.factory() as s:
        out = await seed.link_demo_plant_items(s, world.project_id)
        await s.commit()
    assert out == {"CR-002": "not_this_story"}
    assert (await state(world, iid)).plant_item_id is None


async def test_after_the_plant_seed_the_transformer_order_reads_the_registers_dates(world: World) -> None:
    """Both demo seeders on one project before construction, the plant register's first, then the link."""
    plant_seed = pytest.importorskip("app.modules.plant_register.seed")
    from app.modules.commitment_release import seed
    from app.modules.plant_register.reads import plant_item_dates, plant_item_id_by_code
    from app.modules.project_governance.service import GovernanceService
    from app.modules.projects.models import Project

    today = datetime.now(UTC).date()
    async with world.factory() as s:
        pid = await add_project(s, world.manager, [world.requester])
        project = await s.get(Project, pid)
        project.metadata_ = {"demo_id": "demo-test"}
        await GovernanceService(s).set_model(
            pid,
            source="shipped",
            catalogue_id="neutral",
            version=None,
            four_eyes=True,
            actor_id=world.manager,
            tenant_id=str(world.manager),
        )
        await s.flush()
        await plant_seed.seed_plant_register_demo(s, [pid])
        await seed._seed_project(s, pid)
        linked = await seed.link_demo_plant_items(s, pid)
        await s.commit()
    assert linked == {"CR-002": "linked"}
    async with world.factory() as s:
        plant_id = await plant_item_id_by_code(s, pid, "PL-001")
        register = await plant_item_dates(s, pid, plant_id, today=today)
        view = next(
            v for v in (await CommitmentService(s).item_views(pid, today=today))["items"] if v["code"] == "CR-002"
        )
    # One story on both screens: not ordered in the register, released and unbound in the matrix.
    assert register.status not in ("ordered", "manufactured", "delivered", "commissioned", "handed_over", "cancelled")
    assert (view["status"], view["links"], view["plant_item_code"]) == ("released", [], "PL-001")
    # The register's lead time governs, whatever it is; the row's own 120 days are no longer in force.
    assert (view["lead_time_in_force_days"], view["lead_time_source"]) == (register.lead_time_days, "plant_item")
    assert register.lead_time_days != 120 and view["lead_time_days"] == 120
    # The date is the register's latest order date, not a copy: ahead of today, and not a year out or overdue.
    assert view["date_basis"] == "plant_item"
    assert view["latest_decision_date"] == register.latest_order_date.isoformat()
    assert today <= register.latest_order_date <= today + timedelta(days=60)
    assert view["decision_overdue"] is False


# ── a project that does not use gates (programme rule 26) ──────────────────────────────────


async def test_a_project_without_gates_walks_from_a_planned_item_to_a_committed_one(world: World) -> None:
    """No governance model, enforcement ``block``: request, approval by the tier, contract bound, nothing waits for a gate."""
    from app.modules.commitment_release.models import CommitmentPrecondition
    from tests.pg.commitment_fixtures import set_enforcement

    async with world.factory() as s:
        refs = await CommitmentService(s).references(world.project_id)
    assert (refs["has_model"], refs["gates_in_use"], refs["gates"]) == (False, False, [])
    await set_enforcement(world, "block")
    iid = await item(world, code="CR-NG", amount="40000", ctype="works")

    async def add(kind: str, ref_id: str | None):
        async with world.factory() as s:
            row = await CommitmentService(s).add_precondition(
                world.project_id, iid, kind=kind, ref_id=ref_id, text="", actor_id=world.requester
            )
            await s.commit()
            return row

    # Nothing can wait for a gate, a frame document or an application this project does not have.
    for kind, ref, code, status in (
        ("gate_decided", "G1", "gates_not_in_use", 422),
        ("frame_document_binding", str(uuid.uuid4()), "frame_document_not_found", 404),
        ("funding_approved", str(uuid.uuid4()), "funding_application_not_found", 404),
    ):
        with pytest.raises(CommitmentError) as exc:
            await add(kind, ref)
        assert (exc.value.code, exc.value.status_code) == (code, status)

    # A precondition stored before that check existed: it can never be met, and it says so.
    async with world.factory() as s:
        stale = CommitmentPrecondition(
            project_id=world.project_id, item_id=iid, kind="gate_decided", ref_id="G1", text="", state="open"
        )
        s.add(stale)
        await s.commit()
        stale_id = stale.id
    view = await _item_view(world, iid)
    assert [(p["state"], p["unreachable_reason"]) for p in view["preconditions"]] == [("open", "gates_not_in_use")]
    # Read without the manage right: the screen is told who may remove it.
    assert view["can"]["remove_precondition"] == {"allowed": False, "reason": "manage_required", "applies": True}
    async with world.factory() as s:
        as_manager = await CommitmentService(s).item_views(
            world.project_id, today=TODAY, item_ids=[iid], actor_id=world.manager, manage=True
        )
    assert as_manager["items"][0]["can"]["remove_precondition"] == {"allowed": True, "reason": None, "applies": True}
    with pytest.raises(CommitmentError) as exc:
        await request(world, iid, "40000")
    assert exc.value.code == "preconditions_open"

    async def remove(actor: uuid.UUID, *, manage: bool, reason: str) -> None:
        async with world.factory() as s:
            await CommitmentService(s).remove_precondition(
                world.project_id, iid, stale_id, reason=reason, actor_id=actor, manage=manage
            )
            await s.commit()

    # Only a manager removes it, and only with a reason.
    with pytest.raises(CommitmentError) as exc:
        await remove(world.requester, manage=False, reason="not needed")
    assert (exc.value.code, exc.value.status_code) == ("manage_required", 403)
    with pytest.raises(CommitmentError) as exc:
        await remove(world.manager, manage=True, reason="  ")
    assert (exc.value.code, exc.value.status_code) == ("rationale_required", 422)
    await remove(world.manager, manage=True, reason="This project has no gates")
    assert (await _item_view(world, iid))["preconditions"] == []

    # To the end: requested, approved by the tier holder, and the first thing the release unlocks,
    # a contract bound under it, passes the guard that blocks unreleased commitments.
    d = await request(world, iid, "40000")
    with pytest.raises(CommitmentError) as exc:
        async with world.factory() as s:
            await CommitmentService(s).remove_precondition(
                world.project_id, iid, uuid.uuid4(), reason="x", actor_id=world.manager, manage=True
            )
    assert exc.value.code == "release_pending"
    async with world.factory() as s:
        pending = await CommitmentService(s).item_views(
            world.project_id, today=TODAY, item_ids=[iid], actor_id=world.manager, manage=True
        )
    # Shown disabled with the reason while the request runs, not hidden.
    assert pending["items"][0]["can"]["remove_precondition"] == {
        "allowed": False,
        "reason": "release_pending",
        "applies": True,
    }
    await decide(world, d, world.pm)
    assert (await state(world, iid)).status == "released"
    cid = await add_contract(world, "40000")
    await link(world, iid, "contract", cid)
    async with world.factory() as s:
        verdict = await CommitmentService(s).check_document(
            world.project_id, kind="contract", document_id=cid, new_amount="40000", currency="EUR"
        )
    assert verdict["result"] == "ok"
    assert (await state(world, iid)).status == "committed"


async def test_a_precondition_on_a_gate_is_accepted_only_for_a_gate_of_the_project(world: World) -> None:
    from app.modules.project_governance.public import project_gates
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
        gate = (await project_gates(s, world.project_id))[0].code
        refs = await CommitmentService(s).references(world.project_id)
    assert refs["gates_in_use"] is True
    iid = await item(world, code="CR-WG", amount="40000")
    async with world.factory() as s:
        svc = CommitmentService(s)
        with pytest.raises(CommitmentError) as exc:
            await svc.add_precondition(
                world.project_id, iid, kind="gate_decided", ref_id="no-such-gate", text="", actor_id=world.requester
            )
        assert (exc.value.code, exc.value.status_code) == ("gate_unknown", 422)
        await svc.add_precondition(
            world.project_id, iid, kind="gate_decided", ref_id=gate, text="", actor_id=world.requester
        )
        await s.commit()
    view = await _item_view(world, iid)
    # Waiting for a gate the project has is an ordinary open precondition, not an unreachable one.
    assert [(p["kind"], p["state"], p["unreachable_reason"]) for p in view["preconditions"]] == [
        ("gate_decided", "open", None)
    ]


async def test_linked_preconditions_of_many_items_ask_the_governance_port_once(world: World, monkeypatch) -> None:
    """Six gate preconditions and three document ones over three items: one read of gates, one of documents."""
    from app.modules.commitment_release.models import CommitmentPrecondition
    from app.modules.project_governance import public
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
        gates = [g.code for g in await public.project_gates(s, world.project_id)][:2]
        document = str((await public.project_documents(s, world.project_id))[0].id)
    assert len(gates) == 2
    ids = [await item(world, code=f"CR-N{n}", amount="10000") for n in range(3)]
    async with world.factory() as s:
        for iid in ids:
            for kind, ref in (
                ("gate_decided", gates[0]),
                ("gate_decided", gates[1]),
                ("frame_document_binding", document),
            ):
                s.add(
                    CommitmentPrecondition(
                        project_id=world.project_id, item_id=iid, kind=kind, ref_id=ref, text="", state="open"
                    )
                )
        await s.commit()

    asked = {"gates": 0, "documents": 0}
    real_gates, real_documents = public.project_gates, public.project_documents

    async def counting_gates(session, project_id):
        asked["gates"] += 1
        return await real_gates(session, project_id)

    async def counting_documents(session, project_id):
        asked["documents"] += 1
        return await real_documents(session, project_id)

    async with world.factory() as s:
        svc = CommitmentService(s)
        rows = await svc.repo.list_preconditions(world.project_id, ids)
        assert len(rows) == 9
        monkeypatch.setattr(public, "project_gates", counting_gates)
        monkeypatch.setattr(public, "project_documents", counting_documents)
        targets = await svc.linked_targets(world.project_id, rows)
        states = await svc.precondition_states(
            world.project_id, rows, planned=Decimal("10000"), cumulative=Decimal("0"), targets=targets
        )
    assert asked == {"gates": 1, "documents": 1}
    assert {(p["state"], p["unreachable_reason"]) for p in states} == {("open", None)}
