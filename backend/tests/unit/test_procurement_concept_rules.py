# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of the procurement concept: thresholds, lots, consistency, shortlist, schedule, frameworks.

Each test names the SPEC rule it pins and contains the case that would pass if
the rule were missing (a breach that must be reported, or a boundary that must
flip).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.procurement_concept import evaluator as ev
from app.modules.procurement_concept import fsm
from app.modules.procurement_concept.catalogue import (
    CONTRACT_PACKAGE_KIND_MAP,
    PROCUREMENT_KIND,
    ProcurementCatalogue,
    register_kind,
    validate_procurement_catalogue,
)
from app.modules.procurement_concept.hosting import ProcurementHosting, hosting_of
from app.modules.procurement_concept.schemas import (
    CandidatePatch,
    ConceptSet,
    FrameworkPatch,
    PackagePut,
    ProfileIn,
    SoundingPatch,
)
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

D2026 = date(2026, 6, 1)
D2025 = date(2025, 6, 1)


def _cat(cid: str) -> ProcurementCatalogue:
    register_kind()
    return get_catalogue_kind(PROCUREMENT_KIND).get_shipped(cid)


EU = ev.ConceptFacts(jurisdiction="eu", client_type="sub_central", public_client=True)
PRIVATE = ev.ConceptFacts(jurisdiction="none", client_type="private", public_client=False)


def pkg(code: str = "W1", kind: str = "construction", value: str | None = "1000000", **kw) -> ev.PackageFacts:
    return ev.PackageFacts(
        id=kw.pop("id", code),
        code=code,
        cp_kind=kind,
        estimated_value=None if value is None else Decimal(value),
        currency=kw.pop("currency", "EUR"),
        **kw,
    )


def codes(findings) -> list[str]:
    return [f["code"] for f in findings]


# ── Threshold resolver (rules 2, 4, 5) ──────────────────────────────────


@pytest.mark.parametrize(
    ("facts", "kind", "value", "day", "status"),
    [
        (EU, "construction", "5403999.99", D2026, "below"),
        (EU, "construction", "5404000", D2026, "above"),  # equal to the threshold is above
        (EU, "supply", "215999", D2026, "below"),
        (EU, "supply", "216000", D2026, "above"),
        # Central government has the lower figure for the same value.
        (ev.ConceptFacts("eu", "central", True), "supply", "150000", D2026, "above"),
        # Design is services, never works (rule 7): 300k design is above, 300k works is below.
        (EU, "design", "300000", D2026, "above"),
        (EU, "construction", "300000", D2026, "below"),
        (PRIVATE, "construction", "90000000", D2026, "not_applicable"),
    ],
)
def test_threshold_table(facts, kind, value, day, status) -> None:
    p = pkg(kind=kind, value=value)
    assert ev.threshold_view(_cat("eu"), facts, p, [p], day).status == status


def test_threshold_valid_on_the_planned_start_date_not_today() -> None:
    """2024-2025 works threshold was 5,538,000 (unconfirmed); 5,450,000 is above in 2026, below in 2025."""
    p = pkg(value="5450000")
    in_2026 = ev.threshold_view(_cat("eu"), EU, p, [p], D2026)
    in_2025 = ev.threshold_view(_cat("eu"), EU, p, [p], D2025)
    assert in_2026.status == "above"
    assert in_2026.thresholds[0]["amount"] == "5404000"
    assert in_2025.thresholds[0]["amount"] == "5538000"
    assert in_2025.status == "unconfirmed"


def test_a_day_no_threshold_version_covers_blocks_instead_of_reading_as_not_applicable() -> None:
    """The EU works rows end in 2027: in 2028 the check has no figure, which is a gap, never "free"."""
    p = pkg(value="5450000", procedure_code="direct_award")
    view = ev.threshold_view(_cat("eu"), EU, p, [p], date(2028, 3, 1))
    assert view.status == "unavailable"
    assert [(f["code"], f["severity"]) for f in view.findings] == [("threshold_not_available_for_date", "error")]
    assert "threshold_not_available_for_date" in codes(ev.procedure_findings(_cat("eu"), EU, p, [p], date(2028, 3, 1)))
    # A private client really has no threshold: nothing is reported for the same day.
    assert ev.threshold_view(_cat("eu"), PRIVATE, p, [p], date(2028, 3, 1)).status == "not_applicable"


def test_a_gross_threshold_without_a_tax_rate_warns() -> None:
    uk = ev.ConceptFacts("uk", "central", True)
    p = pkg(value="100", currency="GBP")
    assert "vat_rate_missing_for_gross_threshold" in codes(ev.threshold_view(_cat("uk"), uk, p, [p], D2026).findings)
    with_rate = ev.ConceptFacts("uk", "central", True, vat_rate_pct=Decimal("20"))
    assert "vat_rate_missing_for_gross_threshold" not in codes(
        ev.threshold_view(_cat("uk"), with_rate, p, [p], D2026).findings
    )


