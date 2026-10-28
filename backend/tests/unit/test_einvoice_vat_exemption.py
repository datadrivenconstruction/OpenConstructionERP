# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A zero-VAT document must say why, or say that it is saying nothing.

Two families of findings, one defect. First, the EN 16931 exemption-reason
rules: a VAT breakdown group in an exempting category (E, AE, K, G, O) must
carry an exemption reason text (BT-120) or code (BT-121), and a standard or
zero-rated group (S, Z) must not - each family under the identifier a
receiver's validator reports (BR-E-10, BR-AE-10, BR-IC-10, BR-G-10, BR-O-10,
BR-S-10, BR-Z-10). Second, the house advisory OCE-VAT-01: when an invoice
carries no VAT information at all, the builder infers a 0% rate and category Z,
and before this advisory the check stayed green - a German progress invoice
with a forgotten tax amount exported as zero rated with no finding anywhere.

The dict path (``violations_for``) is used throughout because a rule reachable
only from a hand-built model is unreachable from every caller that exists.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.modules.einvoice import build_einvoice, render_einvoice, violations_for
from app.modules.einvoice.cii import RAM
from app.modules.einvoice.rules import FATAL, WARNING, violation_ids
from app.modules.einvoice.ubl import CBC


def _invoice(**einvoice_overrides) -> dict:
    """An otherwise complete invoice so only the VAT shape under test can fail."""
    meta = {
        "seller": {
            "name": "Global Build Ltd",
            "vat_id": "IE1234567FA",
            "city": "Dublin",
            "country_code": "IE",
        },
        "buyer": {"name": "City Works", "city": "Cork", "country_code": "IE"},
        "buyer_reference": "PO-99887",
    }
    meta.update(einvoice_overrides)
    return {
        "invoice_number": "INV-2026-0055",
        "invoice_direction": "receivable",
        "invoice_date": "2026-07-05",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("0"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("1000.00"),
        "metadata": {"einvoice": meta},
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Excavation",
            "unit": "m3",
            "quantity": Decimal("50"),
            "unit_rate": Decimal("20"),
            "amount": Decimal("1000.00"),
        }
    ]


def _found(invoice: dict, *, profile: str = "en16931") -> list:
    return violations_for(invoice=invoice, line_items=_lines(), profile=profile, defaults={})


# ── exempting categories must carry a reason (BR-E-10 family) ────────────────


@pytest.mark.parametrize(
    ("category", "rule_id"),
    [
        ("E", "BR-E-10"),
        ("AE", "BR-AE-10"),
        ("K", "BR-IC-10"),
        ("G", "BR-G-10"),
        ("O", "BR-O-10"),
    ],
)
def test_an_exempting_category_without_a_reason_is_fatal(category: str, rule_id: str):
    found = _found(_invoice(vat_category=category, vat_rate="0"))
    fatal_ids = {v.rule_id for v in found if v.severity == FATAL}
    assert rule_id in fatal_ids, sorted(fatal_ids)


@pytest.mark.parametrize("field", ["vat_exemption_reason", "vat_exemption_reason_code"])
def test_a_reason_text_or_code_satisfies_the_rule(field: str):
    value = "Reverse charge" if field == "vat_exemption_reason" else "VATEX-EU-AE"
    found = _found(_invoice(vat_category="AE", vat_rate="0", **{field: value}))
    assert "BR-AE-10" not in violation_ids(found)


def test_the_exemption_finding_names_the_invoice_and_both_terms():
    """The reason lives on the invoice (metadata), not in the settings."""
    from app.modules.einvoice.rules import _INVOICE_HOME

    found = _found(_invoice(vat_category="E", vat_rate="0"))
    hit = [v for v in found if v.rule_id == "BR-E-10"]
    assert hit, violation_ids(found)
    assert hit[0].term == "BT-120"
    assert "BT-121" in hit[0].message
    assert _INVOICE_HOME in hit[0].message
    assert "e-invoice settings" not in hit[0].message


# ── S and Z must not carry a reason (BR-S-10, BR-Z-10) ───────────────────────


def test_a_standard_rated_group_with_a_reason_is_fatal():
    inv = _invoice(vat_rate="19", vat_exemption_reason="Not actually exempt")
    inv["tax_amount"] = Decimal("190.00")
    inv["amount_total"] = Decimal("1190.00")
    found = _found(inv)
    fatal_ids = {v.rule_id for v in found if v.severity == FATAL}
    assert "BR-S-10" in fatal_ids, sorted(fatal_ids)


