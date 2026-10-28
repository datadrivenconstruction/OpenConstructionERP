# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of the delivery model (SPEC section 4) and its lifecycles.

Each rule has the case that passes and the case that would pass only if the
rule were missing. Forms come from the shipped neutral catalogue so the rules
are tested against the attributes real data carries.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.delivery_model import rules
from app.modules.delivery_model.catalogue import DELIVERY_FORMS_KIND, register_kinds
from app.modules.delivery_model.fsm import MODEL_FSM, OFI_FSM, PACKAGE_FSM, effective_package_state
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind


@pytest.fixture(scope="module")
def cat():
    register_kinds()
    return get_catalogue_kind(DELIVERY_FORMS_KIND).get_shipped("neutral")


def _codes(findings, severity=None):
    return sorted({f.code for f in findings if severity is None or f.severity == severity})


# ── lifecycles ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fsm", "src", "dst", "ok"),
    [
        (MODEL_FSM, "draft", "under_evaluation", True),
        (MODEL_FSM, "under_evaluation", "proposed", True),
        (MODEL_FSM, "proposed", "under_evaluation", True),
        (MODEL_FSM, "proposed", "approved", True),
        (MODEL_FSM, "approved", "binding", True),
        (MODEL_FSM, "binding", "reopened", True),
        (MODEL_FSM, "reopened", "proposed", True),
        # The way back from a reopening that is rejected or given up (review finding 4a).
        (MODEL_FSM, "reopened", "binding", True),
        (MODEL_FSM, "under_evaluation", "binding", True),
        (MODEL_FSM, "proposed", "binding", True),
        (MODEL_FSM, "draft", "binding", False),
        (MODEL_FSM, "draft", "proposed", False),
        (MODEL_FSM, "under_evaluation", "approved", False),
        (MODEL_FSM, "binding", "under_evaluation", False),
        (MODEL_FSM, "binding", "proposed", False),
        (PACKAGE_FSM, "planned", "cancelled", True),
        (PACKAGE_FSM, "planned", "awarded", False),
        (OFI_FSM, "identified", "ordered", False),
        (OFI_FSM, "route_set", "ordered", True),
        (OFI_FSM, "handed_to_installer", "delivered", False),
    ],
)
def test_transitions(fsm, src, dst, ok) -> None:
    assert fsm.has_transition(src, dst) is ok


@pytest.mark.parametrize(
    ("stored", "kind", "linked", "expected"),
    [
        ("planned", None, None, "planned"),
        ("planned", "bid_package", "draft", "planned"),
        ("planned", "bid_package", "published", "in_procurement"),
        ("planned", "bid_package", "awarded", "awarded"),
        # Bidding that closed without an award is still procurement, not an award (review finding 16).
        ("planned", "bid_package", "closed", "in_procurement"),
        ("planned", "bid_package", "cancelled", "planned"),
        # A tender is closed after its award.
        ("planned", "tender_package", "closed", "awarded"),
        ("planned", "tender_package", "evaluating", "in_procurement"),
        ("planned", "rfq", "published", "in_procurement"),
        ("planned", "contract", "draft", "planned"),
        ("planned", "contract", "active", "awarded"),
        # A terminated contract was let: the package went out, it is not back to planned.
        ("planned", "contract", "terminated", "awarded"),
        ("planned", "subcontract_agreement", "completed", "awarded"),
        ("cancelled", "contract", "active", "cancelled"),
        ("closed", "bid_package", "draft", "closed"),
    ],
)
def test_package_state_is_read_from_the_linked_row(stored, kind, linked, expected) -> None:
    assert effective_package_state(stored, kind, linked) == expected


# ── rule 1: comparison and proposal ────────────────────────────────────────


W = {"cost": Decimal("60"), "time": Decimal("40")}


def test_weighted_totals_are_exact_decimals() -> None:
    scores = {("a", "cost"): 5, ("a", "time"): 2, ("b", "cost"): 3, ("b", "time"): 4}
    totals = rules.weighted_totals(W, ["a", "b"], scores)
    assert totals == {"a": Decimal("3.80"), "b": Decimal("3.40")}
    assert rules.weighted_totals(W, ["a"], {("a", "cost"): 5}) == {"a": None}


def test_floats_are_refused() -> None:
    with pytest.raises(ValueError):
        rules.dec(0.1)


def test_proposal_needs_two_options_full_scores_weights_100_and_rationale() -> None:
    full = {(o, c): 3 for o in ("a", "b") for c in W}
    assert rules.proposal_findings(["a", "b"], W, full, "why", "a") == []
    assert _codes(rules.proposal_findings(["a"], W, {k: v for k, v in full.items() if k[0] == "a"}, "why", "a")) == [
        "single_option_decision"
    ]
    assert _codes(rules.proposal_findings(["a", "b"], {"cost": Decimal("60")}, full, "why", "a")) == ["weights_not_100"]
    partial = {k: v for k, v in full.items() if k != ("b", "time")}
    assert _codes(rules.proposal_findings(["a", "b"], W, partial, "why", "a")) == ["scores_incomplete"]
    assert _codes(rules.proposal_findings(["a", "b"], W, full, "  ", "a")) == ["rationale_missing"]
    assert _codes(rules.proposal_findings(["a", "b"], W, full, "why", "z")) == ["chosen_option_unknown"]


