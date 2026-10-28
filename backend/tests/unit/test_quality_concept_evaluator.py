# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of the quality concept (spec section 4), one test per rule case.

Each test pairs the case the rule refuses with the nearest case it allows, so
a rule that silently stopped applying fails on the first half.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.quality_concept import evaluator as ev
from app.modules.quality_concept.catalogue import shipped_catalogue

# ── rule 1 ──────────────────────────────────────────────────────────────────


def _stages(owner: str | None = "u1", role: str | None = "qa") -> list[ev.StageModelEntry]:
    return [ev.StageModelEntry("functional_test", 4, owner, role)]


def _units(*, total: bool = True, handover: bool = True, regime: str | None = "de_vob_b") -> list[ev.UnitSummary]:
    out = [ev.UnitSummary("partial_package", regime, ("PKG-EL",))]
    if total:
        out.append(ev.UnitSummary("total", regime))
    if handover:
        out.append(ev.UnitSummary("handover_to_operation", regime))
    return out


def _codes(findings) -> list[str]:
    return sorted(f.code for f in findings)


def test_rule1_complete_concept_has_no_findings() -> None:
    assert (
        ev.concept_completeness(
            standards_count=1,
            packages=[ev.PackageScope("PKG-EL", proof_count=3)],
            stages=_stages(),
            units=_units(),
        )
        == []
    )


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"standards_count": 0}, "standards_basis_missing"),
        ({"packages": [ev.PackageScope("PKG-EL", proof_count=0)]}, "package_without_proofs"),
        ({"stages": []}, "stage_model_missing"),
        ({"stages": _stages(owner=None)}, "stage_without_owner"),
        ({"stages": _stages(role="site_manager")}, "stage_without_release_party"),
        ({"units": _units(total=False)}, "acceptance_unit_total_missing"),
        ({"units": _units(handover=False)}, "acceptance_unit_handover_to_operation_missing"),
        ({"units": _units(regime=None)}, "acceptance_regime_missing"),
        ({"packages": [ev.PackageScope("PKG-EL", 1), ev.PackageScope("PKG-HV", 1)]}, "acceptance_unit_per_package"),
    ],
)
def test_rule1_each_gap_is_named(kwargs, code) -> None:
    base = {
        "standards_count": 1,
        "packages": [ev.PackageScope("PKG-EL", proof_count=3)],
        "stages": _stages(),
        "units": _units(),
    }
    base.update(kwargs)
    assert code in _codes(ev.concept_completeness(**base))


def test_rule1_no_proofs_rationale_excuses_a_package() -> None:
    findings = ev.concept_completeness(
        standards_count=1,
        packages=[ev.PackageScope("PKG-EL", proof_count=0, no_proofs_rationale="landscaping only")],
        stages=_stages(),
        units=_units(),
    )
    assert "package_without_proofs" not in _codes(findings)


# ── rule 2 ──────────────────────────────────────────────────────────────────


def test_rule2_deliverer_and_due_required() -> None:
    stages = ["functional_test"]
    assert (
        ev.proof_findings(
            ref="p",
            deliverer_role="contractor",
            required_by_kind="stage",
            required_by_ref="functional_test",
            stage_codes=stages,
        )
        == []
    )
    assert _codes(
        ev.proof_findings(ref="p", deliverer_role=None, required_by_kind=None, required_by_ref=None, stage_codes=stages)
    ) == ["proof_without_deliverer", "proof_without_due"]
    assert _codes(
        ev.proof_findings(
            ref="p",
            deliverer_role="contractor",
            required_by_kind="stage",
            required_by_ref="level_9",
            stage_codes=stages,
        )
    ) == ["proof_due_stage_unknown"]


# ── rules 4-6 ───────────────────────────────────────────────────────────────


def _f(outcome: str, link_id: str, **kw) -> ev.EvidenceFact:
    return ev.EvidenceFact("cc_test_result", link_id, outcome, **kw)


def test_rule4_single_pass_delivers_and_pending_does_not() -> None:
    assert ev.derive_delivery([_f("pass", "t1")]).state == "delivered"
    assert ev.derive_delivery([_f("pending", "t1")]).state == "open"
    assert ev.derive_delivery([]).state == "open"


def test_rule4_counted_proof_needs_computed_number() -> None:
    rule = ev.QuantityRule(Decimal("150"), "m3")
    placed = Decimal("400")  # ceil(400/150) = 3
    two = ev.derive_delivery([_f("pass", "a"), _f("pass", "b")], rule=rule, placed_quantity=placed)
    assert (two.state, two.counted, two.required) == ("partly_delivered", 2, 3)
    three = ev.derive_delivery([_f("pass", "a"), _f("pass", "b"), _f("pass", "c")], rule=rule, placed_quantity=placed)
    assert three.state == "delivered"


