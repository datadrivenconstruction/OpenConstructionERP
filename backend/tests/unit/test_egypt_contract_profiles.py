# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egypt's contract and payment rules live as data in the country-neutral registries.

Two profiles, decided by the project's ``works``: private works follow FIDIC
and the contract (no Egyptian law sets retention), public works follow the
Public Contracts Law 182/2018 and its Executive Regulations (Decree 692/2019):
five percent held, 95 percent paid, within 60 days of the certificate. These
tests hold each profile, the statutory limits table, the payment clocks, the
progress billing block, the decennial liability regime and the compliance
pack, and that no Gulf country picked up an Egyptian figure.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.regional_packs import resolve_progress_billing
from app.modules.contracts.compliance_packs import resolve_pack
from app.modules.contracts.country_defaults import resolve_contract_defaults
from app.modules.contracts.public_procurement import (
    CONTRACTING_SOCIAL_INSURANCE,
    CONTRACTOR_CLASSIFICATIONS,
    LIMIT_FIELDS,
    PUBLIC_WORKS_LIMITS,
    PUBLIC_WORKS_PRICE_ADJUSTMENT,
    limit_value,
    public_works_limits,
)
from app.modules.defects_liability.limitation import derive_period, regime_for
from app.modules.payment_clock.clock import compute_schedule
from app.modules.payment_clock.data import PAYMENT_REGIMES
from app.modules.payment_release.release_certificates import gated_requirements

# Saudi Arabia is left out: it has a public works profile of its own, held
# by test_saudi_public_works.py.
_GULF = ("AE", "QA", "KW", "BH", "OM", "JO")


def _split(resolved: dict) -> list[tuple[str, str]]:
    return [(s["event"], s["release_percent_of_held"]) for s in resolved["values"]["retention_release_split"]]


# ── Public versus private works ───────────────────────────────────────────────


def test_private_works_follow_fidic_and_set_no_retention() -> None:
    private = resolve_contract_defaults("EG", works="private")
    assert private == resolve_contract_defaults("EG")
    assert private["standard_form"].startswith("FIDIC")
    assert private["values"]["retention_percent"] is None
    assert private["values"]["retention_cap_percent"] is None
    assert private["values"]["payment_period_days"] == 56
    # Red Book 14.9: half at the Taking-Over Certificate, half at the end of the DNP.
    assert _split(private) == [("substantial_completion", "50"), ("defects_period_end", "100")]


def test_public_works_hold_five_percent_and_pay_within_sixty_days() -> None:
    public = resolve_contract_defaults("EG", works="public")
    assert public["standard_form"] == "Law 182/2018 tender documents"
    assert Decimal(public["values"]["retention_percent"]) == Decimal("5")
    assert public["values"]["retention_cap_percent"] is None
    assert public["values"]["payment_period_days"] == 60
    # The retention is paid with the final statement after provisional acceptance.
    assert _split(public) == [("substantial_completion", "100")]
    assert public["sources"]["retention_percent"]["source"] == "statute"
    assert "Art. 93" in public["sources"]["retention_percent"]["reference"]
    assert public["sources"]["retention_percent"]["note_key"] == (
        "contracts.works_defaults.EG.public.retention_percent.note"
    )


def test_the_profiles_differ_where_the_law_differs() -> None:
    public = resolve_contract_defaults("EG", works="public")["values"]
    private = resolve_contract_defaults("EG", works="private")["values"]
    differ = sorted(k for k in public if public[k] != private[k])
    assert differ == [
        "certificate_name",
        "payment_period_days",
        "retention_percent",
        "retention_release_split",
    ]


# ── The statutory limits of public works ─────────────────────────────────────


def test_every_limit_is_sourced_and_dated() -> None:
    row = PUBLIC_WORKS_LIMITS["EG"]
    for field in LIMIT_FIELDS:
        figure = row[field]
        assert figure["statute_reference"], field
        assert figure["source_url"].startswith("https://"), field
        assert figure["read_date"] == "2026-10-19", field


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bid_security_max_percent", "1.5"),
        ("performance_security_percent", "5"),
        ("performance_security_due_working_days", "10"),
        ("advance_payment_max_percent", "25"),
        ("advance_payment_max_percent_sme", "50"),
        ("interim_payment_percent", "95"),
        ("retention_percent", "5"),
        ("stored_materials_payment_percent", "75"),
        ("works_payment_days", "60"),
        ("supplies_payment_days", "30"),
        ("variation_max_percent_per_item_works", "25"),
        ("delay_damages_cap_percent_works", "10"),
        ("delay_damages_cap_percent_works_long_delay", "15"),
        ("delay_damages_cap_percent_other", "3"),
        ("delay_damages_cap_percent_other_long_delay", "5"),
        ("price_adjustment_min_duration_months", "6"),
    ],
)
def test_the_limits_read_as_the_law_states_them(field: str, value: str) -> None:
    assert limit_value(public_works_limits("eg"), field) == Decimal(value)


