# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A Turkish sales invoice through the real finance routes: report, file, refusal.

What only a database can show:

* the export reads the statutory taxes stored for the invoice (or for the
  claim it was raised from) and writes nothing, so a GET stays a read;
* an invoice raised from a certified claim carries the VAT the certificate's
  confirmed taxes show, and is refused while they are not confirmed;
* a caller from another project gets the 404 the rest of the platform gives.

Every rate row is synthetic and injected, every party and tax number is
invented, and no assertion states what any country charges. The certificate's
statutory taxes are stored and confirmed here directly through the tax
module's service; the contracts module's own adapter for that is exercised by
its own tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.payment_taxes import Choice, RateRow
from app.modules.einvoice.tr_mapper import tr_invoice_uuid
from app.modules.einvoice.ubl import CAC, CBC, INV

pytestmark = pytest.mark.asyncio

NS = {"inv": INV, "cac": CAC, "cbc": CBC}
BASE = "/api/v1/finance"

SUPPLIER_VKN = "1112223339"
CUSTOMER_VKN = "9876543217"

# Invented. The code and fraction pair exists in the published code list, which
# is all the document rules ask of it; neither is a statement of the law.
RATE = Decimal("18.5")
WH_CODE = "601"

ROWS: tuple[RateRow, ...] = (
    RateRow(
        country_code="TR",
        kind="vat_withholding",
        code=WH_CODE,
        labels={"en": "Synthetic work", "tr": "Sentetik iş"},
        base="vat",
        rate_pct=None,
        numerator=4,
        denominator=10,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        legal_reference="Synthetic Act art. 1",
        source_url="https://example.invalid/act/1",
        read_date="2026-01-01",
        review_status="confirmed",
    ),
)

SELLER = {
    "name": "Örnek Mekanik Tesisat Taahhüt A.Ş.",
    "tax_number": SUPPLIER_VKN,
    "tax_office": "Çankaya",
    "line1": "Şehit Öğretmen Caddesi",
    "building_number": "12/A",
    "district": "Çankaya",
    "city": "Ankara",
    "postcode": "06690",
    "country_code": "TR",
}


@dataclass
class World:
    session: object
    app: FastAPI
    owner_id: uuid.UUID
    project_id: uuid.UUID
    outsider_id: uuid.UUID
    acting: dict

    def act_as(self, user_id: uuid.UUID, role: str = "manager") -> None:
        self.acting.clear()
        self.acting.update({"sub": str(user_id), "role": role})

    def client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")


@pytest_asyncio.fixture
async def world(pg_session, monkeypatch) -> World:
    from app.dependencies import get_current_user_payload, get_session
    from app.modules import finance as finance_module
    from app.modules.contracts.validators import _register_claim_as_tax_source
    from app.modules.finance import einvoice_tr
    from app.modules.finance import router as finance_router
    from app.modules.finance.permissions import register_finance_permissions
    from app.modules.finance.validators import register_finance_rules
    from app.modules.projects.models import Project
    from app.modules.tax_withholding import router as tax_router
    from app.modules.tax_withholding.permissions import register_tax_withholding_permissions
    from app.modules.tax_withholding.validators import register_tax_withholding_rules
    from app.modules.users.models import User

    register_finance_permissions()
    register_finance_rules()
    register_tax_withholding_permissions()
    register_tax_withholding_rules()
    # The real owners, registered the way each module's startup does it: the
    # statutory routes refuse a source kind nobody owns.
    finance_module._register_invoice_tax_source()
    _register_claim_as_tax_source()
    monkeypatch.setattr(einvoice_tr, "_rate_rows", lambda tax_service, country: ROWS)

    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"efatura-owner-{tag}@reference.example", hashed_password="x", full_name="Owner")
    outsider = User(email=f"efatura-outsider-{tag}@reference.example", hashed_password="x", full_name="Outsider")
    pg_session.add_all([owner, outsider])
    await pg_session.flush()
    project = Project(name=f"Ankara MEP {tag}", owner_id=owner.id, currency="TRY", country_code="TR", status="active")
    pg_session.add(project)
    await pg_session.flush()

    app = FastAPI()
    app.include_router(finance_router.router, prefix=BASE)
    app.include_router(tax_router.router, prefix="/api/v1/tax-withholding")
    app.dependency_overrides[tax_router.statutory_row_source] = lambda: lambda country: ROWS
    acting: dict = {"sub": str(owner.id), "role": "manager"}

    async def current_session():
        yield pg_session

    app.dependency_overrides[get_session] = current_session
    app.dependency_overrides[get_current_user_payload] = lambda: dict(acting)
    return World(
        session=pg_session,
        app=app,
        owner_id=owner.id,
        project_id=project.id,
        outsider_id=outsider.id,
        acting=acting,
    )


