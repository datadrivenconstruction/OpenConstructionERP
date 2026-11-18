# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The four worked examples of the US state packs, end to end through the engines.

Each figure below is the one the domain write-up states for a 1.2 million dollar
private commercial job; the tests run the real jurisdiction tables the packs
ship, so a change to a table that moves a number fails here.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.jurisdiction_rules import clear_cache
from app.modules.statutory.service import UnknownJurisdictionError, evaluate_facts


@pytest.fixture(autouse=True)
def _fresh_registry() -> None:
    clear_cache()


def _due(outcome: dict[str, Any], code: str) -> list[str]:
    return [n["due_date"] for n in outcome["notices"] if n["code"] == code]


def _rule_ids(outcome: dict[str, Any]) -> list[str]:
    return [f["rule_id"] for f in outcome["findings"]]


# ── 1. California, LA office fit-out ─────────────────────────────────────────


def _ca(**over: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "jurisdiction": "US-CA",
        "sector": "private",
        "project_type": "nonresidential",
        "agreement_date": "2026-03-02",
        "contract_value": "1200000",
    }
    facts.update(over)
    return facts


def test_ca_tax_splits_materials_and_fixtures() -> None:
    out = evaluate_facts(
        _ca(
            tax={
                "contract_form": "lump_sum",
                "rate_pct": "9.75",
                "lines": [
                    {"id": "m", "kind": "material", "cost": "360000"},
                    {"id": "f", "kind": "fixture", "cost": "80000"},
                    {"id": "l", "kind": "labor", "cost": "500000"},
                ],
            }
        )
    )
    assert out["tax"]["paid_to_suppliers"] == "35100.00"
    assert out["tax"]["reported_as_retailer"] == "7800.00"
    assert out["tax"]["tax_in_bid"] == "42900.00"
    assert out["tax"]["charged_to_customer"] == "0.00"
    assert "us.tax.rate_is_state_base" not in _rule_ids(out)


def test_ca_retention_over_the_sb61_cap_is_an_error() -> None:
    out = evaluate_facts(_ca(retention={"payment_amount": "200000", "retention_amount": "20000"}))
    assert out["retention"]["cap_pct"] == "5"
    assert out["retention"]["cap_amount"] == "10000"
    finding = next(f for f in out["findings"] if f["rule_id"] == "us.retainage.over_cap")
    assert finding["severity"] == "error"
    assert finding["message"] == (
        "Retainage 10% exceeds the California cap of 5% for this contract (Cal. Civ. Code § 8811 (SB 61))."
    )


def test_ca_private_cap_does_not_reach_agreements_before_2026_or_small_residential() -> None:
    before = evaluate_facts(
        _ca(agreement_date="2025-12-31", retention={"payment_amount": "200000", "retention_amount": "20000"})
    )
    assert before["retention"]["over_cap"] is False
    small = evaluate_facts(
        _ca(
            project_type="residential_4_storeys_or_fewer",
            retention={"payment_amount": "200000", "retention_amount": "20000"},
        )
    )
    assert small["retention"]["cap_pct"] is None


def test_ca_lien_calendar() -> None:
    sub = evaluate_facts(
        _ca(notices={"role": "subcontractor", "events": {"first_furnishing": "2026-04-06", "completion": "2026-11-30"}})
    )
    assert _due(sub, "ca_preliminary_notice") == ["2026-04-26"]
    assert _due(sub, "ca_lien_record_no_noc") == ["2027-02-28"]
    assert _due(sub, "ca_private_retention_release") == ["2027-01-14"]

    noc = {"completion": "2026-11-30", "notice_of_completion_recorded": "2026-12-04"}
    sub_noc = evaluate_facts(_ca(notices={"role": "subcontractor", "events": noc}))
    assert _due(sub_noc, "ca_lien_record_after_noc_other") == ["2027-01-03"]
    assert _due(sub_noc, "ca_lien_record_no_noc") == [], "a recorded notice of completion replaces the 90 days"
    gc_noc = evaluate_facts(_ca(notices={"role": "direct_contractor", "events": noc}))
    assert _due(gc_noc, "ca_lien_record_after_noc_direct") == ["2027-02-02"]
    assert _due(gc_noc, "ca_preliminary_notice") == []


