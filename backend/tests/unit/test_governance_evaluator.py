# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The gate evaluator, one test group per behaviour of SPEC section 4.

The evaluator is pure: plain values in, blockers and violations out. Every rule
has a case that passes and, next to it, the smallest change that must make it
fail, so a rule that went missing turns a test red instead of leaving the happy
path green.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.evaluator import (
    AreaState,
    CheckState,
    ConditionState,
    DecisionRequest,
    DocumentState,
    GateContext,
    ProposedCondition,
)

TODAY = date(2026, 10, 11)
OWNER_A = "owner-a"
OWNER_B = "owner-b"
DECIDER = "decider"


def _area(code: str = "A", owner: str | None = OWNER_A, **kw) -> AreaState:
    return AreaState(code=code, owner_user_id=owner, **kw)


def _doc(area: str = "A", doc_type: str = "pep", **kw) -> DocumentState:
    base = dict(
        id=f"doc-{area}-{doc_type}",
        area_code=area,
        doc_type=doc_type,
        required=True,
        status="in_review",
        container_id="c1",
        current_revision_id="rev-1",
        current_content_hash="h1",
        bound_revision_id=None,
        read_only=False,
    )
    base.update(kw)
    return DocumentState(**base)


def _check(area: str = "A", status: str = "ready", **kw) -> CheckState:
    base = dict(
        area_code=area,
        status=status,
        confirmed_by=OWNER_A if area == "A" else OWNER_B,
        confirmed_revisions={f"doc-{area}-pep": "rev-1"},
        stale=False,
        na_rationale="",
    )
    base.update(kw)
    return CheckState(**base)


def _ctx(**kw) -> GateContext:
    base = dict(
        gate_code="G1",
        gate_status="in_review",
        areas=(_area("A", OWNER_A), _area("B", OWNER_B)),
        documents=(_doc("A"), _doc("B")),
        checks=(_check("A"), _check("B", confirmed_revisions={"doc-B-pep": "rev-1"})),
        prior_conditions=(),
        today=TODAY,
        model_stopped=False,
        four_eyes=True,
    )
    base.update(kw)
    return GateContext(**base)


def _req(outcome: str = "go", **kw) -> DecisionRequest:
    base = dict(outcome=outcome, rationale="", decider_id=DECIDER)
    base.update(kw)
    return DecisionRequest(**base)


def _codes(items) -> set[str]:
    return {i.code for i in items}


def test_a_clean_gate_has_no_blockers_and_go_is_valid() -> None:
    ctx = _ctx()
    assert ev.gate_blockers(ctx) == []
    assert ev.validate_decision(ctx, _req("go")) == []


# 1 ── go blocked while a required document is not approved ─────────────────


@pytest.mark.parametrize(
    "doc_kw",
    [
        {"status": "draft"},
        {"container_id": None},
        {"current_revision_id": None},
    ],
)
def test_1_go_is_blocked_by_a_required_document_not_ready(doc_kw) -> None:
    ctx = _ctx(documents=(_doc("A", **doc_kw), _doc("B")))
    blockers = ev.gate_blockers(ctx)
    assert any(b.code == "required_document_not_approved" and b.area_code == "A" for b in blockers)
    assert "required_document_not_approved" in _codes(ev.validate_decision(ctx, _req("go")))


def test_1_an_optional_document_in_draft_blocks_nothing() -> None:
    ctx = _ctx(documents=(_doc("A", status="draft", required=False), _doc("B")))
    assert ev.validate_decision(ctx, _req("go")) == []


def test_1_a_binding_document_counts_as_approved() -> None:
    ctx = _ctx(documents=(_doc("A", status="binding", bound_revision_id="rev-1"), _doc("B")))
    assert ev.validate_decision(ctx, _req("go")) == []


def test_1_a_condition_naming_the_document_turns_the_blocker_into_a_condition() -> None:
    ctx = _ctx(documents=(_doc("A", status="draft"), _doc("B")))
    cond = ProposedCondition(area_code="A", document_type="pep", text="Deliver PEP", owner_user_id=OWNER_A)
    req = _req("go_with_conditions", rationale="PEP to follow", conditions=(cond,))
    assert ev.validate_decision(ctx, req) == []
    # The same condition on another document does not cover it.
    other = replace(cond, document_type="eir")
    req_other = _req("go_with_conditions", rationale="x", conditions=(other,))
    assert "required_document_not_approved" in _codes(ev.validate_decision(ctx, req_other))


