"""Hong Kong SAR pack: the DOMAIN worked examples A, B and C, the Cap. 652 clock, levies and the pack files."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.validation import rules as rules_pkg
from app.core.validation.engine import ValidationContext, rule_registry
from app.core.validation.rules.hongkong import HONGKONG_RULES
from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES, REGION_BY_COUNTRY
from app.modules.boq.models import BOQMarkup
from app.modules.boq.service import _calculate_markup_amounts
from app.modules.contracts.country_defaults import COUNTRY_CONTRACT_DEFAULTS
from app.modules.payment_clock import applicability as app_
from app.modules.payment_clock.clock import compute_schedule
from app.modules.payment_clock.data import PAYMENT_REGIMES, regime_by_code
from app.modules.price_index.quarterly_import import QuarterlyImportError, parse_quarterly_file, quarter_period

_ROOT = Path(__file__).resolve().parents[3]
_PACK = _ROOT / "packs/hongkong-hk/src/openconstructionerp_hongkong_hk"
SOPO = regime_by_code("hk_sopo")

# Example A: public fit-out, new government office, contract 01.02.2026, HK$50,000,000.
CONTRACT_A = {
    "contract_date": "2026-02-01",
    "contract_value": "50000000",
    "sector": "public",
    "payment_term_days": 60,
    "response_term_days": 30,
}
# Example B: private fit-out of an existing office, no Building Authority approval needed.
CONTRACT_B = {"contract_date": "2026-03-01", "contract_value": "50000000", "sector": "private"}
# Example C: HK$800,000 subcontract under A with a pay-when-paid clause.
CONTRACT_C = {
    "contract_date": "2026-04-15",
    "contract_value": "800000",
    "sector": "public",
    "is_subcontract": True,
    "main_contract_covered": True,
    "pay_when_paid": True,
    "payment_term_days": 45,
}


def _run(rule_id: str, data: dict) -> list:
    rules_pkg.register_builtin_rules()
    rule = next(r for r in rule_registry.get_rules_for_sets(["hongkong"]) if r.rule_id == rule_id)
    return asyncio.run(rule.validate(ValidationContext(data=data, metadata={"locale": "en"})))


# ── Cap. 652 regime and clock ────────────────────────────────────────────────


def test_sopo_regime_reads_the_ordinance() -> None:
    assert SOPO is not None
    assert SOPO["country_code"] == "HK"
    assert SOPO["payment_notice_days"] == 30
    assert SOPO["final_date_days"] == 60
    assert SOPO["no_notice_effect"] == "deemed_dispute"
    assert SOPO["applies_from"] == date(2025, 8, 28)
    assert SOPO["min_contract_value"] == Decimal("5000000.00")
    assert SOPO["min_contract_value_supply"] == Decimal("500000.00")
    assert SOPO["adjudication_window_days"] == 28
    assert SOPO["conditional_payment_void"] is True
    assert sum(1 for r in PAYMENT_REGIMES if r["code"] == "hk_sopo") == 1


def test_example_a_valuation_3_dates() -> None:
    schedule = compute_schedule(SOPO, application_date=date(2026, 3, 31), period_end=date(2026, 3, 31))
    assert schedule.payment_notice_deadline == date(2026, 4, 30)
    assert schedule.final_date == date(2026, 5, 30)
    dispute = app_.dispute_date(schedule.payment_notice_deadline)
    assert dispute == date(2026, 5, 1)
    assert app_.adjudication_window_closes(SOPO, dispute) == date(2026, 5, 28)


def test_a_claim_served_before_the_billing_date_counts_from_the_billing_date() -> None:
    early = compute_schedule(SOPO, application_date=date(2026, 3, 20), period_end=date(2026, 3, 31))
    assert early.payment_notice_deadline == date(2026, 4, 30)
    assert any("before the billing date" in line for line in early.derivation)


def test_example_a_money() -> None:
    gross = Decimal("18400000") + Decimal("600000")
    limit = Decimal("50000000") * Decimal("0.05")
    retention = min(gross * Decimal("0.10"), limit)
    assert retention == Decimal("1900000")
    previous_net = Decimal("12500000") - Decimal("1250000")
    assert gross - retention - previous_net == Decimal("5850000")
    assert min(Decimal("27000000") * Decimal("0.10"), limit) == Decimal("2500000")


def test_applicability_of_the_three_examples() -> None:
    assert app_.regime_applicability(SOPO, CONTRACT_A).status == app_.APPLIES
    b = app_.regime_applicability(SOPO, CONTRACT_B)
    assert (b.status, b.reason) == (app_.NEEDS_CONFIRMATION, "private_scope_unconfirmed")
    assert (
        app_.regime_applicability(SOPO, {**CONTRACT_B, "private_scope_confirmed": False}).status == app_.DOES_NOT_APPLY
    )
    c = app_.regime_applicability(SOPO, CONTRACT_C)
    assert (c.status, c.reason) == (app_.APPLIES, "subcontract_of_covered_contract")
    early = {**CONTRACT_A, "contract_date": "2025-08-27"}
    assert app_.regime_applicability(SOPO, early).reason == "made_before_commencement"
    small = {**CONTRACT_A, "contract_value": "4999999.99"}
    assert app_.regime_applicability(SOPO, small).reason == "below_value_threshold"
    supply = {**CONTRACT_A, "contract_value": "500000", "supply_only": True}
    assert app_.regime_applicability(SOPO, supply).status == app_.APPLIES


# ── Rules ────────────────────────────────────────────────────────────────────


def test_rule_set_has_the_thirteen_rules() -> None:
    rules_pkg.register_builtin_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets(["hongkong"])}
    assert ids == {cls.rule_id for cls in HONGKONG_RULES}
    assert len(ids) == 13


def test_example_a_rules() -> None:
    claim = {
        "reference": "Valuation 3",
        "claim_served": "2026-03-31",
        "billing_date": "2026-03-31",
        "claimed_amount": "5850000",
        "admitted_amount": "5200000",
        "response_served": True,
    }
    data = {"contract": CONTRACT_A, "applications": [claim], "as_of": "2026-05-10"}
    assert len(_run("hk.sopo.applicability", data)) == 1
    window = _run("hk.sopo.adjudication_window", data)
    assert len(window) == 1 and window[0].details["date"] == "2026-05-28"
    assert _run("hk.sopo.response_late", data) == []
    late = {**data, "applications": [{**claim, "response_served": False}]}
    found = _run("hk.sopo.response_late", late)
    assert len(found) == 1 and found[0].details["date"] == "2026-04-30"
    assert _run("hk.sopo.payment_term_exceeds_60", data) == []
    assert _run("hk.contract.pay_when_paid", data) == []


def test_example_b_asks_for_the_private_scope() -> None:
    data = {"contract": CONTRACT_B}
    assert len(_run("hk.sopo.private_scope_check", data)) == 1
    assert _run("hk.sopo.applicability", data) == []
    confirmed_out = {"contract": {**CONTRACT_B, "private_scope_confirmed": False}}
    assert _run("hk.sopo.private_scope_check", confirmed_out) == []


def test_example_c_subcontract() -> None:
    data = {"contract": CONTRACT_C}
    assert len(_run("hk.contract.pay_when_paid", data)) == 1
    assert _run("hk.sopo.payment_term_exceeds_60", data) == []
    found = _run("hk.sopo.payment_term_exceeds_60", {"contract": {**CONTRACT_C, "payment_term_days": 75}})
    assert len(found) == 1 and found[0].details["n"] == 75
    assert len(_run("hk.sopo.response_term_exceeds_30", {"contract": {**CONTRACT_C, "response_term_days": 31}})) == 1


def test_levy_tax_retention_pc_sum_and_index_rules() -> None:
    levies = [{"name": "CIC Levy", "percentage": "0.5"}, {"name": "CWR Levy", "percentage": "0.03"}]
    assert _run("hk.levy.missing", {"contract": CONTRACT_A, "markups": levies}) == []
    assert len(_run("hk.levy.missing", {"contract": CONTRACT_A, "markups": levies[:1]})) == 1
    assert len(_run("hk.levy.below_threshold", {"total_value": "3000000"})) == 1
    assert _run("hk.levy.below_threshold", {"total_value": "3000000.01"}) == []
    assert len(_run("hk.tax.nonzero", {"markups": [{"name": "VAT", "category": "tax", "percentage": "5"}]})) == 1
    assert _run("hk.tax.nonzero", {"markups": [{"name": "Tax", "category": "tax", "percentage": "0"}]}) == []
    assert _run("hk.retention.over_limit", {"retention": {"held": "1900000", "limit": "2500000"}}) == []
    over = _run("hk.retention.over_limit", {"retention": {"held": "2700000", "limit": "2500000"}})
    assert len(over) == 1 and "2,500,000.00" in over[0].message
    pc = [{"description": "P.C. Sum for audio-visual system"}]
    assert len(_run("hk.boq.pc_sum_no_attendance", {"positions": pc})) == 1
    full = [*pc, {"description": "Profit on P.C. Sum"}, {"description": "General attendance"}]
    assert _run("hk.boq.pc_sum_no_attendance", {"positions": full}) == []
    series = [{"name": "ArchSD Building Works Tender Price Index (BWTPI)", "source_attribution": ""}]
    assert len(_run("hk.index.attribution", {"index_series": series})) == 1


def test_contract_defaults_row_hk() -> None:
    row = COUNTRY_CONTRACT_DEFAULTS["HK"]
    assert row["retention_percent"]["value"] == "10"
    assert row["retention_cap_percent"]["value"] == "5"
    assert row["payment_period_days"]["value"] == 60


# ── Levies in the markup stack ───────────────────────────────────────────────


def _levy(name: str, pct: str, sort: int) -> BOQMarkup:
    return BOQMarkup(
        name=name,
        markup_type="percentage",
        category="other",
        percentage=pct,
        fixed_amount="0",
        apply_to="cumulative",
        sort_order=sort,
        is_active=True,
        metadata_={"threshold_amount": "3000000", "not_compounded": True},
    )


def test_example_a_levy_is_265000_and_nothing_at_the_threshold() -> None:
    lines = [_levy("CIC", "0.5", 1), _levy("CWR", "0.03", 2)]
    amounts = [a for _, a in _calculate_markup_amounts(Decimal("50000000"), lines)]
    assert amounts == [Decimal("250000"), Decimal("15000")]
    assert sum(amounts) == Decimal("265000")
    at_threshold = [a for _, a in _calculate_markup_amounts(Decimal("3000000"), lines)]
    assert all(a == 0 for a in at_threshold)


def test_hk_markup_template_has_the_levies_and_no_tax() -> None:
    assert REGION_BY_COUNTRY["HK"] == "HK"
    stack = DEFAULT_MARKUP_TEMPLATES["HK"]
    assert not [m for m in stack if m["category"] == "tax"]
    levies = [m for m in stack if m.get("threshold_amount")]
    assert [(m["percentage"], m["threshold_amount"]) for m in levies] == [("0.5", "3000000"), ("0.03", "3000000")]


# ── Price index import ───────────────────────────────────────────────────────


def test_quarterly_import_parses_the_archsd_shape() -> None:
    assert quarter_period("2026", "Q2") == "2026-04"
    assert quarter_period("2026", "Q5") is None
    rows = [
        {"Year": "2026", "Quarter": "Q2", "BWTPI": "1836"},
        {"Year": "2026", "Quarter": "Q3", "BWTPI": "-"},
        {"Year": "2025", "Quarter": "Q4", "BWTPI": "Not Available"},
    ]
    points, skipped = parse_quarterly_file(json.dumps([{"content": rows}]).encode())
    assert points == {"2026-04": Decimal("1836")}
    assert len(skipped) == 2
    with pytest.raises(QuarterlyImportError):
        parse_quarterly_file(b"Year,Quarter,BWTPI\n2026,Q1,-\n")


def test_pack_snapshot_carries_the_attribution() -> None:
    doc = json.loads((_PACK / "data/archsd_tpi.json").read_text(encoding="utf-8"))
    names = {s["name"] for s in doc["series"]}
    assert names == {
        "ArchSD Building Works Tender Price Index (BWTPI)",
        "ArchSD Building Services Tender Price Index (BSTPI)",
    }
    for series in doc["series"]:
        assert "Architectural Services Department" in series["source_attribution"]
        assert series["source_url"].startswith("https://data.gov.hk/")
        assert all(Decimal(v) > 0 for v in series["points"].values())
    bw = next(s for s in doc["series"] if "BWTPI" in s["name"])
    assert bw["points"]["1970-01"] == "100"


def test_hksmm4_skeleton_is_codes_only() -> None:
    doc = json.loads((_PACK / "data/hksmm4_skeleton.json").read_text(encoding="utf-8"))
    codes = [c["code"] for c in doc["codes"]]
    assert len(codes) == len(set(codes)) == 20
    assert all(c.startswith("HKSMM4-") for c in codes)
    assert all(len(c["description_en"]) < 80 for c in doc["codes"])


# ── Pack and demo ────────────────────────────────────────────────────────────


def test_pack_manifest() -> None:
    sys.path.insert(0, str(_ROOT / "packs/hongkong-hk/src"))
    try:
        from openconstructionerp_hongkong_hk import MANIFEST
    finally:
        sys.path.pop(0)
    assert MANIFEST.slug == "hongkong-hk"
    assert MANIFEST.default_currency == "HKD"
    assert MANIFEST.default_locale == "zh-HK"
    assert set(MANIFEST.additional_locales) == {"zh-HK", "en-HK"}
    assert "hongkong" in MANIFEST.validation_rule_sets
    assert MANIFEST.metadata["payment_regime"] == "hk_sopo"
    for path in MANIFEST.additional_locales.values():
        assert (_PACK / path).is_file()
    for rule_pack in MANIFEST.validation_rule_packs:
        assert (_PACK / "rule_packs" / f"{rule_pack}.json").is_file()


def test_demo_template_is_example_a() -> None:
    path = _ROOT / "backend/app/core/demo_packs/hk-gov-office-fitout.py"
    spec = importlib.util.spec_from_file_location("_hk_demo", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tpl = module.TEMPLATE
    assert (tpl.currency, tpl.region, tpl.classification_standard) == ("HKD", "HK", "hksmm4")
    assert "hongkong" in tpl.validation_rule_sets
    assert not [m for m in tpl.markups if m[2] == "tax"]
    levies = [m for m in tpl.markups if len(m) > 4]
    assert [m[1] for m in levies] == [0.5, 0.03]
    assert tpl.claim_retention == 0.10
    direct = sum(Decimal(str(q)) * Decimal(str(r)) for _, _, _, items in tpl.sections for _, _, _, q, r, _ in items)
    total = direct * Decimal("1.08") * Decimal("1.0053")
    assert abs(total - Decimal("50000000")) < Decimal("50000")


# ── Locale: Traditional Chinese never falls back to Simplified ───────────────


def test_traditional_chinese_never_resolves_to_simplified() -> None:
    from app.core.i18n import is_traditional_chinese, locale_candidates
    from app.middleware.accept_language import match_locale

    for tag in ("zh-HK", "zh-MO", "zh-TW", "zh-Hant", "zh-Hant-SG", "zh_TW"):
        assert is_traditional_chinese(tag), tag
        assert "zh" not in locale_candidates(tag)
        assert match_locale([(tag, 1.0)], ["en", "zh"]) == "en"
        assert match_locale([(tag, 1.0)], ["en", "zh", "zh-hk"]) == "zh-hk"
    for tag in ("zh", "zh-CN", "zh-SG", "zh-Hans-HK"):
        assert not is_traditional_chinese(tag), tag
    assert match_locale([("zh-CN", 1.0)], ["en", "zh"]) == "zh"
    assert locale_candidates("zh-TW") == ("zh-tw", "zh-hk")
    assert match_locale([("zh-TW", 1.0), ("de", 0.5)], ["en", "zh", "de"]) == "de"
