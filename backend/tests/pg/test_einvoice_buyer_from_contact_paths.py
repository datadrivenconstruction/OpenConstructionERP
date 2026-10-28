# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An invoice naming a contact carries that contact's address into both documents.

Two callers render an invoice with the EN 16931 engine: the finance export route
and the clearance module. The buyer had to be resolved for both or the same
invoice would export in one and be refused in the other, which is why this
exercises each of them against a real row rather than testing the resolver alone
and assuming the callers reach it.

The invoices below name their seller on the document so that the only thing
under test is where the buyer comes from. Direction matters: on a receivable
invoice the contact is the customer, on a payable one it is the supplier, and
mapping the latter into the buyer slot would file a company as the recipient of
its own invoice.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import app.modules.finance.router as finance_router
from app.modules.contacts.models import Contact
from app.modules.einvoice_clearance.service import build_payload_from_invoice
from app.modules.finance.einvoice_parties import einvoice_defaults_for_invoice
from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.finance.service import FinanceService

pytestmark = pytest.mark.asyncio

_SUBTOTAL = Decimal("1000.00")
_TAX = Decimal("190.00")


def _seller_only_metadata() -> dict:
    """Everything except the buyer, who has to arrive from the contact."""
    return {
        "einvoice": {
            "buyer_reference": "991-12345-67",  # BT-10, XRechnung refuses without it
            "seller": {
                "name": "Harbour Civils GmbH",
                "vat_id": "DE123456789",
                "country_code": "DE",
                "line1": "Dock Road 1",
                "postcode": "20457",
                "city": "Hamburg",
                # BG-6, mandatory on the seller under XRechnung (BR-DE-2).
                "contact_name": "Anke Reimann",
                "contact_phone": "+49 40 1234560",
                "contact_email": "rechnung@harbour-civils.example",
            },
        }
    }


async def _a_contact(session, **over: object) -> Contact:
    base: dict[str, object] = {
        "contact_type": "client",
        "company_name": "City Works Department",
        "country_code": "DE",
        "address": {"text": "Market Square 1", "postcode": "20095", "city": "Hamburg"},
        "is_active": True,
    }
    base.update(over)
    contact = Contact(**base)
    session.add(contact)
    await session.flush()
    return contact


async def _an_invoice(session, *, contact_id: str | None, direction: str = "receivable") -> Invoice:
    invoice = Invoice(
        project_id=uuid.uuid4(),
        contact_id=contact_id,
        invoice_direction=direction,
        invoice_number="RE-2026-0611",
        invoice_date="2026-08-12",
        currency_code="EUR",
        amount_subtotal=_SUBTOTAL,
        tax_amount=_TAX,
        retention_amount=Decimal("0"),
        amount_total=_SUBTOTAL + _TAX,
        status="draft",
        metadata_=_seller_only_metadata(),
    )
    session.add(invoice)
    await session.flush()
    session.add(
        InvoiceLineItem(
            invoice_id=invoice.id,
            description="Concrete works",
            unit="m3",
            quantity=Decimal("10"),
            unit_rate=Decimal("100"),
            amount=_SUBTOTAL,
            vat_rate=Decimal("19"),
            vat_category="S",
            sort_order=0,
        )
    )
    await session.flush()
    await session.refresh(invoice)
    return invoice


# ── what the shared resolver returns ──────────────────────────────────────────


async def test_a_receivable_invoice_gets_its_buyer_from_the_contact(pg_session):
    contact = await _a_contact(pg_session)
    invoice = await _an_invoice(pg_session, contact_id=str(contact.id))

    defaults = await einvoice_defaults_for_invoice(
        pg_session,
        contact_id=invoice.contact_id,
        invoice_direction=invoice.invoice_direction,
    )

    assert defaults["buyer"] == {
        "name": "City Works Department",
        "country_code": "DE",
        "line1": "Market Square 1",
        "postcode": "20095",
        "city": "Hamburg",
    }


async def test_a_payable_invoice_does_not_file_its_supplier_as_the_buyer(pg_session):
    """The same column names the other party when the invoice comes to us."""
    contact = await _a_contact(pg_session)
    invoice = await _an_invoice(pg_session, contact_id=str(contact.id), direction="payable")

    defaults = await einvoice_defaults_for_invoice(
        pg_session,
        contact_id=invoice.contact_id,
        invoice_direction=invoice.invoice_direction,
    )

    assert "buyer" not in defaults


async def test_an_invoice_naming_no_contact_resolves_to_the_settings_alone(pg_session):
    invoice = await _an_invoice(pg_session, contact_id=None)

    defaults = await einvoice_defaults_for_invoice(
        pg_session,
        contact_id=invoice.contact_id,
        invoice_direction=invoice.invoice_direction,
    )

    assert "buyer" not in defaults


# ── the two paths that render ─────────────────────────────────────────────────


async def test_the_finance_export_route_renders_an_invoice_whose_buyer_is_only_a_contact(pg_session, monkeypatch):
    """The route body itself, not a reconstruction of it.

    Access control and nothing else is stubbed: what is under test is that the
    route resolves the buyer at all, which it did not before, since its own
    fallback read an attribute ``Contact`` does not have.
    """

    async def _allow(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(finance_router, "_require_invoice_access", _allow)

    contact = await _a_contact(pg_session)
    invoice = await _an_invoice(pg_session, contact_id=str(contact.id))

    result = await finance_router.export_invoice_einvoice(
        invoice_id=invoice.id,
        session=pg_session,
        fmt="xrechnung",
        dry_run=True,
        embed=False,
        user_id=None,
        _perm=None,
        service=FinanceService(pg_session),
    )

    assert result["problems"] == []
    assert result["valid"] is True


async def test_the_finance_route_still_reports_a_contact_that_cannot_answer(pg_session, monkeypatch):
    """A contact holding only the legacy one-line address is not silently accepted.

    This is the negative that proves the positive above is the rule firing and
    not the check having been loosened.
    """

    async def _allow(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(finance_router, "_require_invoice_access", _allow)

    contact = await _a_contact(pg_session, address={"text": "Market Square 1, 20095 Hamburg"})
    invoice = await _an_invoice(pg_session, contact_id=str(contact.id))

    result = await finance_router.export_invoice_einvoice(
        invoice_id=invoice.id,
        session=pg_session,
        fmt="xrechnung",
        dry_run=True,
        embed=False,
        user_id=None,
        _perm=None,
        service=FinanceService(pg_session),
    )

    assert result["valid"] is False
    assert {v["rule_id"] for v in result["violations"] if v["severity"] == "fatal"} == {"BR-DE-8", "BR-DE-9"}


async def test_the_clearance_path_renders_the_same_buyer(pg_session):
    """The second caller, which never resolved a buyer at all before this."""
    contact = await _a_contact(pg_session)
    invoice = await _an_invoice(pg_session, contact_id=str(contact.id))

    payload, _media_type = await build_payload_from_invoice(
        pg_session,
        invoice_id=invoice.id,
        en16931_profile="xrechnung",
    )

    assert "City Works Department" in payload
    assert "20095" in payload
    assert "Hamburg" in payload