def test_vat_basis_gross_converts_a_net_value() -> None:
    """UK figures include VAT: 4,400,000 net at 20% = 5,280,000 gross, above 5,193,000."""
    uk = ev.ConceptFacts("uk", "central", True, vat_rate_pct=Decimal("20"))
    p = pkg(value="4400000", currency="GBP")
    view = ev.threshold_view(_cat("uk"), uk, p, [p], D2026)
    assert view.thresholds[0]["compared_value"] == "5280000.00"
    no_vat = ev.threshold_view(_cat("uk"), ev.ConceptFacts("uk", "central", True), p, [p], D2026)
    assert no_vat.thresholds[0]["compared_value"] == "4400000.00"


def test_foreign_currency_without_rate_is_unresolved_and_blocks_public_approval() -> None:
    p = pkg(value="100", currency="USD")
    view = ev.threshold_view(_cat("eu"), EU, p, [p], D2026)
    assert view.status == "unresolved"
    f = next(f for f in view.findings if f["code"] == "threshold_currency_unresolved")
    assert f["severity"] == "warning"
    assert f["blocks_approval"] is True


def test_unconfirmed_threshold_only_warns() -> None:
    """UK thresholds ship unconfirmed: a direct award at 50m is a warning, never an error (rule 5)."""
    uk = ev.ConceptFacts("uk", "central", True)
    p = pkg(value="50000000", currency="GBP", procedure_code="direct_award")
    fs = ev.procedure_findings(_cat("uk"), uk, p, [p], D2026)
    assert "procedure_not_allowed_above_threshold" in codes(fs)
    assert {f["severity"] for f in fs} == {"warning"}


def test_verified_threshold_breach_is_an_error() -> None:
    p = pkg(value="6000000", procedure_code="direct_award")
    fs = ev.procedure_findings(_cat("eu"), EU, p, [p], D2026)
    f = next(f for f in fs if f["code"] == "procedure_not_allowed_above_threshold")
    assert f["severity"] == "error"
    below = pkg(value="100000", procedure_code="direct_award")
    assert ev.procedure_findings(_cat("eu"), EU, below, [below], D2026) == []


def test_private_procedure_refused_for_public_client_above_threshold_only() -> None:
    above = pkg(value="6000000", procedure_code="two_stage_negotiated")
    below = pkg(value="100000", procedure_code="two_stage_negotiated")
    assert "procedure_not_allowed_above_threshold" in codes(
        ev.procedure_findings(_cat("eu"), EU, above, [above], D2026)
    )
    assert ev.procedure_findings(_cat("eu"), EU, below, [below], D2026) == []


def test_private_client_cannot_use_a_public_only_procedure() -> None:
    p = pkg(value="100", procedure_code="competitive_dialogue")
    assert codes(ev.procedure_findings(_cat("neutral"), PRIVATE, p, [p], D2026)) == ["procedure_not_allowed_for_client"]


def test_procedure_picker_filters_with_reason() -> None:
    p = pkg(value="6000000")
    rows = {r["code"]: r for r in ev.allowed_procedures(_cat("eu"), EU, p, [p], D2026)}
    assert rows["open"]["allowed"] is True
    assert rows["direct_award"] == {**rows["direct_award"], "allowed": False, "reason": "not_allowed_at_value"}
    assert rows["sealed_bid"]["allowed"] is False


# ── Lot aggregation (rule 3) ────────────────────────────────────────────


def test_three_works_lots_are_aggregated_above_the_threshold() -> None:
    """Three 2m lots: each below, together 6m above; a direct award is splitting."""
    lots = [pkg(f"W{i}", value="2000000", procedure_code="direct_award") for i in (1, 2, 3)]
    view = ev.threshold_view(_cat("eu"), EU, lots[0], lots, D2026)
    assert view.aggregated_value == Decimal("6000000")
    assert view.status == "above"
    assert "lot_splitting_avoids_threshold" in codes(ev.procedure_findings(_cat("eu"), EU, lots[0], lots, D2026))
    open_lots = [pkg(f"W{i}", value="2000000", procedure_code="open") for i in (1, 2, 3)]
    assert ev.procedure_findings(_cat("eu"), EU, open_lots[0], open_lots, D2026) == []


def test_untagged_supply_lots_are_aggregated_by_contract_kind() -> None:
    """Two untagged 150k supply lots are 300k together, above 216k: leaving the tag empty splits nothing."""
    a = pkg("S1", "supply", "150000", procedure_code="direct_award")
    b = pkg("S2", "supply", "150000", procedure_code="direct_award")
    assert ev.aggregated_values(_cat("eu"), [a, b]) == {"S1": Decimal("300000"), "S2": Decimal("300000")}
    assert ev.threshold_view(_cat("eu"), EU, a, [a, b], D2026).status == "above"
    assert "lot_splitting_avoids_threshold" in codes(ev.procedure_findings(_cat("eu"), EU, a, [a, b], D2026))
    # Works are never summed with supplies.
    w = pkg("W1", "construction", "150000")
    assert ev.aggregated_values(_cat("eu"), [a, w]) == {"S1": Decimal("150000"), "W1": Decimal("150000")}


