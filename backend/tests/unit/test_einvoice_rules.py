# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠EN 16931 rule engine tests.

These assert on rule identifiers (``BR-61``), never on the prose of a message.
A message is a translation-and-wording concern that changes; the rule it stands
for is the statutory fact and is what a receiver's validator reports.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal, build_cii_xml
from app.modules.einvoice.rules import (
    _DOCUMENT_MINOR_UNITS,
    FATAL,
    WARNING,
    check,
    money_decimals,
    violation_ids,
)


def _party(**over: object) -> Party:
    base = {
        "name": "Bau GmbH",
        "country_code": "DE",
        "vat_id": "DE123456789",
        "line1": "Baustrasse 1",
        "postcode": "10115",
        "city": "Berlin",
    }
    base.update(over)
    return Party(**base)  # type: ignore[arg-type]


def _invoice(**over: object) -> EInvoice:
    """A minimal invoice that is EN 16931 clean, so a test can break one thing."""
    lines = [
        EInvoiceLine(
            line_id="1",
            name="Concrete C25/30",
            quantity=Decimal("10"),
            unit="m3",
            net_unit_price=Decimal("100"),
            line_net_amount=Decimal("1000"),
            vat_rate=Decimal("19"),
            vat_category="S",
        )
    ]
    base: dict[str, object] = {
        "profile": "zugferd",
        "invoice_number": "RE-2026-001",
        "issue_date": "2026-08-11",
        "currency": "EUR",
        "seller": _party(),
        "buyer": _party(name="Stadtwerke AG", vat_id=None),
        "lines": lines,
        "tax_subtotals": [
            TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000"), tax_amount=Decimal("190"))
        ],
        "line_total": Decimal("1000"),
        "tax_basis_total": Decimal("1000"),
        "tax_total": Decimal("190"),
        "grand_total": Decimal("1190"),
        "due_payable": Decimal("1190"),
    }
    base.update(over)
    return EInvoice(**base)  # type: ignore[arg-type]


# ── the baseline is clean ─────────────────────────────────────────────────────


def test_reference_invoice_has_no_fatal_violations():
    assert [v for v in check(_invoice()) if v.severity == FATAL] == []


# ── BR-61: credit transfer needs a payment account (BT-84) ────────────────────


def test_br_61_credit_transfer_without_account_is_fatal():
    """The live defect: payment means 30 with no IBAN violates BR-61."""
    inv = _invoice(payment_means_code="30")
    assert "BR-61" in violation_ids(check(inv))


def test_br_61_satisfied_by_an_iban():
    inv = _invoice(payment_means_code="30", payee_iban="DE02120300000000202051")
    assert "BR-61" not in violation_ids(check(inv))


def test_br_61_does_not_fire_when_the_instrument_is_undefined():
    """Code 1 makes no credit-transfer claim, so BT-84 is not required."""
    assert "BR-61" not in violation_ids(check(_invoice(payment_means_code="1")))


def test_default_payment_means_makes_no_unbacked_credit_transfer_claim():
    """A bare invoice must not claim a credit transfer it cannot substantiate."""
    inv = _invoice()
    assert inv.payment_means_code == "1"
    assert "BR-61" not in violation_ids(check(inv))


def test_missing_iban_is_advised_but_not_fatal():
    ids = {v.rule_id: v for v in check(_invoice())}
    assert "OCE-PAY-01" in ids
    assert ids["OCE-PAY-01"].severity == WARNING


# ── BR-53: a VAT accounting currency needs its VAT total (BT-111) ─────────────


def test_br_53_tax_currency_without_its_own_vat_total_is_fatal():
    """Two amounts each carrying a currency: BT-6 is meaningless without BT-111."""
    assert "BR-53" in violation_ids(check(_invoice(tax_currency="USD")))


def test_br_53_satisfied_when_the_vat_total_in_tax_currency_is_given():
    inv = _invoice(tax_currency="USD", tax_total_in_tax_currency=Decimal("205.20"))
    assert "BR-53" not in violation_ids(check(inv))


def test_br_53_does_not_fire_when_tax_currency_equals_invoice_currency():
    assert "BR-53" not in violation_ids(check(_invoice(tax_currency="EUR")))


# ── VAT category rules ────────────────────────────────────────────────────────


def test_br_s_5_standard_rated_line_needs_a_positive_rate():
    inv = _invoice(
        lines=[EInvoiceLine("1", "Item", Decimal("1"), "pcs", Decimal("1000"), Decimal("1000"), Decimal("0"), "S")],
        tax_subtotals=[TaxSubtotal("S", Decimal("0"), Decimal("1000"), Decimal("0"))],
        tax_total=Decimal("0"),
        grand_total=Decimal("1000"),
        due_payable=Decimal("1000"),
    )
    assert "BR-S-5" in violation_ids(check(inv))


