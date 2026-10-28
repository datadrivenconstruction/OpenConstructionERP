# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan Room data access layer.

Owns only the positioned-pin table (:class:`PlanPin`). Every other overlay
source is read directly by the service from its owning module with fail-soft
lazy imports, so no repository here reaches across module boundaries.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_room.models import PlanPin


class PlanPinRepository:
    """Data access for :class:`PlanPin`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, pin_id: uuid.UUID) -> PlanPin | None:
        """Get a pin by ID."""
        return await self.session.get(PlanPin, pin_id)

    async def list_for_page(self, document_id: str, page: int) -> list[PlanPin]:
        """List positioned pins on one document page, oldest first."""
        stmt = (
            select(PlanPin)
            .where(PlanPin.document_id == document_id, PlanPin.page == page)
            .order_by(PlanPin.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, pin: PlanPin) -> PlanPin:
        """Insert a new pin."""
        self.session.add(pin)
        await self.session.flush()
        return pin

    async def delete(self, pin_id: uuid.UUID) -> None:
        """Delete a pin."""
        pin = await self.session.get(PlanPin, pin_id)
        if pin is not None:
            await self.session.delete(pin)
            await self.session.flush()