# 2 ── area without owner blocks ─────────────────────────────────────────────


def test_2_an_applicable_area_without_owner_blocks_the_gate() -> None:
    ctx = _ctx(areas=(_area("A", None), _area("B", OWNER_B)))
    assert any(b.code == "area_without_owner" and b.area_code == "A" for b in ev.gate_blockers(ctx))
    assert "area_without_owner" in _codes(ev.validate_decision(ctx, _req("go")))
    # Not even a condition can paper over a missing owner.
    cond = ProposedCondition(area_code="A", document_type=None, text="Name owner", owner_user_id=OWNER_B)
    req = _req("go_with_conditions", rationale="x", conditions=(cond,), proceed_at_risk_areas=("A",))
    assert "area_without_owner" in _codes(ev.validate_decision(ctx, req))


def test_2_an_area_accepted_as_not_applicable_needs_no_owner() -> None:
    ctx = _ctx(
        areas=(_area("A", None, applicable=False, na_rationale="No BIM here"), _area("B", OWNER_B)),
        documents=(_doc("B"),),
        checks=(_check("B", confirmed_revisions={"doc-B-pep": "rev-1"}),),
    )
    assert ev.validate_decision(ctx, _req("go", accepted_not_applicable=("A",))) == []


# 3 ── the snapshot freezes exact revisions and checks ───────────────────────


def test_3_snapshot_names_exact_revisions_hashes_and_check_states() -> None:
    ctx = _ctx()
    snap = ev.build_snapshot(ctx, _req("go"))
    docs = {d["document_id"]: d for d in snap["documents"]}
    assert docs["doc-A-pep"]["revision_id"] == "rev-1"
    assert docs["doc-A-pep"]["content_hash"] == "h1"
    checks = {c["area_code"]: c for c in snap["checks"]}
    assert checks["A"]["status"] == "ready"
    assert checks["A"]["confirmed_by"] == OWNER_A
    assert snap["decider_id"] == DECIDER
    assert snap["four_eyes"] is True


def test_3_snapshot_is_a_copy_not_a_view() -> None:
    ctx = _ctx()
    snap = ev.build_snapshot(ctx, _req("go"))
    later = _ctx(documents=(_doc("A", current_revision_id="rev-2", current_content_hash="h2"), _doc("B")))
    later_snap = ev.build_snapshot(later, _req("go"))
    assert {d["revision_id"] for d in snap["documents"]} == {"rev-1"}
    assert "rev-2" in {d["revision_id"] for d in later_snap["documents"]}


# 4 ── a binding document edit creates a pending draft ───────────────────────


def test_4_a_new_revision_on_a_binding_document_is_pending_not_in_force() -> None:
    doc = _doc(status="binding", bound_revision_id="rev-1", current_revision_id="rev-2")
    assert ev.revision_in_force(doc) == "rev-1"
    assert ev.pending_revision(doc) == "rev-2"
    assert ev.binding_document_changed(doc) is True


def test_4_an_unchanged_binding_document_has_no_pending_revision() -> None:
    doc = _doc(status="binding", bound_revision_id="rev-1", current_revision_id="rev-1")
    assert ev.pending_revision(doc) is None
    assert ev.binding_document_changed(doc) is False


def test_4_attaching_or_resubmitting_a_binding_document_is_refused() -> None:
    doc = _doc(status="binding", bound_revision_id="rev-1")
    assert ev.document_edit_violation(doc, "attach") == "binding_requires_change_request"
    assert ev.document_edit_violation(doc, "submit") == "binding_requires_change_request"
    assert ev.document_edit_violation(_doc(status="draft"), "attach") is None


# 5 ── overdue conditions escalate and block; waiver needs rationale ─────────


def test_5_condition_status_is_overdue_past_its_due_date() -> None:
    cond = ConditionState(id="c", gate_code="G0", area_code="A", status="open", due_date=date(2026, 10, 10))
    assert ev.condition_status(cond, TODAY) == "overdue"
    assert ev.condition_status(replace(cond, due_date=TODAY), TODAY) == "open"
    assert ev.condition_status(replace(cond, status="cleared"), TODAY) == "cleared"
    assert ev.condition_status(replace(cond, due_date=None), TODAY) == "open"


