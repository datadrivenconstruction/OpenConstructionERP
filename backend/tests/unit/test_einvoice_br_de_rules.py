# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The XRechnung rules beyond the postal address, checked against the artefact.

The address half (BR-DE-3/4/8/9) lives in ``test_einvoice_br_de_address``. This
file covers the rest of what a German receiver applies to a document this
platform can actually produce:

    BR-DE-2      the SELLER CONTACT group (BG-6) exists
    BR-DE-5/6/7  its contact point, telephone and email (BT-41, BT-42, BT-43)
    BR-DE-16     a seller tax registration, on stricter terms than BR-CO-26
    BR-DE-23-a   a credit transfer names the account (BG-17)
    BR-DE-24-a   a card payment would need BG-18, which this writer cannot make
    BR-DE-25-a   a direct debit would need BG-19, likewise
    BR-DE-17     the document type code, advisory
    BR-DE-27/28  telephone and email shape, advisory

Verified against itplr-kosit/xrechnung-schematron v2.5.0, the XRechnung 3.0.2
artefact our CustomizationID claims, in
``src/validation/schematron/cii/XRechnung-CII-validation.sch``.

Severity is asserted and not assumed. Six of these are ``flag="fatal"`` and
four are ``flag="warning"``; raising a warning to fatal would block a document
KoSIT accepts, which departs from the rule text exactly as much as ignoring it
does. Every fatal test asserts the whole fatal set rather than membership, so a
one-field edit produces a one-rule answer or the test has caught something else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.einvoice.cii import (
    EInvoice,
    EInvoiceError,
    EInvoiceLine,
    Party,
    TaxSubtotal,
    build_cii_xml,
)
from app.modules.einvoice.rules import DE_INVOICE_TYPE_CODES, FATAL, WARNING, check

XRECHNUNG = "xrechnung"


def _party(**over: object) -> Party:
    base = {
        "name": "Nordbau GmbH",
        "country_code": "DE",
        "vat_id": "DE123456789",
        "line1": "Baustrasse 1",
        "postcode": "10115",
        "city": "Berlin",
        "contact_name": "Anke Reimann",
        "contact_phone": "+49 30 1234560",
        "contact_email": "rechnung@nordbau.example",
    }
    base.update(over)
    return Party(**base)  # type: ignore[arg-type]


def _invoice(**over: object) -> EInvoice:
    """An invoice that is XRechnung clean, so a test can break exactly one thing."""
    base: dict[str, object] = {
        "profile": XRECHNUNG,
        "invoice_number": "RE-2026-001",
        "issue_date": "2026-08-12",
        "currency": "EUR",
        "seller": _party(),
        "buyer": _party(name="Stadtwerke Muenster AG", vat_id=None, city="Muenster", postcode="48143"),
        "lines": [
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
        ],
        "tax_subtotals": [
            TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000"), tax_amount=Decimal("190"))
        ],
        "line_total": Decimal("1000"),
        "tax_basis_total": Decimal("1000"),
        "tax_total": Decimal("190"),
        "grand_total": Decimal("1190"),
        "due_payable": Decimal("1190"),
        "buyer_reference": "04011000-1234512345-06",
    }
    base.update(over)
    return EInvoice(**base)  # type: ignore[arg-type]


def _fatal(inv: EInvoice) -> set[str]:
    return {v.rule_id for v in check(inv) if v.severity == FATAL}


def _warnings(inv: EInvoice) -> set[str]:
    """Only the German advisories.

    The baseline names no bank account, which draws the house advisory
    OCE-PAY-01. That is a true finding about this fixture and says nothing about
    the rule under test, so it is filtered out here rather than papered over by
    putting an IBAN on a document that does not need one.
    """
    return {v.rule_id for v in check(inv) if v.severity == WARNING and v.rule_id.startswith("BR-DE")}


def test_the_baseline_is_clean_which_is_what_makes_a_one_rule_answer_meaningful():
    assert _fatal(_invoice()) == set()


# ── BG-6, the seller contact ─────────────────────────────────────────────────


def test_a_seller_with_no_contact_at_all_is_one_finding_and_not_four():
    """BR-DE-5/6/7 sit on the group, so an absent group cannot also fail them.

    In the schematron the three field asserts have the context
    ``SellerTradeParty/ram:DefinedTradeContact``. A rule whose context does not
    match never fires, so the receiver reports BR-DE-2 alone. Reporting four
    findings here would tell the user to fill three fields on a group that does
    not exist yet, and would not match the report they get back.
    """
    inv = _invoice(seller=_party(contact_name=None, contact_phone=None, contact_email=None))
    assert _fatal(inv) == {"BR-DE-2"}


@pytest.mark.parametrize(
    ("rule_id", "field"),
    [
        ("BR-DE-5", "contact_name"),
        ("BR-DE-6", "contact_phone"),
        ("BR-DE-7", "contact_email"),
    ],
)
def test_a_missing_contact_field_is_fatal_and_is_the_only_finding(rule_id: str, field: str):
    inv = _invoice(seller=_party(**{field: None}))
    assert _fatal(inv) == {rule_id}


