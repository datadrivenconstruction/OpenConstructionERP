# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pins for the defects an independent review found in the quality concept.

Each test names the behaviour that was wrong and fails on the code as it was:
the gate evidence that could never be met, stages that never left ``blocked``,
stage order that could be skipped, one delivered proof standing for all of its
type, counted proofs delivered without a quantity, working days where the
contract counts calendar days, and state machines whose tables were only ever
compared with themselves.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core import acceptance_effects
from app.modules.quality_concept import evaluator as ev
from app.modules.quality_concept import evidence, fsm, hosting
from app.modules.quality_concept.catalogue import shipped_catalogue, validate_quality_catalogue

LINK = ("quality_concept", "p")


def _readiness(state: str | None, errors: list[str] = (), unplanned: list[str] = ()) -> dict:
    return {
        "concept": state is not None,
        "state": state,
        "errors": [{"code": c} for c in errors],
        "preservation_unplanned": list(unplanned),
    }


def _states(items: list) -> dict[str, str]:
    return {i.code: i.state for i in items}


# ── finding 1: the gate evidence ────────────────────────────────────────────


def test_a_concept_in_review_without_errors_meets_the_gate() -> None:
    # The concept is approved by the binding event the gate decision itself publishes,
    # so asking for "approved" before the decision could never be answered yes.
    items = _states(evidence.readiness_items(_readiness("in_review"), LINK))
    assert items == {
        "quality_concept.approved": "met",
        "quality_concept.complete": "met",
        "quality_concept.preservation_planned": "met",
    }


@pytest.mark.parametrize("state", ["approved", "binding"])
def test_an_approved_or_binding_concept_meets_the_gate(state: str) -> None:
    assert _states(evidence.readiness_items(_readiness(state), LINK))["quality_concept.approved"] == "met"


@pytest.mark.parametrize("state", ["draft", "revising"])
def test_a_concept_nobody_submitted_does_not_meet_the_gate(state: str) -> None:
    item = evidence.readiness_items(_readiness(state), LINK)[0]
    assert (item.state, item.detail) == ("not_met", state)


def test_a_concept_in_review_with_errors_does_not_meet_the_gate() -> None:
    items = _states(evidence.readiness_items(_readiness("in_review", ["stage_model_missing"]), LINK))
    assert items["quality_concept.approved"] == "not_met"
    assert items["quality_concept.complete"] == "not_met"


def test_no_concept_is_not_met_with_a_reason_never_silent() -> None:
    """The model hosts quality and the concept was never written: the gate is told it is missing."""
    (item,) = evidence.readiness_items(_readiness(None), LINK)
    assert (item.code, item.state, item.detail) == ("quality_concept.approved", "not_met", "quality_concept_missing")


def _phase_models() -> list:
    from app.modules.project_governance.catalogue import list_catalogues

    return list(list_catalogues())


def _untagged(catalogue, *, hosts: bool = True, enables: bool = True):
    """A shipped phase model with its quality host or its construction phase tag taken away."""
    documents = tuple(
        d if hosts else d.model_copy(update={"hosts": tuple(h for h in d.hosts if h != hosting.SUBJECT)})
        for d in catalogue.document_types
    )
    phases = tuple(
        p
        if enables
        else p.model_copy(update={"enables": tuple(e for e in p.enables if e != hosting.CONSTRUCTION_START)})
        for p in catalogue.phases
    )
    return catalogue.model_copy(update={"document_types": documents, "phases": phases})


def test_every_shipped_phase_model_says_where_quality_lives_and_what_starts_construction() -> None:
    models = _phase_models()
    assert len(models) >= 6
    for cat in models:
        host = hosting.host(cat)
        phases = hosting.phases_enabling(cat, hosting.CONSTRUCTION_START)
        assert host is not None, cat.id
        assert phases, cat.id
        assert host.area_code in {a.code for a in cat.areas}, cat.id
        (phase,) = phases
        other_area = next(a.code for a in cat.areas if a.code != host.area_code)
        other_phase = next(p.code for p in cat.phases if p.code not in phases)
        # The hosting area at the gate into the phase that starts construction is asked; nothing else is.
        assert evidence.applies(cat, host.area_code, other_area, phase, has_data=False) == (True, ""), cat.id
        assert evidence.applies(cat, other_area, other_area, phase, has_data=True) == (False, ""), cat.id
        assert evidence.applies(cat, host.area_code, other_area, other_phase, has_data=True) == (False, ""), cat.id


