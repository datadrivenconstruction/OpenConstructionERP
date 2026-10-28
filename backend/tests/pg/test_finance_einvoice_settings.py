# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The standing e-invoice configuration, stored and read back as a document sees it.

The unit tests cover the merge and the validation on their own. What only a real
database can show is the part in between: that a configuration written through
the update path comes back out of ``einvoice_defaults`` in the shape
``build_einvoice`` merges, and that the single row really is single.

These re-query with a fresh ``select()`` rather than reading the returned object,
because the identity map would otherwise hand back the instance still in memory
and the test would pass on a write that never reached the database.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.einvoice import render_einvoice, violations_for
from app.modules.einvoice.rules import FATAL
from app.modules.finance.einvoice_settings_models import DEFAULT_SCOPE, EInvoiceSettings
from app.modules.finance.einvoice_settings_schemas import EInvoiceSettingsRead, EInvoiceSettingsUpdate
from app.modules.finance.einvoice_settings_service import einvoice_defaults, get_settings, update_settings

pytestmark = pytest.mark.asyncio


def _payload(**over: str) -> EInvoiceSettingsUpdate:
    base = {
        "seller_name": "Hochbau Nord GmbH",
        "seller_vat_id": "DE123456789",
        "seller_country_code": "DE",
        "seller_line1": "Werftstrasse 14",
        "seller_postcode": "24143",
        "seller_city": "Kiel",
        # BG-6, which XRechnung requires on the seller (BR-DE-2, BR-DE-5..7) and
        # which this row is the only home for.
        "seller_contact_name": "Anke Reimann",
        "seller_contact_phone": "+49 431 1234560",
        "seller_contact_email": "rechnung@hochbau-nord.example",
        "payee_iban": "DE02 1203 0000 0000 2020 51",
        "payee_account_name": "Hochbau Nord GmbH",
        "payment_terms": "Net 30 days",
    }
    base.update(over)
    return EInvoiceSettingsUpdate(**base)


async def test_an_unconfigured_instance_offers_no_defaults(pg_session):
    """Nothing configured must read as nothing, not as a row full of blanks."""
    assert await einvoice_defaults(pg_session) == {}


async def test_what_is_written_comes_back_in_the_shape_a_document_merges(pg_session):
    await update_settings(pg_session, _payload(), user_id=uuid.uuid4())
    await pg_session.commit()

    defaults = await einvoice_defaults(pg_session)

    assert defaults["seller"]["name"] == "Hochbau Nord GmbH"
    assert defaults["seller"]["line1"] == "Werftstrasse 14"
    # Stored in wire format, not as the user spaced it.
    assert defaults["payee_iban"] == "DE02120300000000202051"
    assert defaults["payment_terms"] == "Net 30 days"
    # Blank fields are absent rather than empty, or they would blank an invoice.
    assert "seller_tax_number" not in defaults
    assert "payee_bic" not in defaults


async def test_the_configuration_alone_clears_the_seller_violations(pg_session):
    """The point of the whole change, end to end.

    An invoice that names only its buyer is fatally incomplete today. With the
    seller configured it validates and renders, and both agree, because both
    reach the document through the same merge.
    """
    await update_settings(pg_session, _payload(), user_id=None)
    await pg_session.commit()
    defaults = await einvoice_defaults(pg_session)

    invoice = {
        "invoice_number": "RE-2026-0412",
        "invoice_date": "2026-08-11",
        "currency_code": "EUR",
        "amount_subtotal": "1000.00",
        "tax_amount": "190.00",
        "metadata": {
            "einvoice": {
                # The buyer address stays on the document: the settings row is
                # seller-only, and XRechnung wants the buyer city and post code
                # as well (BR-DE-8, BR-DE-9).
                "buyer": {
                    "name": "Stadtwerke Kiel",
                    "country_code": "DE",
                    "postcode": "24103",
                    "city": "Kiel",
                },
                "buyer_reference": "991-01234-56",
            }
        },
    }
    lines = [{"description": "Concrete works", "unit": "m3", "quantity": "10", "unit_rate": "100", "amount": "1000.00"}]

    before = [v for v in violations_for(invoice=invoice, line_items=lines, profile="xrechnung") if v.severity == FATAL]
    assert before, "an invoice with no seller should be fatally incomplete without the settings"

    after = [
        v
        for v in violations_for(invoice=invoice, line_items=lines, profile="xrechnung", defaults=defaults)
        if v.severity == FATAL
    ]
    assert after == [], [f"{v.rule_id}: {v.message}" for v in after]

    _n, _m, body = render_einvoice(invoice=invoice, line_items=lines, profile="xrechnung", defaults=defaults)
    assert b"Hochbau Nord GmbH" in body


async def test_writing_twice_keeps_one_row(pg_session):
    """A settings table that grows a row per save is a settings table with no settings."""
    await update_settings(pg_session, _payload(), user_id=None)
    await pg_session.commit()
    await update_settings(pg_session, _payload(seller_city="Hamburg"), user_id=None)
    await pg_session.commit()

    rows = (await pg_session.execute(select(EInvoiceSettings).where(EInvoiceSettings.scope == DEFAULT_SCOPE))).scalars()
    assert len([*rows]) == 1

    stored = (await einvoice_defaults(pg_session))["seller"]
    assert stored["city"] == "Hamburg"


async def test_a_field_cleared_on_the_form_is_cleared_in_the_document(pg_session):
    """The write is a replace, so removing a bank account has to be expressible."""
    await update_settings(pg_session, _payload(), user_id=None)
    await pg_session.commit()
    assert "payee_iban" in await einvoice_defaults(pg_session)

    await update_settings(pg_session, _payload(payee_iban=""), user_id=None)
    await pg_session.commit()

    assert "payee_iban" not in await einvoice_defaults(pg_session)


async def test_reading_never_creates_a_row(pg_session):
    """``einvoice_defaults`` runs on every export, and a read must not write."""
    await einvoice_defaults(pg_session)
    await pg_session.commit()

    rows = (await pg_session.execute(select(EInvoiceSettings))).scalars()
    assert [*rows] == []


async def test_the_screen_is_told_what_is_still_missing(pg_session):
    """A blank configuration reports the fields that stop an invoice, not all of them."""
    empty = EInvoiceSettingsRead.from_row(await get_settings(pg_session))
    assert empty.complete is False
    assert set(empty.missing) == {"seller_name", "seller_country_code", "seller_vat_id"}

    row = await update_settings(pg_session, _payload(), user_id=None)
    await pg_session.commit()
    filled = EInvoiceSettingsRead.from_row(row)
    assert filled.complete is True
    assert filled.missing == []
