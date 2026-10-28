# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One invoice row must not become two different documents.

An invoice can be rendered as EN 16931 by two callers: the finance export
route, and the clearance module when a tax authority asks for the document.
Both read the same row and both hand plain dicts to the same engine, so the
only way they can disagree is by building those dicts differently - which is
exactly what happened. The finance route flattens its lines through
``_line_item_dicts``, which carries BT-152 and BT-151; the clearance module
built its line dicts inline and left both out. A mixed-rate invoice therefore
exported with its rates and cleared without them, and nothing said so, because
the invoice-level fallback produces a document that reconciles and passes every
rule. It is simply a different document about the same money.

The mixed rates are asserted before the two payloads are compared, and that
order is deliberate: equality alone is satisfied by both paths flattening
together, and the failure that matters reads as "the clearance path lost the
rates" rather than as a diff of two XML blobs.

Scope, so a later reader is not misled: the header dicts the two callers build
are field for field identical today (``finance/router.py`` around the export
route, ``einvoice_clearance/service.py`` in ``build_payload_from_invoice``), so
the header assembled below stands in for the finance one faithfully. What this
pins is the line dicts, where the divergence lived. A future divergence in the
header is out of its reach and would need the route itself.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.einvoice import render_einvoice
from app.modules.einvoice_clearance.service import build_payload_from_invoice
from app.modules.finance.einvoice_settings_service import einvoice_defaults
from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.finance.router import _line_item_dicts

pytestmark = pytest.mark.asyncio

_PROFILE = "xrechnung"

# Standard-rated works beside a reduced-rate supply: 1000 at 19% plus 500 at 7%
# is 225.00 of VAT, which is also what the header carries, so the invoice
# reconciles whether or not the lines keep their own rates. That is what made
# the defect invisible.
_SUBTOTAL = Decimal("1500.00")
_TAX = Decimal("225.00")


def _metadata() -> dict:
    """Everything EN 16931 and XRechnung need, on the document itself.

    Both parties name a country because BR-9 and BR-11 are reachable now: a
    party without one is refused rather than assumed to be German.
    """
    return {
        "einvoice": {
            "buyer_reference": "991-12345-67",  # BT-10, XRechnung will not go without it
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
            "buyer": {
                "name": "City Works Department",
                "country_code": "DE",
                "line1": "Market Square 1",
                "postcode": "20095",
                "city": "Hamburg",
            },
        }
    }


async def _a_mixed_rate_invoice(session) -> Invoice:
    invoice = Invoice(
        project_id=uuid.uuid4(),
        invoice_direction="receivable",
        invoice_number="RE-2026-0518",
        invoice_date="2026-08-11",
        currency_code="EUR",
        amount_subtotal=_SUBTOTAL,
        tax_amount=_TAX,
        retention_amount=Decimal("0"),
        amount_total=_SUBTOTAL + _TAX,
        status="draft",
        metadata_=_metadata(),
    )
    session.add(invoice)
    await session.flush()
    session.add_all(
        [
            InvoiceLineItem(
                invoice_id=invoice.id,
                description="Concrete works",
                unit="m3",
                quantity=Decimal("10"),
                unit_rate=Decimal("100"),
                amount=Decimal("1000.00"),
                vat_rate=Decimal("19"),
                vat_category="S",
                sort_order=0,
            ),
            InvoiceLineItem(
                invoice_id=invoice.id,
                description="Reduced rate supply",
                unit="pcs",
                quantity=Decimal("5"),
                unit_rate=Decimal("100"),
                amount=Decimal("500.00"),
                vat_rate=Decimal("7"),
                vat_category="S",
                sort_order=1,
            ),
        ]
    )
    await session.flush()
    await session.refresh(invoice)
    return invoice


def _header(invoice: Invoice) -> dict:
    """The invoice fields both callers pass, in the shape both build."""
    return {
        "invoice_number": invoice.invoice_number,
        "invoice_direction": invoice.invoice_direction,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "currency_code": invoice.currency_code,
        "amount_subtotal": invoice.amount_subtotal,
        "tax_amount": invoice.tax_amount,
        "retention_amount": invoice.retention_amount,
        "amount_total": invoice.amount_total,
        "notes": invoice.notes,
        "metadata": dict(invoice.metadata_ or {}),
    }


async def test_the_cleared_document_keeps_the_rate_each_line_carries(pg_session):
    """The clearance payload is what a tax authority reads, so it holds the rates."""
    invoice = await _a_mixed_rate_invoice(pg_session)

    payload, media_type = await build_payload_from_invoice(pg_session, invoice_id=invoice.id, en16931_profile=_PROFILE)

    assert media_type == "application/xml"
    assert "<ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>" in payload
    assert "<ram:RateApplicablePercent>7.00</ram:RateApplicablePercent>" in payload


async def test_both_render_paths_produce_the_same_document_for_one_invoice(pg_session):
    """Export and clearance are two readers of one row, not two opinions about it.

    The finance side is driven through its own ``_line_item_dicts`` rather than
    a dict written for the occasion, because a hand-built one would test a
    shape the product does not produce and would agree with whatever this test
    happened to assume.
    """
    invoice = await _a_mixed_rate_invoice(pg_session)

    cleared, _media = await build_payload_from_invoice(pg_session, invoice_id=invoice.id, en16931_profile=_PROFILE)
    _name, _media_type, exported = render_einvoice(
        invoice=_header(invoice),
        line_items=_line_item_dicts(invoice.line_items),
        profile=_PROFILE,
        defaults=await einvoice_defaults(pg_session),
    )

    # Named first so a failure says which rate went missing, not just that two
    # documents differ somewhere.
    assert "<ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>" in cleared
    assert "<ram:RateApplicablePercent>7.00</ram:RateApplicablePercent>" in cleared
    assert cleared == exported.decode("utf-8")


async def test_a_single_rate_invoice_is_unaffected(pg_session):
    """Every invoice written before per-line VAT existed still clears as it did."""
    invoice = await _a_mixed_rate_invoice(pg_session)
    for line in invoice.line_items:
        line.vat_rate = None
        line.vat_category = None
    await pg_session.flush()
    await pg_session.refresh(invoice)

    cleared, _media = await build_payload_from_invoice(pg_session, invoice_id=invoice.id, en16931_profile=_PROFILE)

    # 225.00 on 1500.00 is 15%, the rate derived from the header when no line
    # names one of its own.
    assert "<ram:RateApplicablePercent>15.00</ram:RateApplicablePercent>" in cleared
    assert "<ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>" not in cleared
