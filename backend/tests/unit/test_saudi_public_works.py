# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi public works: the GTPL figures, two dated laws, and the private FIDIC profile beside them.

A Saudi project that records public works is governed by the Government
Tenders and Procurement Law; which one depends on when the tender was
floated, because the 2019 law keeps governing tenders floated before the new
law (Royal Decree M/76, published 2026-09-04) takes effect. The new law's
figures come from law-firm summaries only, so they are shown and never
enforced. Private works keep the FIDIC profile the country row has always had.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.contracts.compliance_packs import RULE_PACKS, resolve_pack
from app.modules.contracts.country_defaults import resolve_contract_defaults
from app.modules.contracts.price_adjustment import PRICE_ADJUSTMENT_TRIGGERS, assess_trigger_claim
from app.modules.contracts.public_procurement import (
    PUBLIC_WORKS_LIMIT_REGIMES,
    has_public_works_limits,
    limit_value,
    public_works_limits,
    validate_limit_regimes,
)
from app.modules.contracts.validators import PriceAdjustmentTermsRule, PublicWorksLimitsRule
from app.modules.defects_liability.limitation import MANDATORY_DEFECTS_INSURANCE, derive_period, regime_for
from app.modules.payment_clock.clock import compute_schedule
from app.modules.payment_clock.data import PAYMENT_REGIMES

_OLD_LAW_DAY = date(2026, 12, 31)
_NEW_LAW_DAY = date(2027, 1, 2)


def _split(resolved: dict) -> list[tuple[str, str]]:
    return [(s["event"], s["release_percent_of_held"]) for s in resolved["values"]["retention_release_split"]]


# ── Contract defaults ────────────────────────────────────────────────────────


def test_public_works_hold_ten_percent_up_to_ten_percent_of_the_contract() -> None:
    public = resolve_contract_defaults("SA", works="public")
    assert Decimal(public["values"]["retention_percent"]) == Decimal("10")
    assert Decimal(public["values"]["retention_cap_percent"]) == Decimal("10")
    assert _split(public) == [("substantial_completion", "100")]
    assert public["values"]["certificate_name"] == "مستخلص"
    # The 70 working days are the payment clock's, never a calendar figure here.
    assert public["values"]["payment_period_days"] is None
    assert "Art. 111" in public["sources"]["retention_percent"]["reference"]
    assert public["sources"]["retention_percent"]["note_key"] == (
        "contracts.works_defaults.SA.public.retention_percent.note"
    )


def test_private_and_unrecorded_works_keep_the_fidic_profile() -> None:
    private = resolve_contract_defaults("SA", works="private")
    assert private == resolve_contract_defaults("SA")
    assert private["standard_form"].startswith("FIDIC")
    assert Decimal(private["values"]["retention_cap_percent"]) == Decimal("5")
    assert private["values"]["payment_period_days"] == 56


@pytest.mark.parametrize("country", ["AE", "QA", "KW", "BH", "OM"])
def test_no_other_gulf_country_gains_a_public_profile(country: str) -> None:
    assert resolve_contract_defaults(country, works="public") == resolve_contract_defaults(country)
    assert public_works_limits(country) is None


# ── Statutory limits, chosen by tender date ──────────────────────────────────


def test_the_dated_regimes_are_sound() -> None:
    assert validate_limit_regimes(PUBLIC_WORKS_LIMIT_REGIMES) == []
    assert has_public_works_limits("SA") and has_public_works_limits("eg")
    assert not has_public_works_limits("AE")


def test_a_tender_floated_before_the_new_law_keeps_the_2019_figures() -> None:
    limits = public_works_limits("SA", tender_date=_OLD_LAW_DAY)
    assert limits is not None and limits["regime"] == "sa_gtpl_2019"
    assert limit_value(limits, "retention_percent") == Decimal("10")
    assert limit_value(limits, "advance_payment_max_percent") == Decimal("10")
    assert limit_value(limits, "performance_security_percent") == Decimal("5")
    assert limit_value(limits, "performance_security_due_working_days") == Decimal("15")
    assert limit_value(limits, "delay_damages_cap_percent_works_long_delay") == Decimal("20")
    assert limit_value(limits, "delay_damages_cap_percent_other") == Decimal("6")
    assert limit_value(limits, "variation_max_increase_percent_of_contract") == Decimal("10")
    assert limit_value(limits, "variation_max_decrease_percent_of_contract") == Decimal("20")


def test_a_tender_under_the_new_law_is_shown_and_never_enforced() -> None:
    limits = public_works_limits("SA", tender_date=_NEW_LAW_DAY)
    assert limits is not None and limits["regime"] == "sa_gtpl_2026"
    assert limits["confidence"] == "needs_expert_review"
    figures = [v for v in limits.values() if isinstance(v, dict) and "value" in v]
    assert figures and all(f["needs_expert_review"] for f in figures)
    # The figure is there to read...
    assert limits["delay_damages_cap_percent_works_long_delay"]["value"] == "15"
    assert limits["variation_max_increase_percent_of_contract"]["value"] == "20"
    # ...and no rule takes it as a limit.
    assert limit_value(limits, "delay_damages_cap_percent_works_long_delay") is None


def test_egypt_answers_its_single_row_for_any_date() -> None:
    assert public_works_limits("EG", tender_date=date(2001, 1, 1)) == public_works_limits("EG")
    assert public_works_limits("EG", tender_date=date(2040, 1, 1)) == public_works_limits("EG")