@pytest.mark.parametrize(("category", "rule"), [("Z", "BR-Z-5"), ("E", "BR-E-5"), ("AE", "BR-AE-5")])
def test_zero_rated_categories_reject_a_nonzero_rate(category: str, rule: str):
    inv = _invoice(
        lines=[
            EInvoiceLine("1", "Item", Decimal("1"), "pcs", Decimal("1000"), Decimal("1000"), Decimal("19"), category)
        ],
        tax_subtotals=[TaxSubtotal(category, Decimal("19"), Decimal("1000"), Decimal("190"))],
    )
    assert rule in violation_ids(check(inv))


def test_br_s_1_line_category_absent_from_the_breakdown():
    """A standard-rated line with no standard-rated VAT breakdown group."""
    inv = _invoice(
        tax_subtotals=[TaxSubtotal("Z", Decimal("0"), Decimal("1000"), Decimal("0"))],
        tax_total=Decimal("0"),
        grand_total=Decimal("1000"),
        due_payable=Decimal("1000"),
    )
    assert "BR-S-1" in violation_ids(check(inv))


def test_br_co_17_vat_amount_must_follow_from_basis_and_rate():
    inv = _invoice(
        tax_subtotals=[TaxSubtotal("S", Decimal("19"), Decimal("1000"), Decimal("150"))],
        tax_total=Decimal("150"),
        grand_total=Decimal("1150"),
        due_payable=Decimal("1150"),
    )
    assert "BR-CO-17" in violation_ids(check(inv))


def test_br_s_8_breakdown_basis_must_equal_the_lines_at_that_rate():
    """Two rates, but the 19% group claims the whole document as its basis."""
    inv = _invoice(
        lines=[
            EInvoiceLine("1", "A", Decimal("1"), "pcs", Decimal("1000"), Decimal("1000"), Decimal("19"), "S"),
            EInvoiceLine("2", "B", Decimal("1"), "pcs", Decimal("500"), Decimal("500"), Decimal("7"), "S"),
        ],
        tax_subtotals=[TaxSubtotal("S", Decimal("19"), Decimal("1500"), Decimal("285"))],
        line_total=Decimal("1500"),
        tax_basis_total=Decimal("1500"),
        tax_total=Decimal("285"),
        grand_total=Decimal("1785"),
        due_payable=Decimal("1785"),
    )
    assert "BR-S-8" in violation_ids(check(inv))


def test_a_correct_two_rate_invoice_is_clean():
    inv = _invoice(
        lines=[
            EInvoiceLine("1", "A", Decimal("1"), "pcs", Decimal("1000"), Decimal("1000"), Decimal("19"), "S"),
            EInvoiceLine("2", "B", Decimal("1"), "pcs", Decimal("500"), Decimal("500"), Decimal("7"), "S"),
        ],
        tax_subtotals=[
            TaxSubtotal("S", Decimal("19"), Decimal("1000"), Decimal("190")),
            TaxSubtotal("S", Decimal("7"), Decimal("500"), Decimal("35")),
        ],
        line_total=Decimal("1500"),
        tax_basis_total=Decimal("1500"),
        tax_total=Decimal("225"),
        grand_total=Decimal("1725"),
        due_payable=Decimal("1725"),
    )
    assert [v for v in check(inv) if v.severity == FATAL] == []


# ── totals ────────────────────────────────────────────────────────────────────


def test_br_co_10_line_total_must_equal_the_sum_of_lines():
    assert "BR-CO-10" in violation_ids(check(_invoice(line_total=Decimal("999"))))


def test_br_co_14_vat_total_must_equal_the_sum_of_the_breakdown():
    inv = _invoice(tax_total=Decimal("200"), grand_total=Decimal("1200"), due_payable=Decimal("1200"))
    assert "BR-CO-14" in violation_ids(check(inv))


def test_br_co_15_grand_total_must_equal_net_plus_vat():
    assert "BR-CO-15" in violation_ids(check(_invoice(grand_total=Decimal("1000"))))


def test_br_co_16_amount_due_must_deduct_the_prepaid_amount():
    assert "BR-CO-16" in violation_ids(check(_invoice(prepaid_amount=Decimal("100"))))


# ── identity ──────────────────────────────────────────────────────────────────


def test_br_co_9_vat_identifier_needs_a_country_prefix():
    assert "BR-CO-9" in violation_ids(check(_invoice(seller=_party(vat_id="123456789"))))


def test_br_co_26_seller_needs_some_registration():
    seller = _party(vat_id=None, tax_number=None, legal_id=None)
    assert "BR-CO-26" in violation_ids(check(_invoice(seller=seller)))


def test_br_16_an_invoice_needs_a_line():
    inv = _invoice(
        lines=[],
        line_total=Decimal("0"),
        tax_basis_total=Decimal("0"),
        tax_total=Decimal("0"),
        grand_total=Decimal("0"),
        due_payable=Decimal("0"),
        tax_subtotals=[],
    )
    assert "BR-16" in violation_ids(check(inv))


