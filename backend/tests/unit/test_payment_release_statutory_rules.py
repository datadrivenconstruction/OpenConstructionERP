# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules V20 to V23 on plain payloads: statutory VAT and payment term rules read from country data.

Every case has a twin that differs in the one input the rule turns on, and a
German project with the same invoices reports nothing, because Germany has no
row in the data these rules read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.payment_release.statutory_rules import (
    STATUTORY_RULE_NUMBERS,
    STATUTORY_RULES,
    DomesticReverseChargeRule,
    ReducedHousingVatRule,
    SplitPaymentRule,
    StatutoryPaymentTermRule,
)
from app.modules.payment_release.validators import PAYLOAD_KEY, RULE_NUMBERS

pytestmark = pytest.mark.asyncio

_MESSAGES = Path(__file__).resolve().parents[2] / "app/core/validation/messages"


def _ctx(payload: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data={PAYLOAD_KEY: {"currency": "PLN", **payload}}, metadata={"locale": locale})


def _invoice(id_: str = "i1", **kw) -> dict:
    base = {
        "id": id_,
        "number": id_.upper(),
        "contact": "k1",
        "contract": "c1",
        "on": "2026-03-02",
        "gross": "24600.00",
        "vat": "4600.00",
        "lines": [{"rate": "23", "category": "S"}],
        "vat_facts": {},
        "payment_methods": [],
    }
    base.update(kw)
    return base


def _pl(**kw) -> dict:
    return {"country": "PL", "works": "private", "housing": {}, "contracts": [], **kw}


async def _problems(rule, payload: dict) -> list[tuple[str, Severity]]:
    out = await rule().validate(_ctx(payload))
    return [(r.details["problem"], r.severity) for r in out if not r.passed]


# ── V20 split payment ─────────────────────────────────────────────────────────


async def test_v20_a_marked_invoice_paid_by_split_payment_passes() -> None:
    inv = _invoice(vat_facts={"split_payment": True}, payment_methods=["split_payment"])
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == []


async def test_v20_an_unmarked_contract_invoice_above_the_threshold_is_pointed_out() -> None:
    found = await _problems(SplitPaymentRule, _pl(invoices=[_invoice()]))
    assert found == [("split_payment_annotation_missing", Severity.WARNING)]


async def test_v20_the_same_invoice_at_the_threshold_is_silent() -> None:
    inv = _invoice(gross="15000.00", vat="2804.88")
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == []


async def test_v20_a_payment_made_another_way_is_an_error_with_the_sanction() -> None:
    inv = _invoice(vat_facts={"split_payment": True, "annex_15": True}, payment_methods=["transfer"])
    out = await SplitPaymentRule().validate(_ctx(_pl(invoices=[inv])))
    bad = [r for r in out if not r.passed]
    assert [(r.details["problem"], r.severity) for r in bad] == [("split_payment_not_used", Severity.ERROR)]
    # 30 percent of VAT 4,600.00
    assert bad[0].details["sanction"] == "1380.00"


async def test_v20_the_same_payment_on_an_inferred_annex_status_only_warns() -> None:
    # The invoice bills a subcontract, so construction works are inferred, not declared.
    inv = _invoice(vat_facts={"split_payment": True}, payment_methods=["transfer"])
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == [("split_payment_not_used", Severity.WARNING)]


async def test_v20_a_payment_without_a_recorded_method_is_not_convicted() -> None:
    # An empty method is "not recorded", which the rule cannot judge.
    inv = _invoice(vat_facts={"split_payment": True}, payment_methods=[""])
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == []


async def test_v20_an_invoice_declared_outside_the_annex_is_silent() -> None:
    inv = _invoice(vat_facts={"annex_15": False}, payment_methods=["transfer"])
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == []


async def test_v20_goods_codes_decide_before_the_contract_does() -> None:
    timber = _invoice(contract="", vat_facts={"pkwiu_codes": ["46.73.11"]})
    works = _invoice(contract="", vat_facts={"pkwiu_codes": ["43.21.10"]})
    assert await _problems(SplitPaymentRule, _pl(invoices=[timber])) == []
    assert await _problems(SplitPaymentRule, _pl(invoices=[works])) == [
        ("split_payment_annotation_missing", Severity.WARNING)
    ]


async def test_v20_a_loose_invoice_without_codes_is_asked_about_not_convicted() -> None:
    inv = _invoice(contract="")
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == [("split_payment_annex_unknown", Severity.INFO)]


async def test_v20_an_invoice_before_november_2019_is_silent() -> None:
    inv = _invoice(on="2019-10-31", payment_methods=["transfer"])
    assert await _problems(SplitPaymentRule, _pl(invoices=[inv])) == []


async def test_v20_a_german_project_is_silent() -> None:
    inv = _invoice(payment_methods=["transfer"])
    assert await _problems(SplitPaymentRule, _pl(country="DE", invoices=[inv])) == []


# ── V21 housing rate ──────────────────────────────────────────────────────────