def test_the_gate_cannot_deadlock_on_its_own_evidence_in_any_shipped_phase_model() -> None:
    """Only the approval of the frame document binds the concept, and a gate may be what approves it.

    So the evidence asked at the gate into construction must be meetable before the decision:
    a concept in review with no errors meets it. Asking for ``binding`` there could wait on
    the very decision it blocks.
    """
    for cat in _phase_models():
        host = hosting.host(cat)
        (phase,) = hosting.phases_enabling(cat, hosting.CONSTRUCTION_START)
        assert evidence.applies(cat, host.area_code, host.area_code, phase, has_data=True) == (True, ""), cat.id
    before_decision = _states(evidence.readiness_items(_readiness("in_review"), LINK))
    assert set(before_decision.values()) == {"met"}


def test_a_phase_model_without_the_tags_answers_unknown_once_not_an_empty_list() -> None:
    cat = next(c for c in _phase_models() if len(c.areas) > 1)
    host = hosting.host(cat)
    (phase,) = hosting.phases_enabling(cat, hosting.CONSTRUCTION_START)
    first = min(a.code for a in cat.areas)
    second = next(a.code for a in cat.areas if a.code != first)
    no_host = _untagged(cat, hosts=False)
    assert hosting.host(no_host) is None
    assert evidence.applies(no_host, first, first, phase, has_data=True) == (
        True,
        "governance_catalogue_has_no_quality_area",
    )
    # Once per attempt: only under the first applicable area.
    assert evidence.applies(no_host, second, first, phase, has_data=True) == (False, "")
    no_phase = _untagged(cat, enables=False)
    assert hosting.phases_enabling(no_phase, hosting.CONSTRUCTION_START) == frozenset()
    assert evidence.applies(no_phase, first, first, phase, has_data=True) == (True, "no_phase_enables_construction")
    # A project that never used the module has nothing to say.
    assert evidence.applies(no_host, first, first, phase, has_data=False) == (False, "")
    assert host is not None


# ── finding 14: planning the before survey is what the gate asks ────────────


def test_a_planned_before_survey_satisfies_gate_readiness() -> None:
    subject = ev.SubjectFact("NB-01", "neighbour_building", frozenset({"excavation"}), {})
    planned = ev.SurveyFact("s1", "NB-01", "before", "planned")
    assert ev.preservation_unplanned([subject], [planned]) == []
    assert ev.preservation_unplanned([subject], []) == ["NB-01"]
    # An after survey is not a before survey, and a subject without a trigger needs none.
    assert ev.preservation_unplanned([subject], [ev.SurveyFact("s2", "NB-01", "after", "planned")]) == ["NB-01"]
    quiet = ev.SubjectFact("NB-02", "neighbour_building", frozenset({"crane_oversail"}), {})
    assert ev.preservation_unplanned([quiet], []) == []


# ── finding 2: plant facts nobody can read ──────────────────────────────────


@pytest.mark.parametrize("reason", ["no_plant_item_linked", "no_plant_register"])
@pytest.mark.parametrize("code", ["delivery_limit_agreed", "plant_item_delivered"])
def test_an_unreadable_plant_fact_is_not_applicable_with_its_reason(code: str, reason: str) -> None:
    ctx = ev.StageContext(plant_unavailable_reason=reason)
    (result,) = ev.evaluate_preconditions([{"code": code}], ctx)
    assert (result.met, result.reason, result.params) == (True, reason, {"not_applicable": True})


def test_a_linked_plant_item_the_register_does_not_know_stays_unmet() -> None:
    (result,) = ev.evaluate_preconditions([{"code": "plant_item_delivered"}], ev.StageContext())
    assert (result.met, result.reason) == (False, "fact_unavailable")


def test_a_readable_plant_fact_decides() -> None:
    ctx = ev.StageContext(plant_item_delivered=False, plant_unavailable_reason="no_plant_register")
    (result,) = ev.evaluate_preconditions([{"code": "plant_item_delivered"}], ctx)
    assert result.met is False


def test_the_default_first_stage_becomes_ready_without_a_plant_register() -> None:
    first = shipped_catalogue().commissioning_stages[0]
    ctx = ev.StageContext(plant_unavailable_reason="no_plant_item_linked")
    results = ev.evaluate_preconditions([p.model_dump() for p in first.default_preconditions], ctx)
    assert ev.computed_stage_state("blocked", results) == "ready"


# ── finding 9: stage order ──────────────────────────────────────────────────


def test_a_not_applicable_stage_does_not_hide_the_blocked_one_before_it() -> None:
    states = ["released", "blocked", "not_applicable", "blocked"]
    assert ev.effective_previous_state(states, 3) == "blocked"
    ctx = ev.StageContext(previous_state=ev.effective_previous_state(states, 3))
    assert ev.evaluate_preconditions([], ctx)[0].met is False