def test_5_an_overdue_condition_from_an_earlier_gate_blocks_the_next() -> None:
    overdue = ConditionState(id="c", gate_code="G0", area_code="A", status="open", due_date=date(2026, 9, 1))
    ctx = _ctx(prior_conditions=(overdue,))
    assert any(b.code == "condition_overdue" and b.ref == "c" for b in ev.gate_blockers(ctx))
    assert "condition_overdue" in _codes(ev.validate_decision(ctx, _req("go")))
    # Waived or cleared conditions do not block.
    assert ev.gate_blockers(_ctx(prior_conditions=(replace(overdue, status="waived"),))) == []


def test_5_overdue_conditions_are_listed_for_escalation() -> None:
    conds = (
        ConditionState(id="late", gate_code="G0", area_code="A", status="open", due_date=date(2026, 1, 1)),
        ConditionState(id="ok", gate_code="G0", area_code="A", status="open", due_date=date(2027, 1, 1)),
    )
    assert [c.id for c in ev.conditions_to_escalate(conds, TODAY)] == ["late"]


@pytest.mark.parametrize("rationale", ["", "   "])
def test_5_a_waiver_needs_a_rationale(rationale: str) -> None:
    assert ev.waiver_violation(rationale) == "waiver_needs_rationale"


def test_5_a_waiver_with_rationale_is_valid() -> None:
    assert ev.waiver_violation("Client accepted the risk in writing") is None


# 6 ── reopen keeps the decision and starts attempt n+1 ──────────────────────


def test_6_reopen_starts_the_next_attempt_and_marks_copied_checks_stale() -> None:
    checks = (_check("A"), _check("B"))
    nxt = ev.next_attempt_checks(checks, carry_stale=True)
    assert all(c.stale for c in nxt)
    assert [c.status for c in nxt] == ["ready", "ready"]
    assert ev.next_attempt_number(3) == 4


def test_6_reopen_needs_a_rationale() -> None:
    assert ev.reopen_violation("decided", "") == "rationale_required"
    assert ev.reopen_violation("in_review", "because") == "gate_not_decided"
    assert ev.reopen_violation("decided", "Cost overrun beyond tolerance") is None


# 7 ── model change needs a mapping and keeps decided gates ──────────────────


def test_7_a_model_change_needs_a_mapping_for_the_current_and_every_decided_phase() -> None:
    violations = ev.validate_phase_mapping(
        new_phase_codes=("p1", "p2", "p3"),
        mapping={"lph1": "p1"},
        current_phase="lph2",
        phases_with_decisions=("lph1",),
    )
    assert "phase_mapping_missing" in _codes(violations)
    ok = ev.validate_phase_mapping(
        new_phase_codes=("p1", "p2", "p3"),
        mapping={"lph1": "p1", "lph2": "p2"},
        current_phase="lph2",
        phases_with_decisions=("lph1",),
    )
    assert ok == []


def test_7_a_mapping_to_an_unknown_phase_is_refused() -> None:
    violations = ev.validate_phase_mapping(
        new_phase_codes=("p1",),
        mapping={"lph1": "zzz"},
        current_phase="lph1",
        phases_with_decisions=(),
    )
    assert "phase_mapping_unknown_target" in _codes(violations)


def test_7_gates_to_keep_are_exactly_those_with_decisions() -> None:
    gates = {"g1": 2, "g2": 0, "g3": 1}
    assert ev.gates_kept_on_model_change(gates) == {"g1", "g3"}


# 8 ── not applicable needs rationale and the decider's acceptance ───────────


def test_8_a_not_applicable_check_without_rationale_blocks() -> None:
    ctx = _ctx(checks=(_check("A", status="not_applicable", na_rationale=""), _check("B")))
    assert "not_applicable_needs_rationale" in _codes(
        ev.validate_decision(ctx, _req("go", accepted_not_applicable=("A",)))
    )


def test_8_a_not_applicable_check_must_be_accepted_by_the_decider() -> None:
    ctx = _ctx(checks=(_check("A", status="not_applicable", na_rationale="No such scope"), _check("B")))
    assert "not_applicable_not_accepted" in _codes(ev.validate_decision(ctx, _req("go")))
    assert ev.validate_decision(ctx, _req("go", accepted_not_applicable=("A",))) == []


