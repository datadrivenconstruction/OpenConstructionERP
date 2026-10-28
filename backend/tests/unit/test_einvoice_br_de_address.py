# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠XRechnung wants more of a postal address than EN 16931 does.

EN 16931 is satisfied by an address that names only its country (BR-8 with
BR-9, BR-10 with BR-11), so a document can be EN 16931 complete and still be
rejected in Germany. XRechnung adds four fatal rules on top:

    BR-DE-3  seller city (BT-37)
    BR-DE-4  seller post code (BT-38)
    BR-DE-8  buyer city (BT-52)
    BR-DE-9  buyer post code (BT-53)

Verified against itplr-kosit/xrechnung-schematron v2.5.0, which is the
XRechnung 3.0.2 artefact and the version our CustomizationID claims, in
``src/validation/schematron/cii/XRechnung-CII-validation.sch``. Each is an
assert with ``flag="fatal"`` on ``[boolean(normalize-space(.))]`` inside the
party's ``PostalTradeAddress``, which is why blank-but-present fails here too.

Every test asserts the *whole* fatal set, not membership. A rule id present in
a document that broke for six other reasons proves nothing about the rule; the
baseline below is clean under the German profile, so a one-field edit produces
a one-rule answer or the test has caught something else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.einvoice import violations_for
from app.modules.einvoice.cii import (
    EInvoice,
    EInvoiceError,
    EInvoiceLine,
    Party,
    TaxSubtotal,
)
from app.modules.einvoice.rules import FATAL, check
from app.modules.einvoice.service import render_einvoice

XRECHNUNG = "xrechnung"


def _party(**over: object) -> Party:
    base = {
        "name": "Nordbau GmbH",
        "country_code": "DE",
        "vat_id": "DE123456789",
        "line1": "Baustrasse 1",
        "postcode": "10115",
        "city": "Berlin",
        # BG-6, mandatory on the seller under BR-DE-2 and BR-DE-5..7. Present in
        # the baseline for the same reason the address is: a test that breaks one
        # field can only produce a one-rule answer if everything else is clean.
        "contact_name": "Anke Reimann",
        "contact_phone": "+49 30 1234560",
        "contact_email": "rechnung@nordbau.example",
    }
    base.update(over)
    return Party(**base)  # type: ignore[arg-type]


def _invoice(**over: object) -> EInvoice:
    """An invoice that is XRechnung clean, so a test can break exactly one field."""
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
        "profile": XRECHNUNG,
        "invoice_number": "RE-2026-001",
        "issue_date": "2026-08-12",
        "currency": "EUR",
        "seller": _party(),
        "buyer": _party(name="Stadtwerke Muenster AG", vat_id=None, city="Muenster", postcode="48143"),
        "lines": lines,
        "tax_subtotals": [
            TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000"), tax_amount=Decimal("190"))
        ],
        "line_total": Decimal("1000"),
        "tax_basis_total": Decimal("1000"),
        "tax_total": Decimal("190"),
        "grand_total": Decimal("1190"),
        "due_payable": Decimal("1190"),
        # BR-DE-15, so the Leitweg-ID is not what a BR-DE-3 test trips over.
        "buyer_reference": "04011000-1234512345-06",
    }
    base.update(over)
    return EInvoice(**base)  # type: ignore[arg-type]


def _fatal(inv: EInvoice) -> set[str]:
    return {v.rule_id for v in check(inv) if v.severity == FATAL}


# ── the baseline is clean, which is what makes a one-rule answer meaningful ───


def test_a_complete_german_invoice_has_no_fatal_findings():
    assert _fatal(_invoice()) == set()


# ── one field out, one rule back ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rule_id", "party", "field"),
    [
        ("BR-DE-3", "seller", "city"),
        ("BR-DE-4", "seller", "postcode"),
        ("BR-DE-8", "buyer", "city"),
        ("BR-DE-9", "buyer", "postcode"),
    ],
)
def test_a_missing_address_field_is_fatal_and_is_the_only_finding(rule_id: str, party: str, field: str):
    inv = _invoice(**{party: _party(**{field: None})})
    assert _fatal(inv) == {rule_id}