def test_stage_order_looks_through_not_applicable_stages_to_a_released_one() -> None:
    assert ev.effective_previous_state(["released", "not_applicable", "blocked"], 2) == "released"
    assert ev.effective_previous_state(["not_applicable", "blocked"], 1) is None
    assert ev.effective_previous_state(["blocked"], 0) is None


# ── finding 8: one delivered proof is not all of its type ───────────────────


def test_an_evidence_type_is_delivered_only_when_every_proof_of_it_is() -> None:
    proofs = [("pressure_test", True), ("pressure_test", False), ("insulation_resistance_test", True)]
    assert ev.delivered_evidence_types(proofs) == {"insulation_resistance_test"}
    assert ev.delivered_evidence_types([("pressure_test", True), ("pressure_test", True)]) == {"pressure_test"}
    assert ev.delivered_evidence_types([]) == frozenset()


# ── finding 10: a stage nobody tested is not a released stage ───────────────


def test_a_named_stage_without_progress_rows_is_unmet() -> None:
    (unmet,) = ev.stages_unmet(["functional_test"], [])
    assert (unmet.kind, unmet.ref) == ("stage", "*:functional_test")


def test_stage_preconditions_read_only_the_systems_in_scope() -> None:
    rows = [("s1", "functional_test", "released"), ("s2", "functional_test", "in_test")]
    assert ev.stages_unmet(["functional_test"], rows, {"s1"}) == []
    assert [u.ref for u in ev.stages_unmet(["functional_test"], rows)] == ["s2:functional_test"]
    assert [u.ref for u in ev.stages_unmet(["functional_test"], rows, {"s3"})] == ["*:functional_test"]


# ── finding 13: package cover ───────────────────────────────────────────────


def test_a_package_named_by_any_unit_is_covered() -> None:
    def codes(units: list[ev.UnitSummary]) -> set[str]:
        found = ev.concept_completeness(
            standards_count=1,
            packages=[ev.PackageScope("P1", 1)],
            stages=[ev.StageModelEntry("s", 1, "u", "qa")],
            units=[*units, ev.UnitSummary("total", "r"), ev.UnitSummary("handover_to_operation", "r")],
        )
        return {f.code for f in found}

    assert "acceptance_unit_per_package" in codes([])
    assert "acceptance_unit_per_package" not in codes([ev.UnitSummary("partial_section", "r", ("P1",))])
    assert "acceptance_unit_per_package" in codes([ev.UnitSummary("partial_section", "r", ("P2",))])


def test_the_statutory_german_regime_allows_partial_units_by_agreement() -> None:
    regime = shipped_catalogue().regime("de_bgb")
    assert regime.partial_allowed is True
    assert "partial_acceptance_by_agreement_only" in regime.unconfirmed_facts


# ── finding 17: a counted proof needs the placed quantity ───────────────────


def _pass(i: int) -> ev.EvidenceFact:
    return ev.EvidenceFact("cc_test_result", str(i), "pass")


def test_a_counted_proof_without_a_placed_quantity_is_not_delivered() -> None:
    rule = ev.QuantityRule(Decimal("150"), "m3")
    d = ev.derive_delivery([_pass(1)], rule=rule, placed_quantity=None, ref="p")
    assert d.state == "partly_delivered"
    assert [f.code for f in d.findings] == ["placed_quantity_missing"]
    assert ev.derive_delivery([], rule=rule, placed_quantity=None).state == "open"


def test_a_counted_proof_with_its_quantity_still_counts() -> None:
    rule = ev.QuantityRule(Decimal("150"), "m3")
    assert ev.derive_delivery([_pass(1), _pass(2)], rule=rule, placed_quantity=Decimal("300")).state == "delivered"
    assert ev.derive_delivery([_pass(1)], rule=rule, placed_quantity=Decimal("300")).state == "partly_delivered"
    # An uncounted proof never needed a quantity.
    assert ev.derive_delivery([_pass(1)]).state == "delivered"


# ── finding 18: certification ───────────────────────────────────────────────


def _level(code: str, floor: str | None, unit: str) -> SimpleNamespace:
    return SimpleNamespace(code=code, min_score=floor, score_unit=unit, review_status="unconfirmed")


def test_a_scheme_without_levels_can_be_certified() -> None:
    assert ev.certify_allowed([], "anything", "gold") is True
    assert ev.certify_allowed([], "anything", None) is False


def test_a_percent_floor_is_not_compared_with_a_points_sum() -> None:
    levels = [_level("gold", "65", "percent")]
    points = [Decimal("40")]
    # 40 points says nothing about 65 percent until the points available are known.
    assert ev.certification_target_at_risk(levels, "gold", points) == []
    assert ev.certification_target_at_risk(levels, "gold", points, points_available=Decimal("50")) == []
    (finding,) = ev.certification_target_at_risk(levels, "gold", points, points_available=Decimal("100"))
    assert finding.params["targeted"] == "40"