def test_8_an_area_marked_not_applicable_without_rationale_blocks() -> None:
    ctx = _ctx(areas=(_area("A", OWNER_A, applicable=False, na_rationale=""), _area("B", OWNER_B)))
    assert "not_applicable_needs_rationale" in _codes(
        ev.validate_decision(ctx, _req("go", accepted_not_applicable=("A",)))
    )


def test_8_marking_not_applicable_is_refused_without_rationale() -> None:
    assert ev.not_applicable_violation("") == "not_applicable_needs_rationale"
    assert ev.not_applicable_violation("Scope excluded by contract") is None


# 9 ── decider entitled by the route; four-eyes optional ─────────────────────


def test_9_an_unentitled_decider_is_refused() -> None:
    assert ev.entitlement_violation(DECIDER, entitled_user_ids=frozenset({"someone"}), role_satisfies=False) == (
        "decider_not_entitled"
    )
    assert ev.entitlement_violation(DECIDER, entitled_user_ids=frozenset({DECIDER}), role_satisfies=False) is None
    # A role-based step answers None for the user set; then the role decides.
    assert ev.entitlement_violation(DECIDER, entitled_user_ids=None, role_satisfies=True) is None
    assert ev.entitlement_violation(DECIDER, entitled_user_ids=None, role_satisfies=False) == "decider_not_entitled"


def test_9_under_four_eyes_an_area_owner_may_not_decide() -> None:
    ctx = _ctx()
    assert "decider_is_area_owner" in _codes(ev.validate_decision(ctx, _req("go", decider_id=OWNER_A)))


def test_9_a_deputy_counts_as_owner_under_four_eyes() -> None:
    ctx = _ctx(areas=(_area("A", OWNER_A, deputy_user_id=DECIDER), _area("B", OWNER_B)))
    assert "decider_is_area_owner" in _codes(ev.validate_decision(ctx, _req("go")))


def test_9_without_four_eyes_an_owner_may_decide() -> None:
    ctx = _ctx(four_eyes=False)
    assert ev.validate_decision(ctx, _req("go", decider_id=OWNER_A)) == []


# 10 ── recycle marks checks stale; hold freezes with resume date ────────────


def test_10_recycle_effects() -> None:
    eff = ev.decision_effects("recycle")
    assert eff.next_gate_status == "in_preparation"
    assert eff.mark_checks_stale is True
    assert eff.new_attempt is True
    assert eff.advance_phase is False


def test_10_hold_needs_a_resume_date_in_the_future() -> None:
    ctx = _ctx()
    assert "hold_needs_resume_date" in _codes(ev.validate_decision(ctx, _req("hold", rationale="permit")))
    past = _req("hold", rationale="permit", hold_resume_date=date(2026, 1, 1))
    assert "hold_needs_resume_date" in _codes(ev.validate_decision(ctx, past))
    ok = _req("hold", rationale="permit", hold_resume_date=date(2026, 12, 1))
    assert ev.validate_decision(ctx, ok) == []
    assert ev.decision_effects("hold").next_gate_status == "on_hold"


def test_10_hold_and_recycle_are_allowed_despite_blockers() -> None:
    ctx = _ctx(documents=(_doc("A", status="draft"), _doc("B")))
    assert ev.validate_decision(ctx, _req("recycle", rationale="Rework the PEP")) == []


@pytest.mark.parametrize("outcome", ["go_with_conditions", "hold", "recycle", "stop"])
def test_10_every_outcome_but_go_needs_a_rationale(outcome: str) -> None:
    ctx = _ctx()
    req = _req(outcome, hold_resume_date=date(2027, 1, 1))
    assert "rationale_required" in _codes(ev.validate_decision(ctx, req))


def test_go_with_conditions_needs_at_least_one_condition() -> None:
    assert "conditions_required" in _codes(ev.validate_decision(_ctx(), _req("go_with_conditions", rationale="x")))


def test_conditions_on_an_outcome_that_cannot_carry_them_are_refused() -> None:
    cond = ProposedCondition(area_code="A", document_type=None, text="x", owner_user_id=OWNER_A)
    assert "conditions_not_allowed" in _codes(ev.validate_decision(_ctx(), _req("go", conditions=(cond,))))