# ── profile rules ─────────────────────────────────────────────────────────────


def test_br_de_15_xrechnung_requires_the_leitweg_id():
    assert "BR-DE-15" in violation_ids(check(_invoice(profile="xrechnung")))


def test_br_de_15_satisfied_by_a_buyer_reference():
    inv = _invoice(profile="xrechnung", buyer_reference="991-01234-56")
    assert "BR-DE-15" not in violation_ids(check(inv))


def test_peppol_accepts_an_order_reference_instead_of_a_buyer_reference():
    inv = _invoice(profile="peppol", order_reference="PO-77")
    assert "PEPPOL-EN16931-R003" not in violation_ids(check(inv))


def test_peppol_requires_one_of_the_two_references():
    assert "PEPPOL-EN16931-R003" in violation_ids(check(_invoice(profile="peppol")))


# ── currency minor units ──────────────────────────────────────────────────────


def test_zero_decimal_currency_prints_no_cents():
    assert money_decimals("JPY") == 0
    assert money_decimals("CLP") == 0


def test_three_decimal_currency_is_capped_at_two_for_en16931():
    """BR-DEC caps document amounts at two decimals, whatever the currency does."""
    assert money_decimals("KWD") == 2


def test_unknown_currency_falls_back_to_two():
    assert money_decimals("ZZZ") == 2


def test_a_yen_invoice_renders_whole_amounts():
    inv = _invoice(
        currency="JPY",
        lines=[EInvoiceLine("1", "A", Decimal("1"), "pcs", Decimal("1000"), Decimal("1000"), Decimal("10"), "S")],
        tax_subtotals=[TaxSubtotal("S", Decimal("10"), Decimal("1000"), Decimal("100"))],
        tax_total=Decimal("100"),
        grand_total=Decimal("1100"),
        due_payable=Decimal("1100"),
    )
    xml = build_cii_xml(inv).decode("utf-8")
    assert "<ram:GrandTotalAmount>1100</ram:GrandTotalAmount>" in xml
    assert "1100.00" not in xml


# ── the sixteen codes whose two registers are said to disagree ────────────────
#
# ISO 4217 (list-one.xml, Pblshd 2026-01-01) against CLDR 49. One case per
# code, so that a change to any single one of them has to be made on purpose.
# The expected values are the ones the writer already produced; these tests
# exist to stop them drifting, not to re-derive them.


_SETTLED_MINOR_UNIT_CASES = [
    # ISO 2, CLDR 0. Two is what shipped: from the registry for COP and MGA,
    # and by a lookup miss landing on the default for the other ten.
    ("AFN", 2),
    ("ALL", 2),
    ("COP", 2),
    ("IRR", 2),
    ("KPW", 2),
    ("LAK", 2),
    ("LBP", 2),
    ("MGA", 2),
    ("MMK", 2),
    ("SOS", 2),
    ("SYP", 2),
    ("YER", 2),
    # ISO 2, CLDR 2: not a disagreement at all. Only CLDR's cashDigits is 0,
    # and that is about handing over banknotes, not writing a total.
    ("PKR", 2),
    # ISO 3, CLDR 0: trimmed to 2 by the BR-DEC cap, exactly like KWD.
    ("IQD", 2),
    # ISO 2, CLDR 0. Decided as zero, and not by preferring one register over
    # the other: the fillér left circulation in 1999 and the sen with it, so
    # there is no subunit for a second digit to mean. Two decimals here would
    # not be a finer forint, only two digits no payment can carry.
    ("HUF", 0),
    ("IDR", 0),
]


@pytest.mark.parametrize(("code", "expected"), _SETTLED_MINOR_UNIT_CASES)
def test_disputed_currency_writes_its_decided_minor_unit(code, expected):
    assert money_decimals(code) == expected


def test_every_disputed_code_is_decided_explicitly_and_none_is_left_to_fallback():
    """The table and the decided set are the SAME set, in both directions.

    Two different holes are being closed here and only one of them is about
    values. A code absent from ``_DOCUMENT_MINOR_UNITS`` would still return 2
    through the fallback and every value assertion above would still pass, so
    coverage has to be asserted separately from the values. That is the first
    direction, and it was the only one asserted before.

    The second matters more now. HUF and IDR used to sit in the table behind an
    "undecided" marker, which meant the table could legitimately hold a code
    that no case had ruled on. With the marker gone that state no longer
    exists, so the containment can be an equality: a code added to the document
    table without a decision recorded beside it here fails this test rather
    than shipping quietly with whatever count its author happened to type.
    """
    decided = {code for code, _ in _SETTLED_MINOR_UNIT_CASES}
    assert decided == set(_DOCUMENT_MINOR_UNITS)
