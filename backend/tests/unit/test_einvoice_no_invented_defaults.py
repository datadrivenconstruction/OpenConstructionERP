# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An unconfigured field must stay unset all the way to the document.

An e-invoice is a legal statement. BT-40 (seller country) and BT-5 (invoice
currency) are mandatory under EN 16931, and a document that answers them with a
value nobody configured states something false rather than states nothing. The
rules that exist to catch the omission (BR-9, BR-11, BR-5) can only fire if the
value is still empty by the time they run, so substituting a default anywhere
between the settings row and the model disarms them silently.

These tests take the dict path the finance export route and the clearance module
take, not a hand-built :class:`Party`: a rule can be reachable from a
hand-constructed model and unreachable from every caller that exists.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.modules.einvoice import (
    EInvoiceError,
    render_einvoice,
    violations_for,
)
from app.modules.einvoice.cii import RAM
from app.modules.einvoice.rules import violation_ids
from app.modules.einvoice.ubl import CAC, CBC


def _invoice(**einvoice_overrides) -> dict:
    """An otherwise complete invoice, so only the field under test can fail."""
    meta = {
        "vat_rate": "20",
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
        "invoice_number": "INV-2026-0042",
        "invoice_direction": "receivable",
        "invoice_date": "2026-07-05",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("200.00"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("1200.00"),
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


def _without_seller_country() -> dict:
    inv = _invoice()
    inv["metadata"]["einvoice"]["seller"].pop("country_code")
    return inv


def _without_any_country() -> dict:
    inv = _without_seller_country()
    inv["metadata"]["einvoice"]["buyer"].pop("country_code")
    return inv


def _found(invoice: dict, profile: str = "peppol") -> set[str]:
    return violation_ids(violations_for(invoice=invoice, line_items=_lines(), profile=profile, defaults={}))


class TestTheCountryNobodyConfigured:
    """BT-40 / BT-55: no country in the settings means no country on the document."""

    def test_a_seller_without_a_country_is_reported_as_br_9(self):
        # The instance has never filled in the e-invoice settings, so the
        # standing defaults are empty and the invoice names no country either.
        assert "BR-9" in _found(_without_seller_country())

    def test_a_buyer_without_a_country_is_reported_as_br_11(self):
        # Settings hold seller fields only, so an unconfigured buyer country is
        # the common case, not the exotic one.
        assert "BR-11" in _found(_without_any_country())

    def test_the_seller_country_message_still_points_at_the_settings_screen(self):
        found = violations_for(invoice=_without_seller_country(), line_items=_lines(), profile="peppol", defaults={})
        hit = [v for v in found if v.rule_id == "BR-9"]
        assert hit, [v.rule_id for v in found]
        assert hit[0].term == "BT-40"
        assert "e-invoice settings" in hit[0].message

    def test_the_buyer_country_message_points_at_the_invoice_not_the_settings(self):
        # The standing settings hold no buyer fields at all, so sending a user
        # there to fix a buyer country sends them to a screen without the field.
        found = violations_for(invoice=_without_any_country(), line_items=_lines(), profile="peppol", defaults={})
        hit = [v for v in found if v.rule_id == "BR-11"]
        assert hit, [v.rule_id for v in found]
        assert hit[0].term == "BT-55"
        assert "e-invoice settings" not in hit[0].message
        assert "invoice" in hit[0].message

    def test_a_cii_export_refuses_rather_than_naming_a_country_it_was_not_given(self):
        with pytest.raises(EInvoiceError) as exc:
            render_einvoice(invoice=_without_seller_country(), line_items=_lines(), profile="xrechnung", defaults={})
        assert "country code" in str(exc.value)

    def test_a_ubl_export_refuses_rather_than_naming_a_country_it_was_not_given(self):
        with pytest.raises(EInvoiceError) as exc:
            render_einvoice(invoice=_without_seller_country(), line_items=_lines(), profile="peppol", defaults={})
        assert "country code" in str(exc.value)

    def test_a_best_effort_cii_document_omits_the_country_element(self):
        # strict=False exists for inspection, and an inspection copy must not
        # contain the false statement either. Absent says nothing; DE lies.
        _name, _media, xml = render_einvoice(
            invoice=_without_any_country(),
            line_items=_lines(),
            profile="xrechnung",
            defaults={},
            strict=False,
        )
        root = ET.fromstring(xml)
        assert root.findall(f".//{{{RAM}}}CountryID") == []

    def test_a_best_effort_ubl_document_omits_the_country_element(self):
        _name, _media, xml = render_einvoice(
            invoice=_without_any_country(),
            line_items=_lines(),
            profile="peppol",
            defaults={},
            strict=False,
        )
        root = ET.fromstring(xml)
        # The wrapper goes too: an empty cac:Country reads as malformed rather
        # than as absent.
        assert root.findall(f".//{{{CAC}}}Country") == []
        assert root.findall(f".//{{{CBC}}}IdentificationCode") == []

    def test_a_configured_country_still_reaches_both_syntaxes(self):
        # The guard must not cost the ordinary case its country.
        _n, _m, cii = render_einvoice(invoice=_invoice(), line_items=_lines(), profile="en16931", defaults={})
        assert ET.fromstring(cii).find(f".//{{{RAM}}}CountryID").text == "IE"
        _n, _m, ubl = render_einvoice(invoice=_invoice(), line_items=_lines(), profile="peppol", defaults={})
        found = ET.fromstring(ubl).findall(f".//{{{CBC}}}IdentificationCode")
        assert [el.text for el in found] == ["IE", "IE"]


class TestTheCurrencyNobodyConfigured:
    """BT-5: the same shape one line away, and the same silenced rule."""

    def test_an_invoice_without_a_currency_is_reported_as_br_5(self):
        inv = _invoice()
        inv["currency_code"] = ""
        assert "BR-5" in _found(inv)

    def test_an_export_without_a_currency_refuses(self):
        inv = _invoice()
        inv["currency_code"] = ""
        with pytest.raises(EInvoiceError) as exc:
            render_einvoice(invoice=inv, line_items=_lines(), profile="peppol", defaults={})
        assert "currency" in str(exc.value)