def test_ca_unclassified_item_and_federal_only_determination() -> None:
    out = evaluate_facts(
        _ca(
            sector="public",
            tax={
                "contract_form": "lump_sum",
                "rate_pct": "7.25",
                "lines": [{"id": "x", "kind": "unclassified", "cost": "100"}],
            },
            wage={"public_work": True, "determination_authorities": ["federal"]},
        )
    )
    ids = _rule_ids(out)
    assert "ca.tax.item_unclassified" in ids
    assert "us.tax.rate_is_state_base" in ids
    assert "ca.pw.federal_only" in ids
    with_state = evaluate_facts(
        _ca(sector="public", wage={"public_work": True, "determination_authorities": ["federal", "state"]})
    )
    assert "ca.pw.federal_only" not in _rule_ids(with_state)


# ── 2. Texas, Houston tilt-up warehouse ──────────────────────────────────────


def _tx(**over: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "jurisdiction": "US-TX",
        "sector": "private",
        "project_type": "nonresidential",
        "agreement_date": "2026-02-02",
        "contract_value": "1200000",
    }
    facts.update(over)
    return facts


def test_tx_lump_sum_and_separated_contracts() -> None:
    lump = evaluate_facts(
        _tx(
            tax={
                "contract_form": "lump_sum",
                "rate_pct": "8.25",
                "lines": [{"id": "m", "kind": "material", "cost": "500000"}],
            }
        )
    )
    assert lump["tax"]["tax_in_bid"] == "41250.00"
    assert lump["tax"]["charged_to_customer"] == "0.00"
    separated = evaluate_facts(
        _tx(
            tax={
                "contract_form": "separated",
                "rate_pct": "8.25",
                "lines": [
                    {"id": "m", "kind": "material", "cost": "500000", "price": "550000"},
                    {"id": "l", "kind": "labor", "cost": "650000", "price": "650000"},
                ],
            }
        )
    )
    assert separated["tax"]["charged_to_customer"] == "45375.00"
    assert separated["tax"]["tax_in_bid"] == "0.00"


def test_tx_contract_form_missing_and_nonresidential_repair_labor() -> None:
    missing = evaluate_facts(_tx(tax={"rate_pct": "8.25", "lines": []}))
    assert "tx.tax.contract_form_missing" in _rule_ids(missing)
    repair = evaluate_facts(
        _tx(
            tax={
                "contract_form": "nonresidential_repair",
                "rate_pct": "8.25",
                "lines": [{"id": "l", "kind": "labor", "cost": "1000", "price": "1000", "priced_tax": "0"}],
            }
        )
    )
    assert "tx.tax.nonres_repair_labor_untaxed" in _rule_ids(repair)
    assert repair["tax"]["charged_to_customer"] == "82.50"


def test_tx_owner_reserve() -> None:
    held = evaluate_facts(_tx(retention={"payment_amount": "1200000", "retention_amount": "120000"}))
    assert held["retention"]["floor_amount"] == "120000"
    assert "tx.lien.owner_reserve_missing" not in _rule_ids(held)
    short = evaluate_facts(_tx(retention={"payment_amount": "1200000", "retention_amount": "60000"}))
    assert "tx.lien.owner_reserve_missing" in _rule_ids(short)
    reserve = evaluate_facts(_tx(notices={"role": "direct_contractor", "events": {"completion": "2026-10-20"}}))
    assert _due(reserve, "tx_owner_reserve_release") == ["2026-11-19"]