# ── rules 3 to 6: allocation ───────────────────────────────────────────────


def _defaults(cat, form: str) -> list[dict]:
    out = []
    for c in cat.risk_categories:
        d = cat.default_for(form, c.code)
        out.append(
            {
                "category_code": c.code,
                "party": d.party,
                "basis": d.basis,
                "shares": d.shares,
                "rationale": "",
                "not_applicable": False,
            }
        )
    return out


def _with(rows: list[dict], code: str, **changes) -> list[dict]:
    return [{**r, **changes} if r["category_code"] == code else r for r in rows]


@pytest.mark.parametrize("form", ["design_bid_build_split", "design_build", "cm_at_risk", "alliance_ipd", "ppp_dbfom"])
def test_catalogue_defaults_are_consistent_with_their_form(cat, form) -> None:
    assert rules.errors(rules.allocation_findings(cat, form, _defaults(cat, form))) == []


def test_rule3_every_category_needs_a_party(cat) -> None:
    rows = _defaults(cat, "design_build")
    missing = [r for r in rows if r["category_code"] != "insurance"]
    assert ("risk_unallocated", "insurance") in {
        (f.code, f.ref) for f in rules.allocation_findings(cat, "design_build", missing)
    }
    na = _with(rows, "insurance", party=None, not_applicable=True)
    assert "not_applicable_needs_rationale" in _codes(rules.allocation_findings(cat, "design_build", na))
    na_ok = _with(rows, "insurance", party=None, not_applicable=True, rationale="Owner self-insures")
    assert rules.errors(rules.allocation_findings(cat, "design_build", na_ok)) == []


def test_rule4_shared_needs_shares_summing_to_100(cat) -> None:
    rows = _defaults(cat, "alliance_ipd")
    bad = _with(rows, "design_errors", shares={"owner": "50", "contractor": "40"})
    assert "shared_risk_not_100" in _codes(rules.allocation_findings(cat, "alliance_ipd", bad))
    one = _with(rows, "design_errors", shares={"owner": "100"})
    assert "shared_needs_two_parties" in _codes(rules.allocation_findings(cat, "alliance_ipd", one))


def test_rule5_deviation_needs_rationale_and_warns(cat) -> None:
    rows = _with(_defaults(cat, "design_build"), "price_escalation", party="owner")
    found = rules.allocation_findings(cat, "design_build", rows)
    assert "deviation_needs_rationale" in _codes(found, rules.ERROR)
    reasoned = _with(rows, "price_escalation", rationale="Indexation clause on steel")
    found = rules.allocation_findings(cat, "design_build", reasoned)
    assert rules.errors(found) == []
    assert _codes(found, rules.WARNING) == ["allocation_deviates_from_default"]


@pytest.mark.parametrize(
    ("form", "category", "party", "reason"),
    [
        ("design_build", "design_errors", "owner", "contractor_designs"),
        ("turnkey_epc", "design_errors", "designer", "contractor_designs"),
        ("design_bid_build_single", "design_errors", "contractor", "owner_designs"),
        ("design_bid_build_split", "design_errors", "trade_contractor", "owner_designs"),
        ("ppp_dbfom", "operation_availability", "owner", "operator_carries_availability"),
    ],
)
def test_rule6_hard_inconsistency_is_an_error_even_with_rationale(cat, form, category, party, reason) -> None:
    rows = _with(_defaults(cat, form), category, party=party, basis="contract", shares=None, rationale="we prefer it")
    found = [f for f in rules.allocation_findings(cat, form, rows) if f.ref == category]
    assert [(f.code, f.severity, f.params.get("reason")) for f in found] == [
        ("allocation_inconsistent_with_form", rules.ERROR, reason)
    ]


# ── rules 7 and 8: packages ────────────────────────────────────────────────


def _template(cat, form: str) -> list[dict]:
    t = cat.template_for(form)
    ids = {p.code: f"id-{p.code}" for p in t.packages}
    return [
        {
            "id": ids[p.code],
            "code": p.code,
            "kind": p.kind,
            "designs": p.designs,
            "builds": p.builds,
            "supplies": p.supplies,
            "manages": p.manages,
            "contracting_party": p.contracting_party,
            "price_basis": p.price_basis,
            "parent_id": ids.get(p.parent) if p.parent else None,
            "status": "planned",
        }
        for p in t.packages
    ]