def test_a_points_floor_is_compared_with_the_points_sum() -> None:
    levels = [_level("gold", "60", "points")]
    assert ev.certification_target_at_risk(levels, "gold", [Decimal("59")]) != []
    assert ev.certification_target_at_risk(levels, "gold", [Decimal("60")]) == []


# ── finding 29: catalogue data ──────────────────────────────────────────────


def test_fidic_counts_calendar_days() -> None:
    (rule,) = shipped_catalogue().regime("fidic_taking_over").deemed_acceptance
    assert (rule.calendar_days, rule.working_days) == (28, None)
    (deemed,) = ev.deemed_dates([rule], completion_notice_at=date(2026, 3, 2))
    # 28 calendar days, weekends and holidays included.
    assert deemed.deemed_on == date(2026, 3, 30)


def test_the_rest_day_is_data_not_a_hardcoded_sunday() -> None:
    monday = date(2026, 3, 2)
    assert ev.add_working_days(monday, 6) == date(2026, 3, 9)
    # A Friday rest day: Fri 6 March is skipped, Sunday counts.
    assert ev.add_working_days(monday, 6, rest_weekdays=(4,)) == date(2026, 3, 9)
    assert ev.add_working_days(monday, 4, rest_weekdays=(4,)) == date(2026, 3, 7)
    assert ev.add_working_days(monday, 4) == date(2026, 3, 6)
    with pytest.raises(ValueError, match="every weekday"):
        ev.add_working_days(monday, 1, rest_weekdays=range(7))


def test_every_material_test_plan_is_reachable_through_its_evidence_type() -> None:
    cat = shipped_catalogue()
    assert validate_quality_catalogue(cat) == []
    for plan in cat.material_test_plans:
        assert cat.test_plan_for(plan.evidence_type).code == plan.code
    assert cat.test_plan_for("asphalt_conformity_tests").code == "asphalt_cores"


def test_two_plans_on_one_evidence_type_are_a_catalogue_error() -> None:
    cat = shipped_catalogue()
    plans = list(cat.material_test_plans)
    clash = plans[1].model_copy(update={"code": "second_plan", "evidence_type": plans[0].evidence_type})
    broken = cat.model_copy(update={"material_test_plans": [*plans, clash]})
    assert any("has another plan" in e for e in validate_quality_catalogue(broken))


def test_a_deemed_rule_counts_one_kind_of_day() -> None:
    cat = shipped_catalogue()
    regime = cat.regime("fidic_taking_over")
    both = regime.deemed_acceptance[0].model_copy(update={"working_days": 12})
    broken = cat.model_copy(
        update={
            "acceptance_regimes": [
                r if r.code != regime.code else r.model_copy(update={"deemed_acceptance": [both]})
                for r in cat.acceptance_regimes
            ]
        }
    )
    assert any("not both" in e for e in validate_quality_catalogue(broken))


# ── findings 3, 6, 11, 27: the state machines, written out by hand ──────────

EXPECTED_MACHINES: dict[str, dict[str, dict[str, str]]] = {
    "concept": {
        "draft": {"submit": "in_review"},
        "in_review": {"return": "draft", "approve": "approved"},
        "approved": {"bind": "binding", "revise": "revising"},
        "binding": {"reopen": "revising"},
        "revising": {"submit": "in_review"},
    },
    "certification": {
        "planned": {"register": "registered", "abandon": "abandoned"},
        "registered": {
            "assess_design": "design_assessed",
            "assess_post_construction": "post_construction_assessed",
            "abandon": "abandoned",
        },
        "design_assessed": {"assess_post_construction": "post_construction_assessed", "abandon": "abandoned"},
        "post_construction_assessed": {"certify": "certified", "miss_level": "level_missed", "abandon": "abandoned"},
        "certified": {},
        "level_missed": {},
        "abandoned": {},
    },
    "credit": {
        "targeted": {"submit_evidence": "evidence_submitted", "drop": "dropped"},
        "evidence_submitted": {
            "achieve": "achieved",
            "not_achieve": "not_achieved",
            "return": "targeted",
            "drop": "dropped",
        },
        "achieved": {},
        "not_achieved": {"submit_evidence": "evidence_submitted"},
        "dropped": {"reinstate": "targeted"},
    },
    "proof": {
        "none": {"accept": "accepted", "waive": "waived"},
        "accepted": {"reopen": "none"},
        "waived": {"reopen": "none"},
    },
    "stage": {
        "blocked": {"mark_ready": "ready", "not_applicable": "not_applicable"},
        "ready": {"mark_blocked": "blocked", "open_test": "in_test", "not_applicable": "not_applicable"},
        "in_test": {"pass": "passed", "fail": "failed", "not_applicable": "not_applicable"},
        "failed": {"open_test": "in_test"},
        "passed": {"release": "released", "open_test": "in_test", "fail": "failed"},
        "released": {"open_test": "in_test", "go_stale": "stale"},
        "stale": {"release": "released", "open_test": "in_test"},
        "not_applicable": {"reinstate": "blocked"},
    },
    "acceptance": {
        "planned": {"request": "requested"},
        "requested": {
            "schedule_inspection": "inspection_scheduled",
            "accept": "accepted",
            "accept_with_reservations": "accepted_with_reservations",
            "refuse": "refused",
            "withdraw": "planned",
            "confirm_deemed": "deemed_accepted",
        },
        "inspection_scheduled": {
            "accept": "accepted",
            "accept_with_reservations": "accepted_with_reservations",
            "refuse": "refused",
            "confirm_deemed": "deemed_accepted",
        },
        "refused": {"request": "requested"},
        "accepted": {"revoke": "requested"},
        "accepted_with_reservations": {"revoke": "requested"},
        "deemed_accepted": {},
    },
    "preservation": {
        "planned": {"invite": "invited", "record_survey": "surveyed", "refuse_access": "access_refused"},
        "invited": {"record_survey": "surveyed", "refuse_access": "access_refused"},
        "surveyed": {"issue_report": "report_issued"},
        "report_issued": {"close": "closed"},
        "closed": {},
        "access_refused": {"close": "closed"},
    },
}
EXPECTED_MIRROR = {
    "concept": {"approve", "bind", "reopen"},
    "stage": {"release", "go_stale", "mark_ready", "mark_blocked"},
    "acceptance": {"accept", "accept_with_reservations", "revoke"},
}


