# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment_release.models import InvoiceRelease, PaymentTerms, RetentionPosting


class PaymentReleaseRepository:
    """Reads and writes the three payment release tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def terms_for(self, contract_id: uuid.UUID) -> PaymentTerms | None:
        return (
            await self.session.execute(select(PaymentTerms).where(PaymentTerms.contract_id == contract_id))
        ).scalar_one_or_none()

    async def release_for(self, invoice_id: uuid.UUID) -> InvoiceRelease | None:
        return (
            await self.session.execute(select(InvoiceRelease).where(InvoiceRelease.invoice_id == invoice_id))
        ).scalar_one_or_none()

    async def posting(self, posting_id: uuid.UUID) -> RetentionPosting | None:
        return await self.session.get(RetentionPosting, posting_id)

    async def add(self, row: PaymentTerms | InvoiceRelease | RetentionPosting) -> None:
        self.session.add(row)
        await self.session.flush()