def test_rule4_material_expired_at_use_does_not_count() -> None:
    fact = ev.EvidenceFact("cc_material_record", "m1", "pass", expired_at_use=True)
    d = ev.derive_delivery([fact])
    assert d.state == "open"
    assert "material_expired_at_use" in _codes(d.findings)


def test_rule5_expired_calibration_does_not_count_and_is_an_error() -> None:
    d = ev.derive_delivery([_f("pass", "t1", calibration_expired=True)])
    assert d.state == "open"
    found = [f for f in d.findings if f.code == "evidence_with_expired_calibration"]
    assert found and found[0].severity == ev.ERROR
    assert ev.calibration_expired(date(2026, 3, 1), "2026-03-02T09:00:00+00:00") is True
    assert ev.calibration_expired(date(2026, 3, 1), "2026-03-01") is False
    assert ev.calibration_expired(None, "2026-03-01") is False


def test_rule6_fail_keeps_open_even_with_pass_on_other_sample() -> None:
    facts = [_f("fail", "t1", sample="S1"), _f("pass", "t2", sample="S2")]
    assert ev.derive_delivery(facts).state == "open"


def test_rule6_retest_referencing_the_failure_cures_it() -> None:
    facts = [_f("fail", "t1", sample="S1"), _f("pass", "t2", sample="S1", retest_of="t1")]
    assert ev.derive_delivery(facts).state == "delivered"


def test_rule6_closed_ncr_cures_the_failure() -> None:
    facts = [_f("fail", "t1", fail_cleared=True), _f("pass", "t2")]
    assert ev.derive_delivery(facts).state == "delivered"


def test_rule6_retest_with_expired_calibration_does_not_cure() -> None:
    facts = [_f("fail", "t1"), _f("pass", "t2", retest_of="t1", calibration_expired=True)]
    assert ev.derive_delivery(facts).state == "open"


def test_stored_decision_wins() -> None:
    assert ev.proof_state("open", "waived") == "waived"
    assert ev.proof_state("delivered", "none") == "delivered"


# ── rules 8-9 ───────────────────────────────────────────────────────────────


def test_rule8_stage_order_is_enforced_even_if_not_listed() -> None:
    res = ev.evaluate_preconditions([], ev.StageContext(previous_state="passed"))
    assert not ev.stage_ready(res)
    assert res[0].reason == "previous_stage_not_released"
    for ok in ("released", "not_applicable"):
        assert ev.stage_ready(ev.evaluate_preconditions([], ev.StageContext(previous_state=ok)))
    assert ev.stage_ready(ev.evaluate_preconditions([], ev.StageContext(previous_state=None)))


@pytest.mark.parametrize(
    ("pre", "bad", "good"),
    [
        (
            {"code": "proofs_delivered", "params": {"evidence_types": ["pressure_test"]}},
            ev.StageContext(),
            ev.StageContext(delivered_evidence_types=frozenset({"pressure_test"})),
        ),
        (
            {"code": "no_open_cx_issues", "params": {"severity": "high"}},
            ev.StageContext(open_cx_issue_severities=("critical",)),
            ev.StageContext(open_cx_issue_severities=("medium", "low")),
        ),
        (
            {"code": "hold_gates_released", "params": {}},
            ev.StageContext(unreleased_gate_count=1),
            ev.StageContext(),
        ),
        (
            {"code": "plant_item_delivered", "params": {}},
            ev.StageContext(plant_item_delivered=None),
            ev.StageContext(plant_item_delivered=True),
        ),
        (
            {"code": "delivery_limit_agreed", "params": {}},
            ev.StageContext(delivery_limit_agreed=False),
            ev.StageContext(delivery_limit_agreed=True),
        ),
        (
            {"code": "authority_acceptance_present", "params": {}},
            ev.StageContext(),
            ev.StageContext(authority_acceptance_present=True),
        ),
        (
            {"code": "systems_released", "params": {"stage": "functional_test", "systems": ["a", "b"]}},
            ev.StageContext(released_systems_by_stage={"functional_test": frozenset({"a"})}),
            ev.StageContext(released_systems_by_stage={"functional_test": frozenset({"a", "b"})}),
        ),
        (
            {"code": "documentation_slots_delivered", "params": {"keys": ["om_manual"]}},
            ev.StageContext(delivered_slot_keys=frozenset({"warranty"})),
            ev.StageContext(delivered_slot_keys=frozenset({"om_manual"})),
        ),
    ],
)
def test_rule9_each_predicate(pre, bad, good) -> None:
    assert not ev.stage_ready(ev.evaluate_preconditions([pre], bad))
    assert ev.stage_ready(ev.evaluate_preconditions([pre], good))