async def _customer(session, **over: object):
    from app.modules.contacts.models import Contact

    base: dict[str, object] = {
        "contact_type": "client",
        "company_name": "Güneş Yapı İnşaat Sanayi ve Ticaret Ltd. Şti.",
        "party_kind": "legal_entity",
        "vat_number": CUSTOMER_VKN,
        "tax_office": "Zincirlikuyu",
        "country_code": "TR",
        "address": {
            "street": "Büyükdere Caddesi",
            "building_number": "100",
            "district": "Şişli",
            "city": "İstanbul",
            "postcode": "34394",
        },
        "is_active": True,
    }
    base.update(over)
    contact = Contact(**base)
    session.add(contact)
    await session.flush()
    return contact


async def _invoice(world: World, *, net: str = "1000.00", tr: dict | None = None, **over: object):
    from app.modules.finance.models import Invoice, InvoiceLineItem

    contact = await _customer(world.session)
    subtotal = Decimal(net)
    values: dict[str, object] = {
        "project_id": world.project_id,
        "contact_id": str(contact.id),
        "invoice_direction": "receivable",
        "invoice_number": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": "2026-10-09",
        "currency_code": "TRY",
        "amount_subtotal": subtotal,
        "tax_amount": Decimal("0"),
        "retention_amount": Decimal("0"),
        "amount_total": subtotal,
        "status": "draft",
        "metadata_": {"einvoice": {"seller": SELLER, "tr": tr if tr is not None else {"profile_id": "TICARIFATURA"}}},
    }
    values.update(over)
    invoice = Invoice(**values)
    world.session.add(invoice)
    await world.session.flush()
    world.session.add(
        InvoiceLineItem(
            invoice_id=invoice.id,
            description="Havalandırma kanalı montajı",
            unit="m",
            quantity=Decimal("10"),
            unit_rate=subtotal / 10,
            amount=subtotal,
            vat_rate=RATE,
            sort_order=0,
        )
    )
    await world.session.flush()
    await world.session.refresh(invoice)
    return invoice


async def _taxes(world: World, *, source_kind: str, source_id: uuid.UUID, net: str, confirm: bool = True):
    """Store (and confirm) statutory taxes through the tax module's own service."""
    from app.modules.tax_withholding import service as tax_service

    calc, lines = await tax_service.upsert_statutory(
        world.session,
        project_id=world.project_id,
        source_kind=source_kind,
        source_id=source_id,
        inputs=tax_service.StatutoryInputs(
            country_code="TR",
            currency_code="TRY",
            document_date=date(2026, 10, 9),
            net_amount=Decimal(net),
            vat_rate_pct=RATE,
            vat_withholding=Choice("selected", code=WH_CODE),
            income_withholding=Choice("not_applicable", reason="Synthetic: not on this document"),
            stamp_duty=Choice("not_applicable", reason="Synthetic: not on this document"),
        ),
        direction="borne_by_us",
        user_id=world.owner_id,
        row_source=lambda country: ROWS,
    )
    if confirm:
        lines, _findings = await tax_service.confirm_statutory(world.session, calc=calc, user_id=world.owner_id)
    return calc, tax_service.result_from_lines(lines)


async def _stored_calcs(session) -> int:
    from app.modules.tax_withholding.models import StatutoryTaxCalc

    return int(await session.scalar(select(func.count()).select_from(StatutoryTaxCalc)) or 0)


