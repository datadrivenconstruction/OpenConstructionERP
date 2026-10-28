# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠How a delivery decision gets approved, and every way the review found it could go wrong.

The carrier document is named by a tag in the governance catalogue and
resolved at read time; no document of the area stands in for it. The mirror is
the only writer of ``approved`` and ``binding``; it re-checks readiness and
four-eyes, and it catches up on a read when the event was lost. The change
path has a way back.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model.errors import DeliveryModelError
from app.modules.delivery_model.events import handle_frame_document
from app.modules.delivery_model.evidence import decision_ready, register_gate_evidence
from app.modules.delivery_model.service import DeliveryModelService
from app.modules.project_governance.evidence import GateAttempt
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.delivery_fixtures import (
    CONTRACT_DOC,
    GATE,
    build_world,
    call,
    change_request,
    compare,
    decisions,
    propose,
    settle_change_request,
    state,
    view,
)
from tests.pg.governance_fixtures import areas, decide, documents, gate, only_evidence, prepare_gate

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory():
    with only_evidence(register=register_gate_evidence):
        async with isolated_engine() as engine:
            yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def world(factory):
    return await build_world(factory)


async def _ready(w, *, proposer: uuid.UUID | None = None) -> dict[str, uuid.UUID]:
    """Compare, confirm the matrix, derive the plan and propose design and build."""
    ids = await compare(w)
    await call(w, "confirm_allocations", None, w.manager)
    await call(w, "derive_packages", w.manager)
    await propose(w, ids["design_build"], actor_id=proposer or w.manager)
    return ids