def test_a_zero_rated_group_with_a_reason_is_fatal():
    found = _found(_invoice(vat_category="Z", vat_rate="0", vat_exemption_reason="Zero rated"))
    fatal_ids = {v.rule_id for v in found if v.severity == FATAL}
    assert "BR-Z-10" in fatal_ids, sorted(fatal_ids)


def test_an_explicit_zero_rated_invoice_without_a_reason_is_clean():
    """Z is a legitimate declaration and needs no justification (BR-Z-10 forbids one)."""
    found = _found(_invoice(vat_category="Z", vat_rate="0"))
    ids = violation_ids(found)
    assert "BR-Z-10" not in ids
    assert "OCE-VAT-01" not in ids


# ── the reason must reach both syntaxes ──────────────────────────────────────


def test_the_reason_reaches_the_cii_document():
    inv = _invoice(
        vat_category="AE",
        vat_rate="0",
        vat_exemption_reason="Reverse charge",
        vat_exemption_reason_code="VATEX-EU-AE",
    )
    ei = build_einvoice(invoice=inv, line_items=_lines(), profile="en16931", defaults={})
    _name, _media, xml = render_einvoice(invoice=inv, line_items=_lines(), profile="en16931", defaults={})
    root = ET.fromstring(xml)
    assert ei.tax_subtotals[0].exemption_reason == "Reverse charge"
    reasons = [el.text for el in root.findall(f".//{{{RAM}}}ExemptionReason")]
    codes = [el.text for el in root.findall(f".//{{{RAM}}}ExemptionReasonCode")]
    assert reasons == ["Reverse charge"]
    assert codes == ["VATEX-EU-AE"]


def test_the_reason_reaches_the_ubl_document():
    inv = _invoice(
        vat_category="AE",
        vat_rate="0",
        vat_exemption_reason="Reverse charge",
        vat_exemption_reason_code="VATEX-EU-AE",
    )
    _name, _media, xml = render_einvoice(invoice=inv, line_items=_lines(), profile="ubl", defaults={})
    root = ET.fromstring(xml)
    reasons = [el.text for el in root.findall(f".//{{{CBC}}}TaxExemptionReason")]
    codes = [el.text for el in root.findall(f".//{{{CBC}}}TaxExemptionReasonCode")]
    assert reasons == ["Reverse charge"]
    assert codes == ["VATEX-EU-AE"]


# ── OCE-VAT-01: inferred zero-rating is no longer silent ─────────────────────


def test_an_invoice_with_no_vat_information_raises_the_advisory():
    """tax_amount=0 and no declared rate or category anywhere: the builder
    falls back to category Z, and before this advisory the check said nothing.
    """
    found = _found(_invoice())
    hit = [v for v in found if v.rule_id == "OCE-VAT-01"]
    assert hit, violation_ids(found)
    assert hit[0].severity == WARNING


def test_the_advisory_does_not_block_the_export():
    found = _found(_invoice())
    assert all(v.severity != FATAL for v in found), [f"{v.rule_id}: {v.message}" for v in found]


@pytest.mark.parametrize(
    "declaration",
    [
        {"vat_rate": "0"},
        {"vat_category": "Z"},
    ],
)
def test_an_explicit_declaration_silences_the_advisory(declaration: dict):
    found = _found(_invoice(**declaration))
    assert "OCE-VAT-01" not in violation_ids(found)


def test_a_positive_tax_amount_silences_the_advisory():
    inv = _invoice()
    inv["tax_amount"] = Decimal("190.00")
    inv["amount_total"] = Decimal("1190.00")
    assert "OCE-VAT-01" not in violation_ids(_found(inv))


def test_a_line_level_rate_silences_the_advisory():
    lines = _lines()
    lines[0]["vat_rate"] = Decimal("0")
    lines[0]["vat_category"] = "Z"
    found = violations_for(invoice=_invoice(), line_items=lines, profile="en16931", defaults={})
    assert "OCE-VAT-01" not in violation_ids(found)


def test_a_zero_value_invoice_does_not_raise_the_advisory():
    """Nothing is billed, so there is no VAT question to leave unanswered."""
    inv = _invoice()
    inv["amount_subtotal"] = Decimal("0")
    inv["amount_total"] = Decimal("0")
    lines = [dict(_lines()[0], amount=Decimal("0"), unit_rate=Decimal("0"))]
    found = violations_for(invoice=inv, line_items=lines, profile="en16931", defaults={})
    assert "OCE-VAT-01" not in violation_ids(found)