# ── The rules on a Saudi public contract ─────────────────────────────────────


def _ctx(
    *,
    works: str = "public",
    retention: str = "10",
    tender_date: str | None = "2026-11-01",
    ld_max: str | None = "2000000",
) -> ValidationContext:
    terms: dict[str, Any] = {"tender_date": tender_date} if tender_date else {}
    return ValidationContext(
        data={
            "project": {"country_code": "SA", "works": works},
            "contract": {
                "id": "c1",
                "status": "draft",
                "contract_type": "lump_sum",
                "counterparty_type": "client",
                "total_value": "10000000",
                "retention_percent": retention,
                "start_date": "2027-03-01",
                "end_date": "2028-03-01",
                "terms": terms,
            },
            "parties": [],
            "securities": [{"security_type": "bank_guarantee", "status": "active", "amount": "500000"}],
            "ld_clauses": [{"max_amount": ld_max}] if ld_max else [],
        },
        metadata={"locale": "en"},
    )


async def _fails(rule: type, context: ValidationContext) -> list:
    return [r for r in await rule().validate(context) if not r.passed]


async def test_retention_above_ten_blocks_a_2019_law_contract() -> None:
    assert await _fails(PublicWorksLimitsRule, _ctx(retention="10")) == []
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(retention="12"))
    assert found.severity == Severity.ERROR
    assert found.details == {"country": "SA", "percent": "12", "limit": "10"}


async def test_a_delay_cap_of_eighteen_percent_passes_under_2019_and_is_not_judged_under_the_new_law() -> None:
    assert await _fails(PublicWorksLimitsRule, _ctx(ld_max="1800000")) == []
    over = await _fails(PublicWorksLimitsRule, _ctx(ld_max="2100000"))
    assert [r.details["limit"] for r in over] == ["20"]
    assert await _fails(PublicWorksLimitsRule, _ctx(ld_max="1800000", tender_date="2027-02-01")) == []


async def test_a_private_saudi_contract_is_silent() -> None:
    assert await PublicWorksLimitsRule().validate(_ctx(works="private", retention="15")) == []


async def test_the_index_formula_rule_does_not_ask_a_saudi_contract_for_coefficients() -> None:
    assert await PriceAdjustmentTermsRule().validate(_ctx()) == []


# ── Price adjustment: a trigger, not a formula ───────────────────────────────


@pytest.mark.parametrize(
    ("material", "contract", "triggered"),
    [("10", "3.01", True), ("9.99", "3.01", False), ("10", "3.00", False), ("-12", "-4", True)],
    ids=["both-thresholds", "material-below", "contract-at-threshold", "a-fall-is-deducted"],
)
def test_both_thresholds_must_be_crossed(material: str, contract: str, triggered: bool) -> None:
    assert assess_trigger_claim("sa_gtpl_ir113", material, contract, contract)["triggered"] is triggered


def test_compensation_above_the_cap_is_left_to_the_court() -> None:
    result = assess_trigger_claim("sa_gtpl_ir113", "15", "25", "25")
    assert result["payable_percent_of_contract"] == Decimal("20")
    assert result["excess_percent_of_contract"] == Decimal("5")


def test_the_trigger_row_records_the_threshold_conflict() -> None:
    row = PRICE_ADJUSTMENT_TRIGGERS["sa_gtpl_ir113"]
    assert row["needs_expert_review"] is True
    assert "five percent (3%)" in row["note"]
    assert row["claim_days"] == 60
    assert {"cement", "steel", "asphalt"} <= set(row["materials"])


# ── Payment clock, compliance pack, decennial liability ──────────────────────


def test_the_public_payment_cycle_is_seventy_working_days() -> None:
    (row,) = [r for r in PAYMENT_REGIMES if r["code"] == "sa_gtpl_ir109"]
    assert row["country_code"] == "SA"
    assert row["payment_notice_days"] == 25 and row["payment_notice_day_basis"] == "business"
    assert row["final_date_days"] == 70 and row["final_date_day_basis"] == "business"
    assert row["interest_basis"] == "contract"
    # Submitted on Sunday 2026-11-01, counted on the Sunday to Thursday week:
    # a Monday to Friday count would give Friday 2026-12-04 instead.
    schedule = compute_schedule(row, application_date=date(2026, 11, 1))
    assert schedule.payment_notice_deadline == date(2026, 12, 6)
    assert schedule.final_date == date(2027, 2, 7)


def test_saudi_arabia_reaches_its_own_compliance_pack() -> None:
    assert resolve_pack("SA", None) == "sa_compliance"
    assert RULE_PACKS["sa_compliance"]["rule_sets"] == ["boq_quality", "masterformat"]


def test_decennial_liability_runs_ten_years_from_completion() -> None:
    spec = regime_for("sa_sbc_decennial")
    assert spec is not None and spec.country_code == "SA" and spec.months == 120
    period = derive_period("sa_sbc_decennial", date(2026, 1, 15))
    assert period is not None and period.end_date == date(2036, 1, 15)


def test_inherent_defects_insurance_is_data_flagged_for_review() -> None:
    row = MANDATORY_DEFECTS_INSURANCE["SA"]
    assert row["years"] == 10
    assert row["effective_date"] == "2020-05-02"
    assert row["needs_expert_review"] is True
    assert row["limitation_regime"] == "sa_sbc_decennial"
