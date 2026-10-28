# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The buyer party read off the contact an invoice already names.

Until this existed no screen could write a buyer address at all: the e-invoice
panel is read-only, and the contact form kept its address as one unstructured
line. That made BR-7 and BR-11, and later BR-DE-8 and BR-DE-9, impossible to
satisfy from the UI rather than merely inconvenient.

The tests below fix the two properties the rest of the feature rests on. The
contact is a floor, not a ceiling: a buyer typed onto one invoice still wins.
And nothing here parses the legacy free-text line, because a post code guessed
out of prose is exported as though someone had confirmed it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.contacts.models import Contact
from app.modules.einvoice import build_einvoice, violations_for
from app.modules.einvoice.rules import FATAL
from app.modules.finance.einvoice_parties import buyer_party_from_contact, contact_display_name


def _contact(**over: object) -> Contact:
    """A contact carrying a complete German postal address."""
    base: dict[str, object] = {
        "contact_type": "client",
        "company_name": "Stadtwerke Kiel",
        "country_code": "DE",
        "vat_number": "DE987654321",
        "address": {"text": "Werftstrasse 14", "postcode": "24143", "city": "Kiel"},
    }
    base.update(over)
    return Contact(**base)


# ── the name a document calls the buyer ───────────────────────────────────────


def test_the_company_is_the_name_when_there_is_one():
    assert contact_display_name(_contact()) == "Stadtwerke Kiel"


def test_a_person_is_named_when_there_is_no_company():
    contact = _contact(company_name=None, first_name="Anke", last_name="Petersen")
    assert contact_display_name(contact) == "Anke Petersen"


def test_the_email_is_the_last_resort():
    contact = _contact(company_name=None, primary_email="rechnung@example.de")
    assert contact_display_name(contact) == "rechnung@example.de"


def test_a_contact_with_no_name_at_all_returns_empty_rather_than_raising():
    """The shape that used to raise.

    The finance router resolved this itself and read ``c.email``, which is not a
    column on ``Contact``: the fallback raised ``AttributeError`` for exactly the
    record it existed to serve. It is asserted here rather than left implicit
    because the invoice list resolves a name for every row, so a single such
    contact took the whole list down with it.
    """
    contact = _contact(company_name=None, primary_email=None)
    assert contact_display_name(contact) == ""


def test_the_registered_name_is_used_before_the_email():
    """A firm with a registered name and no trading name is not billed to its inbox.

    Two functions called ``contact_display_name`` existed, one here and one in
    ``app.core.party_names``, and each docstring claimed to be the only place
    that knows how to name a contact. They agreed on company and person and
    parted company on the last step: the register fell back to ``legal_name``,
    this one to the email address. So the same firm read as "Nordbau Hoch- und
    Tiefbau GmbH" in search and on the punch list, and as an email address on
    its invoice, where BT-44 is the buyer's name.
    """
    contact = _contact(
        company_name=None,
        legal_name="Nordbau Hoch- und Tiefbau GmbH",
        primary_email="rechnung@nordbau.de",
    )
    assert contact_display_name(contact) == "Nordbau Hoch- und Tiefbau GmbH"


