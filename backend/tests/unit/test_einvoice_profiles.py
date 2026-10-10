"""Unit tests for the international profile registry.

Proves each national Peppol CIUS profile resolves, carries the right
CustomizationID (BT-24), and produces a valid EN 16931 UBL document. Sample
data covers several countries so the library is not tied to one jurisdiction.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.modules.einvoice import get_profile, problems_for, render_einvoice
from app.modules.einvoice.profiles import (
    NLCIUS,
    PEPPOL_AUNZ,
    PEPPOL_PROFILE,
    PEPPOL_SG,
    PROFILES,
    SYNTAXES,
)
from app.modules.einvoice.ubl import CAC, CBC, INV

NS = {"inv": INV, "cac": CAC, "cbc": CBC}


def _invoice(country: str, currency: str, vat_rate: str) -> dict:
    return {
        "invoice_number": f"INV-{country}-1",
        "invoice_date": "2026-07-05",
        "currency_code": currency,
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": (Decimal("1000.00") * Decimal(vat_rate) / 100).quantize(Decimal("0.01")),
        "metadata": {
            "einvoice": {
                "vat_rate": vat_rate,
                "seller": {
                    "name": "Global Build",
                    "vat_id": "XX0000000",
                    "city": "Capital",
                    "country_code": country,
                    "electronic_address": "0088:1234567890128",
                    "electronic_address_scheme": "0088",
                },
                "buyer": {"name": "City Works", "city": "Town", "country_code": country},
                "buyer_reference": "PO-2026-1",
            }
        },
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Site works",
            "unit": "m2",
            "quantity": Decimal("100"),
            "unit_rate": Decimal("10"),
            "amount": Decimal("1000.00"),
        }
    ]


def _text(root: ET.Element, path: str) -> str:
    el = root.find(path, NS)
    assert el is not None, f"missing {path}"
    return (el.text or "").strip()


@pytest.mark.parametrize(
    ("profile", "country", "currency", "vat", "customization"),
    [
        ("nlcius", "NL", "EUR", "21", NLCIUS),
        ("peppol_aunz", "AU", "AUD", "10", PEPPOL_AUNZ),
        ("peppol_sg", "SG", "SGD", "9", PEPPOL_SG),
        ("ehf", "NO", "NOK", "25", "urn:cen.eu:en16931:2017#compliant"),
    ],
)
def test_new_profile_resolves_and_renders(profile, country, currency, vat, customization):
    prof = get_profile(profile)
    assert prof is not None
    assert prof.syntax == "ubl"
    assert prof.profile_id == PEPPOL_PROFILE
    assert prof.region
    assert prof.label

    inv = _invoice(country, currency, vat)
    # A well-formed invoice with a buyer reference validates clean.
    assert problems_for(invoice=inv, line_items=_lines(), profile=profile) == []

    _, media, xml = render_einvoice(invoice=inv, line_items=_lines(), profile=profile)
    assert media == "application/xml"
    root = ET.fromstring(xml)
    assert root.tag == f"{{{INV}}}Invoice"
    assert _text(root, "cbc:CustomizationID").startswith(customization)
    assert _text(root, "cbc:ProfileID") == PEPPOL_PROFILE
    assert _text(root, "cbc:DocumentCurrencyCode") == currency


@pytest.mark.parametrize("profile", ["nlcius", "peppol_aunz", "peppol_sg", "ehf"])
def test_new_profile_requires_a_buyer_or_order_reference(profile):
    inv = _invoice("NL", "EUR", "21")
    inv["metadata"]["einvoice"].pop("buyer_reference")
    problems = problems_for(invoice=inv, line_items=_lines(), profile=profile)
    assert any("BT-10" in p or "BT-13" in p or "Buyer reference" in p for p in problems)
    # An order reference (BT-13) satisfies the rule for every Peppol CIUS.
    inv["metadata"]["einvoice"]["order_reference"] = "ORD-321"
    assert problems_for(invoice=inv, line_items=_lines(), profile=profile) == []


def test_registry_profiles_are_self_consistent():
    for name, prof in PROFILES.items():
        assert prof.name == name
        # The registry's own vocabulary, which since UBL-TR holds one syntax
        # outside EN 16931. That the EN 16931 engine refuses it is pinned in
        # test_einvoice_tr_mapper.py.
        assert prof.syntax in SYNTAXES
        assert prof.guideline
        assert prof.label, f"{name} needs a human label"
        assert prof.region, f"{name} needs a region"


def test_new_profiles_are_registered():
    for name in ("nlcius", "ehf", "peppol_aunz", "peppol_sg"):
        assert name in PROFILES