def _ids(report: dict, severity: str | None = None) -> list[str]:
    return [v["rule_id"] for v in report["violations"] if severity is None or v["severity"] == severity]


# ── the report ───────────────────────────────────────────────────────────────


async def test_without_stored_taxes_the_report_says_what_to_do_and_nothing_is_written(world: World) -> None:
    invoice = await _invoice(world)
    before = await _stored_calcs(world.session)

    async with world.client() as client:
        answer = await client.get(
            f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True}
        )

    assert answer.status_code == 200, answer.text
    report = answer.json()
    assert report["format"] == "ubl_tr"
    assert report["valid"] is False
    assert "OCE-TR-21" in _ids(report, "fatal")
    # Previewed with no choice made, so the withholding is held rather than guessed.
    assert "TR-HELD-01" in _ids(report, "fatal")
    assert report["tax_source"]["source_kind"] == "invoice"
    assert report["tax_source"]["source_id"] == str(invoice.id)
    assert report["tax_source"]["status"] == "not_stored"
    assert report["document"]["uuid"] == tr_invoice_uuid(invoice.id)
    assert report["document"]["signed"] is False
    for violation in report["violations"]:
        assert set(violation) == {"rule_id", "severity", "message", "term", "params"}
    # A dry run is a read.
    assert await _stored_calcs(world.session) == before


async def test_confirmed_taxes_give_a_clean_report_and_the_unsigned_file(world: World) -> None:
    invoice = await _invoice(world)
    _calc, result = await _taxes(world, source_kind="invoice", source_id=invoice.id, net="1000.00")
    invoice.tax_amount = result.vat_computed.amount
    invoice.amount_total = invoice.amount_subtotal + result.vat_computed.amount
    await world.session.flush()

    async with world.client() as client:
        dry = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True})
        file = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr"})

    report = dry.json()
    assert report["valid"] is True, report["problems"]
    assert report["tax_source"]["status"] == "confirmed"
    assert report["document"]["invoice_type"] == "TEVKIFAT"
    assert report["document"]["inferred"] == {"invoice_type": "TEVKIFAT"}
    # The document number is left to the integrator: said, and not a blocker.
    assert "TR-ID-01" in _ids(report, "warning")

    assert file.status_code == 200, file.text
    assert file.headers["content-type"].startswith("application/xml")
    assert "_ubl_tr.xml" in file.headers["content-disposition"]
    assert file.headers["x-einvoice-signed"] == "false"
    assert "TR-ID-01" in file.headers["x-einvoice-finding-ids"].split(",")
    root = ET.fromstring(file.content)
    assert root.findtext("cbc:UUID", namespaces=NS) == tr_invoice_uuid(invoice.id)
    assert root.findtext("cbc:InvoiceTypeCode", namespaces=NS) == "TEVKIFAT"
    # The buyer's tax office came from the contact's new column.
    assert (
        root.findtext("cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cac:TaxScheme/cbc:Name", namespaces=NS)
        == "Zincirlikuyu"
    )
    # The figures printed are the stored ones.
    payable = root.findtext("cac:LegalMonetaryTotal/cbc:PayableAmount", namespaces=NS)
    expected = Decimal("1000.00") + result.vat_computed.amount - result.vat_withheld.amount
    assert Decimal(payable) == expected


async def test_draft_taxes_block_the_file_and_the_refusal_names_the_reason(world: World) -> None:
    invoice = await _invoice(world)
    await _taxes(world, source_kind="invoice", source_id=invoice.id, net="1000.00", confirm=False)

    async with world.client() as client:
        dry = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True})
        file = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr"})

    assert "OCE-TR-22" in _ids(dry.json(), "fatal")
    assert file.status_code == 422
    assert "OCE-TR-22" in file.json()["detail"]
    assert "dry_run=true" in file.json()["detail"]


async def test_taxes_computed_on_other_figures_are_refused(world: World) -> None:
    invoice = await _invoice(world, net="1000.00")
    await _taxes(world, source_kind="invoice", source_id=invoice.id, net="900.00")

    async with world.client() as client:
        dry = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True})

    report = dry.json()
    assert "OCE-TR-27" in _ids(report, "fatal")
    stale = next(v for v in report["violations"] if v["rule_id"] == "OCE-TR-27")
    # Both figures are named, and the remedy does not assume which side is stale.
    assert "1000.00" in stale["message"] and "900.00" in stale["message"]
    assert "Set the invoice amounts" in stale["message"]
    assert stale["params"]["differences"]