def test_every_machine_matches_the_table_written_out_here() -> None:
    assert fsm.MACHINES == EXPECTED_MACHINES
    assert {k: set(v) for k, v in fsm.MIRROR_ACTIONS.items()} == EXPECTED_MIRROR


@pytest.mark.parametrize("machine", sorted(EXPECTED_MACHINES))
def test_every_pair_the_hand_table_does_not_list_is_refused(machine: str) -> None:
    table = EXPECTED_MACHINES[machine]
    actions = {a for moves in table.values() for a in moves}
    for state, moves in table.items():
        for action in actions - set(moves):
            with pytest.raises(fsm.TransitionError) as caught:
                fsm.next_state(machine, state, action, mirror=True, rationale="r")
            assert caught.value.code == "invalid_transition", (machine, state, action)


def test_a_planned_unit_cannot_be_deemed_accepted() -> None:
    with pytest.raises(fsm.TransitionError):
        fsm.next_state("acceptance", "planned", "confirm_deemed")
    assert fsm.next_state("acceptance", "requested", "confirm_deemed") == "deemed_accepted"


def test_a_binding_concept_reopens_only_from_governance() -> None:
    assert fsm.next_state("concept", "binding", "reopen", mirror=True) == "revising"
    with pytest.raises(fsm.TransitionError) as caught:
        fsm.next_state("concept", "binding", "reopen")
    assert caught.value.code == "transition_owned_elsewhere"


def test_a_refused_unit_reaches_accepted_through_a_request() -> None:
    state = fsm.next_state("acceptance", "refused", "request")
    assert fsm.next_state("acceptance", state, "accept", mirror=True) == "accepted"
    with pytest.raises(fsm.TransitionError):
        fsm.next_state("acceptance", "refused", "accept", mirror=True)


# ── finding 24: the effect port ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_confirmed_effect_reports_only_the_handlers_that_acted() -> None:
    project = uuid.uuid4()
    seen: list[dict] = []

    async def pays(session, project_id, effect):
        seen.append(effect)
        return {"commitment_ids": ["c1"]} if effect["effect"] == "final_account_due" else None

    async def silent(session, project_id, effect):
        return None

    acceptance_effects.register_effect_handler("test.pays", pays)
    acceptance_effects.register_effect_handler("test.silent", silent)
    try:
        payload = {"effect": "final_account_due", "unit_id": "u", "effective_date": "2026-10-01", "package_refs": []}
        assert await acceptance_effects.apply_effect(None, project, payload) == {
            "test.pays": {"commitment_ids": ["c1"]}
        }
        assert seen == [payload]
        assert await acceptance_effects.apply_effect(None, project, {**payload, "effect": "risk_passes"}) == {}
    finally:
        acceptance_effects.unregister_effect_handler("test.pays")
        acceptance_effects.unregister_effect_handler("test.silent")
    assert await acceptance_effects.apply_effect(None, project, {"effect": "final_account_due"}) == {}