@pytest.mark.parametrize(
    ("rule_id", "field"),
    [
        ("BR-DE-5", "contact_name"),
        ("BR-DE-6", "contact_phone"),
        ("BR-DE-7", "contact_email"),
    ],
)
def test_a_blank_contact_field_fails_exactly_as_an_absent_one(rule_id: str, field: str):
    """KoSIT asserts on ``normalize-space``, so spaces are not a value."""
    inv = _invoice(seller=_party(**{field: "   "}))
    assert _fatal(inv) == {rule_id}


def test_a_contact_point_alone_satisfies_br_de_5():
    """BR-DE-5 accepts a person name or a department name, and one is enough.

    The assert is ``(ram:PersonName, ram:DepartmentName)[normalize-space(.)]``,
    a list of two nodes of which any non-blank one passes. This platform stores
    a single contact point and writes it as the person name, so a
    department-only contact is not expressible here. That is a gap in what a
    user can say, not a stricter reading of the rule: nothing a user can enter
    is rejected that KoSIT would have taken.
    """
    inv = _invoice(seller=_party(contact_name="Rechnungsstelle"))
    assert _fatal(inv) == set()


def test_the_contact_findings_name_the_settings_which_is_where_the_fields_live():
    """A finding is a remedy. All three fields are columns on the standing row."""
    inv = _invoice(seller=_party(contact_name=None, contact_phone=None, contact_email=None))
    messages = [v.message for v in check(inv) if v.rule_id == "BR-DE-2"]
    assert messages and all("e-invoice settings" in m for m in messages)


def test_each_contact_finding_carries_the_business_term_a_receiver_would_quote():
    inv = _invoice(seller=_party(contact_name=None, contact_phone=None, contact_email=None))
    inv.seller.contact_email = "rechnung@nordbau.example"
    terms = {v.rule_id: v.term for v in check(inv) if v.severity == FATAL}
    assert terms == {"BR-DE-5": "BT-41", "BR-DE-6": "BT-42"}


# ── BR-DE-16, where the German rule is stricter than the European one ────────


def test_a_seller_identified_only_by_a_register_number_fails_the_german_rule():
    """BR-CO-26 takes BT-30; BR-DE-16 does not.

    A company that configured only its commercial-register number passes every
    EN 16931 rule and is rejected in Germany, which is the whole point of
    carrying this rule separately instead of leaning on BR-CO-26.
    """
    inv = _invoice(seller=_party(vat_id=None, tax_number=None, legal_id="HRB 12345"))
    assert _fatal(inv) == {"BR-DE-16"}


@pytest.mark.parametrize("field", ["vat_id", "tax_number"])
def test_either_tax_registration_answers_br_de_16(field: str):
    values = {"vat_id": "DE123456789", "tax_number": "21/815/08150"}
    registration = {"vat_id": None, "tax_number": None, "legal_id": "HRB 12345", field: values[field]}
    assert _fatal(_invoice(seller=_party(**registration))) == set()


def test_br_de_16_does_not_apply_to_an_invoice_outside_the_scope_of_vat():
    """The rule names categories S, Z, E, AE, K, G, L and M. O is not among them.

    The O group carries its exemption reason (BR-O-10 requires one), so the
    only rule this document could still trip is the one under test.
    """
    inv = _invoice(
        seller=_party(vat_id=None, tax_number=None, legal_id="HRB 12345"),
        lines=[
            EInvoiceLine(
                line_id="1",
                name="Outside scope",
                quantity=Decimal("1"),
                unit="pcs",
                net_unit_price=Decimal("1000"),
                line_net_amount=Decimal("1000"),
                vat_rate=Decimal("0"),
                vat_category="O",
            )
        ],
        tax_subtotals=[
            TaxSubtotal(
                category="O",
                rate=Decimal("0"),
                basis=Decimal("1000"),
                tax_amount=Decimal("0"),
                exemption_reason="Not subject to VAT",
            )
        ],
        tax_total=Decimal("0"),
        grand_total=Decimal("1000"),
        due_payable=Decimal("1000"),
    )
    assert _fatal(inv) == set()


# ── the payment means and the group it obliges ───────────────────────────────


def test_a_credit_transfer_without_an_account_is_reported_under_the_german_id():
    """BR-DE-23-a is what a German receiver reports where EN 16931 says BR-61."""
    inv = _invoice(payment_means_code="58", payee_iban=None)
    assert "BR-DE-23-a" in _fatal(inv)


@pytest.mark.parametrize(
    ("code", "rule_id"),
    [("48", "BR-DE-24-a"), ("54", "BR-DE-24-a"), ("55", "BR-DE-24-a"), ("59", "BR-DE-25-a")],
)
def test_a_code_whose_group_this_writer_cannot_produce_is_refused(code: str, rule_id: str):
    """A card or direct-debit code can only make a document that is rejected.

    BG-18 and BG-19 are not written by this platform, so the document would
    arrive claiming a payment method it does not describe. Refusing at export is
    the cheaper failure, and it names the identifier the receiver would have.
    """
    inv = _invoice(payment_means_code=code, payee_iban="DE02120300000000202051")
    assert _fatal(inv) == {rule_id}