def test_a_condition_without_text_or_for_an_unknown_area_is_refused() -> None:
    blank = ProposedCondition(area_code="A", document_type=None, text=" ", owner_user_id=OWNER_A)
    ghost = ProposedCondition(area_code="Z", document_type=None, text="x", owner_user_id=OWNER_A)
    req = _req("go_with_conditions", rationale="x", conditions=(blank, ghost))
    assert {"condition_text_required", "condition_unknown_area"} <= _codes(ev.validate_decision(_ctx(), req))


def test_an_unknown_outcome_is_refused() -> None:
    assert "unknown_outcome" in _codes(ev.validate_decision(_ctx(), _req("maybe")))


def test_a_gate_not_in_review_cannot_be_decided() -> None:
    assert "gate_not_in_review" in _codes(ev.validate_decision(_ctx(gate_status="in_preparation"), _req("go")))


# 11 ── stop makes open documents read-only ──────────────────────────────────


def test_11_stop_effects_freeze_every_document_still_in_the_frame() -> None:
    eff = ev.decision_effects("stop")
    assert eff.next_gate_status == "decided"
    assert eff.stop_project is True
    # A binding document is frozen as well: a stopped project's baseline does not move.
    docs = (_doc("A", status="draft"), _doc("B", status="binding", bound_revision_id="rev-1"))
    assert ev.documents_to_freeze(docs) == ("doc-A-pep", "doc-B-pep")


def test_11_a_read_only_document_refuses_every_edit() -> None:
    doc = _doc(status="draft", read_only=True)
    for action in ("attach", "submit", "return"):
        assert ev.document_edit_violation(doc, action) == "document_read_only"


def test_11_a_stopped_project_blocks_every_gate() -> None:
    assert "project_stopped" in _codes(ev.gate_blockers(_ctx(model_stopped=True)))


# 12 ── owner change resets that area's readiness ───────────────────────────


def test_12_owner_change_resets_only_that_area_on_undecided_gates() -> None:
    checks = (_check("A"), _check("B"))
    out = ev.reset_checks_for_owner_change(checks, area_code="A")
    by_area = {c.area_code: c for c in out}
    assert by_area["A"].status == "not_assessed"
    assert by_area["A"].confirmed_by is None
    assert by_area["B"].status == "ready"
    assert ev.gate_accepts_readiness_reset("in_preparation") is True
    assert ev.gate_accepts_readiness_reset("in_review") is True
    assert ev.gate_accepts_readiness_reset("decided") is False


# 13 ── a check goes stale when its document changes ─────────────────────────


def test_13_a_check_is_stale_when_its_document_revision_moved() -> None:
    docs = (_doc("A", current_revision_id="rev-2"), _doc("B"))
    ctx = _ctx(documents=docs)
    assert ev.check_is_stale(ctx.checks[0], docs) is True
    assert ev.check_is_stale(ctx.checks[1], docs) is False
    assert any(b.code == "check_stale" and b.area_code == "A" for b in ev.gate_blockers(ctx))


def test_13_a_stored_stale_flag_blocks_too() -> None:
    ctx = _ctx(checks=(_check("A", stale=True), _check("B")))
    assert "check_stale" in _codes(ev.gate_blockers(ctx))


# 14 ── proceed at risk is explicit and limited to named areas ───────────────


def test_14_a_not_ready_area_blocks_unless_named_at_risk() -> None:
    ctx = _ctx(checks=(_check("A", status="not_ready"), _check("B")))
    assert "area_not_ready" in _codes(ev.validate_decision(ctx, _req("go")))
    cond = ProposedCondition(area_code="A", document_type=None, text="Close gaps", owner_user_id=OWNER_A)
    req = _req("go_with_conditions", rationale="x", conditions=(cond,), proceed_at_risk_areas=("A",))
    assert ev.validate_decision(ctx, req) == []


def test_14_proceed_at_risk_is_refused_on_a_plain_go() -> None:
    ctx = _ctx(checks=(_check("A", status="not_ready"), _check("B")))
    assert "proceed_at_risk_needs_conditions" in _codes(
        ev.validate_decision(ctx, _req("go", proceed_at_risk_areas=("A",)))
    )


def test_14_naming_a_ready_area_at_risk_is_refused() -> None:
    cond = ProposedCondition(area_code="A", document_type=None, text="x", owner_user_id=OWNER_A)
    req = _req("go_with_conditions", rationale="x", conditions=(cond,), proceed_at_risk_areas=("B",))
    assert "proceed_at_risk_area_not_blocking" in _codes(ev.validate_decision(_ctx(), req))