@pytest.mark.asyncio
async def test_a_failing_effect_handler_aborts_the_confirmation() -> None:
    async def breaks(session, project_id, effect):
        raise RuntimeError("ledger closed")

    acceptance_effects.register_effect_handler("test.breaks", breaks)
    try:
        with pytest.raises(RuntimeError, match="ledger closed"):
            await acceptance_effects.apply_effect(None, uuid.uuid4(), {"effect": "final_account_due"})
    finally:
        acceptance_effects.unregister_effect_handler("test.breaks")


# ── finding 21: an explicit null ────────────────────────────────────────────


def test_an_explicit_null_on_a_required_column_is_a_422_before_anything_is_set() -> None:
    from app.modules.quality_concept.errors import QualityConceptError
    from app.modules.quality_concept.models import ProofRequirement
    from app.modules.quality_concept.service import _assign

    proof = ProofRequirement(deliverer_role="contractor", title="t", package_ref="P1")
    with pytest.raises(QualityConceptError) as caught:
        _assign(proof, {"title": "changed", "deliverer_role": None})
    assert (caught.value.code, caught.value.status_code) == ("null_not_allowed", 422)
    assert proof.title == "t"
    _assign(proof, {"package_ref": None, "title": "changed"})
    assert (proof.package_ref, proof.title) == (None, "changed")


# ── finding 31: the exports are matrices, and every message exists in both languages ──


def test_a_pivot_keeps_row_order_joins_shared_cells_and_leaves_gaps_empty() -> None:
    from app.modules.quality_concept.export import pivot

    cells = [("P-02", "om_manual", "open"), ("P-01", "om_manual", "accepted"), ("P-01", "om_manual", "open")]
    table = pivot(cells, ["as_built_drawings", "om_manual"], ["P-01", "P-02", "P-03"])
    assert table == [["P-01", "", "accepted, open"], ["P-02", "", "open"], ["P-03", "", ""]]
    # A row nobody declared still appears; a column nobody declared is an error, not a lost cell.
    assert pivot([("X", "a", "1")], ["a"]) == [["X", "1"]]
    with pytest.raises(KeyError):
        pivot([("X", "b", "1")], ["a"])


def test_every_message_key_exists_in_english_and_german() -> None:
    import json
    from pathlib import Path

    import app.modules.quality_concept as module

    folder = Path(module.__file__).parent / "messages"
    en, de = (json.loads((folder / f"{name}.json").read_text(encoding="utf-8")) for name in ("en", "de"))
    assert set(en) == set(de)
    for key in ("proof_matrix.title", "stage_matrix.title", "col.package_ref", "col.system_id", "col_effects"):
        assert f"quality_concept.export.{key}" in en


def test_a_documentation_set_default_must_be_a_deliverable_the_requirements_module_accepts() -> None:
    """The default is written as a requirement deliverable; ``LOI 300`` would be refused there."""
    shipped = shipped_catalogue()
    assert validate_quality_catalogue(shipped) == []
    data = shipped.model_dump(mode="json")
    target = next(d for d in data["documentation_sets"] if d["fm_data"])
    target["fm_data"][0]["loi"] = "LOI 300"
    errors = validate_quality_catalogue(type(shipped).model_validate(data))
    assert len(errors) == 1
    assert "loi 'LOI 300'" in errors[0]


@pytest.mark.asyncio
async def test_the_module_hears_events_again_after_the_bus_was_emptied(monkeypatch) -> None:
    from app.core.events import event_bus
    from app.modules.quality_concept import events

    heard: list[dict] = []

    async def _record(data: dict, **_: object) -> None:
        heard.append(data)

    monkeypatch.setattr(events, "handle_gate_released", _record)
    saved = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    wildcard = list(event_bus._wildcard_handlers)
    try:
        events.register_quality_concept_subscribers()
        event_bus.clear()
        await event_bus.publish("cc.gate.released", {"gate_id": "1"}, source_module="test")
        assert heard == []
        events.register_quality_concept_subscribers()
        events.register_quality_concept_subscribers()
        await event_bus.publish("cc.gate.released", {"gate_id": "2"}, source_module="test")
        assert heard == [{"gate_id": "2"}]
    finally:
        event_bus.clear()
        for name, handlers in saved.items():
            event_bus._handlers[name].extend(handlers)
        event_bus._wildcard_handlers.extend(wildcard)