def test_a_code_no_german_rule_constrains_passes():
    inv = _invoice(payment_means_code="31", payee_iban="DE02120300000000202051")
    assert _fatal(inv) == set()


# ── the advisory rules, which must stay advisory ─────────────────────────────


def test_an_unexpected_type_code_warns_and_does_not_block():
    """BR-DE-17 is ``flag="warning"`` ("sollen"), so the export still happens."""
    inv = _invoice(type_code="999")
    assert _fatal(inv) == set()
    assert "BR-DE-17" in _warnings(inv)
    assert build_cii_xml(inv, strict=True), "a warning must not refuse the render"


@pytest.mark.parametrize("code", sorted(DE_INVOICE_TYPE_CODES))
def test_every_code_the_cius_names_is_accepted(code: str):
    """Including 875, 876 and 877, the German construction invoice sequence."""
    assert _warnings(_invoice(type_code=code)) == set()


def test_the_construction_type_codes_are_offered_by_name():
    """A user picks a document type, not a number, so the catalogue carries both."""
    assert DE_INVOICE_TYPE_CODES["875"] == "Partial construction invoice"
    assert DE_INVOICE_TYPE_CODES["876"] == "Partial final construction invoice"
    assert DE_INVOICE_TYPE_CODES["877"] == "Final construction invoice"


def test_a_short_telephone_number_warns_and_does_not_block():
    """BR-DE-27: at least three digits in BT-42."""
    inv = _invoice(seller=_party(contact_phone="n/a"))
    assert _fatal(inv) == set()
    assert "BR-DE-27" in _warnings(inv)
    assert build_cii_xml(inv, strict=True)


@pytest.mark.parametrize("email", ["no-at-sign.example", "a@b", "two@@signs.example", "trailing.dot@x.example."])
def test_an_implausible_email_address_warns_and_does_not_block(email: str):
    """BR-DE-28: one @, at least two characters either side, no edge dots."""
    inv = _invoice(seller=_party(contact_email=email))
    assert _fatal(inv) == set()
    assert "BR-DE-28" in _warnings(inv)
    assert build_cii_xml(inv, strict=True)


def test_a_plausible_email_address_says_nothing():
    assert _warnings(_invoice(seller=_party(contact_email="rechnung@nordbau.example"))) == set()


# ── the document, not only the verdict ───────────────────────────────────────


def test_the_contact_is_written_where_a_receiver_reads_bt_43():
    """BT-43 lives in DefinedTradeContact, and BT-34 is a different term.

    The contact email used to be written as a party-level
    ``URIUniversalCommunication`` with ``schemeID="EM"``, which is BT-34. A
    receiver looking for BR-DE-7 found nothing there, so an instance with an
    email on file still failed the rule. It is a child of the contact group now.
    """
    xml = build_cii_xml(_invoice(), strict=True).decode()
    assert "<ram:DefinedTradeContact>" in xml
    assert "<ram:PersonName>Anke Reimann</ram:PersonName>" in xml
    assert "<ram:CompleteNumber>+49 30 1234560</ram:CompleteNumber>" in xml
    assert "<ram:URIID>rechnung@nordbau.example</ram:URIID>" in xml
    contact_at = xml.index("<ram:DefinedTradeContact>")
    address_at = xml.index("<ram:PostalTradeAddress>")
    assert contact_at < address_at, "CII orders the contact before the postal address"


def test_a_party_carries_at_most_one_electronic_address():
    """BT-34 is 0..1, and the contact email is no longer a second one.

    With both an electronic address and a contact email set, the party used to
    grow two ``URIUniversalCommunication`` children.
    """
    seller = _party(electronic_address="0204:991-01234-56", contact_id_scheme="0204")
    xml = build_cii_xml(_invoice(seller=seller), strict=True).decode()
    seller_block = xml.split("<ram:BuyerTradeParty>")[0]
    assert seller_block.count("<ram:URIUniversalCommunication>") == 1


def test_the_group_is_absent_rather_than_empty_when_nothing_is_known():
    """The writer and the BR-DE-2 check have to agree on when BG-6 exists.

    An empty ``DefinedTradeContact`` would satisfy BR-DE-2 at the receiver and
    then fail BR-DE-5/6/7, turning one honest finding into three. A non-strict
    render is used because this document is, correctly, not exportable.
    """
    inv = _invoice(seller=_party(contact_name=None, contact_phone=None, contact_email=None))
    xml = build_cii_xml(inv, strict=False).decode()
    # The buyer in this fixture does carry a contact, so the seller's half of
    # the document is what has to be read here.
    seller_block = xml.split("<ram:BuyerTradeParty>")[0]
    assert "<ram:DefinedTradeContact>" not in seller_block


def test_a_strict_export_refuses_a_seller_with_no_contact():
    """A rule that does not block a render is a rule that ships anyway."""
    inv = _invoice(seller=_party(contact_phone=None))
    with pytest.raises(EInvoiceError) as exc:
        build_cii_xml(inv, strict=True)
    assert "telephone" in str(exc.value)