def test_a_lot_group_narrows_the_supply_aggregation() -> None:
    a = pkg("S1", "supply", "150000", lot_group="steel")
    b = pkg("S2", "supply", "150000", lot_group="steel")
    c = pkg("S3", "supply", "150000", lot_group="glass")
    agg = ev.aggregated_values(_cat("eu"), [a, b, c])
    assert agg == {"S1": Decimal("300000"), "S2": Decimal("300000"), "S3": Decimal("150000")}


def test_lots_in_different_currencies_have_no_sum_and_block_a_public_client() -> None:
    """A lot priced in another currency must not drop out of the sum (it used to form its own group)."""
    a = pkg("W1", value="3000000")
    b = pkg("W2", value="3000000", currency="USD")
    assert ev.aggregated_values(_cat("eu"), [a, b]) == {"W1": None, "W2": None}
    view = ev.threshold_view(_cat("eu"), EU, a, [a, b], D2026)
    assert view.status == "unresolved"
    f = view.findings[0]
    assert (f["code"], f["reason"], f["blocks_approval"]) == (
        "threshold_currency_unresolved",
        "lots_in_different_currencies",
        True,
    )


def test_a_value_without_a_currency_is_unresolved_never_compared() -> None:
    p = pkg(value="9000000", currency="")
    assert ev.aggregated_values(_cat("eu"), [p]) == {"W1": None}
    assert ev.threshold_view(_cat("eu"), EU, p, [p], D2026).status == "unresolved"
    assert (
        ev.convert_to_threshold(
            _cat("eu"),
            Decimal("1"),
            "",
            _cat("eu").jurisdictions[0].thresholds[0],
            vat_rate_pct=Decimal("0"),
            day=D2026,
        )
        is None
    )


def test_cancelled_lots_do_not_count() -> None:
    a = pkg("W1", value="3000000")
    b = pkg("W2", value="3000000", state="cancelled")
    assert ev.aggregated_values(_cat("eu"), [a, b])["W1"] == Decimal("3000000")


def test_small_lot_exemption_within_cap_allows_direct_award() -> None:
    big = pkg("W1", value="5500000", procedure_code="open")
    small = pkg("W2", value="900000", procedure_code="direct_award", small_lot_exemption=True)
    view = ev.threshold_view(_cat("eu"), EU, small, [big, small], D2026)
    assert view.small_lot_exempt is True
    assert view.status == "unconfirmed"  # the exemption rule itself is unconfirmed, so warnings only
    # Above the lot cap the exemption is refused.
    too_big = pkg("W2", value="1200000", procedure_code="direct_award", small_lot_exemption=True)
    v2 = ev.threshold_view(_cat("eu"), EU, too_big, [big, too_big], D2026)
    assert v2.small_lot_exempt is False
    assert "lot_splitting_avoids_threshold" in codes(v2.findings)


def test_small_lot_exemption_where_the_catalogue_has_no_rule_is_an_error() -> None:
    uk = ev.ConceptFacts("uk", "central", True)
    p = pkg("W1", value="100", currency="GBP", small_lot_exemption=True)
    f = next(
        f
        for f in ev.threshold_view(_cat("uk"), uk, p, [p], D2026).findings
        if f["code"] == "lot_splitting_avoids_threshold"
    )
    assert f["severity"] == "error"


# ── Plan and consistency (rules 1, 6, 7, 12) ────────────────────────────


def test_contract_package_kind_mapping_is_total() -> None:
    mod3_kinds = {
        "design",
        "construction",
        "design_and_construction",
        "supply",
        "supply_and_install",
        "management_services",
        "operation",
        "project_agreement",
    }
    assert set(CONTRACT_PACKAGE_KIND_MAP) == mod3_kinds
    kinds = {k.code for k in _cat("neutral").package_kinds}
    assert {v for v in CONTRACT_PACKAGE_KIND_MAP.values() if v} <= kinds


def test_every_contract_package_needs_an_award_package_except_the_project_agreement() -> None:
    cps = [
        {"id": "a", "code": "A", "kind": "construction"},
        {"id": "b", "code": "B", "kind": "project_agreement"},
        {"id": "c", "code": "C", "kind": "supply"},
    ]
    assert [f["ref"] for f in ev.plan_findings(cps, {"a"})] == ["C"]


def test_design_package_needs_a_fee_and_services_rules() -> None:
    assert "design_fee_estimate_missing" in codes(
        ev.package_findings(_cat("eu"), pkg("D1", "design", None, procedure_code="open"))
    )
    assert ev.package_findings(_cat("eu"), pkg("D1", "design", "200000", procedure_code="open")) == []