@pytest.mark.asyncio
async def test_a_neighbour_refusal_reaches_the_screen_with_a_code() -> None:
    """A neighbouring service refuses with a bare string; the screens read ``detail.code``."""
    from fastapi import HTTPException

    from app.modules.quality_concept import router as qc_router

    async def neighbour() -> None:
        raise HTTPException(status_code=409, detail="Package is already issued")

    with pytest.raises(HTTPException) as caught:
        await qc_router._run(neighbour())
    detail = caught.value.detail
    assert caught.value.status_code == 409
    assert (detail["code"], detail["message_key"]) == ("neighbour_refused", "quality_concept.errors.neighbour_refused")
    assert detail["detail"] == "Package is already issued"
    assert detail["message"]

    async def coded() -> None:
        raise HTTPException(status_code=403, detail={"code": "manage_required"})

    with pytest.raises(HTTPException) as kept:
        await qc_router._run(coded())
    assert kept.value.detail == {"code": "manage_required"}


@pytest.mark.asyncio
async def test_the_unit_list_reads_names_and_acts_once_for_all_units(monkeypatch) -> None:
    from app.modules.quality_concept import capabilities as caps
    from app.modules.quality_concept import references
    from app.modules.quality_concept import router as qc_router
    from app.modules.quality_concept.models import AcceptanceUnit

    calls = {"labels": 0, "acts": 0, "concept": 0, "catalogue": 0, "effects": 0, "proposed": []}
    shared = []

    async def labels(session, project_id, refs):
        calls["labels"] += 1
        return {}

    async def acts(session, project_id, ids):
        calls["acts"] += 1
        return {}

    async def nothing(*args, **kwargs):
        return []

    async def concept(project_id):
        calls["concept"] += 1
        return SimpleNamespace(holidays=[])

    async def catalogue(concept):
        calls["catalogue"] += 1
        return SimpleNamespace(regime=lambda code: None)

    async def effects_of(unit_ids):
        calls["effects"] += 1
        return {u: [] for u in unit_ids}

    async def unmet(project_id, unit, facts):
        shared.append(facts)
        return []

    async def proposed(project_id, unit, *, catalogue, effects):
        # The list hands down what it read; nothing is read again per unit.
        calls["proposed"].append((catalogue is not None, effects))
        return []

    monkeypatch.setattr(references, "labels", labels)
    monkeypatch.setattr(references, "handover_packages", acts)
    pid = uuid.uuid4()
    caller = caps.Caller(user_id=uuid.uuid4(), edit=True, manage=True, waive=True)
    svc = SimpleNamespace(
        session=None,
        require_concept=concept,
        catalogue_for=catalogue,
        unmet_preconditions=unmet,
        deemed_dates=nothing,
        proposed_effects=proposed,
        repo=SimpleNamespace(effects_of=effects_of),
        ctx=SimpleNamespace(caller=caller, concept_state="draft", gates_in_use=True),
    )
    units = [
        AcceptanceUnit(
            id=uuid.uuid4(),
            project_id=pid,
            code=f"AU-{i}",
            kind="total",
            state="accepted" if i == 2 else "planned",
            package_refs=[],
            preconditions={},
            reservations=[],
            refusal_defects=[],
        )
        for i in range(3)
    ]
    out = await qc_router._units_out(svc, pid, units, date(2026, 1, 1))
    assert [o["code"] for o in out] == ["AU-0", "AU-1", "AU-2"]
    assert calls == {"labels": 1, "acts": 1, "concept": 1, "catalogue": 1, "effects": 1, "proposed": [(True, [])]}
    # The two open units share one set of project-wide facts.
    assert len(shared) == 2 and shared[0] is shared[1]


def test_the_concept_can_reach_binding_in_every_shipped_phase_model() -> None:
    """Governance binds a frame document only at a gate that lists it, and the concept follows that document.

    A model whose quality document is required at no gate would keep the concept in review for
    the life of the project: no approved revision, the plan closed to edits.
    """
    models = _phase_models()
    assert len(models) >= 6
    for cat in models:
        document = cat.host_of(hosting.SUBJECT)
        assert document is not None, cat.id
        assert document.required_at_gates, cat.id
        gates = {g.code: g for g in cat.gates}
        assert set(document.required_at_gates) <= set(gates), cat.id
        # Bound no later than the gate into construction: the plan is in force while the works run.
        order = {p.code: p.order for p in cat.phases}
        (start,) = hosting.phases_enabling(cat, hosting.CONSTRUCTION_START)
        first = min(order[gates[code].to_phase] for code in document.required_at_gates)
        assert first <= order[start], (cat.id, document.required_at_gates)


@pytest.mark.asyncio
async def test_four_eyes_is_read_through_the_governance_port(monkeypatch) -> None:
    from app.modules.project_governance import public
    from app.modules.quality_concept.service import QualityConceptService

    asked = []

    async def controls(session, project_id):
        asked.append(project_id)
        return public.control_settings(SimpleNamespace(four_eyes=False, current_phase="p1", stopped=False))

    monkeypatch.setattr(public, "project_controls", controls)
    pid = uuid.uuid4()
    assert await QualityConceptService(None)._four_eyes(pid) is False
    assert asked == [pid]
    # No model: the control is on until somebody with the authority switches it off.
    assert public.control_settings(None).four_eyes is True


