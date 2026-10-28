# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The economics service against PostgreSQL: the three parts, the readings, and the approval.

No mocks. The estimate is a real bill read through the bill's own helpers, the commitments are real purchase
orders counted by the cost spine's rule, the gate is the shipped eleven-area model, and a decision is a real
governance gate decision.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.economics.errors import EconomicsError
from app.modules.economics.events import handle_frame_document
from app.modules.economics.evidence import plan_ready, register_gate_evidence
from app.modules.economics.service import EconomicsService
from app.modules.project_governance.evidence import GateAttempt
from tests._pg import isolated_engine
from tests.pg.economics_fixtures import (
    COMMERCIAL_DOC,
    DIRECT,
    GATE,
    add_commitment,
    build_world,
    call,
    fill,
    fill_registers,
)
from tests.pg.governance_fixtures import areas, decide, documents, only_evidence, prepare_gate

pytestmark = pytest.mark.asyncio

D = Decimal


@pytest_asyncio.fixture
async def factory():
    with only_evidence(register=register_gate_evidence):
        async with isolated_engine() as engine:
            yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def world(factory):
    return await build_world(factory)


@pytest_asyncio.fixture
async def ungoverned(factory):
    return await build_world(factory, governance=False)


async def _status(w) -> str:
    return (await call(w, "require_plan")).status


async def _code(awaitable) -> str:
    with pytest.raises(EconomicsError) as exc:
        await awaitable
    return exc.value.code


# ── the plan takes its basis from the project ────────────────────────────────


async def test_the_plan_takes_currency_and_classification_standard_from_the_project(world) -> None:
    plan = await call(world, "require_plan")
    assert (plan.currency, plan.classification_standard, plan.status) == ("EUR", "din276", "draft")
    assert plan.discount_rate_pct is None


# ── the cost frame is compared with the bill and the commitments ─────────────


async def test_the_frame_is_compared_with_the_bill_by_classification_code(world) -> None:
    await call(world, "patch_plan", {"markup_allowance": D("200000")}, world.manager)
    await call(world, "add_frame_line", {"code": "300", "title": "Construction", "amount": D("2000000")}, world.manager)
    await call(world, "add_frame_line", {"code": "400", "title": "Services", "amount": D("200000")}, world.manager)
    frame = await call(world, "cost_frame")
    by_code = {r["code"]: r for r in frame["lines"]}
    # 331 and 351 sit under 300; 411 under 400; nothing is invented or dropped.
    assert by_code["300"]["estimate"] == "1500000.00"
    assert by_code["400"]["estimate"] == "250000.00"
    assert by_code["300"]["variance"] == "-500000.00"
    assert by_code["400"]["variance"] == "50000.00"
    t = frame["totals"]
    assert (t["estimate_assigned"], t["estimate_unassigned"], t["unassigned_count"]) == ("1750000.00", "10000.00", 1)
    assert t["estimate_direct"] == f"{DIRECT}.00"
    # the markup comes from the bill's own cascade: 10 percent of the direct cost
    assert t["markups"] == "176000.00"
    assert t["estimate"] == "1936000.00"
    assert t["frame"] == "2400000.00"
    assert t["variance"] == "-464000.00"
    # the three parts add up: assigned + unassigned + markups == the bill's total
    assert D(t["estimate_assigned"]) + D(t["estimate_unassigned"]) + D(t["markups"]) == D(t["estimate"])
    assert frame["markups"] == [{"name": "Project reserve", "category": "contingency", "amount": "176000.00"}]


async def test_commitments_are_read_from_the_cost_spine_under_the_frame_line_that_covers_them(world) -> None:
    await call(world, "add_frame_line", {"code": "300", "title": "Construction", "amount": D("500000")}, world.manager)
    assert (await call(world, "cost_frame"))["totals"]["committed_available"] is False
    async with world.factory() as s:
        await add_commitment(s, world.project_id, "331", "600000")
        await add_commitment(s, world.project_id, "999", "1000")
        await s.commit()
    frame = await call(world, "cost_frame")
    line = frame["lines"][0]
    assert line["committed"] == "600000.00"
    assert frame["totals"]["committed_unassigned"] == "1000.00"
    # the over-commitment is an error finding, the over-estimate a warning
    found = {(f.code, f.severity) for f in await call(world, "findings")}
    assert ("committed_over_frame", "error") in found
    assert ("estimate_over_frame", "warning") in found
    assert ("committed_unassigned", "warning") in found


