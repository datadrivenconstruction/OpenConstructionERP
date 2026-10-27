# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync against a real PostgreSQL database with a mocked Xero.

Each test asks one question across finance, contacts, guarantees and the sync:
is a push idempotent, does a blocked document never reach the ledger, does a
retry clear a failure, does a pulled payment mark the invoice paid, and do the
DATEV and journal exports carry the project's documents.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.crypto import decrypt_secret
from app.modules.accounting_sync import service as svc_mod
from app.modules.accounting_sync.demo import seed_demo_accounting_sync
from app.modules.accounting_sync.models import ExternalRef, SyncLogEntry
from app.modules.accounting_sync.postings import build_journal
from app.modules.accounting_sync.service import AccountingSyncService
from app.modules.contacts.models import Contact
from app.modules.finance.models import Invoice, InvoiceLineItem, Payment
from app.modules.guarantees.models import Guarantee
from app.modules.payroll.models import PayrollBatch
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine


@pytest.fixture(autouse=True)
def _rules_registered():
    from app.modules.accounting_sync.validators import register_accounting_sync_rules

    register_accounting_sync_rules()


class FakeXero:
    """Minimal in-memory Xero: contacts, tracking, invoices, payments."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.invoices: dict[str, dict] = {}
        self.payments: list[dict] = []
        self.fail_next: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.fail_next and path.endswith("/Invoices"):
            msg, self.fail_next = self.fail_next, None
            return httpx.Response(400, json={"Elements": [{"ValidationErrors": [{"Message": msg}]}]})
        if path.endswith("/Contacts"):
            return httpx.Response(
                200, json={"Contacts": [{"ContactID": "C-" + json.loads(request.content)["Contacts"][0]["Name"][:3]}]}
            )
        if path.endswith("/TrackingCategories") and request.method == "GET":
            return httpx.Response(
                200, json={"TrackingCategories": [{"Name": "Project", "TrackingCategoryID": "TC", "Options": []}]}
            )
        if path.endswith("/Options"):
            return httpx.Response(200, json={"Options": [{"TrackingOptionID": "OPT-1"}]})
        if path.endswith("/Invoices"):
            inv = json.loads(request.content)["Invoices"][0]
            inv_id = inv.get("InvoiceID") or f"X-{len(self.invoices) + 1}"
            total = sum(
                Decimal(li["UnitAmount"]) * (Decimal("1.19") if li["TaxType"] else 1) for li in inv["LineItems"]
            )
            self.invoices[inv_id] = inv
            return httpx.Response(
                200, json={"Invoices": [{"InvoiceID": inv_id, "Total": str(total.quantize(Decimal("0.01")))}]}
            )
        if path.endswith("/Payments"):
            return httpx.Response(200, json={"Payments": self.payments})
        return httpx.Response(404, json={})


async def _all_ids(svc: AccountingSyncService, conn) -> set[str]:
    """Every document in scope, as if the user ticked them all after review."""
    return {d.record_id for d in await svc.documents(conn) if d.source != "payroll"}


@pytest_asyncio.fixture
async def ctx(monkeypatch):
    fake = FakeXero()
    monkeypatch.setattr(svc_mod, "transport_factory", lambda _p: httpx.MockTransport(fake))
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            owner = User(email=f"o-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
            session.add(owner)
            await session.flush()
            project = Project(name="Riverside", owner_id=owner.id, project_code="P-100", country_code="DE")
            session.add(project)
            client = Contact(
                contact_type="client", company_name="Müller Bau GmbH", vat_number="DE123456789", country_code="DE"
            )
            sub = Contact(contact_type="subcontractor", company_name="Steelworks AG")
            session.add_all([client, sub])
            await session.flush()
            ar = Invoice(
                project_id=project.id, contact_id=str(client.id), invoice_direction="receivable",
                invoice_number="AR-001", invoice_date="2026-03-31", currency_code="EUR",
                amount_subtotal=Decimal("10000.00"), tax_amount=Decimal("1900.00"), amount_total=Decimal("11900.00"),
                status="approved", source_claim_id=uuid.uuid4(),
            )  # fmt: skip
            ap = Invoice(
                project_id=project.id, contact_id=str(sub.id), invoice_direction="payable",
                invoice_number="SUB-17", invoice_date="2026-04-02", currency_code="EUR",
                amount_subtotal=Decimal("5000.10"), tax_amount=Decimal("950.02"), amount_total=Decimal("5950.12"),
                status="approved", metadata_={"source": "subcontract_payment_application"},
            )  # fmt: skip
            session.add_all([ar, ap])
            await session.flush()
            session.add(
                InvoiceLineItem(invoice_id=ar.id, description="Interim payment 3", quantity=Decimal("1"),
                                unit_rate=Decimal("10000"), amount=Decimal("10000.00"), vat_rate=Decimal("19"))
            )  # fmt: skip
            session.add(
                Guarantee(project_id=project.id, reference="PB-1", guarantee_type="performance_bond", status="issued",
                          issuer_bank="Northbridge Bank", amount=Decimal("1000000"), original_amount=Decimal("1000000"),
                          currency="EUR", commission_rate_pct=Decimal("0.75"), issue_date=date(2026, 2, 1))
            )  # fmt: skip
            await session.flush()
            svc = AccountingSyncService(session)
            conn = await svc.create_connection(
                {"name": "Xero test", "provider": "xero", "country_code": "DE", "chart_template": "DE-SKR03",
                 "client_id": "cid", "client_secret": "s3cret", "external_tenant_id": "T1"},
                str(owner.id),
            )  # fmt: skip
            conn.tokens_enc = svc_mod.encrypt_secret(
                json.dumps({"access_token": "AT", "refresh_token": "RT", "expires_at": 9e12})
            )
            conn.status = "connected"
            await session.flush()
            yield session, svc, conn, fake, ar, ap, project


@pytest.mark.asyncio
async def test_secret_is_stored_encrypted(ctx) -> None:
    _session, _svc, conn, *_ = ctx
    assert conn.client_secret_enc != "s3cret" and decrypt_secret(conn.client_secret_enc) == "s3cret"


@pytest.mark.asyncio
async def test_documents_cover_ipc_subcontractor_and_guarantee_fee(ctx) -> None:
    _session, svc, conn, *_ = ctx
    docs = {d.number: d for d in await svc.documents(conn)}
    assert docs["AR-001"].source == "interim_payment" and docs["AR-001"].project_code == "P-100"
    assert docs["SUB-17"].source == "subcontractor" and docs["SUB-17"].lines[0].category == "subcontract_cost"
    assert docs["SUB-17"].lines[0].tax_code == "VAT" and docs["SUB-17"].gross_total == Decimal("5950.12")
    fee = docs["GF-PB-1-2026"]
    assert fee.source == "guarantee_fee" and fee.gross_total == Decimal("7500.00")


@pytest.mark.asyncio
async def test_push_is_idempotent_and_logs_each_record(ctx) -> None:
    session, svc, conn, fake, ar, *_ = ctx
    first = await svc.push(conn, record_ids=await _all_ids(svc, conn))
    assert first == {"success": 3, "failed": 0, "skipped": 0}
    posts = [r for r in fake.requests if r.url.path.endswith("/Invoices")]
    assert len(posts) == 3
    again = await svc.push(conn, record_ids=await _all_ids(svc, conn))
    assert again == {"success": 0, "failed": 0, "skipped": 3}
    assert len([r for r in fake.requests if r.url.path.endswith("/Invoices")]) == 3
    ref = (await session.execute(select(ExternalRef).where(ExternalRef.record_id == str(ar.id)))).scalar_one()
    ar.notes = "changed"
    await session.flush()
    line = (await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == ar.id))).scalar_one()
    line.description = "Interim payment 3 (revised)"
    await session.flush()
    await svc.push(conn, record_ids=await _all_ids(svc, conn))
    last = fake.invoices[ref.external_id]
    assert last["InvoiceID"] == ref.external_id  # update, not a duplicate
    assert len(fake.invoices) == 3


@pytest.mark.asyncio
async def test_closed_period_blocks_without_calling_the_ledger_and_retry_clears_it(ctx) -> None:
    session, svc, conn, fake, ar, *_ = ctx
    conn.lock_date = date(2026, 3, 31)
    counts = await svc.push(conn, record_ids={str(ar.id)})
    assert counts["failed"] == 1 and not [r for r in fake.requests if r.url.path.endswith("/Invoices")]
    entry = (await session.execute(select(SyncLogEntry).where(SyncLogEntry.status == "failed"))).scalar_one()
    assert "closed through 2026-03-31" in entry.error_reason
    conn.lock_date = date(2026, 1, 31)
    assert await svc.retry(entry) == "success"
    await session.refresh(entry)
    assert entry.resolved


@pytest.mark.asyncio
async def test_provider_failure_is_logged_with_reason_and_attempts_count(ctx) -> None:
    session, svc, conn, fake, ar, *_ = ctx
    fake.fail_next = "Account code '8400' is not a valid code"
    await svc.push(conn, record_ids={str(ar.id)})
    fake.fail_next = "Account code '8400' is not a valid code"
    await svc.push(conn, record_ids={str(ar.id)})
    rows = list((await session.execute(select(SyncLogEntry).order_by(SyncLogEntry.attempt))).scalars())
    assert [r.attempt for r in rows] == [1, 2] and "not a valid code" in rows[1].error_reason
    status = await svc.status_summary()
    assert status["open_failures"] == 2


@pytest.mark.asyncio
async def test_findings_flag_unmapped_account_and_missing_tax_id(ctx) -> None:
    _session, svc, conn, *_ = ctx
    await svc.set_account_mappings(conn, [{"category": "subcontract_cost", "account_code": "", "account_name": ""}])
    ids = {f["rule_id"] for f in await svc.findings(conn)}
    assert "accounting_sync.unmapped_account" in ids
    assert "accounting_sync.contact_missing_tax_id" in ids  # Steelworks AG has no VAT number


@pytest.mark.asyncio
async def test_pulled_payment_marks_the_invoice_paid_once(ctx) -> None:
    session, svc, conn, fake, ar, *_ = ctx
    await svc.push(conn, record_ids={str(ar.id)})
    ext = (
        (await session.execute(select(ExternalRef).where(ExternalRef.record_id == str(ar.id)))).scalar_one().external_id
    )
    fake.payments = [{"PaymentID": "P-1", "Amount": "11900.00", "Date": "2026-04-20", "Invoice": {"InvoiceID": ext}}]
    assert (await svc.pull_payments(conn))["success"] == 1
    assert (await svc.pull_payments(conn))["skipped"] == 1
    pays = list((await session.execute(select(Payment).where(Payment.invoice_id == ar.id))).scalars())
    assert len(pays) == 1 and pays[0].amount == Decimal("11900.00")
    await session.refresh(ar)
    assert ar.status == "paid"


@pytest.mark.asyncio
async def test_datev_and_journal_exports_from_a_file_connection(ctx) -> None:
    _session, svc, _conn, _fake, _ar, _ap, project = ctx
    datev_conn = await svc.create_connection(
        {"name": "DATEV", "provider": "datev", "country_code": "DE", "project_ids": [project.id],
         "settings": {"consultant_number": "1001", "client_number": "1"}}
    )  # fmt: skip
    assert datev_conn.chart_template == "DE-SKR03"
    period = (date(2026, 1, 1), date(2026, 12, 31))
    content, name, media = await svc.export(datev_conn, "datev_postings", period)
    rows = content.decode("cp1252").split("\r\n")
    assert name.startswith("EXTF_Buchungsstapel_") and "windows-1252" in media
    assert any('"AR-001"' in r and ";8400;" in r for r in rows)
    assert any('"SUB-17"' in r and ";3100;" in r and '"P-100"' in r for r in rows)
    content, _, _ = await svc.export(datev_conn, "journal_csv", period, ["document_number", "account", "debit"])
    assert "AR-001,1400,11900.00" in content.decode("utf-8")
    saft_xml, _, _ = await svc.export(datev_conn, "saft", period)
    assert b"<TotalDebit>" in saft_xml


@pytest.mark.asyncio
async def test_demo_seeds_a_success_and_a_failure_and_a_datev_connection(ctx) -> None:
    session, svc, _conn, _fake, _ar, _ap, project = ctx
    written = await seed_demo_accounting_sync(session, project_id=project.id, currency="EUR")
    assert written >= 2
    names = {c.name: c for c in await svc.list_connections()}
    live = names["Demo ledger (sandbox)"]
    statuses = {e.status for e in (await svc.list_log(live))[0]}
    assert statuses == {"success", "failed"}
    datev_conn = names["DATEV export (SKR03)"]
    content, _, _ = await svc.export(datev_conn, "datev_postings", (date(2026, 1, 1), date(2026, 12, 31)))
    assert content.startswith(b'"EXTF";700;21;')


@pytest.mark.asyncio
async def test_push_needs_reviewed_documents(ctx) -> None:
    _session, svc, conn, fake, *_ = ctx
    with pytest.raises(HTTPException):
        await svc.push(conn, record_ids=set())
    assert not fake.requests


@pytest.mark.asyncio
async def test_approved_payroll_posts_to_wages_payable(ctx) -> None:
    session, svc, conn, _fake, _ar, _ap, project = ctx
    session.add(
        PayrollBatch(project_id=project.id, period_label="2026-W14", period_end="2026-04-05", status="approved",
                     currency="EUR", total_amount="4200.00")
    )  # fmt: skip
    session.add(PayrollBatch(project_id=project.id, period_label="draft", status="draft", total_amount="99"))
    await session.flush()
    docs = [d for d in await svc.documents(conn) if d.source == "payroll"]
    assert len(docs) == 1 and docs[0].gross_total == Decimal("4200.00")
    lines = build_journal(docs[0], await svc.mapping(conn))
    accounts = {ln.account: (ln.debit, ln.credit) for ln in lines}
    assert accounts["4110"][0] == Decimal("4200.00")
    assert accounts["1740"][1] == Decimal("4200.00")
