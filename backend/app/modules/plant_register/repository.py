# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access of the plant register: every child row is read by ``(project_id, id)``.

That pairing is the IDOR guard: an id from another project simply is not
found, so the service answers 404 without ever saying the row exists.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plant_register.models import (
    DecisionPaper,
    DeliveryLimit,
    ItService,
    LeadTimeQuote,
    PlantItem,
    PlantSettings,
    SlotReservation,
    SparePartRequirement,
)

T = TypeVar("T")


class PlantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_scoped(
        self, model: type[T], project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False
    ) -> T | None:
        stmt = select(model).where(model.id == row_id, model.project_id == project_id)  # type: ignore[attr-defined]
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def settings(self, project_id: uuid.UUID) -> PlantSettings | None:
        stmt = select(PlantSettings).where(PlantSettings.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def items(self, project_id: uuid.UUID) -> list[PlantItem]:
        stmt = select(PlantItem).where(PlantItem.project_id == project_id).order_by(PlantItem.code)
        return list((await self.session.execute(stmt)).scalars())

    async def item_by_code(self, project_id: uuid.UUID, code: str) -> PlantItem | None:
        stmt = select(PlantItem).where(PlantItem.project_id == project_id, PlantItem.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _children(self, model: type[T], project_id: uuid.UUID, item_id: uuid.UUID | None, order: Any) -> list[T]:
        stmt = select(model).where(model.project_id == project_id)  # type: ignore[attr-defined]
        if item_id is not None:
            stmt = stmt.where(model.plant_item_id == item_id)  # type: ignore[attr-defined]
        return list((await self.session.execute(stmt.order_by(order))).scalars())

    async def quotes(self, project_id: uuid.UUID, item_id: uuid.UUID | None = None) -> list[LeadTimeQuote]:
        return await self._children(LeadTimeQuote, project_id, item_id, LeadTimeQuote.created_at)

    async def slots(self, project_id: uuid.UUID, item_id: uuid.UUID | None = None) -> list[SlotReservation]:
        return await self._children(SlotReservation, project_id, item_id, SlotReservation.created_at)

    async def papers(self, project_id: uuid.UUID, item_id: uuid.UUID | None = None) -> list[DecisionPaper]:
        return await self._children(DecisionPaper, project_id, item_id, DecisionPaper.created_at)

    async def limits(self, project_id: uuid.UUID, item_id: uuid.UUID | None = None) -> list[DeliveryLimit]:
        return await self._children(DeliveryLimit, project_id, item_id, DeliveryLimit.step)

    async def spares(self, project_id: uuid.UUID, item_id: uuid.UUID | None = None) -> list[SparePartRequirement]:
        return await self._children(SparePartRequirement, project_id, item_id, SparePartRequirement.created_at)

    async def it_services(self, project_id: uuid.UUID) -> list[ItService]:
        stmt = select(ItService).where(ItService.project_id == project_id).order_by(ItService.created_at)
        return list((await self.session.execute(stmt)).scalars())

    async def paper_by_instance(self, instance_id: uuid.UUID) -> DecisionPaper | None:
        stmt = select(DecisionPaper).where(DecisionPaper.approval_instance_id == instance_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def items_by_purchase_order(self, po_id: uuid.UUID) -> list[PlantItem]:
        stmt = select(PlantItem).where(PlantItem.purchase_order_id == po_id)
        return list((await self.session.execute(stmt)).scalars())

    async def held_slots_due(self, project_id: uuid.UUID | None, today: date) -> list[SlotReservation]:
        """Held slots whose conversion deadline passed before ``today``, locked."""
        stmt = select(SlotReservation).where(SlotReservation.status == "held", SlotReservation.convert_by_date < today)
        if project_id is not None:
            stmt = stmt.where(SlotReservation.project_id == project_id)
        return list((await self.session.execute(stmt.order_by(SlotReservation.id).with_for_update())).scalars())

    async def project_ids_with_items(self) -> list[uuid.UUID]:
        """Every project that keeps a plant register (the periodic job walks them)."""
        stmt = select(PlantItem.project_id).distinct().order_by(PlantItem.project_id)
        return list((await self.session.execute(stmt)).scalars())

    async def submitted_paper_ids(self) -> list[uuid.UUID]:
        stmt = select(DecisionPaper.id).where(DecisionPaper.status == "submitted").order_by(DecisionPaper.id)
        return list((await self.session.execute(stmt)).scalars())