def test_advance_package_needs_reason_and_release() -> None:
    no_reason = pkg(is_advance=True, procedure_code="open")
    assert {"advance_without_reason", "advance_package_not_released"} <= set(
        codes(ev.package_findings(_cat("eu"), no_reason))
    )
    ok = pkg(is_advance=True, advance_reason="Piling before permit", advance_released=True, procedure_code="open")
    assert ev.package_findings(_cat("eu"), ok) == []


def test_an_advance_flag_where_no_gate_releases_procurement_is_a_note_and_blocks_nothing() -> None:
    """Nothing can be run ahead of a gate that does not exist, so rule 12 has nothing to ask for."""
    leftover = pkg(is_advance=True, procedure_code="open", advance_applies=False)
    found = ev.package_findings(_cat("eu"), leftover)
    assert [(f["code"], f["severity"], f["blocks_approval"]) for f in found] == [
        ("advance_flag_not_applicable", "warning", False)
    ]
    # The same row where a gate does release procurement is asked for its reason and its release.
    gated = pkg(is_advance=True, procedure_code="open")
    assert {"advance_without_reason", "advance_package_not_released"} <= set(
        codes(ev.package_findings(_cat("eu"), gated))
    )
    # A package that never carried the flag gets no note.
    assert ev.package_findings(_cat("eu"), pkg(procedure_code="open", advance_applies=False)) == []


def test_every_finding_the_new_states_raise_has_a_rule_and_both_languages() -> None:
    from app.modules.procurement_concept.messages import is_key_present
    from app.modules.procurement_concept.validators import PROCUREMENT_RULES

    by_code = {code: rule for rule in PROCUREMENT_RULES for code in rule.codes}
    for code in ("advance_flag_not_applicable", "concept_required_at_no_gate"):
        rule = by_code[code]
        for locale in ("en", "de"):
            assert is_key_present(f"procurement_concept.findings.{code}", locale), (code, locale)
            assert is_key_present(f"procurement_concept.rules.{rule.key}", locale), (rule.key, locale)
            assert is_key_present(f"procurement_concept.rules.{rule.key}_fix", locale), (rule.key, locale)
    for locale in ("en", "de"):
        assert is_key_present("procurement_concept.errors.advance_not_applicable", locale), locale


def test_design_build_package_needs_functional_tender_basis() -> None:
    db = pkg("DB", "design_and_construction", procedure_code="open", tender_basis="detailed")
    assert codes(ev.consistency_findings(_cat("eu"), "design_build", [db])) == [
        "procedure_inconsistent_with_delivery_form"
    ]
    fn = pkg("DB", "design_and_construction", procedure_code="open", tender_basis="functional")
    assert ev.consistency_findings(_cat("eu"), "design_build", [fn]) == []
    assert ev.consistency_findings(_cat("eu"), "design_bid_build_single", [db]) == []


def test_cm_at_risk_main_package_needs_two_stages() -> None:
    main = pkg("GMP", "construction", procedure_code="open")
    trade = pkg("T1", "construction", procedure_code="open", parent_id="GMP")
    assert [f["ref"] for f in ev.consistency_findings(_cat("eu"), "cm_at_risk", [main, trade])] == ["GMP"]
    two = pkg("GMP", "construction", procedure_code="restricted")
    assert ev.consistency_findings(_cat("eu"), "cm_at_risk", [two, trade]) == []


def test_split_form_with_one_works_package_warns() -> None:
    f = ev.consistency_findings(_cat("eu"), "design_bid_build_split", [pkg("W1")])
    assert [(x["code"], x["severity"]) for x in f] == [("split_form_without_trade_packages", "warning")]


# ── Prequalification (rules 8, 10) ──────────────────────────────────────

CRIT = [
    {"code": "exclusion_grounds", "kind": "pass_fail", "weight": "0"},
    {"code": "similar_projects", "kind": "scored", "weight": "60"},
    {"code": "technical_capacity", "kind": "scored", "weight": "40"},
]


def cand(i: int, lst: str = "short", s1: str = "80", s2: str = "70", passed: bool = True, **kw):
    return {
        "id": f"c{i}",
        "list": lst,
        "registered": kw.pop("registered", True),
        "rationale": kw.pop("rationale", ""),
        "scores": {
            "exclusion_grounds": {"passed": passed},
            "similar_projects": {"score": s1},
            "technical_capacity": {"score": s2},
        },
    }


def test_scoring_is_decimal_weighted() -> None:
    sc = ev.candidate_score(CRIT, cand(1, s1="85.5", s2="72.25")["scores"])
    # 85.5 * 0.6 + 72.25 * 0.4 = 51.3 + 28.9 = 80.2
    assert sc["total"] == Decimal("80.20")
    assert sc["passed_all"] is True


def test_weights_must_sum_to_100() -> None:
    assert ev.weights_findings(CRIT, "p") == []
    assert codes(ev.weights_findings([*CRIT[:2], {"code": "x", "kind": "scored", "weight": "39.99"}], "p")) == [
        "prequal_weights_not_100"
    ]