def test_rule9_unknown_predicate_is_never_met() -> None:
    assert not ev.stage_ready(ev.evaluate_preconditions([{"code": "eval_python"}], ev.StageContext()))


def test_computed_stage_state() -> None:
    blocked = ev.evaluate_preconditions([], ev.StageContext(previous_state="in_test"))
    assert ev.computed_stage_state("ready", blocked) == "blocked"
    assert ev.computed_stage_state("blocked", []) == "ready"
    assert ev.computed_stage_state("released", blocked) == "released"


def test_rule12_dependants_go_stale() -> None:
    deps = {"ist-1": frozenset({"hvac", "elec"}), "ist-2": frozenset({"fire"})}
    assert ev.stale_dependants("hvac", deps, released=["ist-1", "ist-2"]) == ["ist-1"]
    assert ev.stale_dependants("hvac", deps, released=["ist-2"]) == []


# ── rules 13, 17 ────────────────────────────────────────────────────────────


def test_rule13_unmet_blocks_without_reservations() -> None:
    unmet = [ev.UnmetPrecondition("defects", "punch-1")]
    blocking, reservations = ev.acceptance_request_check(unmet, reservable=["defects"], with_reservations=False)
    assert _codes(blocking) == ["acceptance_preconditions_unmet"] and reservations == []
    blocking, reservations = ev.acceptance_request_check(unmet, reservable=["defects"], with_reservations=True)
    assert blocking == [] and reservations == unmet


def test_rule13_only_reservable_kinds_may_be_reserved() -> None:
    unmet = [ev.UnmetPrecondition("stage", "functional_test")]
    blocking, reservations = ev.acceptance_request_check(unmet, reservable=["defects"], with_reservations=True)
    assert _codes(blocking) == ["precondition_not_reservable"] and reservations == []


def test_rule17_total_needs_all_partials() -> None:
    partials = [("u1", "accepted", False), ("u2", "requested", False), ("u3", "planned", True)]
    assert [u.ref for u in ev.total_acceptance_unmet(partials)] == ["u2"]


# ── rule 14 ─────────────────────────────────────────────────────────────────


def test_rule14_vob_b_counts_saturdays_as_working_days() -> None:
    # Monday 2026-03-02 + 12 Werktage (Mon-Sat) = Monday 2026-03-16 (Sunday 03-08 and 03-15 skipped).
    assert ev.add_working_days(date(2026, 3, 2), 12, saturday_is_working_day=True) == date(2026, 3, 16)
    # Without Saturdays it would be Wednesday 2026-03-18.
    assert ev.add_working_days(date(2026, 3, 2), 12, saturday_is_working_day=False) == date(2026, 3, 18)


def test_rule14_holidays_are_skipped() -> None:
    assert ev.add_working_days(date(2026, 3, 2), 1, holidays=[date(2026, 3, 3)]) == date(2026, 3, 4)


def test_rule14_deemed_dates_from_catalogue() -> None:
    vob = shipped_catalogue().regime("de_vob_b")
    dates = ev.deemed_dates(vob.deemed_acceptance, completion_notice_at="2026-03-02", use_started_at="2026-03-02")
    by = {d.trigger: d.deemed_on for d in dates}
    assert by == {"completion_notice": date(2026, 3, 16), "use_start": date(2026, 3, 9)}
    assert all(d.source_url or d.source_title for d in dates)
    assert ev.deemed_due_findings(dates, date(2026, 3, 8), "u") == []
    due = ev.deemed_due_findings(dates, date(2026, 3, 9), "u")
    assert [f.params["trigger"] for f in due] == ["use_start"] and due[0].severity == ev.WARNING


def test_rule14_bgb_needs_the_contractor_deadline() -> None:
    bgb = shipped_catalogue().regime("de_bgb")
    no_deadline = ev.deemed_dates(bgb.deemed_acceptance, completion_notice_at="2026-03-02")
    assert no_deadline[0].needs_deadline and no_deadline[0].deemed_on is None
    with_deadline = ev.deemed_dates(bgb.deemed_acceptance, completion_notice_at="2026-03-02", deadline_at="2026-03-20")
    assert with_deadline[0].deemed_on == date(2026, 3, 20)


# ── rule 15 ─────────────────────────────────────────────────────────────────


def test_rule15_effects_proposed_once() -> None:
    vob = shipped_catalogue().regime("de_vob_b")
    first = {e.effect for e in ev.proposed_effects(vob.effects, applied=[])}
    assert "limitation_starts" in first
    second = {e.effect for e in ev.proposed_effects(vob.effects, applied=["limitation_starts"])}
    assert second == first - {"limitation_starts"}


