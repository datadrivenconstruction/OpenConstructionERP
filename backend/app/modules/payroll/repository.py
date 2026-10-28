# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Async SQLAlchemy repositories for the Payroll module."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll.models import PayrollBatch, PayrollDeduction, PayrollEntry


class PayrollBatchRepository:
    """Data access for PayrollBatch."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, batch: PayrollBatch) -> PayrollBatch:
        self.session.add(batch)
        await self.session.flush()
        await self.session.refresh(batch)
        return batch

    async def get_by_id(self, batch_id: uuid.UUID) -> PayrollBatch | None:
        return await self.session.get(PayrollBatch, batch_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PayrollBatch], int]:
        base = select(PayrollBatch).where(PayrollBatch.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(PayrollBatch.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def update_fields(self, batch_id: uuid.UUID, **fields: Any) -> None:
        batch = await self.session.get(PayrollBatch, batch_id)
        if batch is None:
            return
        for key, value in fields.items():
            attr = "metadata_" if key == "metadata" else key
            setattr(batch, attr, value)
        await self.session.flush()


class PayrollEntryRepository:
    """Data access for PayrollEntry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_create(self, entries: list[PayrollEntry]) -> list[PayrollEntry]:
        if not entries:
            return []
        self.session.add_all(entries)
        await self.session.flush()
        return entries

    async def list_for_batch(self, batch_id: uuid.UUID) -> list[PayrollEntry]:
        stmt = (
            select(PayrollEntry)
            .where(PayrollEntry.batch_id == batch_id)
            .order_by(PayrollEntry.work_date.asc(), PayrollEntry.worker.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, entry_id: uuid.UUID) -> PayrollEntry | None:
        return await self.session.get(PayrollEntry, entry_id)

    async def update_fields(self, entry_id: uuid.UUID, **fields: Any) -> None:
        entry = await self.session.get(PayrollEntry, entry_id)
        if entry is None:
            return
        for key, value in fields.items():
            attr = "metadata_" if key == "metadata" else key
            setattr(entry, attr, value)
        await self.session.flush()


class PayrollDeductionRepository:
    """Data access for PayrollDeduction (withholding lines on a payslip)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, deduction: PayrollDeduction) -> PayrollDeduction:
        self.session.add(deduction)
        await self.session.flush()
        await self.session.refresh(deduction)
        return deduction

    async def get_by_id(self, deduction_id: uuid.UUID) -> PayrollDeduction | None:
        return await self.session.get(PayrollDeduction, deduction_id)

    async def delete(self, deduction: PayrollDeduction) -> None:
        await self.session.delete(deduction)
        await self.session.flush()

    async def list_for_entry(self, entry_id: uuid.UUID) -> list[PayrollDeduction]:
        stmt = (
            select(PayrollDeduction)
            .where(PayrollDeduction.entry_id == entry_id)
            .order_by(PayrollDeduction.ordinal.asc(), PayrollDeduction.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_entries(self, entry_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PayrollDeduction]]:
        """Bulk-load deductions for many entries, grouped by ``entry_id``.

        Lets the batch-detail view fetch every payslip's deductions in one query
        instead of N per-entry round trips.
        """
        if not entry_ids:
            return {}
        stmt = (
            select(PayrollDeduction)
            .where(PayrollDeduction.entry_id.in_(entry_ids))
            .order_by(PayrollDeduction.ordinal.asc(), PayrollDeduction.created_at.asc())
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[PayrollDeduction]] = {}
        for ded in result.scalars().all():
            grouped.setdefault(ded.entry_id, []).append(ded)
        return grouped

    async def max_ordinal_for_entry(self, entry_id: uuid.UUID) -> int:
        """Return the highest ordinal among an entry's deductions, or -1 if none."""
        stmt = select(func.max(PayrollDeduction.ordinal)).where(PayrollDeduction.entry_id == entry_id)
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(value) if value is not None else -1