def test_shortlist_rules() -> None:
    p = pkg(procedure_code="competitive_negotiated")  # min 3
    two = [cand(1), cand(2)]
    assert "shortlist_below_min_bidders" in codes(ev.shortlist_findings(_cat("eu"), p, CRIT, Decimal("60"), two))
    three = [cand(1), cand(2), cand(3), cand(4, "excluded")]
    assert codes(ev.shortlist_findings(_cat("eu"), p, CRIT, Decimal("60"), three)) == [
        "excluded_candidate_without_rationale"
    ]
    failing = [cand(1), cand(2), cand(3, passed=False)]
    assert codes(ev.shortlist_findings(_cat("eu"), p, CRIT, Decimal("60"), failing)) == [
        "shortlisted_candidate_fails_prequal"
    ]
    low = [cand(1), cand(2), cand(3, s1="10", s2="10")]
    assert codes(ev.shortlist_findings(_cat("eu"), p, CRIT, Decimal("60"), low)) == [
        "shortlisted_candidate_fails_prequal"
    ]
    free = [cand(1), cand(2), cand(3, registered=False)]
    assert codes(ev.shortlist_findings(_cat("eu"), p, CRIT, Decimal("60"), free)) == ["candidate_not_registered"]


def test_restricted_procedure_needs_its_own_minimum_of_five() -> None:
    p = pkg(procedure_code="restricted")
    four = [cand(i) for i in range(4)]
    assert "shortlist_below_min_bidders" in codes(ev.shortlist_findings(_cat("eu"), p, CRIT, Decimal("0"), four))


def test_evidence_expiring_before_award_warns() -> None:
    ev_rows = [{"ref": "cert:1", "expires": date(2026, 5, 1)}, {"ref": "cert:2", "expires": date(2027, 1, 1)}]
    f = ev.evidence_findings("c1", ev_rows, date(2026, 6, 1))
    assert [(x["code"], x["severity"], x["evidence"]) for x in f] == [
        ("prequal_evidence_expires_before_award", "warning", "cert:1")
    ]


# ── Market sounding (rule 9) ────────────────────────────────────────────


def test_tight_capacity_needs_mitigation_or_resplit() -> None:
    rows = [
        {"id": "a", "capacity_signal": "tight", "mitigation": ""},
        {"id": "b", "capacity_signal": "insufficient", "mitigation": "Split into two lots"},
        {"id": "c", "capacity_signal": "insufficient", "mitigation": "", "resplit": True},
        {"id": "d", "capacity_signal": "ample", "mitigation": ""},
    ]
    assert [f["ref"] for f in ev.capacity_findings(rows)] == ["a"]


# ── Award schedule (rule 11) ────────────────────────────────────────────


def test_backward_pass() -> None:
    p = pkg(procedure_code="open", need_date=date(2027, 6, 30), lead_time_days=60)
    bp = ev.backward_pass(_cat("eu"), p)
    assert bp is not None
    assert bp.award_date == date(2027, 5, 1)
    assert bp.procedure_days == 115
    assert bp.start_date == date(2027, 1, 6)


def test_start_in_the_past_or_before_release_is_infeasible_unless_released_advance() -> None:
    p = pkg(procedure_code="open", need_date=date(2027, 3, 1), lead_time_days=0)
    today = date(2026, 10, 11)
    assert codes(ev.schedule_findings(_cat("eu"), p, today=today, release_date=None)) == []
    late_gate = ev.schedule_findings(_cat("eu"), p, today=today, release_date=date(2026, 12, 1))
    assert [(f["code"], f["severity"], f["reason"]) for f in late_gate] == [
        ("award_schedule_infeasible", "error", "start_before_release_gate")
    ]
    past = ev.schedule_findings(_cat("eu"), p, today=date(2027, 1, 1), release_date=None)
    assert past[0]["reason"] == "start_in_past"
    adv = pkg(
        procedure_code="open",
        need_date=date(2027, 3, 1),
        is_advance=True,
        advance_reason="Long lead",
        advance_released=True,
    )
    assert (
        ev.schedule_findings(_cat("eu"), adv, today=today, release_date=date(2026, 12, 1))[0]["severity"] == "warning"
    )


# ── Frameworks (rule 13) ────────────────────────────────────────────────


def test_framework_call_off_checks() -> None:
    p = pkg("S1", "supply", "100000", procedure_code="framework_call_off", framework_agreement_id="f1")
    fw = {"state": "active", "package_kinds": ["supply"], "end_date": date(2027, 12, 31), "currency": "EUR"}
    cat = _cat("eu")
    big = Decimal("100000")

    def check(framework, *, award=None, remaining=big, package=p):
        return codes(ev.framework_findings(cat, package, framework, award_date=award, remaining=remaining))

    assert check(fw, award=date(2027, 1, 1)) == []
    assert check(fw, award=date(2027, 1, 1), remaining=Decimal("99999.99")) == ["framework_exhausted"]
    assert check(fw, award=date(2028, 1, 1)) == ["framework_expired"]
    assert check({**fw, "package_kinds": ["works"]}) == ["framework_scope_mismatch"]
    assert check({**fw, "state": "draft"}) == ["framework_not_active"]