async def test_a_supplier_invoice_is_not_an_e_fatura_we_issue(world: World) -> None:
    invoice = await _invoice(world, invoice_direction="payable")

    async with world.client() as client:
        dry = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True})

    assert "OCE-TR-29" in _ids(dry.json(), "fatal")


async def test_there_is_no_hybrid_pdf_of_an_e_fatura(world: World) -> None:
    invoice = await _invoice(world)
    async with world.client() as client:
        answer = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "embed": True})
    assert answer.status_code == 422


async def test_finance_owns_the_invoice_source_so_its_taxes_go_through_the_real_routes(world: World) -> None:
    """Stored and confirmed over HTTP, with finance's own resolver deciding whose invoice it is."""
    from app.modules.tax_withholding.source_owners import registered_source_kinds, resolve_source_project

    invoice = await _invoice(world)
    assert "invoice" in registered_source_kinds()
    assert await resolve_source_project(world.session, "invoice", invoice.id) == world.project_id
    assert await resolve_source_project(world.session, "invoice", uuid.uuid4()) is None

    statutory = f"/api/v1/tax-withholding/statutory/invoice/{invoice.id}"
    body = {
        "project_id": str(world.project_id),
        "direction": "borne_by_us",
        "source_reference": invoice.invoice_number,
        "country_code": "TR",
        "currency_code": "TRY",
        "document_date": "2026-10-09",
        "net_amount": "1000.00",
        "vat_rate_pct": str(RATE),
        "vat_withholding": {"state": "selected", "code": WH_CODE},
        "income_withholding": {"state": "not_applicable", "reason": "Synthetic: not on this document"},
        "stamp_duty": {"state": "not_applicable", "reason": "Synthetic: not on this document"},
    }
    async with world.client() as client:
        nobody = await client.put(f"/api/v1/tax-withholding/statutory/invoice/{uuid.uuid4()}", json=body)
        stored = await client.put(statutory, json=body)
        confirmed = await client.post(f"{statutory}/confirm", json={"project_id": str(world.project_id)})
        dry = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True})

    assert nobody.status_code == 404
    assert stored.status_code == 200, stored.text
    assert confirmed.status_code == 200, confirmed.text
    report = dry.json()
    assert report["tax_source"]["status"] == "confirmed"
    # Only the invoice's own VAT figure is still to be brought into line with them.
    assert set(_ids(report, "fatal")) <= {"OCE-TR-27"}


# ── the fields ───────────────────────────────────────────────────────────────


async def test_the_turkish_fields_are_written_whole_and_a_mistyped_key_is_refused(world: World) -> None:
    invoice = await _invoice(world, tr={})
    url = f"{BASE}/invoices/{invoice.id}/einvoice/tr"

    async with world.client() as client:
        typo = await client.put(url, json={"profil_id": "TICARIFATURA"})
        bad = await client.put(url, json={"profile_id": "NOT_A_SCENARIO"})
        good = await client.put(url, json={"profile_id": "temelfatura", "document_id": "ABC2026000000042"})
        read = await client.get(url)

    assert typo.status_code == 422
    assert bad.status_code == 422
    assert good.status_code == 200, good.text
    body = read.json()
    assert body["fields"]["profile_id"] == "TEMELFATURA"
    assert body["fields"]["document_id"] == "ABC2026000000042"
    assert body["uuid"] == tr_invoice_uuid(invoice.id)
    assert body["tax_source"]["source_kind"] == "invoice"
    assert body["line_ids"] == [str(item.id) for item in invoice.line_items]
    # The seller beside the block is untouched by the write.
    await world.session.refresh(invoice)
    assert invoice.metadata_["einvoice"]["seller"]["tax_number"] == SUPPLIER_VKN


