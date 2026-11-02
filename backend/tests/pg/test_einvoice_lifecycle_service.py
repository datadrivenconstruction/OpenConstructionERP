# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice lifecycle through the service: consolidation, hash chain, export mode, setup gate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.einvoice_clearance import service
from app.modules.einvoice_clearance.models import EInvoiceProfile
from app.modules.einvoice_clearance.regimes import COUNTRY_REGIMES
from app.modules.finance.models import Invoice

pytestmark = pytest.mark.asyncio


async def _profile(session, country: str, **extra) -> EInvoiceProfile:
    regime = COUNTRY_REGIMES[country]
    profile = EInvoiceProfile(
        company_key=f"co-{uuid.uuid4().hex[:8]}",
        country=country,
        regime=regime.regime,
        platform=regime.platform,
        tax_registration_id="310122393500003",
        certificate_reference="vault:csid/egs-1",
        adapter_key="reference",
        mode="export",
        **extra,
    )
    session.add(profile)
    await session.flush()
    return profile


async def _sale(session, project_id, number: str, day: str, net: str, tax: str) -> Invoice:
    invoice = Invoice(
        project_id=project_id,
        invoice_direction="receivable",
        invoice_number=number,
        invoice_date=day,
        currency_code="MYR",
        amount_subtotal=Decimal(net),
        tax_amount=Decimal(tax),
        retention_amount=Decimal("0"),
        amount_total=Decimal(net) + Decimal(tax),
        status="draft",
        metadata_={},
    )
    session.add(invoice)
    await session.flush()
    return invoice


async def test_consolidated_document_groups_eligible_receipts(pg_session):
    project_id = uuid.uuid4()
    profile = await _profile(pg_session, "MY", settings={"annual_turnover": "40000000"})
    await _sale(pg_session, project_id, "R-1", "2026-10-03", "613.00", "49.04")
    await _sale(pg_session, project_id, "R-2", "2026-10-30", "220.00", "0")
    await _sale(pg_session, project_id, "R-BIG", "2026-10-15", "12400.00", "0")
    await _sale(pg_session, project_id, "R-NOV", "2026-11-01", "50.00", "0")

    preview = await service.consolidated_preview(pg_session, profile=profile, project_id=project_id, period="2026-10")
    assert preview["count"] == 2
    assert preview["total"] == "882.04"
    assert preview["due_date"] == "2026-11-07"
    assert [(r["number"], r["reason"]) for r in preview["excluded"]] == [("R-BIG", "over_cap")]

    document, _findings = await service.create_consolidated(
        pg_session, profile=profile, project_id=project_id, period="2026-10"
    )
    assert document.document_kind == "consolidated"
    assert document.period == "2026-10"
    assert document.total_amount == Decimal("882.04")
    assert document.country_fields["buyer_tin"] == "EI00000000010"

    view = service.lifecycle_view(document, profile, now=datetime(2026, 11, 8, tzinfo=UTC))
    assert "EINV-MY-001" in [f["rule_id"] for f in view["findings"]]
    assert view["has_consolidation"] is True
    assert view["allowed_actions"] == ["validate", "download"]


async def test_saudi_documents_chain_their_hashes(pg_session):
    profile = await _profile(pg_session, "SA", settings={"seller_name": "Bobs Records"})
    genesis = COUNTRY_REGIMES["SA"].lifecycle["hash_chain"]["genesis"]

    def body(number: str):
        return SimpleNamespace(
            project_id=uuid.uuid4(),
            invoice_id=None,
            invoice_number=number,
            invoice_date="2026-03-10T09:00:00",
            currency_code="SAR",
            total_amount="5290.00",
            country_fields={"vat_total": "690.00"},
            payload=f"<Invoice><ID>{number}</ID></Invoice>",
            payload_media_type="application/xml",
            document_kind="simplified",
        )

    first, _ = await service.create_document(pg_session, profile=profile, body=body("SIM-1"))
    second, _ = await service.create_document(pg_session, profile=profile, body=body("SIM-2"))
    assert first.previous_hash == genesis
    assert second.previous_hash == first.country_fields["invoice_hash"]
    assert second.country_fields["qr"]

    with pytest.raises(service.ClearanceError, match="Export only"):
        await service.submit_document(pg_session, document=second, profile=profile)


async def test_setup_rows_list_only_active_registrations(pg_session):
    await _profile(pg_session, "MY")
    rows = {row["country"]: row for row in await service.setup_rows(pg_session)}
    assert rows["MY"]["mode"] == "export"
    assert rows["MY"]["has_consolidation"] is True
    assert "DE" not in rows or rows["DE"]["platform"]