def test_framework_in_another_currency_or_with_an_unknown_remainder_blocks() -> None:
    """No cross-currency comparison: 100,000 EUR against "200,000 left" in USD says nothing."""
    cat = _cat("eu")
    p = pkg("S1", "supply", "100000", procedure_code="framework_call_off", framework_agreement_id="f1")
    usd = {"state": "active", "package_kinds": ["supply"], "end_date": None, "currency": "USD"}
    assert codes(ev.framework_findings(cat, p, usd, award_date=None, remaining=Decimal("200000"))) == [
        "framework_currency_mismatch"
    ]
    eur = {**usd, "currency": "EUR"}
    assert codes(ev.framework_findings(cat, p, eur, award_date=None, remaining=None)) == ["framework_remaining_unknown"]


def test_a_call_off_is_recognised_by_the_catalogue_attribute_not_by_the_procedure_code() -> None:
    """A company catalogue may name its call-off procedure anything (finding 15)."""
    body = _cat("neutral").model_dump(mode="json")
    for proc in body["procedures"]:
        if proc["code"] == "framework_call_off":
            proc["code"] = "abruf"
    for lt in body["lead_time_defaults"]:
        if lt["procedure"] == "framework_call_off":
            lt["procedure"] = "abruf"
    for j in body["jurisdictions"]:
        for t in j["thresholds"]:
            for key in ("allowed_above", "allowed_below"):
                t[key] = ["abruf" if c == "framework_call_off" else c for c in t[key]]
        for m in j["min_periods"]:
            if m["procedure"] == "framework_call_off":
                m["procedure"] = "abruf"
    cat = ProcurementCatalogue.model_validate(body)
    assert validate_procurement_catalogue(cat, "tenant") == []
    assert cat.is_call_off("abruf") is True
    assert cat.is_call_off("open") is False
    fw = {"state": "active", "package_kinds": [], "end_date": None, "currency": "EUR"}
    renamed = pkg("S1", "supply", "10", procedure_code="abruf", framework_agreement_id="f1")
    assert ev.framework_findings(cat, renamed, fw, award_date=None, remaining=Decimal("10")) == []
    not_call_off = pkg("S1", "supply", "10", procedure_code="open", framework_agreement_id="f1")
    assert codes(ev.framework_findings(cat, not_call_off, fw, award_date=None, remaining=Decimal("10"))) == [
        "framework_procedure_mismatch"
    ]
    assert codes(
        ev.framework_findings(
            cat, pkg("S1", "supply", "10", procedure_code="abruf"), None, award_date=None, remaining=None
        )
    ) == ["framework_missing"]


# ── Catalogue codes are data (finding 15) ───────────────────────────────


def test_a_company_catalogue_may_define_its_own_jurisdiction_and_client_types() -> None:
    body = _cat("eu").model_dump(mode="json")
    juris = body["jurisdictions"][0]
    juris["code"] = "br_federal"
    juris["client_types"] = ["uniao", "privado"]
    juris["private_client_type"] = "privado"
    for t in juris["thresholds"]:
        t["client_type"] = "uniao"
    juris["thresholds"] = [t for t in juris["thresholds"] if t["valid_to"] is None or t["valid_to"] >= "2026-01-01"]
    cat = ProcurementCatalogue.model_validate(body)
    errors = [
        e for e in validate_procurement_catalogue(cat, "tenant") if not e.startswith("threshold_validity_overlap")
    ]
    assert errors == []
    facts = ev.ConceptFacts("br_federal", "uniao", True)
    p = pkg(value="6000000")
    view = ev.threshold_view(cat, facts, p, [p], D2026)
    assert view.thresholds
    assert {t["position"] for t in view.thresholds} == {"above"}
    # The codes the shipped catalogue used no longer name a regime in this one.
    assert ev.threshold_view(cat, EU, p, [p], D2026).status == "not_applicable"


def test_a_threshold_for_a_client_type_the_jurisdiction_does_not_list_is_refused() -> None:
    body = _cat("eu").model_dump(mode="json")
    body["jurisdictions"][0]["thresholds"][0]["client_type"] = "ghost"
    errors = validate_procurement_catalogue(ProcurementCatalogue.model_validate(body), "tenant")
    assert any(e.startswith("threshold_unknown_client_type") for e in errors)


# ── Governance hosting through module 1's port, never by code ───────────


def _phase_models() -> list:
    from app.modules.project_governance.catalogue import list_catalogues

    return list(list_catalogues())


def _reshaped(cat, *, first_phase_enables: bool, later_phases_enable: bool):
    """The model with the procurement capability moved; every code kept."""
    body = cat.model_dump(mode="json")
    first = min(body["phases"], key=lambda p: p["order"])
    for phase in body["phases"]:
        enables = [c for c in phase["enables"] if c != "procurement"]
        keeps = first_phase_enables if phase is first else later_phases_enable and "procurement" in phase["enables"]
        if keeps:
            enables.append("procurement")
        phase["enables"] = enables
    return type(cat).model_validate(body)