async def test_frame_lines_that_contain_one_another_are_refused(world) -> None:
    await call(world, "add_frame_line", {"code": "330", "amount": D("1")}, world.manager)
    assert (
        await _code(call(world, "add_frame_line", {"code": "300", "amount": D("1")}, world.manager))
        == "frame_lines_overlap"
    )
    assert (
        await _code(call(world, "add_frame_line", {"code": "331", "amount": D("1")}, world.manager))
        == "frame_lines_overlap"
    )
    assert (
        await _code(call(world, "add_frame_line", {"code": "330", "amount": D("1")}, world.manager))
        == "frame_code_exists"
    )
    await call(world, "add_frame_line", {"code": "340", "amount": D("1")}, world.manager)


async def test_the_frame_is_generated_from_the_codes_of_the_bill_at_the_depth_asked(world) -> None:
    created = await call(world, "generate_frame", depth=1, amounts="estimate", replace=False, actor_id=world.manager)
    assert [(f.code, f.amount) for f in created] == [("300", D("1500000")), ("400", D("250000"))]
    again = await call(world, "generate_frame", depth=1, amounts="zero", replace=False, actor_id=world.manager)
    assert again == []
    deep = await call(world, "generate_frame", depth=2, amounts="estimate", replace=True, actor_id=world.manager)
    assert sorted(f.code for f in deep) == ["330", "350", "410"]


# ── the business case ────────────────────────────────────────────────────────


async def test_an_investment_can_be_read_from_the_cost_frame_instead_of_typed(world) -> None:
    await call(world, "patch_plan", {"markup_allowance": D("100")}, world.manager)
    await call(world, "add_frame_line", {"code": "300", "amount": D("900")}, world.manager)
    await call(
        world,
        "add_flow_line",
        {"kind": "investment", "source": "cost_frame", "year_from": 0, "year_to": 1},
        world.manager,
    )
    case = await call(world, "business_case")
    assert case["lines"][0]["amount"] == "1000.00"
    line_id = UUID((await call(world, "cost_frame"))["lines"][0]["id"])
    await call(world, "patch_frame_line", line_id, {"amount": D("1900")}, world.manager)
    assert (await call(world, "business_case"))["key_figures"]["total_investment"] == "2000.00"


async def test_key_figures_of_a_complete_case(world) -> None:
    await fill(world)
    case = await call(world, "business_case")
    figures = case["key_figures"]
    assert figures["total_investment"] == "2600000.00"
    assert figures["total_revenue"] == "3200000.00"
    assert figures["total_operating_cost"] == "480000.00"
    assert figures["residual_value"] == "1500000.00"
    assert figures["net_cash_flow"] == "1620000.00"
    assert D(figures["npv"]) > 0
    assert figures["irr_pct"] is not None and D(figures["irr_pct"]) > D("4")
    assert figures["payback_year"] is not None
    assert [r["year"] for r in case["cash_flow"]] == list(range(11))
    # the cumulative column ends on the net cash flow
    assert case["cash_flow"][-1]["cumulative"] == figures["net_cash_flow"]


async def test_without_a_discount_rate_the_present_value_is_not_made_up(world) -> None:
    await call(world, "add_flow_line", {"kind": "investment", "amount": D("100")}, world.manager)
    figures = (await call(world, "business_case"))["key_figures"]
    assert figures["npv"] is None and figures["benefit_cost_ratio"] is None
    assert "discount_rate_missing" in {f.code for f in await call(world, "findings")}


# ── financing ────────────────────────────────────────────────────────────────


async def test_the_sources_are_checked_against_the_investment(world) -> None:
    await fill(world)
    fin = await call(world, "financing")
    assert fin["requirement"] == "2600000.00"
    assert fin["coverage"] == {
        "sources_total": "2600000.00",
        "shortfall": "0.00",
        "surplus": "0.00",
        "covered": True,
        "coverage_pct": "100.00",
    }
    loan = next(s for s in fin["sources"] if s["kind"] == "bank_loan")
    assert loan["share_pct"] == "50.00" and loan["tranche_total"] == "1300000.00"
    await call(world, "patch_source", UUID(loan["id"]), {"amount": D("1000000")}, world.manager)
    short = (await call(world, "financing"))["coverage"]
    assert (short["shortfall"], short["covered"]) == ("300000.00", False)
    codes = {f.code for f in await call(world, "findings")}
    assert {"financing_shortfall", "tranches_differ_from_source"} <= codes


