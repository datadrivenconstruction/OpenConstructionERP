# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""French works contracts measured against the Code de la commande publique, CCAG-Travaux 2021 and the 1970s laws.

The French row lives in the same registries as the Egyptian one
(:mod:`app.modules.contracts.public_procurement`,
:mod:`app.modules.contracts.price_adjustment`), so every case here is a
distinguishing case for France: the same contract on an Egyptian or a private
project answers differently, and where France and Egypt share a rule the
French figure is what decides.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.contracts.price_adjustment import PRICE_ADJUSTMENT_REGIMES, compute_adjustment, regime_for
from app.modules.contracts.public_procurement import (
    FR_REVISION_INDICES,
    PUBLIC_WORKS_LIMITS,
    PUBLIC_WORKS_PRICE_ADJUSTMENT,
    delay_damages_amount,
)
from app.modules.contracts.validators import (
    PriceAdjustmentTermsRule,
    PrivateWorksRetentionCapRule,
    PublicWorksLimitsRule,
    SubcontractDirectPaymentRule,
    SubcontractPaymentGuaranteeRule,
    register_contracts_validation_rules,
)
from app.modules.defects_liability import limitation

_PACK = Path(__file__).resolve().parents[3] / "packs" / "france-fr" / "src" / "openconstructionerp_france_fr"


def _ctx(
    *,
    country: str = "FR",
    works: str | None = "public",
    counterparty_type: str = "client",
    value: str = "900000",
    retention: str = "3",
    terms: dict[str, Any] | None = None,
    ld_clauses: list[dict[str, Any]] | None = None,
    start: str | None = "2026-01-15",
    end: str | None = "2026-03-01",
) -> ValidationContext:
    return ValidationContext(
        data={
            "project": {"country_code": country, "works": works},
            "contract": {
                "id": "c1",
                "status": "draft",
                "contract_type": "lump_sum",
                "counterparty_type": counterparty_type,
                "total_value": value,
                "retention_percent": retention,
                "start_date": start,
                "end_date": end,
                "terms": terms or {},
            },
            "parties": [],
            "securities": [],
            "ld_clauses": ld_clauses or [],
        },
        metadata={"locale": "en"},
    )


async def _fails(rule: type, context: ValidationContext) -> list:
    return [r for r in await rule().validate(context) if not r.passed]


_SME_STATE = {"contractor_is_sme": True, "public_buyer_category": "state"}


# ── Retention: 5 %, and 3 % for an SME working for a large buyer ─────────────


@pytest.mark.asyncio
async def test_four_percent_retention_blocks_an_sme_working_for_the_state_and_no_one_else() -> None:
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(retention="4", terms=_SME_STATE))
    assert found.severity == Severity.ERROR
    assert (found.details["percent"], found.details["limit"]) == ("4", "3")
    large_company = {"contractor_is_sme": False, "public_buyer_category": "state"}
    assert await _fails(PublicWorksLimitsRule, _ctx(retention="4", terms=large_company)) == []
    small_buyer = {"contractor_is_sme": True, "public_buyer_category": "other"}
    assert await _fails(PublicWorksLimitsRule, _ctx(retention="4", terms=small_buyer)) == []


@pytest.mark.asyncio
async def test_the_three_percent_tier_covers_large_public_bodies_too() -> None:
    terms = {"contractor_is_sme": True, "public_buyer_category": "large_public_body"}
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(retention="4", terms=terms))
    assert found.details["limit"] == "3"


@pytest.mark.asyncio
async def test_the_sme_tiers_do_not_reach_back_before_2025() -> None:
    before = {**_SME_STATE, "procedure_launch_date": "2024-11-04", "advance_payment_percent": "20"}
    assert await _fails(PublicWorksLimitsRule, _ctx(retention="4", terms=before)) == []
    after = {**_SME_STATE, "procedure_launch_date": "2025-01-06"}
    assert len(await _fails(PublicWorksLimitsRule, _ctx(retention="4", terms=after))) == 1