def test_a_first_phase_that_enables_procurement_releases_it_from_project_start() -> None:
    """No gate leads into the first phase: that is "nothing holds it", not "the gate is unknown"."""
    cat = next(c for c in _phase_models() if c.id == "neutral")
    doc = cat.host_of("procurement")
    tagged = hosting_of(cat)
    assert tagged.release_gate_codes and tagged.released_from_start is False
    opened = hosting_of(_reshaped(cat, first_phase_enables=True, later_phases_enable=False))
    assert opened == ProcurementHosting(doc.area, (doc.code,), (), True)
    # A later phase that enables it again adds no release gate: nothing was held for that gate to release.
    both = hosting_of(_reshaped(cat, first_phase_enables=True, later_phases_enable=True))
    assert both == opened
    # No phase enables it at all: not known, which is a different answer.
    nowhere = hosting_of(_reshaped(cat, first_phase_enables=False, later_phases_enable=False))
    assert (nowhere.release_gate_codes, nowhere.released_from_start) == ((), False)


def test_every_shipped_phase_model_resolves_a_host_and_a_release_gate() -> None:
    models = _phase_models()
    assert models
    for cat in models:
        hosting = hosting_of(cat)
        doc = cat.host_of("procurement")
        assert doc is not None, cat.id
        assert hosting.area_code == doc.area, cat.id
        assert hosting.area_code in {a.code for a in cat.areas}, cat.id
        assert hosting.document_types == (doc.code,), cat.id
        enabling = {p.code for p in cat.phases_enabling("procurement")}
        # Every shipped model holds procurement behind a gate. Opening it from project start is a shape a
        # company model may have, and one a shipped model must not slip into by a misplaced tag.
        assert not hosting.released_from_start, cat.id
        assert hosting.release_gate_codes, cat.id
        assert {g.to_phase for g in cat.gates if g.code in hosting.release_gate_codes} <= enabling, cat.id


def test_a_model_without_the_tags_resolves_nothing_instead_of_guessing() -> None:
    """Strip the tags and keep every code: nothing is matched by a familiar name."""
    cat = _phase_models()[0]
    body = cat.model_dump(mode="json")
    for doc in body["document_types"]:
        doc["hosts"] = [h for h in doc["hosts"] if h != "procurement"]
    for phase in body["phases"]:
        phase["enables"] = [c for c in phase["enables"] if c != "procurement"]
    assert hosting_of(type(cat).model_validate(body)) == ProcurementHosting()
    assert hosting_of(None) == ProcurementHosting()


# ── Hand transitions and request bodies ─────────────────────────────────


def test_a_person_can_only_submit_or_return_the_concept() -> None:
    """Approval is the governance gate (finding 6): approved and reopened are never asked for by hand."""
    assert fsm.CONCEPT_HAND_TARGETS == ("in_review", "draft")


def test_explicit_null_on_a_non_nullable_field_is_refused() -> None:
    for body in ({"jurisdiction": None}, {"vat_rate_pct": None}, {"release_gate_code": None}):
        with pytest.raises(ValueError, match="null is not allowed"):
            ConceptSet.model_validate(body)
    with pytest.raises(ValueError, match="null is not allowed"):
        PackagePut.model_validate({"currency": None})
    with pytest.raises(ValueError, match="null is not allowed"):
        ProfileIn.model_validate({"name": None})
    # The four bodies the review reproduced a 500 with.
    for model, body in (
        (CandidatePatch, {"list": None}),
        (FrameworkPatch, {"max_value": None}),
        (SoundingPatch, {"held_on": None}),
        (SoundingPatch, {"package_ids": None}),
    ):
        with pytest.raises(ValueError, match="null is not allowed"):
            model.model_validate(body)
    # Fields that are nullable in the table stay clearable.
    assert ConceptSet.model_validate({"governance_document_id": None}).governance_document_id is None
    assert PackagePut.model_validate({"estimated_value": None, "procedure_code": None}).procedure_code is None


def test_money_and_percent_ranges_are_validated() -> None:
    with pytest.raises(ValueError, match="more than two decimals"):
        PackagePut.model_validate({"estimated_value": "1.005", "currency": "EUR"})
    with pytest.raises(ValueError, match="too large"):
        PackagePut.model_validate({"estimated_value": "10000000000000000", "currency": "EUR"})
    with pytest.raises(ValueError):
        ProfileIn.model_validate({"pass_mark": "100.01"})
    assert PackagePut.model_validate({"estimated_value": "1.50", "currency": "EUR"}).estimated_value == Decimal("1.50")


def test_concept_codes_are_plain_strings_of_the_catalogue() -> None:
    body = ConceptSet.model_validate({"jurisdiction": "br_federal", "client_type": "uniao"})
    assert (body.jurisdiction, body.client_type) == ("br_federal", "uniao")
    with pytest.raises(ValueError):
        ConceptSet.model_validate({"jurisdiction": "Not A Code"})