def test_tx_monthly_notice_affidavit_and_payment() -> None:
    sub = evaluate_facts(_tx(notices={"role": "subcontractor", "work_months": ["2026-05"]}))
    assert _due(sub, "tx_monthly_notice_nonresidential") == ["2026-08-15"]
    gc = evaluate_facts(
        _tx(
            notices={
                "role": "direct_contractor",
                "events": {
                    "completion": "2026-10-20",
                    "pay_request_received": "2026-06-01",
                    "payment_received": "2026-07-06",
                },
            }
        )
    )
    assert _due(gc, "tx_affidavit_original_nonresidential") == ["2027-02-15"]
    assert _due(gc, "tx_affidavit_original_nonresidential_suit") == ["2028-02-15"]
    assert _due(gc, "tx_private_owner_payment") == ["2026-07-06"]
    assert _due(gc, "tx_private_sub_payment") == ["2026-07-13"]
    assert _due(gc, "tx_monthly_notice_nonresidential") == []


def test_tx_monthly_notice_finding_turns_into_an_error_once_past() -> None:
    out = evaluate_facts(_tx(notices={"role": "subcontractor", "work_months": ["2026-05"], "today": "2026-08-16"}))
    finding = next(f for f in out["findings"] if f["rule_id"] == "us.lien.notice_due")
    assert finding["severity"] == "error"
    assert finding["message"] == (
        "Notice of claim for unpaid work due 2026-08-15 for 2026-05 work (Tex. Prop. Code § 53.056(a-1)(1))."
    )


def test_tx_public_retainage_switches_at_five_million_and_skips_small_contracts() -> None:
    small = evaluate_facts(_tx(sector="public", contract_value="350000", retention={"retention_pct": "10"}))
    assert small["retention"]["cap_pct"] is None
    mid = evaluate_facts(_tx(sector="public", contract_value="1200000", retention={"retention_pct": "10"}))
    assert mid["retention"]["cap_pct"] == "10" and not mid["retention"]["over_cap"]
    big = evaluate_facts(_tx(sector="public", contract_value="5000000", retention={"retention_pct": "10"}))
    assert big["retention"]["cap_pct"] == "5" and big["retention"]["over_cap"]


# ── 3. New York, Manhattan mixed-use ─────────────────────────────────────────


def _ny(**over: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "jurisdiction": "US-NY",
        "sector": "private",
        "project_type": "nonresidential",
        "agreement_date": "2026-05-04",
        "contract_value": "1200000",
    }
    facts.update(over)
    return facts


def test_ny_capital_improvement_against_repair() -> None:
    lines = [
        {"id": "m", "kind": "material", "cost": "400000", "price": "400000"},
        {"id": "l", "kind": "labor", "cost": "800000", "price": "800000"},
    ]
    capital = evaluate_facts(
        _ny(
            tax={
                "contract_form": "capital_improvement",
                "rate_pct": "8.875",
                "exemption_certificate_on_file": True,
                "lines": lines,
            }
        )
    )
    assert capital["tax"]["paid_to_suppliers"] == "35500.00"
    assert capital["tax"]["charged_to_customer"] == "0.00"
    assert "ny.tax.capital_improvement_no_st124" not in _rule_ids(capital)
    repair = evaluate_facts(_ny(tax={"contract_form": "repair_maintenance", "rate_pct": "8.875", "lines": lines}))
    assert repair["tax"]["charged_to_customer"] == "106500.00"


def test_ny_capital_improvement_without_st124() -> None:
    out = evaluate_facts(_ny(tax={"contract_form": "capital_improvement", "rate_pct": "8.875", "lines": []}))
    assert "ny.tax.capital_improvement_no_st124" in _rule_ids(out)


def test_ny_private_retainage_cap_and_lien_windows() -> None:
    out = evaluate_facts(_ny(retention={"payment_amount": "250000", "retention_pct": "10"}))
    assert out["retention"]["cap_amount"] == "12500"
    assert "us.retainage.over_cap" in _rule_ids(out)
    small = evaluate_facts(_ny(contract_value="149999", retention={"payment_amount": "25000", "retention_pct": "10"}))
    assert small["retention"]["cap_pct"] is None
    lien = evaluate_facts(_ny(notices={"role": "direct_contractor", "events": {"last_work": "2026-12-15"}}))
    assert _due(lien, "ny_lien_filing") == ["2027-08-15"]
    condo = evaluate_facts(_ny(project_type="single_family", notices={"events": {"last_work": "2026-12-15"}}))
    assert _due(condo, "ny_lien_filing_single_family") == ["2027-04-15"]
    assert _due(condo, "ny_lien_filing") == []