async def _decide_gate(w, *, decider: uuid.UUID | None = None, deliver: bool = True) -> None:
    g = await prepare_gate(w, GATE)
    await decide(w, g.id, "go", decider=decider)
    if deliver:
        doc = (await documents(w))[CONTRACT_DOC]
        await handle_frame_document(
            {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"},
            session_factory=w.factory,
        )


# ── finding 1: the carrier is named by data, never guessed ──────────────────


CARRIERS = {
    "neutral": ("procurement", "procurement_strategy"),
    "riba_2020": ("procurement", "procurement_strategy"),
    "aia_b101": ("procurement", "procurement_strategy"),
    "hoai_lph": ("procurement", "procurement_strategy"),
    "aho_heft9": ("e", "vertragsstruktur"),
    "elf_module_framework": ("m02_contract_management", CONTRACT_DOC),
}


@pytest.mark.parametrize("catalogue_id", sorted(CARRIERS))
async def test_every_shipped_phase_model_carries_the_decision_and_takes_a_proposal(factory, catalogue_id) -> None:
    """The review found five of six models with no way to approve; under hoai_lph the bill of quantities bound it."""
    w = await build_world(factory, catalogue_id=catalogue_id)
    ids = await compare(w)
    model = await view(w, can_manage=True)
    doc = (await documents(w))[CARRIERS[catalogue_id][1]]
    by_id = {a.id: code for code, a in (await areas(w)).items()}
    assert model["carrier"] == {
        "document_id": str(doc.id),
        "document_type": CARRIERS[catalogue_id][1],
        "document_status": "draft",
        "missing_reason": None,
    }
    assert by_id[doc.area_id] == CARRIERS[catalogue_id][0]
    assert model["can"]["propose"] == {"applies": True, "allowed": True, "reason": None}
    await propose(w, ids["design_build"])
    assert (await state(w)).status == "proposed"
    async with w.factory() as s:
        assert await DeliveryModelService(s).procurement_released(w.project_id) is not None


@pytest.mark.parametrize("catalogue_id", ["hoai_lph", "neutral"])
async def test_a_phase_model_without_a_carrier_refuses_the_proposal(factory, catalogue_id) -> None:
    """A tenant model that hosts the delivery model nowhere: no other document of the area stands in."""
    w = await build_world(factory, catalogue_id=catalogue_id, carrier=False)
    ids = await compare(w)
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_build"])
    assert (exc.value.code, exc.value.status_code) == ("carrier_missing", 409)
    model = await view(w, can_manage=True)
    assert model["status"] == "under_evaluation"
    assert model["carrier"] == {
        "document_id": None,
        "document_type": None,
        "document_status": None,
        "missing_reason": "carrier_missing",
    }
    assert model["can"]["propose"] == {"applies": True, "allowed": False, "reason": "carrier_missing"}
    async with w.factory() as s:
        assert await DeliveryModelService(s).procurement_released(w.project_id) is None


async def test_without_a_governance_model_the_project_uses_no_gates_and_needs_no_carrier(factory) -> None:
    """No gates means approval by hand: the missing frame document is not a reason to refuse the proposal."""
    w = await build_world(factory, governance=False)
    ids = await compare(w)
    model = await view(w, can_manage=True)
    assert model["gates_in_use"] is False
    assert model["carrier"]["missing_reason"] is None
    assert model["can"]["propose"] == {"applies": True, "allowed": True, "reason": None}
    await propose(w, ids["design_build"])
    assert (await state(w)).status == "proposed"


async def test_a_blocking_provider_says_unknown_once_when_there_is_no_carrier(factory) -> None:
    """Not an empty list: a project that uses the module and cannot be checked must be visible at the gate."""
    w = await build_world(factory, carrier=False)
    await compare(w)
    g = await gate(w, GATE)
    attempt = GateAttempt(gate_id=g.id, gate_code=GATE, attempt_no=1)
    async with w.factory() as s:
        found = [
            (code, item.code, item.state, item.detail)
            for code, area in sorted((await areas(w)).items())
            for item in await decision_ready(s, w.project_id, attempt, area)
        ]
    assert found == [("m01_project_management", "delivery_carrier_missing", "unknown", "carrier_missing")]


async def test_evidence_is_reported_in_the_area_of_the_carrier_document_only(world) -> None:
    w = world
    await compare(w)
    g = await gate(w, GATE)
    attempt = GateAttempt(gate_id=g.id, gate_code=GATE, attempt_no=1)
    async with w.factory() as s:
        by_area = {
            code: [(i.code, i.state) for i in await decision_ready(s, w.project_id, attempt, area)]
            for code, area in (await areas(w)).items()
        }
    assert {code for code, items in by_area.items() if items} == {"m02_contract_management"}
    assert ("delivery_decision_proposed", "not_met") in by_area["m02_contract_management"]
    # The gate that carries the decision is also the one into the phase that enables procurement:
    # rule 10 is checked here too.
    assert ("delivery_ofi_routes", "met") in by_area["m02_contract_management"]


# ── findings 2 and 3: no stored link, and a lost event is caught up ─────────


async def test_the_decision_is_approved_by_the_gate_and_records_the_carrier(world) -> None:
    w = world
    await _ready(w)
    assert (await view(w))["carrier"]["document_status"] != "binding"
    await _decide_gate(w)
    doc = (await documents(w))[CONTRACT_DOC]
    d = (await decisions(w))["design_build"]
    assert (await state(w)).status == "binding"
    assert (d["status"], d["approval_source"], d["approved_by"]) == ("approved", "gate", str(w.decider))
    assert d["governance_document_id"] == str(doc.id)
    assert d["four_eyes"] is True and d["four_eyes_violated"] is False
    # Finding 6: the approved record carries the matrix and the plan it was approved with.
    matrix = await call(w, "allocation_matrix")
    assert len(d["snapshot"]["allocations"]) == len(matrix["items"]) > 0
    assert [p["code"] for p in d["snapshot"]["packages"]] != []
    assert d["snapshot_hash"] and len(d["snapshot_hash"]) == 64


async def test_a_lost_binding_event_is_caught_up_by_the_next_read(world) -> None:
    w = world
    await _ready(w)
    await _decide_gate(w, deliver=False)  # the subscriber never ran
    assert (await state(w)).status == "proposed"
    model = await view(w)
    assert model["status"] == "binding"
    # The read wrote, and the write is committed: a fresh session sees it.
    fresh = await state(w)
    assert fresh.status == "binding" and fresh.current_decision_id is not None
    assert (await decisions(w))["design_build"]["status"] == "approved"


async def test_a_failing_mirror_is_logged_at_warning(world, caplog) -> None:
    w = world

    def broken():
        raise RuntimeError("database gone")

    with caplog.at_level("WARNING", logger="app.modules.delivery_model.events"):
        out = await handle_frame_document(
            {"project_id": str(w.project_id), "document_id": str(uuid.uuid4()), "status": "binding"},
            session_factory=broken,
        )
    assert out is False
    assert [r.levelname for r in caplog.records if "binding mirror failed" in r.getMessage()] == ["WARNING"]


# ── finding 4d: readiness is checked again at approval ──────────────────────


async def test_an_allocation_undone_after_the_gate_check_blocks_the_approval(world) -> None:
    w = world
    await _ready(w)
    g = await prepare_gate(w, GATE)
    await decide(w, g.id, "go")
    # Between the gate's evidence check and the mirror: the matrix is still editable while proposed.
    await call(w, "put_allocation", "insurance", {"party": None}, w.manager)
    doc = (await documents(w))[CONTRACT_DOC]
    event = {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"}
    assert await handle_frame_document(event, session_factory=w.factory) is True  # the reason was recorded
    assert await handle_frame_document(event, session_factory=w.factory) is False  # and only once
    assert (await state(w)).status == "proposed"
    model = await view(w)
    assert model["approval_blocked_reason"] == "approval_not_ready"
    await call(w, "confirm_allocations", ["insurance"], w.manager)
    assert (await view(w))["status"] == "proposed"  # insurance still has no party
    await call(w, "put_allocation", "insurance", {"party": "insurer", "basis": "insurance"}, w.manager)
    await call(w, "confirm_allocations", ["insurance"], w.manager)
    assert (await view(w))["status"] == "binding"


# ── finding 11: four-eyes is enforced, and stored ───────────────────────────


async def test_the_proposer_cannot_be_the_one_who_approves(world) -> None:
    w = world
    await _ready(w, proposer=w.decider)
    await _decide_gate(w, decider=w.decider)
    assert (await state(w)).status == "proposed"
    d = (await decisions(w))["design_build"]
    assert (d["status"], d["approved_by"]) == ("proposed", None)
    assert d["approval_blocked_reason"] == "four_eyes_proposer_is_approver"
    # The way out: someone else proposes. The old gate decision predates that proposal and approves nothing.
    await call(w, "withdraw", w.decider)
    ids = {o["form_code"]: uuid.UUID(o["id"]) for o in (await call(w, "comparison"))["options"]}
    await propose(w, ids["design_build"], actor_id=w.manager)
    assert (await state(w)).status == "proposed"
    assert (await view(w))["approval_blocked_reason"] == "approval_needs_change_request"
    cr = await change_request(w)
    await settle_change_request(w, cr, "approved")
    current = next(d for d in await call(w, "decision_views") if d["is_current"])
    assert (current["status"], current["approval_source"]) == ("approved", "change_request")
    assert current["approved_by"] == str(w.decider) and current["proposed_by"] == str(w.manager)


async def test_four_eyes_applies_to_the_change_request_path_too(world) -> None:
    w = world
    ids = await _ready(w)
    await _decide_gate(w)
    cr = await change_request(w)
    await call(w, "reopen", w.manager)
    await propose(w, ids["design_build"], actor_id=w.decider)  # same form, a new record
    await settle_change_request(w, cr, "approved", by=w.decider)
    assert (await state(w)).status == "proposed"
    assert (await view(w))["approval_blocked_reason"] == "four_eyes_proposer_is_approver"


async def test_the_four_eyes_setting_is_stored_at_approval_and_a_later_toggle_changes_nothing(world) -> None:
    w = world
    await _ready(w)
    await _decide_gate(w)
    assert (await decisions(w))["design_build"]["four_eyes"] is True
    async with w.factory() as s:
        await GovernanceService(s).update_settings(
            w.project_id,
            four_eyes=False,
            decision_route_id=None,
            change_route_id=None,
            fields_set={"four_eyes"},
            actor_id=w.manager,
        )
        await s.commit()
    assert (await decisions(w))["design_build"]["four_eyes"] is True


async def test_with_four_eyes_off_the_proposer_may_approve_and_that_is_what_is_stored(world) -> None:
    w = world
    async with w.factory() as s:
        await GovernanceService(s).update_settings(
            w.project_id,
            four_eyes=False,
            decision_route_id=None,
            change_route_id=None,
            fields_set={"four_eyes"},
            actor_id=w.manager,
        )
        await s.commit()
    await _ready(w, proposer=w.decider)
    await _decide_gate(w, decider=w.decider)
    d = (await decisions(w))["design_build"]
    assert (d["status"], d["four_eyes"], d["four_eyes_violated"]) == ("approved", False, False)


# ── finding 4: the change path ──────────────────────────────────────────────


async def test_a_rejected_change_request_returns_the_model_to_binding_and_restores_the_matrix(world) -> None:
    w = world
    ids = await _ready(w)
    await _decide_gate(w)
    cr = await change_request(w)
    await call(w, "reopen", w.manager)
    await call(
        w,
        "put_allocation",
        "insurance",
        {"party": "owner", "rationale": "self insured during the reopening"},
        w.manager,
    )
    await propose(w, ids["design_bid_build_single"])
    await settle_change_request(w, cr, "rejected")  # governance publishes no event for a rejection
    assert (await state(w)).status == "proposed"
    model = await view(w)  # the next read settles it
    assert (model["status"], model["selected_form_code"], model["change_request_id"]) == (
        "binding",
        "design_build",
        None,
    )
    by_form = await decisions(w)
    assert by_form["design_bid_build_single"]["status"] == "rejected"
    assert by_form["design_build"]["status"] == "approved" and by_form["design_build"]["is_current"] is True
    matrix = await call(w, "allocation_matrix")
    insurance = next(i["allocation"] for i in matrix["items"] if i["category_code"] == "insurance")
    frozen = next(a for a in by_form["design_build"]["snapshot"]["allocations"] if a["category_code"] == "insurance")
    assert (insurance["party"], insurance["rationale"]) == (frozen["party"], frozen["rationale"])
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "patch_weights", {"innovation": "8"}, w.manager)
    assert exc.value.code == "model_not_editable"


async def test_a_rejected_change_request_is_settled_before_any_new_proposal_too(world) -> None:
    w = world
    await _ready(w)
    await _decide_gate(w)
    cr = await change_request(w)
    await call(w, "reopen", w.manager)
    await settle_change_request(w, cr, "rejected")
    assert (await view(w))["status"] == "binding"


async def test_a_reopening_can_be_given_up(world) -> None:
    w = world
    await _ready(w)
    await _decide_gate(w)
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "close_reopening", w.manager)
    assert exc.value.code == "reopening_not_open"
    await change_request(w)
    await call(w, "reopen", w.manager)
    model = await view(w, can_manage=True)
    assert model["can"]["close_reopening"] == {"applies": True, "allowed": True, "reason": None}
    await call(w, "close_reopening", w.manager)
    after = await view(w, can_manage=True)
    assert (after["status"], after["change_request_id"]) == ("binding", None)
    assert after["can"]["close_reopening"] == {"applies": False, "allowed": False, "reason": "reopening_not_open"}