def test_interim_payment_and_retention_add_up_to_the_work_executed() -> None:
    limits = public_works_limits("EG")
    assert limit_value(limits, "interim_payment_percent") + limit_value(limits, "retention_percent") == 100


def test_no_other_country_has_public_works_limits_by_accident() -> None:
    assert set(PUBLIC_WORKS_LIMITS) == {"EG", "FR", "PK"}
    assert public_works_limits("AE") is None
    assert public_works_limits(None) is None
    assert PUBLIC_WORKS_PRICE_ADJUSTMENT == {
        "EG": "eg_law182_art97",
        "FR": "fr_ccag_travaux_2021_art_10_5",
        "PK": "pk_pec_sbd_clause_70",
    }


def test_unconfirmed_figures_are_marked_for_expert_review_and_carry_no_number() -> None:
    grades = CONTRACTOR_CLASSIFICATIONS["EG"]
    assert grades["needs_expert_review"] is True
    assert [g["grade"] for g in grades["grades"]] == ["1", "2", "3", "4", "5", "6", "7"]
    assert all(g["max_project_value"] is None for g in grades["grades"])
    insurance = CONTRACTING_SOCIAL_INSURANCE["EG"]
    assert insurance["needs_expert_review"] is True
    # Table 8 of Law 148/2019 was not read in the primary text: no percentage ships.
    assert insurance["contribution_multiplier_percent"] is None
    assert insurance["wage_percent_by_work_type"] == []


# ── Payment clocks ────────────────────────────────────────────────────────────


def _regime(code: str) -> dict:
    return next(r for r in PAYMENT_REGIMES if r["code"] == code)


def test_a_works_certificate_is_paid_within_sixty_calendar_days() -> None:
    schedule = compute_schedule(_regime("eg_law182_works"), application_date=date(2026, 3, 1))
    assert schedule.final_date == date(2026, 4, 30)
    assert _regime("eg_law182_works")["interest_basis"] == "prescribed_rate"


def test_supplies_are_paid_within_thirty_days() -> None:
    schedule = compute_schedule(_regime("eg_law182_supplies"), application_date=date(2026, 3, 1))
    assert schedule.final_date == date(2026, 3, 31)


# ── Progress billing block ────────────────────────────────────────────────────


def test_the_egyptian_billing_block_holds_no_retention_tier_for_private_works() -> None:
    billing = resolve_progress_billing(country_code="EG")
    assert billing["retention_policy"]["tiers"] == []
    public = billing["retention_policy"]["public_client_rate"]
    assert (public["percent_of_executed_work"], public["paid_percent_of_executed_work"]) == ("5", "95")
    assert billing["stored_materials"]["public_client_valuation"]["paid_percent_of_scheduled_value"] == "75"
    regimes = billing["billing_cycle"]["payment_clock_regimes"]
    assert {r["code"] for r in PAYMENT_REGIMES} >= set(regimes.values())


def test_the_social_insurance_clearance_gates_payment_release_as_a_warning() -> None:
    (requirement,) = gated_requirements(resolve_progress_billing(country_code="EG"))
    assert requirement["cert_type"] == "social_security_clearance"
    assert requirement["release_effect"] == "warn"
    assert requirement["applies_to_kinds"] == ["interim", "final"]
    assert requirement["needs_expert_review"] is True


@pytest.mark.parametrize("country", _GULF)
def test_no_gulf_country_reads_the_egyptian_block(country: str) -> None:
    assert resolve_progress_billing(country_code=country) is None
    assert resolve_contract_defaults(country, works="public") == resolve_contract_defaults(country)


def test_a_german_requirement_written_for_the_claim_rollup_does_not_gate_release() -> None:
    assert gated_requirements(resolve_progress_billing(country_code="DE")) == []


# ── Decennial liability and the compliance pack ──────────────────────────────


def test_decennial_liability_runs_ten_years_from_acceptance() -> None:
    spec = regime_for("eg_civil_651")
    assert spec is not None and spec.months == 120
    period = derive_period("eg_civil_651", date(2026, 6, 30))
    assert period.end_date == date(2036, 6, 30)


def test_an_egyptian_project_resolves_its_own_compliance_pack() -> None:
    assert resolve_pack("EG", None) == "eg_compliance"
