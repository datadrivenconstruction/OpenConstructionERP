# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A freshly seeded office-frankfurt invoice survives an XRechnung dry-run.

The German showcase preflight found the seeded invoices unusable for the
E-Rechnung walkthrough: every invoice carried ``contact_id`` NULL and no
Leitweg-ID, so the dry-run failed BR-7/BR-11 (buyer name and country),
BR-DE-8/9 (buyer city and post code) and BR-DE-15 (BT-10 buyer reference)
before a user had typed anything. The generator was fine; the seed was the
gap.

The seed now bills one receivable interim invoice to the client contact,
whose directory record answers the buyer's postal address and VAT id, and
stores the Leitweg-ID plus the seller party under ``metadata["einvoice"]``.
This test installs the demo into a real database and then walks exactly the
resolution path the export route walks (``einvoice_defaults_for_invoice``
into ``violations_for``), so what is asserted is the document a user would
actually get, not a hand-built lookalike.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import select

from app.core.demo_projects import install_demo_project
from app.modules.contacts.models import Contact
from app.modules.einvoice import violations_for
from app.modules.einvoice.rules import FATAL
from app.modules.finance.einvoice_parties import einvoice_defaults_for_invoice
from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.finance.router import _line_item_dicts

pytestmark = pytest.mark.asyncio

_DEMO_ID = "office-frankfurt"
_LEITWEG_ID = "06-4300251-83"


async def _seeded_receivable(session) -> Invoice:
    """Install the demo and return its one receivable showcase invoice."""
    result = await install_demo_project(session, _DEMO_ID)
    await session.flush()
    rows = (
        (
            await session.execute(
                select(Invoice).where(
                    Invoice.project_id == result["project_id"],
                    Invoice.invoice_direction == "receivable",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected exactly one seeded receivable invoice, found {len(rows)}"
    return rows[0]


def _invoice_dict(invoice: Invoice) -> dict:
    """The invoice as the export route hands it to the e-invoice engine."""
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


async def test_the_seeded_invoice_bills_a_buyer_the_directory_can_answer(pg_session) -> None:
    """The invoice names its counterparty, and the contact carries the master data."""
    invoice = await _seeded_receivable(pg_session)

    assert invoice.contact_id, "the showcase invoice is not linked to any contact"
    contact = (await pg_session.execute(select(Contact).where(Contact.id == invoice.contact_id))).scalar_one_or_none()
    assert contact is not None, "the linked contact does not exist"
    assert contact.contact_type == "client"
    assert contact.company_name == "Nordkranz Projekt GmbH & Co. KG"
    assert contact.vat_number, "the buyer contact carries no VAT id"
    assert contact.country_code == "DE"
    address = contact.address or {}
    assert address.get("city") == "Frankfurt am Main"
    assert address.get("postcode") == "60327"
    assert address.get("street"), "the buyer contact carries no street"

    # BT-10 lives on the invoice, because the reference belongs to the
    # document rather than to the counterparty.
    einvoice_meta = (invoice.metadata_ or {}).get("einvoice") or {}
    assert einvoice_meta.get("leitweg_id") == _LEITWEG_ID


async def test_the_seeded_invoice_passes_an_xrechnung_dry_run(pg_session) -> None:
    """Zero fatal findings on the exact path the export route resolves through."""
    invoice = await _seeded_receivable(pg_session)
    line_items = (
        (
            await pg_session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice.id)
                .order_by(InvoiceLineItem.sort_order)
            )
        )
        .scalars()
        .all()
    )
    assert line_items, "the showcase invoice seeded no line items"

    defaults = await einvoice_defaults_for_invoice(
        pg_session,
        contact_id=invoice.contact_id,
        invoice_direction=invoice.invoice_direction,
    )
    # The buyer half really comes from the linked contact, not from settings
    # (a fresh install has none) and not from the invoice metadata.
    buyer = defaults.get("buyer") or {}
    assert buyer.get("name") == "Nordkranz Projekt GmbH & Co. KG"
    assert buyer.get("postcode") == "60327"
    assert buyer.get("city") == "Frankfurt am Main"
    assert buyer.get("country_code") == "DE"

    found = violations_for(
        invoice=_invoice_dict(invoice),
        line_items=_line_item_dicts(line_items),
        profile="xrechnung",
        defaults=defaults,
    )
    fatal = [v for v in found if v.severity == FATAL]
    assert fatal == [], "fatal findings on a fresh seed: " + "; ".join(f"{v.rule_id}: {v.message}" for v in fatal)


async def test_the_seeded_amounts_are_measured_figures_that_still_reconcile(pg_session) -> None:
    """Non-round line amounts, and a header that follows from them exactly.

    Two properties, and they pull against each other, which is why they are
    pinned together. A progress invoice is billed off an Aufmaß, so amounts
    ending in six zeros read as placeholders to anybody who has priced one - but
    the installer derives the header from the lines in float while the EN 16931
    engine recomputes the VAT group in Decimal, and any drift between the two
    makes BR-CO-17 fatal and the whole walkthrough stops.

    Asserted as properties rather than as literals: whether this showcase keeps
    these particular figures is a decision about the case, while "not round" and
    "the arithmetic is exact" are the contract that must survive it.
    """
    invoice = await _seeded_receivable(pg_session)
    line_items = (
        (
            await pg_session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice.id)
                .order_by(InvoiceLineItem.sort_order)
            )
        )
        .scalars()
        .all()
    )
    assert line_items, "the showcase invoice seeded no line items"

    amounts = [Decimal(str(item.amount)) for item in line_items]
    for item, amount in zip(line_items, amounts, strict=True):
        assert amount > 0, f"{item.description}: a billed line needs an amount"
        # A round ten-thousand is the shape of a made-up number. Real measured
        # progress does not land there, and the case audit rejected the seed for
        # exactly that.
        assert amount % Decimal("10000") != 0, f"{item.description}: {amount} is a round figure, not a measured one"
        # The screen shows quantity x unit rate = amount; a lump sum that
        # disagrees with its own multiplication is visible on the invoice.
        assert Decimal(str(item.quantity)) * Decimal(str(item.unit_rate)) == amount, item.description

    subtotal = sum(amounts, Decimal("0"))
    assert Decimal(str(invoice.amount_subtotal)) == subtotal, "the net total is not the sum of the lines (BR-CO-10)"

    # The engine derives the VAT group from the lines and the declared rate, so
    # the stored tax has to be exactly that or BR-CO-17 refuses the document.
    vat_rate = Decimal(str(((invoice.metadata_ or {}).get("einvoice") or {}).get("vat_rate")))
    assert vat_rate == Decimal("19"), "the German showcase is a standard-rated invoice"
    expected_tax = (subtotal * vat_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(invoice.tax_amount)) == expected_tax, "the stored VAT is not 19% of the net total (BR-CO-17)"
    assert Decimal(str(invoice.amount_total)) == subtotal + expected_tax, "gross is not net plus VAT (BR-CO-15)"
    assert (subtotal + expected_tax) % Decimal("10000") != 0, "the gross total landed on a round figure"