@pytest.mark.asyncio
async def test_six_percent_retention_blocks_everyone() -> None:
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(retention="6"))
    assert found.details["limit"] == "5"


# ── Advance: 5 % to 30 %, SME minimums 30 % (State) and 10 % (large bodies) ──


@pytest.mark.asyncio
async def test_a_twenty_percent_advance_is_short_for_an_sme_working_for_the_state() -> None:
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(terms={**_SME_STATE, "advance_payment_percent": "20"}))
    assert found.severity == Severity.ERROR
    assert found.rule_id == "contracts.public_works_limits"
    assert (found.details["percent"], found.details["limit"]) == ("20", "30")
    assert "below" in found.message


@pytest.mark.asyncio
async def test_the_same_advance_is_lawful_for_a_large_company_or_when_renounced() -> None:
    large = {"contractor_is_sme": False, "public_buyer_category": "state", "advance_payment_percent": "20"}
    assert await _fails(PublicWorksLimitsRule, _ctx(terms=large)) == []
    renounced = {**_SME_STATE, "advance_payment_percent": "0"}
    assert await _fails(PublicWorksLimitsRule, _ctx(terms=renounced)) == []


@pytest.mark.asyncio
async def test_a_large_body_owes_an_sme_ten_percent_and_everyone_five() -> None:
    body = {"contractor_is_sme": True, "public_buyer_category": "large_public_body", "advance_payment_percent": "8"}
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(terms=body))
    assert found.details["limit"] == "10"
    (general,) = await _fails(PublicWorksLimitsRule, _ctx(terms={"advance_payment_percent": "4"}))
    assert general.details["limit"] == "5"


@pytest.mark.asyncio
async def test_an_advance_above_thirty_percent_is_only_a_warning() -> None:
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(terms={"advance_payment_percent": "35"}))
    assert found.severity == Severity.WARNING
    assert found.details["limit"] == "30"
    assert "minister" not in found.message


# ── Delay penalties: 1/3000 a day, capped at 10 %, waived up to EUR 1,000 ────


def test_the_ccag_penalty_on_a_worked_example() -> None:
    assert delay_damages_amount("FR", "900000", 120) == Decimal("36000.00")
    assert delay_damages_amount("FR", "900000", 400) == Decimal("90000.00")


def test_penalties_up_to_one_thousand_euros_are_waived_and_one_euro_more_is_not() -> None:
    assert delay_damages_amount("FR", "300000", 10) == Decimal("0")
    assert delay_damages_amount("FR", "300000", 11) == Decimal("1100.00")


def test_a_country_without_a_daily_rate_computes_nothing() -> None:
    assert delay_damages_amount("EG", "900000", 10) is None


@pytest.mark.asyncio
async def test_the_ccag_rate_passes_and_another_rate_must_be_a_listed_derogation() -> None:
    ccag = [{"id": "ld1", "per_day_amount": "300", "max_amount": "90000"}]
    assert await _fails(PublicWorksLimitsRule, _ctx(ld_clauses=ccag)) == []
    other = [{"id": "ld1", "per_day_amount": "450", "max_amount": "90000"}]
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(ld_clauses=other))
    assert found.severity == Severity.WARNING
    assert (found.details["amount"], found.details["expected"]) == ("450", "300")


@pytest.mark.asyncio
async def test_a_cap_above_ten_percent_warns_in_france_because_the_ccap_may_derogate() -> None:
    above = [{"id": "ld1", "per_day_amount": "300", "max_amount": "135000"}]
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(ld_clauses=above))
    assert found.severity == Severity.WARNING
    assert (found.details["percent"], found.details["limit"]) == ("15", "10")


# ── Direct payment of a subcontractor from EUR 600 incl. VAT ─────────────────


def _sub(value: str, terms: dict[str, Any] | None = None, **kw: Any) -> ValidationContext:
    return _ctx(counterparty_type="subcontractor", value=value, terms=terms, **kw)