async def test_a_grant_is_checked_against_its_funding_application(world) -> None:
    from app.modules.funding.models import FundingApplication, FundingProgramme

    async with world.factory() as s:
        programme = FundingProgramme(code="P1", name="Programme", country="DE")
        s.add(programme)
        await s.flush()
        app = FundingApplication(
            project_id=world.project_id,
            programme_id=programme.id,
            code="A-1",
            title="Grant",
            status="submitted",
            requested_amount=D("100000"),
            currency="EUR",
        )
        s.add(app)
        await s.flush()
        app_id = app.id
        await s.commit()
    assert (
        await _code(
            call(
                world,
                "add_source",
                {"kind": "grant", "amount": D("1"), "funding_application_id": uuid4()},
                world.manager,
            )
        )
        == "funding_application_not_found"
    )
    src = await call(
        world,
        "add_source",
        {"kind": "grant", "name": "State grant", "amount": D("150000"), "funding_application_id": app_id},
        world.manager,
    )
    fin = await call(world, "financing")
    assert fin["sources"][0]["award"] == {
        "code": "A-1",
        "title": "Grant",
        "status": "submitted",
        "amount": "100000.00",
        "basis": "requested",
    }
    assert "grant_over_award" in {f.code for f in await call(world, "findings")}
    await call(world, "patch_source", UUID(str(src.id)), {"amount": D("100000")}, world.manager)
    assert "grant_over_award" not in {f.code for f in await call(world, "findings")}


# ── the lifecycle ────────────────────────────────────────────────────────────


async def test_a_plan_with_open_errors_cannot_be_proposed(world) -> None:
    with pytest.raises(EconomicsError) as exc:
        await call(world, "propose", "ready", world.manager)
    assert (exc.value.code, exc.value.status_code) == ("plan_has_errors", 422)
    assert {"discount_rate_missing", "frame_empty", "no_investment", "no_sources"} <= {
        v["code"] for v in exc.value.violations
    }
    assert await _status(world) == "draft"


async def test_a_proposal_freezes_the_edits_and_a_withdrawal_opens_them(world) -> None:
    await fill(world)
    approval = await call(world, "propose", "Business case, frame and financing agree.", world.manager)
    assert (await _status(world), approval.number, approval.status) == ("proposed", 1, "proposed")
    assert approval.snapshot["key_figures"]["total_investment"] == "2600000.00"
    assert len(approval.snapshot_hash) == 64
    assert (
        await _code(call(world, "add_frame_line", {"code": "500", "amount": D("1")}, world.manager))
        == "plan_not_editable"
    )
    await call(world, "withdraw", world.manager)
    assert await _status(world) == "draft"
    await call(world, "add_frame_line", {"code": "500", "amount": D("1")}, world.manager)


async def test_a_project_with_gates_is_not_approved_by_hand(world) -> None:
    await fill(world)
    await call(world, "propose", "ok", world.manager)
    assert await _code(call(world, "approve_by_hand", world.decider)) == "approved_by_gate_decision"