async def test_the_invoice_patch_route_refuses_a_malformed_block_too(world: World) -> None:
    from app.modules.finance.schemas import InvoiceUpdate

    with pytest.raises(ValueError, match="profil_id"):
        InvoiceUpdate(metadata={"einvoice": {"tr": {"profil_id": "TICARIFATURA"}}})
    # Every other e-invoice key stays as free as it was.
    assert InvoiceUpdate(metadata={"einvoice": {"anything": {"goes": 1}}}).metadata is not None


async def test_a_block_stored_before_validation_is_reported_not_a_crash(world: World) -> None:
    invoice = await _invoice(world, tr={"profil_id": "TICARIFATURA"})

    async with world.client() as client:
        dry = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True})

    assert dry.status_code == 200
    assert "OCE-TR-20" in _ids(dry.json(), "fatal")


# ── the project boundary ─────────────────────────────────────────────────────


async def test_another_projects_user_reaches_none_of_it(world: World) -> None:
    invoice = await _invoice(world)
    world.act_as(world.outsider_id, "manager")

    async with world.client() as client:
        answers = [
            await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr", "dry_run": True}),
            await client.get(f"{BASE}/invoices/{invoice.id}/einvoice", params={"format": "ubl_tr"}),
            await client.get(f"{BASE}/invoices/{invoice.id}/einvoice/tr"),
            await client.put(f"{BASE}/invoices/{invoice.id}/einvoice/tr", json={"profile_id": "TEMELFATURA"}),
        ]

    assert [answer.status_code for answer in answers] == [answers[0].status_code] * 4
    assert answers[0].status_code in (403, 404)
    await world.session.refresh(invoice)
    assert invoice.metadata_["einvoice"]["tr"] == {"profile_id": "TICARIFATURA"}


async def test_a_viewer_reads_the_report_and_cannot_write_the_fields(world: World) -> None:
    invoice = await _invoice(world)
    world.act_as(world.owner_id, "viewer")

    async with world.client() as client:
        read = await client.get(f"{BASE}/invoices/{invoice.id}/einvoice/tr")
        write = await client.put(f"{BASE}/invoices/{invoice.id}/einvoice/tr", json={"profile_id": "TEMELFATURA"})

    assert read.status_code == 200
    assert write.status_code == 403


# ── the profile picker ───────────────────────────────────────────────────────


async def test_a_turkish_seller_is_offered_ubl_tr_first(world: World) -> None:
    from app.modules.finance.einvoice_settings_service import get_settings

    async with world.client() as client:
        before = (await client.get(f"{BASE}/einvoice-profiles")).json()
        settings = await get_settings(world.session)
        settings.seller_country_code = "TR"
        settings.seller_tax_office = "Çankaya"
        await world.session.flush()
        after = (await client.get(f"{BASE}/einvoice-profiles")).json()

    assert "ubl_tr" in [profile["key"] for profile in before["profiles"]]
    assert after["default"] == "ubl_tr"
    assert settings.as_defaults()["seller"]["tax_office"] == "Çankaya"


# ── certificate to invoice ───────────────────────────────────────────────────


async def _certified_claim(world: World, *, gross: str = "1000.00"):
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine

    contact = await _customer(world.session)
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Mekanik tesisat işleri",
        project_id=world.project_id,
        currency="TRY",
        retention_percent=Decimal("0"),
        status="active",
        terms={},
        counterparty_type="client",
        counterparty_id=contact.id,
        metadata_={"einvoice": {"seller": SELLER, "tr": {"profile_id": "TICARIFATURA"}}},
    )
    world.session.add(contract)
    await world.session.flush()
    sov = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01",
        description="Havalandırma kanalı montajı",
        unit="m",
        quantity=Decimal("100"),
        unit_rate=Decimal("100"),
        total_value=Decimal("10000"),
    )
    world.session.add(sov)
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=f"HK-{uuid.uuid4().hex[:4]}",
        claim_date="2026-10-09",
        gross_amount=Decimal(gross),
        retention_amount=Decimal("0"),
        net_due=Decimal(gross),
        currency="TRY",
        status="certified",
    )
    world.session.add(claim)
    await world.session.flush()
    world.session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=sov.id,
            period_completed_qty=Decimal("10"),
            period_completed_value=Decimal(gross),
        )
    )
    await world.session.flush()
    return claim