def test_a_unit_is_accepted_only_through_its_handover_act() -> None:
    """The handover catch-up takes back every accepted unit on a revoked act.

    That undoes no decision of a person only while no person can accept a unit. A user action
    into either accepted state turns this red, and the catch-up then needs to tell the two apart.
    """
    accepted = {"accepted", "accepted_with_reservations"}
    into = {action for moves in fsm.ACCEPTANCE.values() for action, target in moves.items() if target in accepted}
    assert into == {"accept", "accept_with_reservations"}
    assert into <= fsm.MIRROR_ACTIONS["acceptance"]
    for state, moves in fsm.ACCEPTANCE.items():
        for action in into & set(moves):
            with pytest.raises(fsm.TransitionError):
                fsm.next_state("acceptance", state, action)
            assert fsm.next_state("acceptance", state, action, mirror=True) in accepted


def test_every_plan_write_follows_a_lost_change_request_before_it_asks_whether_the_plan_is_open() -> None:
    """A write that checks the plan without the catch-up answers ``binding_requires_change_request`` after a
    change request whose event was lost, while its sibling write goes through."""
    import ast
    import inspect

    from app.modules.quality_concept.service import QualityConceptService

    tree = ast.parse(inspect.getsource(QualityConceptService))
    checked = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        if not any(c.func.attr == "_assert_plan_editable" for c in calls):
            continue
        checked.append(fn.name)
        reopening = [
            c
            for c in calls
            if c.func.attr == "reconcile_governance"
            and any(k.arg == "reopen" and getattr(k.value, "value", None) is True for k in c.keywords)
        ]
        assert reopening, fn.name
    assert len(checked) >= 3, checked


def test_the_readiness_screen_is_told_why_the_gate_cannot_read_the_concept() -> None:
    """The reason on ``GET /readiness`` is the one the gate evidence answers ``unknown`` with."""
    cat = next(c for c in _phase_models() if len(c.areas) > 1)
    (phase,) = hosting.phases_enabling(cat, hosting.CONSTRUCTION_START)
    first = min(a.code for a in cat.areas)
    read = {"has_data": True, "has_frame_document": True}
    assert evidence.unknown_reason(cat, **read) is None
    assert evidence.unknown_reason(cat, has_data=True, has_frame_document=False) == "quality_frame_document_missing"
    for broken in (_untagged(cat, hosts=False), _untagged(cat, enables=False)):
        reason = evidence.unknown_reason(broken, **read)
        assert reason is not None
        assert evidence.applies(broken, first, first, phase, has_data=True) == (True, reason)
    # No phase model, or a project that never used the module: the gate asks nothing.
    assert evidence.unknown_reason(None, **read) is None
    assert evidence.unknown_reason(_untagged(cat, hosts=False), has_data=False, has_frame_document=False) is None


@pytest.mark.asyncio
async def test_a_stage_row_names_who_released_it(monkeypatch) -> None:
    from app.modules.quality_concept import references
    from app.modules.quality_concept import router as qc_router

    someone = uuid.uuid4()

    async def user_names(session, ids):
        return {str(someone): "Dana Releaser"}

    monkeypatch.setattr(references, "user_names", user_names)
    svc = SimpleNamespace(session=None)
    released, waiting = await qc_router._with_people(
        svc, [{"id": "a", "released_by": str(someone)}, {"id": "b", "released_by": None}]
    )
    assert released["released_by_name"] == "Dana Releaser"
    assert waiting["released_by_name"] is None


@pytest.mark.asyncio
async def test_a_project_wide_fact_is_read_once_per_request() -> None:
    from app.modules.quality_concept.service import ProjectFacts

    reads = []

    async def load():
        reads.append(1)
        return ["row"]

    facts = ProjectFacts()
    assert await facts.get("proofs", load) == ["row"]
    assert await facts.get("proofs", load) == ["row"]
    assert await facts.get("progress", load) == ["row"]
    assert len(reads) == 2


def test_the_export_declares_the_language_it_was_written_in() -> None:
    import ast
    import inspect

    from app.modules.quality_concept import export
    from app.modules.quality_concept import router as qc_router

    assert export.rendered_language("de") == "de"
    assert export.rendered_language("de-AT") == "de"
    assert export.rendered_language("en") == "en"
    # No texts ship for an unknown code: the document comes out in English and says so.
    assert export.rendered_language("zz") == "en"
    assert export.rendered_language("") == "en"
    source = inspect.getsource(qc_router.export)
    assert ast.parse(source) is not None
    assert '"Content-Language": rendered_language(locale)' in source