def test_a_trading_name_of_only_spaces_does_not_erase_the_person():
    """Whitespace is truthy, and that used to be the whole bug.

    ``if contact.company_name`` passes for a string of spaces, so the name was
    returned and then stripped to nothing: an invoice whose buyer line was blank
    on a record that named a person perfectly well.
    """
    contact = _contact(company_name="   ", first_name="Anke", last_name="Petersen")
    assert contact_display_name(contact) == "Anke Petersen"


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"company_name": None, "first_name": "Anke", "last_name": "Petersen"},
        {"company_name": None, "legal_name": "Nordbau GmbH"},
        {"company_name": "   ", "first_name": "Anke", "last_name": "Petersen"},
        {"company_name": None, "legal_name": "Nordbau GmbH", "primary_email": "a@b.de"},
    ],
    ids=["company", "person", "registered", "blank-company", "registered-and-email"],
)
def test_the_invoice_and_the_registers_call_one_party_one_name(over: dict[str, object]):
    """The property that makes "one place knows how to name a contact" true.

    Asserted as agreement between the two functions rather than against literals,
    because literals in this file would go on passing after the two rules drifted
    apart again, which is exactly how they drifted apart the first time. The
    email is the one step this side may add, and only when the register has
    nothing at all to say.
    """
    from app.core.party_names import contact_display_name as register_display_name

    contact = _contact(**over)
    register_label = register_display_name(
        contact.company_name, contact.legal_name, contact.first_name, contact.last_name
    )
    assert register_label, "the fixture must give the register something to name, or it proves nothing"
    assert contact_display_name(contact) == register_label


# ── the address a document needs ──────────────────────────────────────────────


def test_a_structured_address_answers_every_field_a_german_invoice_needs():
    assert buyer_party_from_contact(_contact()) == {
        "name": "Stadtwerke Kiel",
        "country_code": "DE",
        "vat_id": "DE987654321",
        "line1": "Werftstrasse 14",
        "postcode": "24143",
        "city": "Kiel",
    }


@pytest.mark.parametrize("spelling", ["postcode", "postal_code", "zip"])
def test_the_post_code_is_read_under_each_spelling_in_circulation(spelling: str):
    """Project addresses say ``postcode``, the geocoder also accepts ``postal_code``."""
    contact = _contact(address={"city": "Kiel", spelling: "24143"})
    assert buyer_party_from_contact(contact)["postcode"] == "24143"


@pytest.mark.parametrize("spelling", ["line1", "street", "text"])
def test_the_address_line_is_read_under_each_spelling_in_circulation(spelling: str):
    contact = _contact(address={spelling: "Werftstrasse 14"})
    assert buyer_party_from_contact(contact)["line1"] == "Werftstrasse 14"


def test_a_legacy_one_line_address_is_not_split_into_a_city_and_a_post_code():
    """The decision this feature turns on, asserted rather than described.

    Every contact captured before this change holds one unstructured line. It
    becomes the address line as written, and the city and the post code stay
    unanswered, so the user is told they are missing. Splitting them out would
    succeed on this string and mis-file the next one, and a wrong post code is
    exported silently while an absent one is reported.
    """
    contact = _contact(address={"text": "Werftstrasse 14, 24143 Kiel"})

    party = buyer_party_from_contact(contact)

    assert party["line1"] == "Werftstrasse 14, 24143 Kiel"
    assert "postcode" not in party
    assert "city" not in party


def test_a_field_the_contact_cannot_answer_is_absent_rather_than_empty():
    """An empty string would count as an answer and block the invoice's own."""
    contact = _contact(company_name=None, primary_email=None, country_code=None, vat_number=None, address=None)
    assert buyer_party_from_contact(contact) == {}


def test_an_address_that_is_not_a_dict_is_ignored_rather_than_fatal():
    """The column is untyped JSON, so it can hold whatever was written to it."""
    assert buyer_party_from_contact(_contact(address="Werftstrasse 14")) == {
        "name": "Stadtwerke Kiel",
        "country_code": "DE",
        "vat_id": "DE987654321",
    }


# ── how it reaches a document ─────────────────────────────────────────────────


def _invoice(einvoice_meta: dict) -> dict:
    return {
        "invoice_number": "RE-2026-0501",
        "invoice_date": "2026-08-12",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("190.00"),
        "metadata": {"einvoice": einvoice_meta},
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Concrete works",
            "unit": "m3",
            "quantity": Decimal("10"),
            "unit_rate": Decimal("100"),
            "amount": Decimal("1000.00"),
        }
    ]