def test_the_package_body_takes_only_fields_the_module_reads() -> None:
    """A field nothing reads is not offered for writing; the cost reference is the BOQ section or nothing."""
    with pytest.raises(ValueError):
        PackagePut.model_validate({"lead_buffer_days": 3})
    # The need date may be bound to a schedule milestone, which the module reads.
    assert PackagePut.model_validate({"need_activity_id": "00000000-0000-0000-0000-000000000001"}).need_activity_id
    section = "00000000-0000-0000-0000-000000000002"
    with pytest.raises(ValueError):
        PackagePut.model_validate({"cost_ref_kind": "cost_line", "cost_ref_id": section})
    with pytest.raises(ValueError, match="together"):
        PackagePut.model_validate({"cost_ref_id": section})
    assert PackagePut.model_validate({"cost_ref_kind": "boq_section", "cost_ref_id": section}).cost_ref_kind
    assert PackagePut.model_validate({"cost_ref_kind": None, "cost_ref_id": None}).cost_ref_id is None


def test_award_criterion_weights_are_percentages_that_sum_to_100() -> None:
    ok = PackagePut.model_validate({"evaluation_weights": {"price": "60", "quality": 40}})
    assert ok.evaluation_weights == {"price": "60", "quality": "40"}
    assert PackagePut.model_validate({"evaluation_weights": {}}).evaluation_weights == {}
    for bad in ({"price": "60", "quality": "30"}, {"price": "101", "quality": "-1"}, {"price": "abc"}, {"": "100"}):
        with pytest.raises(ValueError):
            PackagePut.model_validate({"evaluation_weights": bad})


# ── State machines and the shipped catalogues (finding 18) ──────────────


def test_package_states_a_person_may_set_exclude_what_execution_reads_back() -> None:
    assert fsm.can_set_package_state_by_hand("procedure_set", "on_hold") is True
    assert fsm.can_set_package_state_by_hand("on_hold", "procedure_set") is True
    assert fsm.can_set_package_state_by_hand("procedure_set", "cancelled") is True
    # Nobody types a package into tender or awards it by hand, and closed states stay closed.
    for state in fsm.PACKAGE_STATES:
        for target in fsm.READ_BACK_TARGETS:
            assert fsm.can_set_package_state_by_hand(state, target) is False, (state, target)
    assert fsm.can_set_package_state_by_hand("awarded", "cancelled") is False
    assert fsm.can_set_package_state_by_hand("cancelled", "planned") is False
    assert fsm.can_set_package_state_by_hand("planned", "planned") is False


def test_read_back_is_monotone_and_idempotent() -> None:
    assert fsm.read_back_target("procedure_set", "in_tender") == "in_tender"
    assert fsm.read_back_target("shortlisted", "awarded") == "awarded"
    assert fsm.read_back_target("in_tender", "awarded") == "awarded"
    assert fsm.read_back_target("in_tender", "in_tender") is None  # a repeated event
    assert fsm.read_back_target("awarded", "in_tender") is None  # a late event
    assert fsm.read_back_target("cancelled", "awarded") is None
    assert fsm.read_back_target("procedure_set", "cancelled") is None  # not a read-back target


def test_concept_and_framework_machines_have_no_way_out_of_their_terminal_states() -> None:
    assert fsm.CONCEPT_FSM["binding"] == ()
    assert fsm.can_transition(fsm.CONCEPT_FSM, "draft", "in_review") is True
    assert fsm.can_transition(fsm.CONCEPT_FSM, "draft", "approved") is False
    assert fsm.can_transition(fsm.CONCEPT_FSM, "in_review", "in_review") is False
    for terminal in ("expired", "terminated"):
        assert fsm.FRAMEWORK_FSM[terminal] == ()
    assert fsm.can_transition(fsm.FRAMEWORK_FSM, "draft", "active") is True
    assert fsm.can_transition(fsm.FRAMEWORK_FSM, "active", "draft") is False


def test_every_shipped_procurement_catalogue_loads_and_validates() -> None:
    register_kind()
    shipped = get_catalogue_kind(PROCUREMENT_KIND).shipped()
    assert {c.id for c in shipped} >= {"neutral", "eu"}
    for cat in shipped:
        assert validate_procurement_catalogue(cat, "shipped") == [], cat.id
        assert cat.jurisdictions, cat.id
        codes = {p.code for p in cat.procedures}
        for juris in cat.jurisdictions:
            assert juris.private_client_type in juris.client_types, (cat.id, juris.code)
            for t in juris.thresholds:
                assert t.source_url and t.valid_from is not None, (cat.id, juris.code)
                assert set(t.allowed_above) | set(t.allowed_below) <= codes, (cat.id, juris.code)
        # Every package kind module 3 can plan maps onto a kind this catalogue knows.
        kinds = {k.code for k in cat.package_kinds}
        assert {v for v in CONTRACT_PACKAGE_KIND_MAP.values() if v} <= kinds, cat.id
