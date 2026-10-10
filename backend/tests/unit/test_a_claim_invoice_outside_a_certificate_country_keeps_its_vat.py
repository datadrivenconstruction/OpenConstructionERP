# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A claim invoice in a country without a payment certificate layout is untouched.

Where a project's country has a payment certificate (hakediş) layout, the
invoice raised from a certified claim takes its VAT from the claim's confirmed
statutory taxes. Everywhere else the invoice is computed as it always was: the
contract's own ``metadata.einvoice.vat_rate`` on the gross, rounded half up to
two decimals, no statutory calculation consulted.

The figures below were captured from the code before the certificate path was
added, and are pinned as literals rather than recomputed, so a change to the
old arithmetic fails here instead of moving with it. The rates are invented.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, ProgressClaim
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="owner-keeps-vat@test.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        yield s


async def _certified_claim(s, *, country: str, currency: str, gross: str, retention: str, einvoice: dict | None):
    project = Project(
        id=uuid.uuid4(),
        name=f"Keeps its VAT {country}",
        owner_id=OWNER_ID,
        currency=currency,
        country_code=country,
        status="active",
    )
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency=currency,
        retention_percent=Decimal("0"),
        status="active",
        terms={},
        metadata_={"einvoice": einvoice} if einvoice else {},
    )
    s.add(contract)
    await s.flush()
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=f"PC-{uuid.uuid4().hex[:4]}",
        claim_date="2026-06-01",
        gross_amount=Decimal(gross),
        retention_amount=Decimal(retention),
        net_due=Decimal(gross) - Decimal(retention),
        currency=currency,
        status="certified",
    )
    s.add(claim)
    await s.flush()
    return claim


@pytest.mark.parametrize(
    ("country", "currency", "gross", "retention", "einvoice", "tax", "total"),
    [
        # 12345.67 x 7.5% = 925.92525, half up to the cent.
        (
            "DE",
            "EUR",
            "12345.67",
            "617.28",
            {"vat_rate": "7.5", "buyer_reference": "04011000-1234512345-06"},
            "925.93",
            "13271.60",
        ),
        # 2000.10 x 12.25% = 245.01225.
        ("GB", "GBP", "2000.10", "0", {"vat_rate": "12.25"}, "245.01", "2245.11"),
        # No rate agreed on the contract: no VAT is invented.
        ("DE", "EUR", "5000.00", "250.00", None, "0", "5000.00"),
        ("GB", "GBP", "5000.00", "0", {"buyer_reference": "PO-7"}, "0", "5000.00"),
    ],
)
@pytest.mark.asyncio
async def test_the_vat_of_a_claim_invoice_is_the_contract_rate_on_the_gross(
    session, country, currency, gross, retention, einvoice, tax, total
) -> None:
    claim = await _certified_claim(
        session, country=country, currency=currency, gross=gross, retention=retention, einvoice=einvoice
    )

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)

    assert invoice.currency_code == currency
    assert Decimal(str(invoice.amount_subtotal)) == Decimal(gross)
    assert Decimal(str(invoice.tax_amount)) == Decimal(tax)
    assert Decimal(str(invoice.amount_total)) == Decimal(total)
    assert Decimal(str(invoice.retention_amount)) == Decimal(retention)
    assert invoice.source_claim_id == claim.id
    assert (invoice.metadata_ or {}).get("einvoice") == (einvoice or None)
    # Nothing certificate-specific leaks onto an invoice outside that path.
    assert "tax_source" not in (invoice.metadata_ or {})
