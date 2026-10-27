# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ accounting connections for the demo projects.

Two connections are shared by every demo project: a sandbox-style live ledger
whose sync log shows the project's invoices and bills pushed, one payment pulled
back and one push that failed with the reason the ledger gave; and a DATEV file
connection on the SKR03 template, so the EXTF Buchungsstapel downloads from the
demo. No credentials are stored: the live connection holds no OAuth token, so a
real push asks the admin to authorise it first.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting_sync.models import AccountingConnection, ExternalRef, SyncLogEntry
from app.modules.accounting_sync.postings import money
from app.modules.accounting_sync.service import PUSHABLE_STATUSES, AccountingSyncService

logger = logging.getLogger(__name__)

LIVE_NAME = "Demo ledger (sandbox)"
DATEV_NAME = "DATEV export (SKR03)"


async def _connection(
    svc: AccountingSyncService, name: str, data: dict, project_id: uuid.UUID, created_by: str | None
) -> AccountingConnection:
    row = (
        await svc.session.execute(select(AccountingConnection).where(AccountingConnection.name == name))
    ).scalar_one_or_none()
    if row is None:
        row = await svc.create_connection({"name": name, **data, "project_ids": [project_id]}, created_by)
    elif str(project_id) not in (row.project_ids or []):
        row.project_ids = [*(row.project_ids or []), str(project_id)]
    return row


async def seed_demo_accounting_sync(
    session: AsyncSession, *, project_id: uuid.UUID, currency: str, created_by: str | None = None
) -> int:
    """Seed the two demo connections and the live one's sync log; returns log rows written."""
    from app.modules.finance.models import Invoice

    svc = AccountingSyncService(session)
    live = await _connection(
        svc,
        LIVE_NAME,
        {"provider": "xero", "base_currency": currency or "EUR", "is_sandbox": True, "chart_template": "generic"},
        project_id,
        created_by,
    )
    live.status = "connected"
    live.external_tenant_id = live.external_tenant_id or "demo-tenant"
    await _connection(
        svc,
        DATEV_NAME,
        {
            "provider": "datev",
            "country_code": "DE",
            "chart_template": "DE-SKR03",
            "base_currency": "EUR",
            "settings": {"consultant_number": "1001", "client_number": "1"},
        },
        project_id,
        created_by,
    )
    invoices = list(
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.project_id == project_id, Invoice.status.in_(PUSHABLE_STATUSES))
                .order_by(Invoice.invoice_date)
                .limit(8)
            )
        ).scalars()
    )
    written = 0
    for n, inv in enumerate(invoices):
        kind = "ar_invoice" if inv.invoice_direction == "receivable" else "ap_bill"
        if n == len(invoices) - 1 and n > 0:
            session.add(
                SyncLogEntry(
                    connection_id=live.id,
                    project_id=project_id,
                    action="push",
                    record_type=kind,
                    record_id=str(inv.id),
                    record_label=inv.invoice_number,
                    status="failed",
                    attempt=2,
                    amount=money(inv.amount_total),
                    error_reason="Xero 400: Account code '5999' is not a valid code for this document.",
                )
            )
            written += 1
            continue
        ext = f"demo-{uuid.uuid5(uuid.NAMESPACE_URL, str(inv.id)).hex[:12]}"
        session.add(
            ExternalRef(
                connection_id=live.id,
                record_type=kind,
                record_id=str(inv.id),
                external_id=ext,
                pushed_total=money(inv.amount_subtotal) + money(inv.tax_amount),
                remote_total=money(inv.amount_subtotal) + money(inv.tax_amount),
            )
        )
        session.add(
            SyncLogEntry(
                connection_id=live.id,
                project_id=project_id,
                action="push",
                record_type=kind,
                record_id=str(inv.id),
                record_label=inv.invoice_number,
                status="success",
                external_id=ext,
                amount=money(inv.amount_total),
            )
        )
        written += 1
        if inv.status == "paid":
            session.add(
                SyncLogEntry(
                    connection_id=live.id,
                    project_id=project_id,
                    action="pull",
                    record_type="payment",
                    record_id=str(inv.id),
                    record_label=inv.invoice_number,
                    status="success",
                    external_id=f"{ext}-pay",
                    amount=money(inv.amount_total),
                )
            )
            written += 1
    if not invoices:
        session.add(
            SyncLogEntry(
                connection_id=live.id,
                project_id=project_id,
                action="pull",
                record_type="payment",
                status="failed",
                amount=Decimal("0"),
                error_reason="Not connected: authorise the connection first",
            )
        )
        written += 1
    live.last_sync_status = "failed"
    await session.flush()
    return written
