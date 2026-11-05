# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync data access over the module's own tables."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting_sync.models import AccountingConnection, AccountMapping, TaxCodeMapping


class AccountingSyncRepository:
    """Queries over connections and their account and tax mappings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_connections(self) -> list[AccountingConnection]:
        rows = await self.session.execute(select(AccountingConnection).order_by(AccountingConnection.name))
        return list(rows.scalars())

    async def list_connections_page(self, *, offset: int, limit: int) -> tuple[list[AccountingConnection], int]:
        total = (await self.session.execute(select(func.count()).select_from(AccountingConnection))).scalar_one()
        rows = await self.session.execute(
            select(AccountingConnection).order_by(AccountingConnection.name).offset(offset).limit(limit)
        )
        return list(rows.scalars()), int(total)

    async def get_connection(self, connection_id: uuid.UUID) -> AccountingConnection | None:
        return await self.session.get(AccountingConnection, connection_id)

    async def account_mappings(self, connection_id: uuid.UUID) -> list[AccountMapping]:
        rows = await self.session.execute(
            select(AccountMapping)
            .where(AccountMapping.connection_id == connection_id)
            .order_by(AccountMapping.category)
        )
        return list(rows.scalars())

    async def tax_mappings(self, connection_id: uuid.UUID) -> list[TaxCodeMapping]:
        rows = await self.session.execute(
            select(TaxCodeMapping)
            .where(TaxCodeMapping.connection_id == connection_id)
            .order_by(TaxCodeMapping.direction, TaxCodeMapping.tax_code)
        )
        return list(rows.scalars())