def test_ny_public_work_needs_a_state_or_city_schedule() -> None:
    out = evaluate_facts(_ny(sector="public", wage={"public_work": True, "determination_authorities": ["federal"]}))
    assert "ny.pw.schedule_missing" in _rule_ids(out)
    ok = evaluate_facts(_ny(sector="public", wage={"public_work": True, "determination_authorities": ["city"]}))
    assert "ny.pw.schedule_missing" not in _rule_ids(ok)


# ── 4. Florida, Miami condo ──────────────────────────────────────────────────


def _fl(**over: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "jurisdiction": "US-FL",
        "sector": "private",
        "project_type": "residential",
        "agreement_date": "2026-01-15",
        "contract_value": "1200000",
    }
    facts.update(over)
    return facts


def test_fl_surtax_stops_at_five_thousand_per_item() -> None:
    # The 1 percent Miami-Dade surtax is an input, read from form DR-15DSS.
    out = evaluate_facts(
        _fl(
            tax={
                "contract_form": "lump_sum",
                "rate_pct": "6",
                "surtax_pct": "1",
                "lines": [
                    {"id": "bulk", "kind": "material", "cost": "390000"},
                    {"id": "chiller", "kind": "material", "cost": "60000", "quantity": "1", "priced_surtax": "600"},
                ],
            }
        )
    )
    chiller = next(line for line in out["tax"]["lines"] if line["id"] == "chiller")
    assert chiller["surtax_base"] == "5000.00"
    assert out["tax"]["tax_in_bid"] == "30950.00"
    assert "fl.tax.surtax_over_item_cap" in _rule_ids(out)
    assert "us.tax.rate_is_state_base" not in _rule_ids(out)


def test_fl_notice_to_owner_and_claim_of_lien() -> None:
    out = evaluate_facts(
        _fl(
            notices={
                "role": "subcontractor",
                "events": {
                    "first_furnishing": "2026-03-10",
                    "final_furnishing": "2026-10-20",
                    "claim_recorded": "2027-01-10",
                },
            }
        )
    )
    assert _due(out, "fl_notice_to_owner") == ["2026-04-24"]
    assert _due(out, "fl_claim_of_lien") == ["2027-01-18"]
    assert _due(out, "fl_claim_service") == ["2027-01-25"]
    assert _due(out, "fl_lien_enforcement") == ["2028-01-10"]


def test_fl_private_retainage_has_no_cap_and_local_wage_clause_is_preempted() -> None:
    out = evaluate_facts(_fl(retention={"payment_amount": "200000", "retention_pct": "10"}))
    assert out["retention"]["cap_pct"] is None
    assert "us.retainage.over_cap" not in _rule_ids(out)
    late = evaluate_facts(_fl(sector="public", agreement_date="2026-10-01", contract_clauses=["local_wage_clause"]))
    finding = next(f for f in late["findings"] if f["rule_id"] == "fl.pw.local_wage_clause")
    assert finding["severity"] == "info"
    early = evaluate_facts(_fl(sector="public", agreement_date="2026-09-29", contract_clauses=["local_wage_clause"]))
    assert "fl.pw.local_wage_clause" not in _rule_ids(early)


def test_fl_public_retainage_cap_starts_above_200k() -> None:
    at = evaluate_facts(_fl(sector="public", contract_value="200000", retention={"retention_pct": "10"}))
    assert at["retention"]["cap_pct"] is None
    above = evaluate_facts(_fl(sector="public", contract_value="200001", retention={"retention_pct": "10"}))
    assert above["retention"]["over_cap"] is True


def test_unknown_jurisdiction_is_refused() -> None:
    with pytest.raises(UnknownJurisdictionError):
        evaluate_facts({"jurisdiction": "DE-BY"})