async def test_a_change_request_approved_before_the_new_proposal_approves_it_when_it_comes(world) -> None:
    """Finding 4b: no second event follows, so the proposal itself has to catch up."""
    w = world
    ids = await _ready(w)
    await _decide_gate(w)
    cr = await change_request(w)
    await call(w, "reopen", w.manager)
    await settle_change_request(w, cr, "approved")
    assert (await state(w)).status == "reopened"
    await propose(w, ids["design_build"])  # same form, so the plan and the matrix still fit
    d = next(d for d in await call(w, "decision_views") if d["is_current"])
    assert (await state(w)).status == "binding"
    assert (d["status"], d["approval_source"], d["governance_ref_id"]) == ("approved", "change_request", str(cr))
    # Approved when it was proposed, not at the earlier moment the change request was decided.
    assert d["approved_at"] >= d["proposed_at"]


async def test_an_old_gate_decision_does_not_approve_a_later_proposal(world) -> None:
    """Finding 4c: the gate branch had no time guard."""
    w = world
    await _ready(w, proposer=w.decider)
    await _decide_gate(w, decider=w.decider)  # binding, but four-eyes left the decision proposed
    await call(w, "withdraw", w.decider)
    ids = {o["form_code"]: uuid.UUID(o["id"]) for o in (await call(w, "comparison"))["options"]}
    await propose(w, ids["design_build"], actor_id=w.manager)
    d = next(d for d in await call(w, "decision_views") if d["is_current"])
    assert (d["status"], d["approved_by"]) == ("proposed", None)
    assert d["approval_blocked_reason"] == "approval_needs_change_request"


