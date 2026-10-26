# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guarantees.models import Guarantee, GuaranteeEvent, GuaranteeFacility


class GuaranteeRepository:
    """Queries over guarantees, their audit events and the bank facilities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, guarantee_id: uuid.UUID) -> Guarantee | None:
        return await self.session.get(Guarantee, guarantee_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        guarantee_type: str | None = None,
        status: str | None = None,
        direction: str | None = None,
        contract_id: uuid.UUID | None = None,
        subcontractor_id: uuid.UUID | None = None,
        statuses: Sequence[str] | None = None,
        expiring_before: date | None = None,
    ) -> list[Guarantee]:
        stmt = select(Guarantee)
        if project_id is not None:
            stmt = stmt.where(Guarantee.project_id == project_id)
        if guarantee_type:
            stmt = stmt.where(Guarantee.guarantee_type == guarantee_type)
        if status:
            stmt = stmt.where(Guarantee.status == status)
        if statuses:
            stmt = stmt.where(Guarantee.status.in_(list(statuses)))
        if direction:
            stmt = stmt.where(Guarantee.direction == direction)
        if contract_id is not None:
            stmt = stmt.where(Guarantee.contract_id == contract_id)
        if subcontractor_id is not None:
            stmt = stmt.where(Guarantee.subcontractor_id == subcontractor_id)
        if expiring_before is not None:
            stmt = stmt.where(Guarantee.expiry_date.is_not(None), Guarantee.expiry_date <= expiring_before)
        result = await self.session.execute(
            stmt.order_by(Guarantee.expiry_date.asc().nulls_last(), Guarantee.reference)
        )
        return list(result.scalars().all())

    async def reference_taken(self, project_id: uuid.UUID, reference: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = (
            select(func.count())
            .select_from(Guarantee)
            .where(Guarantee.project_id == project_id, Guarantee.reference == reference)
        )
        if exclude is not None:
            stmt = stmt.where(Guarantee.id != exclude)
        return int((await self.session.execute(stmt)).scalar_one() or 0) > 0

    async def count_in_project(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Guarantee).where(Guarantee.project_id == project_id)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def events(self, guarantee_id: uuid.UUID) -> list[GuaranteeEvent]:
        stmt = (
            select(GuaranteeEvent)
            .where(GuaranteeEvent.guarantee_id == guarantee_id)
            .order_by(GuaranteeEvent.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def facilities(self) -> list[GuaranteeFacility]:
        stmt = select(GuaranteeFacility).order_by(GuaranteeFacility.bank_name, GuaranteeFacility.name)
        return list((await self.session.execute(stmt)).scalars().all())
