# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules V11 to V14 and V16 to V18 on plain payloads: each one speaks on its case and only there."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.payment_release.validators import (
    PAYLOAD_KEY,
    PAYMENT_RELEASE_RULES,
    RULE_NUMBERS,
    DuplicateInvoiceRule,
    EarlyPaymentDiscountRule,
    InvoicedWithinValueRule,
    InvoiceSequenceRule,
    InvoiceVatRule,
    ReleaseRecomputedRule,
    RetentionTermsRule,
)

pytestmark = pytest.mark.asyncio

_MESSAGES = Path(__file__).resolve().parents[2] / "app/core/validation/messages"


def _ctx(payload: dict, locale: str = "en") -> ValidationContext:
    return ValidationContext(data={PAYLOAD_KEY: {"currency": "EUR", **payload}}, metadata={"locale": locale})


def _contract(**kw) -> dict:
    base = {
        "id": "c1",
        "code": "SC-01",
        "status": "active",
        "invoice_mode": "cumulative",
        "warranty_enabled": False,
        "discount_enabled": False,
        "rounding_enabled": False,
        "rounding_step": "0",
        "has_measurement": False,
        "measured": "0",
        "invoiced_series": "0",
        "current_value": "0",
        "retention_held": "0",
        "invoices": [],
        "postings": [],
    }
    base.update(kw)
    return base


def _inv(id_: str, kind: str = "interim", **kw) -> dict:
    base = {
        "id": id_,
        "number": id_.upper(),
        "kind": kind,
        "claim": False,
        "net_after": "0",
        "released": False,
        "release": "0",
        "release_computed": "0",
        "rounding": "0",
        "discount": "0",
        "retention": "0",
        "retention_source": "terms",
        "payable": "0",
        "paid_cash": "0",
        "last_payment_on": "",
        "discount_until": "",
    }
    base.update(kw)
    return base


async def _fails(rule, payload: dict, locale: str = "en") -> list:
    return [r for r in await rule().validate(_ctx(payload, locale)) if not r.passed]


async def test_rules_are_silent_without_their_payload() -> None:
    for rule in PAYMENT_RELEASE_RULES:
        assert await rule().validate(ValidationContext(data={"other": {}})) == []
    assert set(RULE_NUMBERS.values()) == {"V11", "V12", "V13", "V14", "V16", "V17", "V18", "V19"}


async def test_v11_a_falling_cumulative_total_and_an_invoice_after_the_final() -> None:
    payload = {
        "contracts": [
            _contract(
                invoices=[
                    _inv("a", net_after="5000"),
                    _inv("b", net_after="3000"),
                    _inv("f", "final", net_after="9000"),
                    _inv("late", net_after="9500"),
                    _inv("dw", "daywork", net_after="100"),
                ]
            )
        ]
    }
    found = await _fails(InvoiceSequenceRule, payload)
    problems = sorted(r.details["problem"] for r in found)
    assert problems == ["cumulative_total_fell", "invoice_after_final"]
    fell = next(r for r in found if r.details["problem"] == "cumulative_total_fell")
    assert fell.element_ref == "b"
    assert "EUR" in fell.message and "5,000.00" in fell.message
    # Incremental: a smaller invoice is just less new work.
    payload["contracts"][0]["invoice_mode"] = "incremental"
    payload["contracts"][0]["invoices"] = payload["contracts"][0]["invoices"][:2]
    assert await _fails(InvoiceSequenceRule, payload) == []


async def test_v11_a_claim_invoice_on_a_cumulative_contract_is_a_warning() -> None:
    payload = {"contracts": [_contract(invoices=[_inv("a", claim=True, net_after="100")])]}
    (found,) = await _fails(InvoiceSequenceRule, payload)
    assert found.severity == Severity.WARNING
    assert found.details["problem"] == "claim_invoice_in_cumulative"


