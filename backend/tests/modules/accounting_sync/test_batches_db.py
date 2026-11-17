# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export batches against a real PostgreSQL database: numbering, idempotency, one active batch per record,
concurrent creates, tenant isolation, import and reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.accounting_sync.batches import BatchParams, BatchService
from app.modules.accounting_sync.export_validators import register_export_rules
from app.modules.accounting_sync.ledger_import import LedgerImportService, reconcile
from app.modules.accounting_sync.models import AccountMapping, BatchItem, ExportBatch
from app.modules.accounting_sync.service import AccountingSyncService
from app.modules.accounting_sync.validators import register_accounting_sync_rules
from app.modules.contacts.models import Contact
from app.modules.finance.models import Invoice, InvoiceLineItem, ProjectBudget
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine

PERIOD = (date(2026, 1, 1), date(2026, 12, 31))
SETTINGS = {"consultant_number": "1001", "client_number": "20002", "fiscal_year_start": "20260101"}


def _params(fmt: str = "datev", types: tuple[str, ...] = ("ar_invoice", "ap_bill")) -> BatchParams:
    return BatchParams(fmt=fmt, period=PERIOD, record_types=list(types))


@pytest.fixture(autouse=True)
def _rules():
    register_accounting_sync_rules()
    register_export_rules()


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            owner = User(email=f"o-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
            session.add(owner)
            await session.flush()
            project = Project(name="Riverside", owner_id=owner.id, project_code="P-100", country_code="DE")
            client = Contact(
                contact_type="client", company_name="Mueller Bau GmbH", vat_number="DE811128135", country_code="DE"
            )
            sub = Contact(contact_type="subcontractor", company_name="Steelworks AG", country_code="DE")
            session.add_all([project, client, sub])
            await session.flush()
            ar = Invoice(
                project_id=project.id, contact_id=str(client.id), invoice_direction="receivable",
                invoice_number="AR-001", invoice_date="2026-03-31", currency_code="EUR",
                amount_subtotal=Decimal("10000.00"), tax_amount=Decimal("1900.00"), amount_total=Decimal("11900.00"),
                status="approved",
            )  # fmt: skip
            ap = Invoice(
                project_id=project.id, contact_id=str(sub.id), invoice_direction="payable",
                invoice_number="SUB-17", invoice_date="2026-04-02", currency_code="EUR",
                amount_subtotal=Decimal("5000.10"), tax_amount=Decimal("950.02"), amount_total=Decimal("5950.12"),
                status="approved",
            )  # fmt: skip
            session.add_all([ar, ap])
            await session.flush()
            for inv, text, amt in ((ar, "Interim payment 3", "10000.00"), (ap, "Structural steel", "5000.10")):
                session.add(
                    InvoiceLineItem(
                        invoice_id=inv.id, description=text, quantity=Decimal("1"), unit_rate=Decimal(amt),
                        amount=Decimal(amt), vat_rate=Decimal("19"),
                    )
                )  # fmt: skip
            session.add(
                ProjectBudget(project_id=project.id, category="concrete", currency_code="EUR",
                              original_budget=Decimal("1000"), revised_budget=Decimal("1200"))
            )  # fmt: skip
            svc = AccountingSyncService(session)
            conn = await svc.create_connection(
                {"name": "DATEV A", "provider": "datev", "country_code": "DE", "chart_template": "DE-SKR03",
                 "settings": dict(SETTINGS)},
                str(owner.id),
            )  # fmt: skip
            conn_b = await svc.create_connection(
                {"name": "DATEV B", "provider": "datev", "country_code": "DE", "chart_template": "DE-SKR03",
                 "settings": dict(SETTINGS)},
                str(owner.id),
            )  # fmt: skip
            await session.commit()
            yield factory, conn.id, conn_b.id, str(owner.id)


async def _conn(session: AsyncSession, conn_id: uuid.UUID):
    return await AccountingSyncService(session).get_connection(conn_id)


@pytest.mark.asyncio
async def test_batch_is_numbered_hashed_and_blocks_a_second_export_until_voided(world) -> None:
    factory, a, _b, user = world
    async with factory() as s:
        conn, svc = await _conn(s, a), BatchService(s)
        first, created = await svc.create(conn, _params(), key=None, user_id=user)
        await s.commit()
        assert created and first.batch_no == 1 and first.row_count == 2 and first.status == "exported"
        assert first.sha256 == hashlib.sha256(first.content).hexdigest() and len(first.sha256) == 64
        assert first.total_gross == Decimal("17850.12") and first.media_type.endswith("windows-1252")
        preview = await svc.preview(conn, _params())
        again = [f for f in preview["findings"] if f["rule_id"] == "accounting_export.already_exported"]
        assert len(again) == 2 and again[0]["params"]["batch"] == 1 and preview["errors"] >= 2
        with pytest.raises(HTTPException) as err:
            await svc.create(conn, _params(), key=None, user_id=user)
        assert err.value.status_code == 409
        voided = await svc.void(conn, await svc.get(conn, first.id), "Wrong period", user)
        await s.commit()
        assert voided.status == "voided" and voided.void_reason == "Wrong period"
        items = (await s.execute(select(BatchItem).where(BatchItem.batch_id == first.id))).scalars().all()
        assert items and not any(i.active for i in items)
        second, _ = await svc.create(conn, _params(), key=None, user_id=user)
        await s.commit()
        assert second.batch_no == 2 and second.sha256 != "" and second.id != first.id


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_the_same_batch(world) -> None:
    factory, a, _b, user = world
    async with factory() as s:
        conn, svc = await _conn(s, a), BatchService(s)
        one, c1 = await svc.create(conn, _params(), key="k-1", user_id=user)
        await s.commit()
        two, c2 = await svc.create(conn, _params(), key="k-1", user_id=user)
        assert (c1, c2) == (True, False) and one.id == two.id
        count = (await s.execute(select(ExportBatch).where(ExportBatch.connection_id == a))).scalars().all()
        assert len(count) == 1


@pytest.mark.asyncio
async def test_concurrent_creates_with_one_key_give_one_batch(world) -> None:
    factory, a, _b, user = world

    async def attempt() -> tuple[uuid.UUID, bool]:
        async with factory() as s:
            batch, created = await BatchService(s).create(await _conn(s, a), _params(), key="same", user_id=user)
            await s.commit()
            return batch.id, created

    results = await asyncio.gather(*(attempt() for _ in range(4)))
    assert len({r[0] for r in results}) == 1 and sum(1 for r in results if r[1]) == 1
    async with factory() as s:
        rows = (await s.execute(select(ExportBatch).where(ExportBatch.connection_id == a))).scalars().all()
        assert len(rows) == 1 and rows[0].batch_no == 1


@pytest.mark.asyncio
async def test_concurrent_creates_without_a_key_still_export_each_record_once(world) -> None:
    factory, a, _b, user = world

    async def attempt() -> str:
        async with factory() as s:
            try:
                await BatchService(s).create(await _conn(s, a), _params(), key=None, user_id=user)
                await s.commit()
                return "created"
            except HTTPException as exc:
                await s.rollback()
                return str(exc.status_code)

    results = await asyncio.gather(*(attempt() for _ in range(3)))
    assert results.count("created") == 1 and results.count("409") == 2
    async with factory() as s:
        assert len((await s.execute(select(ExportBatch))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_a_batch_belongs_to_its_connection_only(world) -> None:
    factory, a, b, user = world
    async with factory() as s:
        batch, _ = await BatchService(s).create(await _conn(s, a), _params(), key=None, user_id=user)
        await s.commit()
        conn_b, svc = await _conn(s, b), BatchService(s)
        with pytest.raises(HTTPException) as err:
            await svc.get(conn_b, batch.id)
        assert err.value.status_code == 404
        assert (await svc.page(conn_b, offset=0, limit=10))[1] == 0
        mine, _ = await svc.create(conn_b, _params(), key=None, user_id=user)  # the same records, another ledger
        await s.commit()
        assert mine.batch_no == 1 and mine.id != batch.id


@pytest.mark.asyncio
async def test_unmapped_account_is_a_red_finding_and_blocks_the_batch(world) -> None:
    factory, a, _b, user = world
    async with factory() as s:
        conn, svc = await _conn(s, a), BatchService(s)
        row = (
            await s.execute(
                select(AccountMapping).where(
                    AccountMapping.connection_id == a, AccountMapping.category == "subcontract_cost"
                )
            )
        ).scalar_one()
        row.account_code = ""
        await s.flush()
        preview = await svc.preview(conn, _params())
        red = [f for f in preview["findings"] if f["rule_id"] == "accounting_sync.unmapped_account"]
        assert red and red[0]["severity"] == "error" and "subcontract_cost" in red[0]["message"]
        with pytest.raises(HTTPException) as err:
            await svc.create(conn, _params(), key=None, user_id=user)
        assert err.value.status_code == 422


@pytest.mark.asyncio
async def test_missing_datev_settings_block_only_the_datev_format(world) -> None:
    factory, a, _b, user = world
    async with factory() as s:
        conn, svc = await _conn(s, a), BatchService(s)
        conn.settings_ = {}
        await s.flush()
        rules = {f["rule_id"] for f in (await svc.preview(conn, _params()))["findings"]}
        assert "accounting_export.datev_settings" in rules
        assert "accounting_export.datev_settings" not in {
            f["rule_id"] for f in (await svc.preview(conn, _params("journal")))["findings"]
        }


@pytest.mark.asyncio
async def test_budgets_and_cost_codes_export_as_csv_and_xlsx(world) -> None:
    factory, a, _b, user = world
    async with factory() as s:
        conn, svc = await _conn(s, a), BatchService(s)
        await svc.set_cost_codes(
            conn, [{"platform_code": "P-100", "standard": "project", "external_cost_center": "1000"}]
        )
        batch, _ = await svc.create(conn, _params("csv", ("budget", "cost_code")), key=None, user_id=user)
        text = batch.content.decode("utf-8")
        assert batch.row_count == 2 and "budget" in text and "cost_code" in text and "1200.00" in text
        xlsx, _ = await svc.create(conn, _params("xlsx", ("ar_invoice",)), key=None, user_id=user)
        assert xlsx.batch_no == 2 and xlsx.content[:2] == b"PK" and xlsx.file_name.endswith(".xlsx")
        with pytest.raises(HTTPException) as err:
            await svc.preview(conn, _params("datev", ("budget",)))
        assert err.value.status_code == 422


@pytest.mark.asyncio
async def test_import_and_reconciliation_flag_one_mismatch(world) -> None:
    factory, a, _b, _user = world
    books = (
        b"Document;Date;Account;Debit;Credit;Status\r\n"
        b"AR-001;31.03.2026;1400;11.900,00;0;paid\r\n"
        b"AR-001;31.03.2026;8400;0;10.000,00;\r\n"
        b"AR-001;31.03.2026;1776;0;1.900,00;\r\n"
        b"SUB-17;02.04.2026;3400;5.000,10;0;\r\n"
        b"SUB-17;02.04.2026;1576;900,00;0;\r\n"
        b"SUB-17;02.04.2026;1600;0;5.900,10;\r\n"
        b"X-1;10.05.2026;4000;42,00;0;\r\n"
    )
    async with factory() as s:
        conn, sync = await _conn(s, a), AccountingSyncService(s)
        result = await LedgerImportService(s).import_file(conn, io.BytesIO(books), "books.csv")
        await s.commit()
        assert result.lines == 7 and result.skipped == 0
        listed = await LedgerImportService(s).list_imports(conn)
        assert listed[0]["lines"] == 7 and listed[0]["date_from"] == "2026-03-31"
        docs = await sync.documents(conn, period=PERIOD)
        platform = [{"number": d.number, "record_id": d.record_id, "amount": d.gross_total} for d in docs]
        report = reconcile(platform, await LedgerImportService(s).books_totals(conn, PERIOD))
        assert report["counts"] == {"matched": 1, "mismatches": 1, "platform_only": 0, "books_only": 1}
        assert report["matched"][0]["number"] == "AR-001" and report["matched"][0]["payment_status"] == "paid"
        bad = report["mismatches"][0]
        assert (
            bad["number"] == "SUB-17" and bad["difference"] == "-50.02" and report["books_only"][0]["number"] == "X-1"
        )