# ── rule 18 ─────────────────────────────────────────────────────────────────


def test_rule18_certified_needs_level_at_or_above_target() -> None:
    levels = shipped_catalogue().scheme("dgnb_new_construction").levels
    assert ev.certify_allowed(levels, "gold", "platinum")
    assert ev.certify_allowed(levels, "gold", "gold")
    assert not ev.certify_allowed(levels, "gold", "silver")


def test_rule18_credit_totals_below_floor_warn_with_review_status() -> None:
    levels = shipped_catalogue().scheme("dgnb_new_construction").levels  # gold floor 65
    # The floor is a percentage, so it is read against the points the project can score.
    available = Decimal("100")
    at_risk = ev.certification_target_at_risk(
        levels, "gold", [Decimal("30"), Decimal("30")], points_available=available
    )
    assert _codes(at_risk) == ["certification_target_at_risk"]
    assert at_risk[0].params["review_status"] == "unconfirmed" and at_risk[0].severity == ev.WARNING
    assert (
        ev.certification_target_at_risk(levels, "gold", [Decimal("40"), Decimal("25")], points_available=available)
        == []
    )
    assert ev.certification_target_at_risk(levels, "gold", []) == []


# ── rules 19-20 ─────────────────────────────────────────────────────────────


def test_rule19_before_survey_needed_before_trigger_starts() -> None:
    sub = ev.SubjectFact("nb-1", "neighbour_building", frozenset({"excavation"}), {"excavation": date(2026, 5, 1)})
    started = ev.preservation_findings([sub], [], today=date(2026, 5, 2))
    assert [(f.code, f.severity) for f in started] == [("preservation_missing_before_start", ev.ERROR)]
    upcoming = ev.preservation_findings([sub], [], today=date(2026, 4, 1))
    assert [(f.code, f.severity) for f in upcoming] == [("preservation_missing_before_start", ev.WARNING)]
    done = ev.SurveyFact("s1", "nb-1", "before", "surveyed", acknowledged=True)
    assert ev.preservation_findings([sub], [done], today=date(2026, 5, 2)) == []
    planned_only = ev.SurveyFact("s1", "nb-1", "before", "planned")
    assert ev.preservation_findings([sub], [planned_only], today=date(2026, 5, 2))


def test_rule19_non_triggering_activity_needs_nothing() -> None:
    sub = ev.SubjectFact("t-1", "trees", frozenset({"crane_oversail"}))
    assert ev.preservation_findings([sub], [], today=date(2026, 5, 2)) == []


def test_rule20_unacknowledged_warns_and_refusal_is_enough() -> None:
    plain = ev.SurveyFact("s1", "nb-1", "before", "surveyed")
    assert _codes(ev.preservation_findings([], [plain], date(2026, 5, 2))) == ["preservation_acknowledged"]
    refused = ev.SurveyFact("s1", "nb-1", "before", "surveyed", access_refused=True)
    assert ev.preservation_findings([], [refused], date(2026, 5, 2)) == []


def test_after_survey_pairs_with_its_before() -> None:
    before = ev.SurveyFact("b", "nb-1", "before", "surveyed", acknowledged=True)
    after_ok = ev.SurveyFact("a", "nb-1", "after", "surveyed", acknowledged=True, paired_with_id="b")
    after_bad = ev.SurveyFact("a2", "nb-1", "after", "surveyed", acknowledged=True)
    assert ev.preservation_findings([], [before, after_ok], date(2026, 5, 2)) == []
    assert _codes(ev.preservation_findings([], [before, after_bad], date(2026, 5, 2))) == [
        "preservation_after_unpaired"
    ]


# ── rule 21 ─────────────────────────────────────────────────────────────────


def test_rule21_frequency_short_warns() -> None:
    short = ev.material_frequency_short(
        plan_code="concrete_compressive",
        per_quantity=Decimal("150"),
        placed=Decimal("301"),
        passing=2,
        review_status="unconfirmed",
    )
    assert _codes(short) == ["material_test_frequency_short"] and short[0].params["required"] == 3
    assert (
        ev.material_frequency_short(
            plan_code="c", per_quantity=Decimal("150"), placed=Decimal("300"), passing=2, review_status="unconfirmed"
        )
        == []
    )


def test_decimal_and_date_parsing_is_strict() -> None:
    assert ev.to_decimal("12.50") == Decimal("12.50")
    assert ev.to_decimal(1.5) is None
    assert ev.to_decimal("NaN") is None
    assert ev.to_date("2026-03-02T23:30:00+00:00") == date(2026, 3, 2)
    assert ev.to_date("garbage") is None
