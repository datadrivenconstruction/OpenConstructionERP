# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Booking export demo: a sample connector and approved supplier invoices to export.

All account numbers, tax keys and the creditor number are synthetic sample configuration of a
made-up supplier, not a chart of accounts. Idempotent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.connector_models import AccountingConnectorConfig
from app.modules.finance.invoice_capture_models import CapturedInvoice
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

SUPPLIER = "Baustoffe Nord GmbH"
NAME = "Booking export (sample)"
SETTINGS = {
    "sample": True,
    "delimiter": ";",
    "decimal": ",",
    "account_map": {"mat": {"account": "3400", "tax_key": "9"}, "mat7": {"account": "3300", "tax_key": "8"}},
    "creditor_accounts": {SUPPLIER: "70001"},
    "base_currency": "EUR",
}


async def seed_booking_export_demo(session: AsyncSession, project_ids: list[uuid.UUID] | None = None) -> dict[str, int]:
    config = (
        await session.execute(select(AccountingConnectorConfig).where(AccountingConnectorConfig.name == NAME))
    ).scalar_one_or_none()
    created = 0
    if config is None:
        session.add(
            AccountingConnectorConfig(
                name=NAME, connector_type="booking_csv", direction="push", is_active=True, settings_=dict(SETTINGS)
            )
        )
        created = 1
    project = (
        await session.execute(select(Project).where(Project.id.in_(project_ids)).limit(1))
        if project_ids
        else await session.execute(select(Project).limit(1))
    ).scalar_one_or_none()
    invoices = 0
    if project is not None:
        have = {
            n
            for (n,) in (
                await session.execute(
                    select(CapturedInvoice.invoice_number).where(CapturedInvoice.supplier_name == SUPPLIER)
                )
            ).all()
        }
        base = date.today().replace(day=1) - timedelta(days=1)  # last day of the previous month
        rows = [
            ("RE-88412", base.replace(day=14), "1000.00", "190.00", "1190.00", "approved", "mat", []),
            (
                "RE-88430",
                base.replace(day=21),
                "700.00",
                "109.00",
                "809.00",
                "approved",
                "mat",
                [
                    {"description": "Concrete", "amount": "500.00", "account": "mat", "tax_rate": "19"},
                    {"description": "Timber", "amount": "200.00", "account": "mat7", "tax_rate": "7"},
                ],
            ),
            ("RE-88455", base.replace(day=25), "250.00", "47.50", "297.50", "captured", "mat", []),
            ("RE-88460", base.replace(day=26), "80.00", "15.20", "95.20", "approved", "unmapped", []),
        ]
        for number, day, net, tax, gross, state, account, lines in rows:
            if number in have:
                continue
            session.add(
                CapturedInvoice(
                    project_id=project.id,
                    direction="payable",
                    status=state,
                    supplier_name=SUPPLIER,
                    invoice_number=number,
                    invoice_date=day.isoformat(),
                    currency_code="EUR",
                    amount_net=Decimal(net),
                    amount_tax=Decimal(tax),
                    amount_gross=Decimal(gross),
                    line_items=lines,
                    booking_expense_account=account,
                    booking_project_id=project.id,
                    booking_cost_code="300.20",
                    extraction_engine="manual",
                )
            )
            invoices += 1
    await session.flush()
    return {"connectors": created, "invoices": invoices}