async def test_v21_eight_percent_on_a_flat_above_150_m2_is_pointed_out() -> None:
    inv = _invoice(lines=[{"rate": "8", "category": "AA"}])
    payload = _pl(invoices=[inv], housing={"object_kind": "flat", "usable_area_m2": "180"})
    assert await _problems(ReducedHousingVatRule, payload) == [("reduced_rate_above_area_limit", Severity.WARNING)]


async def test_v21_the_same_invoice_on_a_150_m2_flat_is_silent() -> None:
    inv = _invoice(lines=[{"rate": "8", "category": "AA"}])
    payload = _pl(invoices=[inv], housing={"object_kind": "flat", "usable_area_m2": "150"})
    assert await _problems(ReducedHousingVatRule, payload) == []


async def test_v21_eight_percent_without_a_recorded_object_is_pointed_out() -> None:
    inv = _invoice(lines=[{"rate": "8", "category": "AA"}])
    assert await _problems(ReducedHousingVatRule, _pl(invoices=[inv])) == [
        ("reduced_rate_object_unknown", Severity.WARNING)
    ]


async def test_v21_an_invoice_split_between_both_rates_is_silent() -> None:
    # Above the limit the invoice carries the standard rate on the excess: it
    # has already been split, which is what the rule asks for.
    inv = _invoice(lines=[{"rate": "8", "category": "AA"}, {"rate": "23", "category": "S"}])
    payload = _pl(invoices=[inv], housing={"object_kind": "flat", "usable_area_m2": "180"})
    assert await _problems(ReducedHousingVatRule, payload) == []


async def test_v21_the_standard_rate_is_never_questioned() -> None:
    payload = _pl(invoices=[_invoice()], housing={"object_kind": "commercial_premises"})
    assert await _problems(ReducedHousingVatRule, payload) == []


# ── V22 reverse charge ────────────────────────────────────────────────────────


async def test_v22_a_reverse_charged_line_after_november_2019_is_pointed_out() -> None:
    inv = _invoice(vat="0", lines=[{"rate": "0", "category": "AE"}])
    assert await _problems(DomesticReverseChargeRule, _pl(invoices=[inv])) == [
        ("domestic_reverse_charge_ended", Severity.WARNING)
    ]


async def test_v22_the_same_line_before_november_2019_is_silent() -> None:
    inv = _invoice(on="2019-10-31", vat="0", lines=[{"rate": "0", "category": "AE"}])
    assert await _problems(DomesticReverseChargeRule, _pl(invoices=[inv])) == []


async def test_v22_a_german_reverse_charge_is_silent() -> None:
    inv = _invoice(vat="0", lines=[{"rate": "0", "category": "AE"}])
    assert await _problems(DomesticReverseChargeRule, _pl(country="DE", invoices=[inv])) == []


# ── V23 payment term ──────────────────────────────────────────────────────────


def _terms_contract(interim: int | None, final: int | None) -> dict:
    return {"id": "c1", "code": "SC-01", "interim_due_days": interim, "final_due_days": final, "invoices": []}


async def test_v23_a_term_longer_than_sixty_days_is_pointed_out() -> None:
    payload = _pl(contracts=[_terms_contract(61, 30)], invoices=[])
    assert await _problems(StatutoryPaymentTermRule, payload) == [("payment_term_over_cap", Severity.WARNING)]


async def test_v23_sixty_days_is_within_the_cap() -> None:
    payload = _pl(contracts=[_terms_contract(60, 60)], invoices=[])
    assert await _problems(StatutoryPaymentTermRule, payload) == []


async def test_v23_a_german_contract_is_silent() -> None:
    payload = _pl(country="DE", contracts=[_terms_contract(90, 90)], invoices=[])
    assert await _problems(StatutoryPaymentTermRule, payload) == []


# ── Registry and messages ─────────────────────────────────────────────────────


async def test_the_rules_are_numbered_apart_from_v11_to_v18() -> None:
    assert set(STATUTORY_RULE_NUMBERS.values()) == {"V20", "V21", "V22", "V23"}
    assert not set(STATUTORY_RULE_NUMBERS) & set(RULE_NUMBERS)
    for rule in STATUTORY_RULES:
        assert await rule().validate(ValidationContext(data={"other": {}})) == []


async def test_every_message_exists_in_every_locale() -> None:
    keys = {
        "split_payment_annotation_missing",
        "split_payment_not_used",
        "split_payment_annex_unknown",
        "reduced_rate_above_area_limit",
        "reduced_rate_object_unknown",
        "reduced_rate_not_eligible",
        "domestic_reverse_charge_ended",
        "payment_term_over_cap",
    }
    for path in sorted(_MESSAGES.glob("*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))["payment_release"]
        missing = sorted(k for k in keys if not (bundle.get(k, {}).get("fail") and bundle[k].get("suggestion")))
        assert missing == [], f"{path.name} lacks {missing}"


async def test_the_polish_message_is_polish() -> None:
    out = await SplitPaymentRule().validate(_ctx(_pl(invoices=[_invoice()]), locale="pl"))
    assert "mechanizm podzielonej płatności" in out[0].message