async def test_a_claim_invoice_waits_for_the_certificates_confirmed_taxes(world: World) -> None:
    from app.modules.finance.service import FinanceService

    claim = await _certified_claim(world)
    service = FinanceService(world.session)

    with pytest.raises(HTTPException) as nothing_stored:
        await service.create_receivable_from_claim(claim.id)
    assert nothing_stored.value.status_code == 409
    assert "have not been computed" in nothing_stored.value.detail

    await _taxes(world, source_kind="progress_claim", source_id=claim.id, net="1000.00", confirm=False)
    with pytest.raises(HTTPException) as draft:
        await service.create_receivable_from_claim(claim.id)
    assert draft.value.status_code == 409
    assert "not confirmed" in draft.value.detail
    assert await service.invoices.find_by_source_claim(claim.id) is None


async def test_a_certificate_taxed_on_another_amount_than_the_claim_gross_is_refused(world: World) -> None:
    """A price adjustment above the VAT line makes the taxed amount differ from the claim's lines."""
    from app.modules.finance.service import FinanceService

    claim = await _certified_claim(world, gross="1000.00")
    await _taxes(world, source_kind="progress_claim", source_id=claim.id, net="1080.00")
    service = FinanceService(world.session)

    with pytest.raises(HTTPException) as differs:
        await service.create_receivable_from_claim(claim.id)

    assert differs.value.status_code == 409
    assert "1080.00" in differs.value.detail
    assert "1000.00" in differs.value.detail
    assert await service.invoices.find_by_source_claim(claim.id) is None


async def test_the_invoice_of_a_certificate_carries_the_certificates_vat(world: World) -> None:
    from app.modules.finance.service import FinanceService
    from app.modules.finance.validators import evaluate_claim_invoice

    claim = await _certified_claim(world)
    _calc, result = await _taxes(world, source_kind="progress_claim", source_id=claim.id, net="1000.00")

    invoice = await FinanceService(world.session).create_receivable_from_claim(claim.id)

    # The same figure, not a second calculation of it.
    assert Decimal(str(invoice.tax_amount)) == result.vat_computed.amount
    assert Decimal(str(invoice.amount_total)) == Decimal("1000.00") + result.vat_computed.amount
    assert invoice.currency_code == "TRY"
    assert [Decimal(str(item.vat_rate)) for item in invoice.line_items] == [RATE]

    async with world.client() as client:
        url = f"{BASE}/invoices/{invoice.id}/einvoice"
        dry = (await client.get(url, params={"format": "ubl_tr", "dry_run": True})).json()
        file = await client.get(url, params={"format": "ubl_tr"})

    assert dry["tax_source"]["source_kind"] == "progress_claim"
    assert dry["tax_source"]["source_id"] == str(claim.id)
    assert dry["valid"] is True, dry["problems"]
    assert file.status_code == 200, file.text
    root = ET.fromstring(file.content)
    printed = root.findtext("cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount", namespaces=NS)
    assert Decimal(printed) == result.vat_computed.amount

    record = {
        "invoice_number": invoice.invoice_number,
        "currency_code": invoice.currency_code,
        "amount_subtotal": str(invoice.amount_subtotal),
        "tax_amount": str(invoice.tax_amount),
        "certificate": {
            "currency_code": "TRY",
            "net_amount": "1000.00",
            "vat_computed": str(result.vat_computed.amount),
        },
    }
    assert await evaluate_claim_invoice(record) == []

    # An invoice edited away from its certificate is an error in both places.
    invoice.tax_amount = result.vat_computed.amount + Decimal("1.00")
    await world.session.flush()
    async with world.client() as client:
        changed = (await client.get(url, params={"format": "ubl_tr", "dry_run": True})).json()
    assert "OCE-TR-23" in _ids(changed, "fatal")
    failures = await evaluate_claim_invoice({**record, "tax_amount": str(invoice.tax_amount)})
    assert [failure.rule_id for failure in failures] == ["finance.invoice_agrees_with_certificate"]