async def test_v12_a_confirmed_release_that_no_longer_matches_and_a_bad_rounding() -> None:
    payload = {
        "contracts": [
            _contract(
                rounding_enabled=True,
                rounding_step="100",
                invoices=[
                    _inv("a", released=True, release="900", release_computed="950"),
                    _inv("b", rounding="100"),
                    _inv("c", released=True, release="500", release_computed="500.004", rounding="99.99"),
                ],
            )
        ]
    }
    found = await _fails(ReleaseRecomputedRule, payload)
    assert sorted((r.element_ref, r.details["problem"]) for r in found) == [
        ("a", "release_differs"),
        ("b", "rounding_out_of_range"),
    ]


async def test_v13_retention_on_a_final_without_warranty_overposting_early_posting_and_held_on_completion() -> None:
    payload = {
        "contracts": [
            _contract(
                status="completed",
                retention_held="-10",
                warranty_period_months=24,
                invoices=[_inv("f", "final", retention="50")],
                postings=[
                    {
                        "id": "p1",
                        "retention_kind": "warranty",
                        "event": "defects_period_end",
                        "event_on": "2026-01-15",
                        "posted_on": "2027-06-01",
                        "amount": "10",
                    },
                    {
                        "id": "p2",
                        "retention_kind": "interim",
                        "event": "substantial_completion",
                        "event_on": "",
                        "posted_on": "2026-01-01",
                        "amount": "5",
                    },
                ],
            ),
            _contract(id="c2", code="SC-02", status="completed", retention_held="40"),
        ]
    }
    found = await _fails(RetentionTermsRule, payload)
    got = sorted((r.element_ref, r.details["problem"], r.severity.value) for r in found)
    assert got == [
        ("c1", "posting_exceeds_held", "error"),
        ("c2", "retention_still_held", "info"),
        ("f", "final_retention_without_warranty", "error"),
        ("p1", "posting_before_event", "warning"),  # posted before 2028-01-15
        ("p2", "posting_without_event_date", "warning"),  # no event date at all
    ]
    # Warranty agreed: retention on the final is the point.
    payload["contracts"][0]["warranty_enabled"] = True
    assert "final_retention_without_warranty" not in {
        r.details["problem"] for r in await _fails(RetentionTermsRule, payload)
    }


async def test_v14_discount_not_agreed_and_kept_back_after_the_deadline() -> None:
    late = _inv(
        "a",
        discount="20",
        release="1000",
        payable="980",
        paid_cash="980",
        last_payment_on="2026-05-30",
        discount_until="2026-05-14",
    )
    on_time = _inv(
        "b",
        discount="20",
        release="1000",
        payable="980",
        paid_cash="980",
        last_payment_on="2026-05-10",
        discount_until="2026-05-14",
    )
    full = _inv(
        "c",
        discount="20",
        release="1000",
        payable="980",
        paid_cash="1000",
        last_payment_on="2026-05-30",
        discount_until="2026-05-14",
    )
    payload = {"contracts": [_contract(discount_enabled=True, invoices=[late, on_time, full])]}
    (found,) = await _fails(EarlyPaymentDiscountRule, payload)
    assert (found.element_ref, found.details["problem"]) == ("a", "discount_after_deadline")
    payload["contracts"][0]["discount_enabled"] = False
    found = await _fails(EarlyPaymentDiscountRule, payload)
    assert {r.details["problem"] for r in found} == {"discount_not_agreed"}
    assert all(r.severity == Severity.ERROR for r in found)


async def test_v16_invoiced_over_measured_or_over_the_contract() -> None:
    measured = _contract(has_measurement=True, measured="8000", invoiced_series="8000.02", current_value="20000")
    within = _contract(id="c2", has_measurement=True, measured="8000", invoiced_series="8000.01")
    unmeasured = _contract(id="c3", invoiced_series="12000", current_value="10000")
    found = await _fails(InvoicedWithinValueRule, {"contracts": [measured, within, unmeasured]})
    assert sorted((r.element_ref, r.details["problem"]) for r in found) == [
        ("c1", "invoiced_over_measured"),
        ("c3", "invoiced_over_contract"),
    ]