@pytest.mark.asyncio
async def test_direct_payment_starts_at_six_hundred_euros() -> None:
    assert await SubcontractDirectPaymentRule().validate(_sub("599")) == []
    (found,) = await _fails(SubcontractDirectPaymentRule, _sub("600"))
    assert found.severity == Severity.WARNING


@pytest.mark.asyncio
async def test_waiving_direct_payment_blocks_and_recording_it_passes() -> None:
    (found,) = await _fails(SubcontractDirectPaymentRule, _sub("50000", {"direct_payment": False}))
    assert found.severity == Severity.ERROR
    assert await _fails(SubcontractDirectPaymentRule, _sub("50000", {"direct_payment": True})) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [_sub("50000", works="private"), _sub("50000", country="EG"), _ctx(value="50000")],
    ids=["private_fr", "public_eg", "main_contract_fr"],
)
async def test_direct_payment_is_silent_off_french_public_subcontracts(context: ValidationContext) -> None:
    assert await SubcontractDirectPaymentRule().validate(context) == []


# ── Private subcontract: caution or délégation de paiement ───────────────────


@pytest.mark.asyncio
async def test_a_private_subcontract_without_a_payment_guarantee_warns() -> None:
    (found,) = await _fails(SubcontractPaymentGuaranteeRule, _sub("50000", works="private"))
    assert found.severity == Severity.WARNING
    for kind in ("caution", "delegation_de_paiement"):
        context = _sub("50000", {"payment_guarantee": kind}, works="private")
        assert await _fails(SubcontractPaymentGuaranteeRule, context) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [_sub("50000"), _ctx(works="private"), _sub("50000", works="private", country="EG")],
    ids=["public_fr", "main_contract_fr", "private_eg"],
)
async def test_the_guarantee_rule_is_silent_elsewhere(context: ValidationContext) -> None:
    assert await SubcontractPaymentGuaranteeRule().validate(context) == []


# ── Private works retention: 5 % by loi 71-584 ───────────────────────────────


@pytest.mark.asyncio
async def test_private_french_retention_above_five_percent_blocks() -> None:
    assert await _fails(PrivateWorksRetentionCapRule, _ctx(works="private", retention="5")) == []
    (found,) = await _fails(PrivateWorksRetentionCapRule, _ctx(works="private", retention="6"))
    assert found.severity == Severity.ERROR
    assert (found.details["percent"], found.details["limit"]) == ("6", "5")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        _ctx(works="public", retention="6"),
        _ctx(works=None, retention="6"),
        _ctx(works="private", country="EG", retention="10"),
        _ctx(works="private", country="CN", retention="10"),
    ],
    ids=["public_fr", "unrecorded_fr", "private_eg", "private_cn"],
)
async def test_the_private_cap_needs_a_private_variant_that_states_a_statute(context: ValidationContext) -> None:
    assert await PrivateWorksRetentionCapRule().validate(context) == []


# ── Price revision: CCAG-Travaux art. 10.5, coefficient rounded up ───────────

_FR_REVISION = "fr_ccag_travaux_2021_art_10_5"


def test_the_revision_coefficient_is_rounded_up_to_the_thousandth() -> None:
    # C = 0.125 + 0.875 x 123.6 / 120.0 = 1.02625, rounded up to 1.027 (nearest would give 1.026).
    result = compute_adjustment(_FR_REVISION, "100000", [("BT01", "0.875")], {"BT01": "120.0"}, {"BT01": "123.6"})
    assert result.revision_coefficient == Decimal("1.027")
    assert result.total == Decimal("2700.00")
    assert result.items[0].amount == Decimal("2625.00")
    assert result.as_dict()["revision_coefficient"] == "1.027"


def test_a_falling_index_rounds_up_toward_the_contractor_too() -> None:
    result = compute_adjustment(_FR_REVISION, "100000", [("BT01", "0.875")], {"BT01": "120.0"}, {"BT01": "116.4"})
    assert result.revision_coefficient == Decimal("0.974")
    assert result.total == Decimal("-2600.00")


