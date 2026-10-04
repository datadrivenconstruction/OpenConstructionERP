# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ireland and Hungary move construction VAT to the customer, and the catalogue says how.

Both countries run a domestic reverse charge on construction between businesses,
and both put a sentence on the invoice that is the whole of the obligation. A
catalogue without them sends an Irish subcontractor or a Hungarian contractor to
the reverse-charge screen with nothing to copy onto the invoice, and the
validation rule then fails the invoice for missing wording it could never have
known.
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.tax_withholding.data import REVERSE_CHARGE_RULES, reverse_charge_rule
from app.modules.tax_withholding.router import list_reverse_charge_rules
from app.modules.tax_withholding.schemas import ReverseChargeRuleResponse


def test_ireland_names_the_principal_contractor_on_the_invoice() -> None:
    rule = reverse_charge_rule("IE_RCT_REVERSE_CHARGE")
    assert rule is not None
    assert rule["country_code"] == "IE"
    assert "16(3)" in rule["legal_reference"]
    assert "accounted for by the Principal Contractor" in rule["invoice_wording"]


def test_hungary_prints_the_statutory_words_with_their_accents() -> None:
    rule = reverse_charge_rule("HU_FORDITOTT_ADOZAS_EPITES")
    assert rule is not None
    assert rule["country_code"] == "HU"
    assert "142. § (1) b)" in rule["legal_reference"]
    # The Act asks for these two words. An ASCII spelling is a different
    # string and not what the authority reads for.
    assert rule["invoice_wording"].lower() == "fordított adózás"


def test_every_rule_code_is_unique_and_upper_case() -> None:
    codes = [rule["rule_code"] for rule in REVERSE_CHARGE_RULES]
    assert len(codes) == len(set(codes))
    for code in codes:
        assert code == code.upper(), code


def test_every_rule_country_is_an_iso_code_its_code_starts_with() -> None:
    for rule in REVERSE_CHARGE_RULES:
        assert len(rule["country_code"]) == 2 and rule["country_code"].isupper(), rule["rule_code"]
        assert rule["rule_code"].startswith(f"{rule['country_code']}_"), rule["rule_code"]


def test_every_rule_fits_the_response_schema() -> None:
    for rule in REVERSE_CHARGE_RULES:
        ReverseChargeRuleResponse(**rule)


@pytest.mark.parametrize(
    ("country", "expected"), [("IE", {"IE_RCT_REVERSE_CHARGE"}), ("hu", {"HU_FORDITOTT_ADOZAS_EPITES"})]
)
def test_the_endpoint_filters_to_one_country(country: str, expected: set[str]) -> None:
    rules = asyncio.run(list_reverse_charge_rules(country_code=country))
    assert {rule.rule_code for rule in rules} == expected


def test_the_endpoint_without_a_country_lists_all_six() -> None:
    rules = asyncio.run(list_reverse_charge_rules(country_code=None))
    assert {rule.country_code for rule in rules} == {"GB", "DE", "ES", "FR", "IE", "HU"}