def test_14_not_assessed_blocks_like_not_ready() -> None:
    ctx = _ctx(checks=(_check("A", status="not_assessed"), _check("B")))
    assert "area_not_ready" in _codes(ev.gate_blockers(ctx))


def test_14_a_missing_check_row_counts_as_not_assessed() -> None:
    ctx = _ctx(checks=(_check("B"),))
    assert any(b.code == "area_not_ready" and b.area_code == "A" for b in ev.gate_blockers(ctx))


def test_ready_with_risks_does_not_block() -> None:
    ctx = _ctx(checks=(_check("A", status="ready_with_risks"), _check("B")))
    assert ev.validate_decision(ctx, _req("go")) == []


# 15 ── trail export rows and i18n keys ──────────────────────────────────────


def test_15_every_violation_code_has_an_english_message() -> None:
    import json
    from pathlib import Path

    import app.modules.project_governance as pkg

    en = json.loads((Path(pkg.__file__).parent / "messages" / "en.json").read_text(encoding="utf-8"))
    errors = en["governance"]["errors"]
    missing = sorted(c for c in ev.ALL_CODES if c not in errors)
    assert missing == []


def test_15_trail_rows_carry_keys_not_english() -> None:
    rows = ev.trail_rows(
        [
            {
                "attempt_no": 1,
                "outcome": "go_with_conditions",
                "decided_by": DECIDER,
                "decided_at": "2026-10-11T10:00:00+00:00",
                "rationale": "ok",
                "conditions": [{"text": "x", "status": "open"}],
            }
        ]
    )
    assert rows[0]["outcome_key"] == "governance.outcome.go_with_conditions"
    assert rows[0]["attempt_no"] == 1
    assert rows[0]["conditions"] == 1


# ── 14 blocking evidence is liftable like a not-ready area ──


def _evidence_ctx() -> GateContext:
    return _ctx(evidence=(ev.EvidenceState(area_code="A", code="permit", state="not_met", blocking=True),))


def _at_risk(area: str) -> DecisionRequest:
    cond = ProposedCondition(area_code="A", document_type=None, text="Obtain permit", owner_user_id=OWNER_A)
    return _req("go_with_conditions", rationale="x", conditions=(cond,), proceed_at_risk_areas=(area,))


def test_14_blocking_evidence_blocks_without_at_risk() -> None:
    ctx = _evidence_ctx()
    assert "evidence_not_met" in _codes(ev.validate_decision(ctx, _req("go")))
    cond = ProposedCondition(area_code="A", document_type=None, text="x", owner_user_id=OWNER_A)
    req = _req("go_with_conditions", rationale="x", conditions=(cond,))
    assert "evidence_not_met" in _codes(ev.validate_decision(ctx, req))


def test_14_blocking_evidence_is_lifted_by_conditional_go_with_the_area_at_risk() -> None:
    assert ev.validate_decision(_evidence_ctx(), _at_risk("A")) == []


def test_14_blocking_evidence_is_not_lifted_on_a_plain_go() -> None:
    codes = _codes(ev.validate_decision(_evidence_ctx(), _req("go", proceed_at_risk_areas=("A",))))
    assert {"evidence_not_met", "proceed_at_risk_needs_conditions"} <= codes


def test_14_blocking_evidence_is_not_lifted_when_another_area_is_at_risk() -> None:
    codes = _codes(ev.validate_decision(_evidence_ctx(), _at_risk("B")))
    assert {"evidence_not_met", "proceed_at_risk_area_not_blocking"} <= codes


def test_14_a_stale_check_is_not_lifted_by_proceeding_at_risk() -> None:
    """Nobody attested the document as it now stands, so the area has to confirm again."""
    ctx = _ctx(checks=(_check("A", stale=True), _check("B", confirmed_revisions={"doc-B-pep": "rev-1"})))
    cond = ProposedCondition(area_code="A", document_type=None, text="Confirm again", owner_user_id=OWNER_A)
    req = _req("go_with_conditions", rationale="x", conditions=(cond,), proceed_at_risk_areas=("A",))
    codes = _codes(ev.validate_decision(ctx, req))
    assert codes == {"check_stale", "proceed_at_risk_area_not_blocking"}