@pytest.mark.parametrize(
    ("rule_id", "party", "field"),
    [
        ("BR-DE-3", "seller", "city"),
        ("BR-DE-4", "seller", "postcode"),
        ("BR-DE-8", "buyer", "city"),
        ("BR-DE-9", "buyer", "postcode"),
    ],
)
def test_a_blank_address_field_fails_exactly_as_an_absent_one(rule_id: str, party: str, field: str):
    """KoSIT asserts on ``normalize-space``, so spaces are not a value."""
    inv = _invoice(**{party: _party(**{field: "   "})})
    assert _fatal(inv) == {rule_id}


def test_each_finding_carries_the_business_term_a_receiver_would_quote():
    inv = _invoice(seller=_party(city=None, postcode=None), buyer=_party(city=None, postcode=None))
    terms = {v.rule_id: v.term for v in check(inv) if v.severity == FATAL}
    assert terms == {"BR-DE-3": "BT-37", "BR-DE-4": "BT-38", "BR-DE-8": "BT-52", "BR-DE-9": "BT-53"}


def test_the_seller_findings_name_the_settings_and_the_buyer_findings_name_the_contact():
    """Each side names the editor that holds it, because that is where the user goes.

    A finding is a remedy, not a label. The seller lives in the standing
    settings and the buyer is read from the contact the invoice bills, so a
    buyer finding pointing at the invoice would send the user to the one
    screen with no such field on it.
    """
    inv = _invoice(seller=_party(city=None, postcode=None), buyer=_party(city=None, postcode=None))
    where = {v.rule_id: v.message for v in check(inv) if v.severity == FATAL}
    for rule_id in ("BR-DE-3", "BR-DE-4"):
        assert "e-invoice settings" in where[rule_id]
    for rule_id in ("BR-DE-8", "BR-DE-9"):
        assert "e-invoice settings" not in where[rule_id]
        assert "on the contact this invoice bills" in where[rule_id]


# ── the rules are German, and only German ────────────────────────────────────


@pytest.mark.parametrize("profile", ["en16931", "zugferd", "facturx", "peppol", "ubl", "nlcius", "ehf"])
def test_no_other_profile_cites_a_br_de_rule_for_the_same_missing_address(profile: str):
    """A receiver outside Germany validates against its own CIUS.

    The same document, missing everything XRechnung demands beyond EN 16931,
    must raise nothing under any other flavour: the address (BR-DE-3/4/8/9), the
    seller contact group (BR-DE-2 and BR-DE-5..7) and the tax registration on
    German terms (BR-DE-16, where a register number alone is fine in Europe).
    Profiles that require a Buyer reference get one, so the only difference
    under test is the German surplus.
    """
    stripped = {
        "city": None,
        "postcode": None,
        "contact_name": None,
        "contact_phone": None,
        "contact_email": None,
    }
    inv = _invoice(
        profile=profile,
        seller=_party(vat_id=None, tax_number=None, legal_id="HRB 12345", **stripped),
        buyer=_party(**stripped),
    )
    assert _fatal(inv) == set()


@pytest.mark.parametrize("profile", ["en16931", "zugferd", "facturx", "peppol", "ubl", "nlcius", "ehf"])
def test_no_other_profile_warns_about_a_german_only_advisory(profile: str):
    """The advisory half of the family is just as national as the fatal half."""
    inv = _invoice(profile=profile, type_code="999", seller=_party(contact_phone="n/a"))
    assert {v.rule_id for v in check(inv) if v.rule_id.startswith("BR-DE")} == set()


# ── the same thing through the dict path every caller actually uses ──────────


