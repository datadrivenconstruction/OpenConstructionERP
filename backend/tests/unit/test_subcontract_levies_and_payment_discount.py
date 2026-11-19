"""Levies, retention and payment discount on a subcontractor invoice, from the worked examples.

Example 1 of the subcontractor award domain: contract sum 400,008.60, levies
0.3 + 0.5 + 0.4 = 1.2 %, retention 10 % per payment capped at 5 % of the
contract sum (20,000.43), first invoice 120,000.00, payment discount 2 % in 14 days.
Retention and every levy are taken on the same gross amount, so their order does
not matter: 120,000.00 - 12,000.00 - 1,440.00 = 106,560.00 payable; the discount
is 2 % of that, 2,131.20, leaving 104,428.80.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.subcontractors.terms import (
    NET_AFTER_RETENTION,
    LevyTerm,
    PaymentTerms,
    build_deductions,
    retention_cap_amount,
)
from app.modules.subcontractors.terms_checks import (
    check_discount_reconciles,
    check_levies_reconcile,
    check_recipient_outside_radius,
)

D = Decimal

LEVIES = (
    LevyTerm(code="insurance", name="Construction insurance", rate_percent=D("0.3")),
    LevyTerm(code="cleaning", name="Site cleaning", rate_percent=D("0.5")),
    LevyTerm(code="power", name="Site power and water", rate_percent=D("0.4")),
)


def _terms(**over) -> PaymentTerms:
    base = {
        "retention_percent": D("10"),
        "retention_cap_amount": retention_cap_amount(D("400008.60"), D("5")),
        "payment_discount_percent": D("2"),
        "payment_discount_days": 14,
        "payment_discount_agreed": True,
        "levies": LEVIES,
    }
    base.update(over)
    return PaymentTerms(**base)


def test_retention_cap_is_five_percent_of_the_contract_sum() -> None:
    assert retention_cap_amount(D("400008.60"), D("5")) == D("20000.43")


def test_first_invoice_matches_the_worked_example() -> None:
    s = build_deductions(D("120000.00"), _terms(), invoice_date=date(2026, 3, 2), paid_on=date(2026, 3, 16))
    assert [line["amount"] for line in s["levies"]] == [D("360.00"), D("600.00"), D("480.00")]
    assert s["levies_total"] == D("1440.00")
    assert s["retention_base"] == D("120000.00")
    assert s["retention_amount"] == D("12000.00")
    assert s["payable"] == D("106560.00")
    assert s["payment_discount_amount"] == D("2131.20")
    assert s["payable_with_discount"] == D("104428.80")
    assert s["discount_due_date"] == date(2026, 3, 16)
    assert s["discount_applies"] is True
    assert s["amount_to_pay"] == D("104428.80")
    assert [line["kind"] for line in s["lines"]] == [
        "work_value",
        "retention",
        "levy",
        "levy",
        "levy",
        "payable",
        "payment_discount",
    ]
    assert check_levies_reconcile(s) == []
    assert check_discount_reconciles(s) == []


def test_late_payment_loses_the_discount() -> None:
    s = build_deductions(D("120000.00"), _terms(), invoice_date=date(2026, 3, 2), paid_on=date(2026, 3, 17))
    assert s["discount_applies"] is False
    assert s["amount_to_pay"] == D("106560.00")


def test_unpaid_invoice_offers_the_discount_but_does_not_take_it() -> None:
    s = build_deductions(D("120000.00"), _terms(), invoice_date=date(2026, 3, 2))
    assert s["discount_applies"] is None
    assert s["amount_to_pay"] == D("106560.00")
    assert s["payable_with_discount"] == D("104428.80")


def test_retention_stops_at_the_cap() -> None:
    s = build_deductions(D("120000.00"), _terms(), retained_to_date=D("12000.00"))
    assert s["retention_amount"] == D("8000.43")
    assert s["retention_capped"] is True
    assert s["payable"] == D("120000.00") - D("1440.00") - D("8000.43")


def test_a_levy_agreed_on_net_after_retention_takes_its_rate_of_gross_less_retention() -> None:
    on_net = tuple(
        LevyTerm(code=lv.code, name=lv.name, rate_percent=lv.rate_percent, levy_base=NET_AFTER_RETENTION)
        for lv in LEVIES
    )
    s = build_deductions(D("120000.00"), _terms(levies=on_net))
    assert s["retention_amount"] == D("12000.00")
    # 1.2 % of 108,000.00 = 324 + 540 + 432
    assert s["levies_total"] == D("1296.00")
    assert s["payable"] == D("106704.00")
    assert check_levies_reconcile(s) == []


def test_final_account_levy_is_charged_once_at_final_account() -> None:
    once = LevyTerm(code="waste", name="Waste", rate_percent=D("1"), applies_at="final_account")
    fixed = LevyTerm(code="facilities", name="Facilities", basis="fixed", fixed_amount=D("250"))
    terms = _terms(levies=(*LEVIES, once, fixed), payment_discount_percent=None)
    interim = build_deductions(D("120000.00"), terms)
    final = build_deductions(D("120000.00"), terms, final_account=True)
    assert interim["levies_total"] == D("1690.00")
    assert final["levies_total"] == D("2890.00")
    assert interim["payment_discount_amount"] == D("0")


def test_a_statement_that_does_not_add_up_is_found() -> None:
    s = build_deductions(D("120000.00"), _terms())
    tampered = {**s, "payable": D("107000.00")}
    assert check_levies_reconcile(tampered)[0].params == {"expected": "106560.00", "payable": "107000.00"}
    wrong_discount = {**s, "payment_discount_amount": D("2000.00")}
    assert check_discount_reconciles(wrong_discount)[0].params["expected"] == "2131.20"


def test_recipient_outside_radius_is_flagged_with_its_distance() -> None:
    payload = {
        "radius_km": "50",
        "recipients": [
            {"id": "a", "name": "Near GmbH", "distance_km": "12.4"},
            {"id": "b", "name": "Far AG", "distance_km": "83.2"},
            {"id": "c", "name": "No address KG", "distance_km": None},
        ],
    }
    findings = check_recipient_outside_radius(payload)
    assert [f.element_ref for f in findings] == ["Far AG"]
    assert findings[0].params == {"distance": "83", "radius": "50"}


# ── German pack rules and pack defaults ──────────────────────────────────


def _validate(rule, payload):
    import asyncio

    from app.core.validation.engine import ValidationContext

    return asyncio.run(rule.validate(ValidationContext(data=payload, metadata={"locale": "en"})))


def test_vob_retention_maximum_comes_from_the_pack() -> None:
    from app.modules.dach_pack.subcontract_rules import vob_retention_maximum

    maximum, statute = vob_retention_maximum()
    assert maximum == D("10")
    assert "17" in statute


def test_german_retention_above_ten_percent_warns_only_in_germany() -> None:
    from app.modules.dach_pack.subcontract_rules import DeRetentionOverVobCap

    s = build_deductions(D("120000.00"), _terms(retention_percent=D("12")))
    payload = {**s, "country_code": "DE", "element_ref": "PA-001"}
    results = _validate(DeRetentionOverVobCap(), payload)
    assert [r.passed for r in results] == [False]
    assert "12" in results[0].message and "10" in results[0].message
    assert _validate(DeRetentionOverVobCap(), {**payload, "country_code": "AT"}) == []
    ok = {**build_deductions(D("120000.00"), _terms()), "country_code": "DE"}
    assert [r.passed for r in _validate(DeRetentionOverVobCap(), ok)] == [True]


def test_german_payment_discount_without_agreement_warns() -> None:
    from app.modules.dach_pack.subcontract_rules import DePaymentDiscountUnagreed

    s = build_deductions(D("120000.00"), _terms(payment_discount_agreed=False))
    results = _validate(DePaymentDiscountUnagreed(), {**s, "country_code": "DE"})
    assert [r.passed for r in results] == [False]
    assert "2131.20" in results[0].message
    agreed = build_deductions(D("120000.00"), _terms())
    assert [r.passed for r in _validate(DePaymentDiscountUnagreed(), {**agreed, "country_code": "DE"})] == [True]


def test_pack_levy_defaults_follow_the_market_and_carry_no_rate() -> None:
    from app.modules.subcontractors.terms_service import pack_levy_defaults

    extra = [
        (
            "germany-de",
            "DE",
            {
                "levies": [
                    {"code": "bauwesenversicherung", "name": {"de": "Bauwesenversicherung", "en": "CAR insurance"}}
                ]
            },
        )
    ]
    de = pack_levy_defaults(["DE"], "de", extra=extra)
    assert [(d.code, d.name, d.pack) for d in de] == [("bauwesenversicherung", "Bauwesenversicherung", "germany-de")]
    assert pack_levy_defaults(["FR"], "en", extra=extra) == []
    assert pack_levy_defaults(["*"], "en", extra=extra) == []
    assert "default_percent" not in de[0].model_dump()


def test_germany_pack_ships_levy_names_without_rates() -> None:
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "packs/germany-de/src/openconstructionerp_germany_de/subcontract_levies.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["country"] == "DE"
    assert len(data["levies"]) >= 5
    for levy in data["levies"]:
        assert set(levy["name"]) >= {"de", "en"}
        assert not any(key in levy for key in ("rate", "rate_percent", "default_percent"))