async def test_v17_reverse_charge_with_vat_and_lines_without_a_rate() -> None:
    payload = {
        "invoices": [
            {"id": "rc", "number": "RC", "vat": "19", "lines": [{"rate": "0", "category": "AE"}]},
            {"id": "rc2", "number": "RC2", "vat": "0", "lines": [{"rate": "19", "category": "AE"}]},
            {"id": "ok", "number": "OK", "vat": "0", "lines": [{"rate": "0", "category": "AE"}]},
            {"id": "mix", "number": "MIX", "vat": "26", "lines": [{"rate": "19", "category": "S"}, {"rate": None}]},
            {"id": "one", "number": "ONE", "vat": "19", "lines": [{"rate": None}]},
        ]
    }
    found = await _fails(InvoiceVatRule, payload)
    assert sorted((r.element_ref, r.details["problem"], r.severity.value) for r in found) == [
        ("mix", "line_without_vat_rate", "warning"),
        ("rc", "reverse_charge_with_vat", "error"),
        ("rc2", "reverse_charge_with_vat", "error"),
    ]


async def test_v18_same_number_twice_and_same_amount_same_day() -> None:
    payload = {
        "invoices": [
            {"id": "1", "number": "R-100", "contact": "k", "gross": "500", "on": "2026-03-01"},
            {"id": "2", "number": "r 100", "contact": "k", "gross": "700", "on": "2026-03-05"},
            {"id": "3", "number": "R-200", "contact": "k", "gross": "900", "on": "2026-04-01"},
            {"id": "4", "number": "R-201", "contact": "k", "gross": "900", "on": "2026-04-01"},
            {"id": "5", "number": "R-100", "contact": "other", "gross": "500", "on": "2026-03-01"},
        ]
    }
    found = await _fails(DuplicateInvoiceRule, payload)
    assert sorted((r.element_ref, r.details["problem"], r.severity.value) for r in found) == [
        ("2", "duplicate_number", "error"),
        ("4", "possible_duplicate", "warning"),
    ]


async def test_messages_exist_in_every_backend_language_with_the_same_placeholders() -> None:
    english = json.loads((_MESSAGES / "en.json").read_text(encoding="utf-8"))["payment_release"]
    for path in sorted(_MESSAGES.glob("*.json")):
        block = json.loads(path.read_text(encoding="utf-8")).get("payment_release")
        assert block is not None, path.name
        assert set(block) == set(english), path.name
        for key, pair in english.items():
            for part in ("fail", "suggestion"):
                text = block[key][part]
                assert text.strip(), (path.name, key, part)
                assert "—" not in text and "–" not in text, (path.name, key, part)
                for name in ("{" + p for p in pair[part].split("{")[1:]):
                    assert name.split("}")[0] + "}" in text, (path.name, key, part, name)


async def test_a_finding_reads_in_the_callers_language() -> None:
    payload = {"contracts": [_contract(invoices=[_inv("a", net_after="10"), _inv("b", net_after="5")])]}
    (en,) = await _fails(InvoiceSequenceRule, payload, "en")
    (de,) = await _fails(InvoiceSequenceRule, payload, "de")
    assert en.message != de.message and "SC-01" in de.message


async def test_v13_is_silent_on_retention_paid_back_after_its_events() -> None:
    payload = {
        "contracts": [
            _contract(
                status="completed",
                warranty_enabled=True,
                warranty_period_months=24,
                retention_held="0",
                invoices=[_inv("f", "final", retention="50")],
                postings=[
                    {
                        "id": "p1",
                        "retention_kind": "interim",
                        "event": "substantial_completion",
                        "event_on": "2026-01-15",
                        "posted_on": "2026-01-15",
                        "amount": "100",
                    },
                    {
                        "id": "p2",
                        "retention_kind": "warranty",
                        "event": "defects_period_end",
                        "event_on": "2026-01-15",
                        "posted_on": "2028-01-15",
                        "amount": "50",
                    },
                ],
            )
        ]
    }
    assert await _fails(RetentionTermsRule, payload) == []