def _invoice_dict(**einvoice_overrides: object) -> dict:
    """The finance route's shape: parties arrive under ``metadata.einvoice``.

    A rule can be reachable from a hand-built model and unreachable from every
    caller that exists, so at least one pair has to travel this way.
    """
    meta: dict = {
        "vat_rate": "19",
        "seller": {
            "name": "Nordbau GmbH",
            "vat_id": "DE123456789",
            "country_code": "DE",
            "postcode": "10115",
            "city": "Berlin",
            "contact_name": "Anke Reimann",
            "contact_phone": "+49 30 1234560",
            "contact_email": "rechnung@nordbau.example",
        },
        "buyer": {
            "name": "Stadtwerke Muenster AG",
            "country_code": "DE",
            "postcode": "48143",
            "city": "Muenster",
        },
        "buyer_reference": "04011000-1234512345-06",
    }
    meta.update(einvoice_overrides)
    return {
        "invoice_number": "RE-2026-002",
        "invoice_direction": "receivable",
        "invoice_date": "2026-08-12",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("190.00"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("1190.00"),
        "metadata": {"einvoice": meta},
    }


def _dict_lines() -> list[dict]:
    return [
        {
            "description": "Excavation",
            "unit": "m3",
            "quantity": Decimal("50"),
            "unit_rate": Decimal("20"),
            "amount": Decimal("1000.00"),
            "vat_rate": Decimal("19"),
            "vat_category": "S",
        }
    ]


def _dict_fatal(invoice: dict, defaults: dict | None = None) -> set[str]:
    found = violations_for(
        invoice=invoice, line_items=_dict_lines(), profile=XRECHNUNG, defaults=defaults if defaults is not None else {}
    )
    return {v.rule_id for v in found if v.severity == FATAL}


def test_the_dict_path_produces_a_clean_document_when_the_addresses_are_filled_in():
    assert _dict_fatal(_invoice_dict()) == set()


@pytest.mark.parametrize(
    ("rule_id", "party", "field"),
    [
        ("BR-DE-3", "seller", "city"),
        ("BR-DE-4", "seller", "postcode"),
        ("BR-DE-8", "buyer", "city"),
        ("BR-DE-9", "buyer", "postcode"),
    ],
)
def test_the_dict_path_reports_each_missing_address_field(rule_id: str, party: str, field: str):
    invoice = _invoice_dict()
    invoice["metadata"]["einvoice"][party].pop(field)
    assert _dict_fatal(invoice) == {rule_id}


def test_the_settings_screen_is_a_real_remedy_for_the_seller_half():
    """Seller city and post code are columns on the standing settings row.

    The invoice says nothing about the seller address; the configuration
    supplies it, and the two seller rules go quiet. If this ever fails, the
    findings are pointing users at a screen that cannot fix them.
    """
    invoice = _invoice_dict()
    invoice["metadata"]["einvoice"]["seller"].pop("city")
    invoice["metadata"]["einvoice"]["seller"].pop("postcode")
    assert _dict_fatal(invoice) == {"BR-DE-3", "BR-DE-4"}
    defaults = {"seller": {"city": "Berlin", "postcode": "10115"}}
    assert _dict_fatal(invoice, defaults=defaults) == set()


# ── validation is not optional: the export refuses ───────────────────────────


def test_a_strict_export_refuses_an_invoice_without_a_buyer_post_code():
    """A rule that does not block a render is a rule that ships anyway."""
    invoice = _invoice_dict()
    invoice["metadata"]["einvoice"]["buyer"].pop("postcode")
    with pytest.raises(EInvoiceError) as exc:
        render_einvoice(invoice=invoice, line_items=_dict_lines(), profile=XRECHNUNG, defaults={})
    assert "buyer post code" in str(exc.value)


def test_a_strict_export_still_succeeds_once_the_addresses_are_complete():
    """The refusal above has to be the address, not the fixture being broken."""
    _name, _media, xml = render_einvoice(
        invoice=_invoice_dict(), line_items=_dict_lines(), profile=XRECHNUNG, defaults={}
    )
    assert b"48143" in xml
    assert b"Muenster" in xml