_SELLER: dict = {
    "seller": {
        "name": "Hochbau Nord GmbH",
        "vat_id": "DE123456789",
        "country_code": "DE",
        "line1": "Werftstrasse 14",
        "postcode": "24103",
        "city": "Kiel",
        # BG-6, mandatory on the seller under XRechnung (BR-DE-2, BR-DE-5..7).
        # The seller half has to be clean for a test about the buyer half.
        "contact_name": "Anke Reimann",
        "contact_phone": "+49 431 1234560",
        "contact_email": "rechnung@hochbau-nord.example",
    }
}


def test_a_contact_alone_carries_a_german_invoice_past_every_fatal_rule():
    """The whole point: nothing about the buyer is typed onto the invoice.

    Before this, an invoice naming a perfectly complete customer still failed
    BR-7, BR-11, BR-DE-8 and BR-DE-9, and no screen could answer them.
    """
    defaults = {**_SELLER, "buyer": buyer_party_from_contact(_contact())}
    invoice = _invoice({"buyer_reference": "991-01234-56"})

    fatal = [
        v
        for v in violations_for(invoice=invoice, line_items=_lines(), profile="xrechnung", defaults=defaults)
        if v.severity == FATAL
    ]

    assert fatal == [], [f"{v.rule_id}: {v.message}" for v in fatal]


def test_the_contact_is_a_floor_and_the_invoice_overrides_it():
    """A one-off recipient stays expressible on the document itself."""
    defaults = {**_SELLER, "buyer": buyer_party_from_contact(_contact())}
    invoice = _invoice(
        {
            "buyer": {"name": "Stadtwerke Flensburg", "city": "Flensburg", "postcode": "24937"},
            "buyer_reference": "991-01234-56",
        }
    )

    ei = build_einvoice(invoice=invoice, line_items=_lines(), profile="xrechnung", defaults=defaults)

    assert ei.buyer.name == "Stadtwerke Flensburg"
    assert ei.buyer.city == "Flensburg"
    assert ei.buyer.postcode == "24937"
    # Field-wise: the country the invoice stayed silent about still arrives.
    assert ei.buyer.country_code == "DE"


def test_every_buyer_party_finding_sends_the_user_to_the_contact():
    """A finding is a remedy, and it is only a remedy if the screen it names has the field.

    All four used to say the invoice, which was true of the data model and
    useless to the user: the panel is read-only and no screen wrote a buyer.
    Moving the buyer to the contact without moving these sentences would have
    relocated the dead end rather than closing it.

    The buyer reference is deliberately not in this set. BT-10 identifies the
    recipient's routing on this one document and belongs on the invoice, so a
    later edit sweeping every message containing the word buyer would be wrong.
    """
    invoice = _invoice({"buyer_reference": "991-01234-56"})

    messages = {
        v.rule_id: v.message
        for v in violations_for(invoice=invoice, line_items=_lines(), profile="xrechnung", defaults=dict(_SELLER))
        if v.severity == FATAL
    }

    # Also proves the set is closed: a fifth buyer rule would land here and fail
    # rather than ship pointing at a screen nobody checked.
    assert set(messages) == {"BR-7", "BR-11", "BR-DE-8", "BR-DE-9"}, messages
    for rule_id, message in messages.items():
        assert "on the contact this invoice bills" in message, f"{rule_id}: {message}"
        assert "on this invoice" not in message, f"{rule_id}: {message}"


def test_a_contact_missing_the_city_still_fails_the_german_rules():
    """The rules are not weakened by having a contact behind them."""
    contact = _contact(address={"text": "Werftstrasse 14"})
    defaults = {**_SELLER, "buyer": buyer_party_from_contact(contact)}
    invoice = _invoice({"buyer_reference": "991-01234-56"})

    fatal = {
        v.rule_id
        for v in violations_for(invoice=invoice, line_items=_lines(), profile="xrechnung", defaults=defaults)
        if v.severity == FATAL
    }

    assert fatal == {"BR-DE-8", "BR-DE-9"}