# ── finding 8: rule 9 before the first approval, and withdraw ───────────────


async def test_withdraw_clears_the_form_and_rule9_still_asks_for_dispositions(world) -> None:
    from decimal import Decimal

    from app.modules.contracts.models import Contract

    w = world
    ids = await _ready(w)
    async with w.factory() as s:
        contract = Contract(
            project_id=w.project_id,
            code="C-1",
            title="Design and build works",
            contract_type="design_build",
            counterparty_type="subcontractor",
            total_value=Decimal("1000000"),
            currency="EUR",
            status="active",
            metadata_={},
        )
        s.add(contract)
        await s.commit()
    pkgs = {p["code"]: p for p in await call(w, "package_views")}
    await call(w, "link_package", uuid.UUID(pkgs["design_and_build"]["id"]), "contract", contract.id, w.manager)
    await call(w, "withdraw", w.manager)
    model = await view(w)
    assert (model["status"], model["selected_form_code"], model["current_decision_id"]) == (
        "under_evaluation",
        None,
        None,
    )
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_bid_build_single"])
    assert exc.value.code == "form_change_impacts_packages"
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "withdraw", w.manager)
    assert (exc.value.code, exc.value.status_code) == ("decision_not_pending", 409)


async def test_can_flags_say_what_the_enforcement_says(world) -> None:
    w = world
    await compare(w)
    reader = await view(w)
    assert reader["can"]["propose"] == {"applies": True, "allowed": False, "reason": "permission_missing"}
    manager = await view(w, can_edit=True, can_manage=True)
    assert manager["can"]["propose"] == {"applies": True, "allowed": True, "reason": None}
    assert manager["can"]["withdraw"] == {"applies": False, "allowed": False, "reason": "decision_not_pending"}
    assert manager["can"]["reopen"] == {"applies": False, "allowed": False, "reason": "model_not_binding"}
    assert manager["can"]["edit"] == {"applies": True, "allowed": True, "reason": None}
    await call(w, "confirm_allocations", None, w.manager)
    await call(w, "derive_packages", w.manager)
    ids = {o["form_code"]: uuid.UUID(o["id"]) for o in (await call(w, "comparison"))["options"]}
    await propose(w, ids["design_build"])
    proposed = await view(w, can_edit=True, can_manage=True)
    assert proposed["can"]["propose"] == {"applies": False, "allowed": False, "reason": "decision_pending"}
    assert proposed["can"]["edit"] == {"applies": False, "allowed": False, "reason": "model_not_editable"}
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_build"])
    assert exc.value.code == "decision_pending"
    await _decide_gate(w)
    bound = await view(w, can_edit=True, can_manage=True)
    assert bound["can"]["reopen"] == {"applies": True, "allowed": False, "reason": "change_request_required"}
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "reopen", w.manager)
    assert exc.value.code == "change_request_required"
    async with w.factory() as s:
        assert await DeliveryModelService(s).is_carrier_area_owner(w.project_id, w.owner) is True
        assert await DeliveryModelService(s).is_carrier_area_owner(w.project_id, w.editor) is False