def test_a_regime_without_rounding_prints_no_coefficient() -> None:
    result = compute_adjustment("eg_law182_art97", "1000", [("steel", "0.5")], {"steel": "100"}, {"steel": "110"})
    assert result.revision_coefficient is None
    assert "revision_coefficient" not in result.as_dict()


def test_france_revises_by_the_ccag_regime_on_insee_indices_without_shipping_their_series_ids() -> None:
    assert PUBLIC_WORKS_PRICE_ADJUSTMENT["FR"] == _FR_REVISION
    regime = regime_for(_FR_REVISION)
    assert regime is not None and regime["mandatory"] is False
    assert regime["period_months"] == 1 and regime["min_duration_months"] == 3
    codes = {row["code"] for row in FR_REVISION_INDICES}
    assert {"BT01", "TP01"} <= codes
    assert all(row["insee_series_id"] is None and row["needs_expert_review"] for row in FR_REVISION_INDICES)
    assert _FR_REVISION in PRICE_ADJUSTMENT_REGIMES


@pytest.mark.asyncio
async def test_a_revisable_french_contract_without_weights_warns_and_a_firm_price_does_not() -> None:
    long = {"start": "2026-01-15", "end": "2026-12-15"}
    (found,) = await _fails(PriceAdjustmentTermsRule, _ctx(**long))
    assert found.severity == Severity.WARNING
    assert "must be price-adjusted by law" not in found.message
    firm = {"price_adjustment": {"firm_price": True}}
    assert await _fails(PriceAdjustmentTermsRule, _ctx(terms=firm, **long)) == []
    assert await PriceAdjustmentTermsRule().validate(_ctx(start="2026-01-15", end="2026-03-01")) == []


# ── The French row ───────────────────────────────────────────────────────────


def test_the_french_row_cites_the_code_and_the_ccag() -> None:
    row = PUBLIC_WORKS_LIMITS["FR"]
    assert "commande publique" in row["law"] and "CCAG-Travaux 2021" in row["law"]
    assert row["retention_percent_sme"]["effective_date"] == "2025-01-01"
    assert row["advance_payment_min_percent_sme"]["value"] == "30"
    assert row["delay_damages_daily_divisor"]["value"] == 3000
    assert row["delay_damages_waiver_amount"]["value"] == 1000


# ── Warranties after reception ───────────────────────────────────────────────


def test_the_three_french_warranties_run_from_reception() -> None:
    by_code = {spec.code: spec for spec in limitation.LIMITATION_REGIMES if spec.country_code == "FR"}
    assert {code: spec.months for code, spec in by_code.items()} == {
        "fr_civil_1792_6": 12,
        "fr_civil_1792_3": 24,
        "fr_civil_1792": 120,
    }
    assert all(spec.starts_from == "acceptance" for spec in by_code.values())


# ── The pack says what it runs ───────────────────────────────────────────────


def _pack(name: str) -> dict[str, Any]:
    return json.loads((_PACK / "rule_packs" / f"{name}.json").read_text(encoding="utf-8"))


def test_the_pack_enables_only_rules_the_engine_runs() -> None:
    register_contracts_validation_rules()
    procurement = _pack("code_commande_publique")
    assert {
        "contracts.public_works_limits",
        "contracts.price_adjustment_terms",
        "contracts.subcontract_direct_payment",
    } <= set(procurement["enables_rule_ids"])
    private = _pack("nf_p_03_001")
    assert {"contracts.private_works_retention_cap", "contracts.subcontract_payment_guarantee"} <= set(
        private["enables_rule_ids"]
    )
    for pack in (procurement, private):
        for rule_id in pack["enables_rule_ids"]:
            assert rule_registry.get_rule(rule_id) is not None, rule_id


def test_the_outdated_twenty_percent_advance_rule_is_gone() -> None:
    pack = _pack("code_commande_publique")
    listed = set(pack["enables_rule_ids"]) | set(pack["planned_not_built_rule_ids"])
    assert "ccp.avance_forfaitaire_min_20_pct" not in listed
    assert "ccp.avance_forfaitaire_min_20_pct" in pack["superseded_rule_ids_note"]
