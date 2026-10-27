# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync tables on PostgreSQL: exact money, JSON settings and the idempotency key.

Re-queries with a fresh ``select()`` after expiring the session, so the test
reads what reached the database and not the instance still in memory.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.accounting_sync.models import ExternalRef, SyncLogEntry, TaxCodeMapping
from app.modules.accounting_sync.service import AccountingSyncService

pytestmark = pytest.mark.asyncio


async def test_template_mapping_and_settings_round_trip(pg_session) -> None:
    svc = AccountingSyncService(pg_session)
    conn = await svc.create_connection(
        {"name": "PG DATEV", "provider": "datev", "country_code": "DE", "settings": {"journal_columns": ["account"]}}
    )
    await pg_session.flush()
    pg_session.expire_all()
    taxes = {
        (m.tax_code, m.direction): m
        for m in (
            await pg_session.execute(select(TaxCodeMapping).where(TaxCodeMapping.connection_id == conn.id))
        ).scalars()
    }
    assert taxes[("VAT", "purchase")].external_code == "9"
    assert taxes[("VAT", "sales")].rate_pct == Decimal("19.0000")
    again = await svc.get_connection(conn.id)
    assert again.settings_ == {"journal_columns": ["account"]}


async def test_external_ref_is_unique_per_record(pg_session) -> None:
    svc = AccountingSyncService(pg_session)
    conn = await svc.create_connection({"name": "PG Xero", "provider": "xero"})
    pg_session.add(ExternalRef(connection_id=conn.id, record_type="ar_invoice", record_id="r1", external_id="X1"))
    await pg_session.flush()
    nested = await pg_session.begin_nested()
    pg_session.add(ExternalRef(connection_id=conn.id, record_type="ar_invoice", record_id="r1", external_id="X2"))
    with pytest.raises(IntegrityError):
        await pg_session.flush()
    await nested.rollback()


async def test_log_amount_keeps_cents_exactly(pg_session) -> None:
    svc = AccountingSyncService(pg_session)
    conn = await svc.create_connection({"name": "PG QBO", "provider": "qbo"})
    pg_session.add(
        SyncLogEntry(
            connection_id=conn.id,
            action="push",
            record_type="ar_invoice",
            status="success",
            amount=Decimal("0.10") + Decimal("0.20"),
        )
    )
    await pg_session.flush()
    pg_session.expire_all()
    row = (await pg_session.execute(select(SyncLogEntry).where(SyncLogEntry.connection_id == conn.id))).scalar_one()
    assert row.amount == Decimal("0.30")
