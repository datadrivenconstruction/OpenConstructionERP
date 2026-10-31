# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.measurement_book.models import MeasurementBookEntry


class MeasurementBookRepository:
    """Reads entries and the BOQ positions they measure."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entry_id: uuid.UUID) -> MeasurementBookEntry | None:
        return await self.session.get(MeasurementBookEntry, entry_id)

    async def entries(
        self, project_id: uuid.UUID, boq_position_id: uuid.UUID | None = None
    ) -> list[MeasurementBookEntry]:
        stmt = select(MeasurementBookEntry).where(MeasurementBookEntry.project_id == project_id)
        if boq_position_id is not None:
            stmt = stmt.where(MeasurementBookEntry.boq_position_id == boq_position_id)
        stmt = stmt.order_by(MeasurementBookEntry.entry_date, MeasurementBookEntry.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def project_positions(self, project_id: uuid.UUID) -> list[Position]:
        """Every measurable position of the project's BOQs, in bill order."""
        stmt = (
            select(Position)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id, Position.unit != "")
            .order_by(BOQ.created_at, Position.sort_order)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def position_project(self, position_id: uuid.UUID) -> uuid.UUID | None:
        stmt = select(BOQ.project_id).join(Position, Position.boq_id == BOQ.id).where(Position.id == position_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