async def _decide_gate(w) -> None:
    await fill_registers(w)
    g = await prepare_gate(w, GATE)
    await decide(w, g.id, "go")
    doc = (await documents(w))[COMMERCIAL_DOC]
    await handle_frame_document(
        {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"},
        session_factory=w.factory,
    )


async def test_the_gate_decision_approves_the_plan_by_someone_else_than_the_proposer(world) -> None:
    await fill(world)
    await call(world, "propose", "ok", world.manager)
    await _decide_gate(world)
    plan = await call(world, "require_plan")
    assert plan.status == "approved"
    approvals = await call(world, "plan_view", actor_id=world.manager, can_edit=True, can_manage=True)
    current = approvals["approvals"][0]
    assert (current["status"], current["approval_source"], current["four_eyes"]) == ("approved", "gate", True)
    assert current["approved_by"] == str(world.decider)
    assert current["key_figures"]["total_investment"] == "2600000.00"
    assert approvals["editable"] is False


async def test_four_eyes_holds_at_the_gate_when_the_decider_proposed(world) -> None:
    await fill(world)
    await call(world, "propose", "ok", world.decider)
    await _decide_gate(world)
    plan = await call(world, "require_plan")
    assert plan.status == "proposed"
    view = await call(world, "plan_view", actor_id=world.manager, can_edit=True, can_manage=True)
    assert view["approvals"][0]["blocked_reason"] == "four_eyes_proposer_is_approver"


async def test_reopening_with_gates_needs_a_change_request(world) -> None:
    await fill(world)
    await call(world, "propose", "ok", world.manager)
    await _decide_gate(world)
    assert await _code(call(world, "reopen", world.manager, "price rise")) == "change_request_required"


REGISTER_OPEN = dict.fromkeys(
    (
        "economics_securities_in_place",
        "economics_insurance_in_place",
        "economics_tax_clarified",
        "economics_receivables_payables_set",
        "economics_administration_set",
    ),
    "not_met",
)


async def _fill_registers(world) -> None:
    await fill_registers(world)


async def test_the_gate_reads_the_plan_through_its_evidence_provider(world) -> None:
    doc = (await documents(world))[COMMERCIAL_DOC]
    attempt = GateAttempt(gate_id=uuid4(), gate_code=GATE, attempt_no=1)
    area = next(a for a in (await areas(world)).values() if a.id == doc.area_id)
    async with world.factory() as s:
        items = await plan_ready(s, world.project_id, attempt, area)
    assert {i.code: i.state for i in items} == {
        **REGISTER_OPEN,
        "economics_proposed": "not_met",
        "economics_financing_covered": "not_met",
        "economics_no_errors": "not_met",
    }
    await fill(world)
    await call(world, "propose", "ok", world.manager)
    async with world.factory() as s:
        items = await plan_ready(s, world.project_id, attempt, area)
    assert {i.code: i.state for i in items} == {
        **REGISTER_OPEN,
        "economics_proposed": "met",
        "economics_financing_covered": "met",
        "economics_no_errors": "met",
    }
    await _fill_registers(world)
    async with world.factory() as s:
        items = await plan_ready(s, world.project_id, attempt, area)
    assert {i.code: i.state for i in items if i.code in REGISTER_OPEN} == dict.fromkeys(REGISTER_OPEN, "met")
    other = next(a for a in (await areas(world)).values() if a.id != doc.area_id)
    async with world.factory() as s:
        assert await plan_ready(s, world.project_id, attempt, other) == []


# ── without gates ────────────────────────────────────────────────────────────


async def test_without_gates_a_manager_other_than_the_proposer_approves_by_hand(ungoverned) -> None:
    w = ungoverned
    await fill(w)
    await call(w, "propose", "ok", w.manager)
    assert await _code(call(w, "approve_by_hand", w.manager)) == "four_eyes_proposer_is_approver"
    await call(w, "approve_by_hand", w.decider)
    assert await _status(w) == "approved"


async def test_reopening_without_gates_needs_a_reason_and_closing_it_restores_the_approved_plan(ungoverned) -> None:
    w = ungoverned
    await fill(w)
    await call(w, "propose", "ok", w.manager)
    await call(w, "approve_by_hand", w.decider)
    assert await _code(call(w, "reopen", w.manager, "")) == "reopen_reason_required"
    await call(w, "reopen", w.manager, "construction prices rose")
    await call(w, "patch_plan", {"markup_allowance": D("999")}, w.manager)
    await call(w, "add_frame_line", {"code": "700", "amount": D("5")}, w.manager)
    await call(w, "close_reopening", w.manager)
    plan = await call(w, "require_plan")
    assert (plan.status, plan.markup_allowance) == ("approved", D("200000"))
    assert [f["code"] for f in (await call(w, "cost_frame"))["lines"]] == ["300", "400"]
    assert (await call(w, "business_case"))["key_figures"]["total_investment"] == "2600000.00"


async def test_a_second_proposal_supersedes_the_approved_one_when_it_is_approved(ungoverned) -> None:
    w = ungoverned
    await fill(w)
    await call(w, "propose", "ok", w.manager)
    await call(w, "approve_by_hand", w.decider)
    await call(w, "reopen", w.manager, "scope grew")
    await call(w, "patch_plan", {"markup_allowance": D("300000")}, w.manager)
    # the investment is read from the frame, so the sources now fall short and the plan cannot be proposed
    assert await _code(call(w, "propose", "again", w.manager)) == "plan_has_errors"
    src = (await call(w, "financing"))["sources"][0]
    await call(w, "patch_source", UUID(src["id"]), {"amount": D("1400000")}, w.manager)
    tranche = src["tranches"][0]
    await call(w, "patch_tranche", UUID(tranche["id"]), {"amount": D("1400000")}, w.manager)
    await call(w, "propose", "again", w.manager)
    await call(w, "approve_by_hand", w.decider)
    views = (await call(w, "plan_view", actor_id=w.manager, can_edit=True, can_manage=True))["approvals"]
    assert [(a["number"], a["status"]) for a in views] == [(2, "approved"), (1, "superseded")]


async def test_drawing_a_tranche_stays_open_after_approval(ungoverned) -> None:
    w = ungoverned
    await fill(w)
    await call(w, "propose", "ok", w.manager)
    await call(w, "approve_by_hand", w.decider)
    tranche = (await call(w, "financing"))["sources"][0]["tranches"][0]
    await call(w, "patch_tranche", UUID(tranche["id"]), {"status": "drawn"}, w.manager)
    drawn = (await call(w, "financing"))["sources"][0]["tranches"][0]
    assert drawn["status"] == "drawn" and drawn["drawn_on"]
    assert (
        await _code(call(w, "patch_tranche", UUID(tranche["id"]), {"amount": D("1")}, w.manager)) == "plan_not_editable"
    )
    assert await _code(call(w, "delete_tranche", UUID(tranche["id"]), w.manager)) == "plan_not_editable"


async def test_the_service_reads_money_as_exact_decimals(ungoverned) -> None:
    w = ungoverned
    await call(w, "add_frame_line", {"code": "300", "amount": D("0.1")}, w.manager)
    await call(w, "add_frame_line", {"code": "400", "amount": D("0.2")}, w.manager)
    async with w.factory() as s:
        frame = await EconomicsService(s).cost_frame(w.project_id)
    assert frame["totals"]["lines"] == "0.30"


# ── registers ────────────────────────────────────────────────────────────────


async def test_registers_stay_editable_while_the_plan_is_proposed(world) -> None:
    await fill(world)
    await call(world, "propose", "ok", world.manager)
    await _fill_registers(world)
    regs = await call(world, "registers")
    assert regs["state"] == dict.fromkeys(regs["state"], True)
    assert regs["tax"]["confirmed_by_name"]
    assert [p["area"] for p in regs["process"]] == ["receivables", "payables", "administration"]


async def test_a_changed_tax_treatment_is_no_longer_confirmed(world) -> None:
    await call(
        world, "put_tax", {"vat_treatment": "standard", "input_tax_deduction": True, "confirm": True}, world.manager
    )
    await call(
        world, "put_tax", {"vat_treatment": "exempt", "input_tax_deduction": False, "confirm": False}, world.manager
    )
    regs = await call(world, "registers")
    assert regs["tax"]["confirmed"] is False and regs["tax"]["confirmed_by"] is None
    assert "tax_not_confirmed" in [f["code"] for f in regs["findings"]]


async def test_an_expired_security_is_flagged_and_a_period_must_run_forwards(world) -> None:
    await call(
        world,
        "add_security",
        {"kind": "bid", "description": "Old bond", "status": "in_place", "valid_until": "2020-01-01"},
        world.manager,
    )
    regs = await call(world, "registers")
    assert regs["securities"][0]["lapsed"] is True
    assert "security_expired" in [f["code"] for f in regs["findings"]]
    assert (
        await _code(
            call(
                world,
                "add_insurance",
                {"kind": "liability", "insurer": "X", "period_from": "2026-05-01", "period_to": "2026-01-01"},
                world.manager,
            )
        )
        == "period_invalid"
    )


async def test_a_security_of_another_project_is_not_found(world) -> None:
    from uuid import uuid4

    assert (
        await _code(call(world, "patch_security", uuid4(), {"status": "released"}, world.manager))
        == "security_not_found"
    )
    assert await _code(call(world, "delete_insurance", uuid4(), world.manager)) == "insurance_not_found"


async def test_the_approval_names_who_proposed_and_who_approved(world) -> None:
    await fill(world)
    await call(world, "propose", "ok", world.manager)
    view = await call(world, "plan_view", actor_id=world.manager, can_edit=True, can_manage=True)
    approval = view["approvals"][0]
    assert approval["proposed_by_name"] and approval["approved_by_name"] == ""
    assert view["can"]["records"] is True
