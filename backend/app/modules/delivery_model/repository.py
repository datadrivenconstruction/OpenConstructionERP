# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the delivery model. Every child lookup is by ``(project_id, id)``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.delivery_model.models import (
    ContractItem,
    ContractPackage,
    DecisionCriterion,
    DeliveryDecision,
    DeliveryModel,
    DeliveryOption,
    OptionScore,
    OwnerFurnishedItem,
    RiskAllocation,
)


class DeliveryModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_model(self, project_id: uuid.UUID, *, lock: bool = False) -> DeliveryModel | None:
        stmt = select(DeliveryModel).where(DeliveryModel.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _child(self, model: type, project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False) -> Any:
        stmt = select(model).where(model.project_id == project_id, model.id == row_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _list(self, model: type, project_id: uuid.UUID, *order: Any) -> list[Any]:
        stmt = select(model).where(model.project_id == project_id).order_by(*order)
        return list((await self.session.execute(stmt)).scalars())

    async def option(self, project_id: uuid.UUID, option_id: uuid.UUID) -> DeliveryOption | None:
        return await self._child(DeliveryOption, project_id, option_id)

    async def options(self, project_id: uuid.UUID) -> list[DeliveryOption]:
        return await self._list(DeliveryOption, project_id, DeliveryOption.sort_order, DeliveryOption.created_at)

    async def criteria(self, project_id: uuid.UUID) -> list[DecisionCriterion]:
        return await self._list(DecisionCriterion, project_id, DecisionCriterion.sort_order, DecisionCriterion.code)

    async def scores(self, project_id: uuid.UUID) -> list[OptionScore]:
        return await self._list(OptionScore, project_id, OptionScore.created_at)

    async def decision(self, project_id: uuid.UUID, decision_id: uuid.UUID) -> DeliveryDecision | None:
        return await self._child(DeliveryDecision, project_id, decision_id)

    async def decisions(self, project_id: uuid.UUID) -> list[DeliveryDecision]:
        return await self._list(DeliveryDecision, project_id, DeliveryDecision.created_at.desc())

    async def allocations(self, project_id: uuid.UUID, *, lock: bool = False) -> list[RiskAllocation]:
        stmt = (
            select(RiskAllocation).where(RiskAllocation.project_id == project_id).order_by(RiskAllocation.category_code)
        )
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars())

    async def allocation(self, project_id: uuid.UUID, category: str, *, lock: bool = False) -> RiskAllocation | None:
        stmt = select(RiskAllocation).where(
            RiskAllocation.project_id == project_id, RiskAllocation.category_code == category
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def package(self, project_id: uuid.UUID, package_id: uuid.UUID, *, lock: bool = False) -> Any:
        return await self._child(ContractPackage, project_id, package_id, lock=lock)

    async def packages(self, project_id: uuid.UUID) -> list[ContractPackage]:
        return await self._list(ContractPackage, project_id, ContractPackage.sort_order, ContractPackage.code)

    async def ofi(self, project_id: uuid.UUID, ofi_id: uuid.UUID, *, lock: bool = False) -> Any:
        return await self._child(OwnerFurnishedItem, project_id, ofi_id, lock=lock)

    async def ofis(self, project_id: uuid.UUID) -> list[OwnerFurnishedItem]:
        return await self._list(OwnerFurnishedItem, project_id, OwnerFurnishedItem.code)

    async def contract_item(self, project_id: uuid.UUID, item_id: uuid.UUID, *, lock: bool = False) -> Any:
        return await self._child(ContractItem, project_id, item_id, lock=lock)

    async def contract_items(self, project_id: uuid.UUID) -> list[ContractItem]:
        return await self._list(ContractItem, project_id, ContractItem.group_code, ContractItem.code)