@pytest.mark.parametrize(
    "form",
    [
        f
        for f in (
            "design_bid_build_split",
            "design_bid_build_single",
            "design_build",
            "design_build_novated",
            "turnkey_epc",
            "cm_at_risk",
            "cm_agency",
            "management_contracting",
            "partnering_two_stage",
            "alliance_ipd",
            "integrator",
            "ppp_dbfom",
        )
    ],
)
def test_every_template_fits_its_own_form(cat, form) -> None:
    assert rules.package_findings(cat.form(form), _template(cat, form)) == []


def _reasons(findings):
    return sorted(f.params.get("reason") or f.code for f in findings)


def test_rule7_shapes(cat) -> None:
    dbb = _template(cat, "design_bid_build_single")
    dbb[1]["designs"] = True
    assert _reasons(rules.package_findings(cat.form("design_bid_build_single"), dbb)) == [
        "owner_designs_no_design_and_build"
    ]

    db = _template(cat, "design_build")
    assert _reasons(rules.package_findings(cat.form("design_build"), db[:1])) == ["one_design_and_construction_package"]
    cancelled = [*db[:1], {**db[1], "status": "cancelled"}]
    assert _reasons(rules.package_findings(cat.form("design_build"), cancelled)) == [
        "one_design_and_construction_package"
    ]

    cmar = _template(cat, "cm_at_risk")
    loose = [{**p, "parent_id": None} if p["code"] == "trade_mep" else p for p in cmar]
    assert _reasons(rules.package_findings(cat.form("cm_at_risk"), loose)) == ["trade_package_under_gmp"]

    agency = _template(cat, "cm_agency")
    held = [{**p, "contracting_party": "manager"} if p["code"] == "trade_mep" else p for p in agency]
    assert _reasons(rules.package_findings(cat.form("cm_agency"), held)) == ["trade_contracts_held_by_owner"]
    mc = _template(cat, "management_contracting")
    owner_held = [{**p, "contracting_party": "owner"} if p["code"] == "works_mep" else p for p in mc]
    assert _reasons(rules.package_findings(cat.form("management_contracting"), owner_held)) == [
        "trade_contracts_held_by_manager"
    ]

    alliance = _template(cat, "alliance_ipd")
    assert _reasons(rules.package_findings(cat.form("alliance_ipd"), alliance * 2)) == ["one_project_agreement"]


def test_rule8_price_basis_error_and_contract_type_warning(cat) -> None:
    db = _template(cat, "design_build")
    db[1]["price_basis"] = "remeasure"
    found = rules.package_findings(cat.form("design_build"), db)
    assert [(f.code, f.severity) for f in found] == [("price_basis_inconsistent_with_form", rules.ERROR)]
    dbb = _template(cat, "design_bid_build_single")
    found = rules.package_findings(
        cat.form("design_bid_build_single"), dbb, linked_contract_types={"id-main_works": "design_build"}
    )
    assert [(f.code, f.severity) for f in found] == [("contract_type_inconsistent_with_form", rules.WARNING)]
    found = rules.package_findings(
        cat.form("design_build"),
        _template(cat, "design_build"),
        linked_contract_types={"id-design_and_build": "design_build"},
    )
    assert found == []


# ── rules 10 and 11: owner-furnished items ─────────────────────────────────


PKG = [{"id": "p1", "code": "P1", "kind": "construction", "status": "planned", "need_date": "2027-03-01"}]


def _ofi(**kw) -> dict:
    return {
        "code": "OFI-1",
        "install_by": "package",
        "package_id": "p1",
        "procurement_route": "rfq",
        "status": "route_set",
        **kw,
    }


def test_rule10_route_and_installer_error_only_after_procurement_release() -> None:
    assert rules.ofi_findings([_ofi()], PKG, procurement_released=True) == []
    before = rules.ofi_findings([_ofi(procurement_route="none_yet")], PKG, procurement_released=False)
    after = rules.ofi_findings([_ofi(procurement_route="none_yet")], PKG, procurement_released=True)
    assert [(f.code, f.severity) for f in before] == [("ofi_without_route", rules.WARNING)]
    assert [(f.code, f.severity) for f in after] == [("ofi_without_route", rules.ERROR)]
    orphan = rules.ofi_findings([_ofi(package_id=None)], PKG, procurement_released=True)
    assert [f.code for f in orphan] == ["ofi_without_route"]
    owner_installs = rules.ofi_findings([_ofi(install_by="owner", package_id=None)], PKG, procurement_released=True)
    assert owner_installs == []


def test_rule11_late_for_installer_warns() -> None:
    late = rules.ofi_findings([_ofi(expected_delivery_date="2027-03-15")], PKG, procurement_released=True)
    assert [(f.code, f.severity) for f in late] == [("ofi_late_for_installer", rules.WARNING)]
    assert rules.ofi_findings([_ofi(expected_delivery_date="2027-02-15")], PKG, procurement_released=True) == []
