# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.service_charges.models import (
    ApportionmentKey,
    ChargeBudget,
    ChargeDemand,
    OwnersAssociation,
    YearEndReconciliation,
)


class ServiceChargesRepository:
    """Queries over associations, keys, budgets, demands and reconciliations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def associations(self, project_id: uuid.UUID) -> list[OwnersAssociation]:
        stmt = select(OwnersAssociation).where(OwnersAssociation.project_id == project_id)
        return list((await self.session.execute(stmt.order_by(OwnersAssociation.name))).scalars().all())

    async def keys(self, association_id: uuid.UUID) -> list[ApportionmentKey]:
        stmt = select(ApportionmentKey).where(ApportionmentKey.association_id == association_id)
        return list((await self.session.execute(stmt.order_by(ApportionmentKey.name))).scalars().all())

    async def budgets(self, association_id: uuid.UUID) -> list[ChargeBudget]:
        stmt = select(ChargeBudget).where(ChargeBudget.association_id == association_id)
        return list((await self.session.execute(stmt.order_by(ChargeBudget.year.desc()))).scalars().all())

    async def budget_for_year(self, association_id: uuid.UUID, year: int) -> ChargeBudget | None:
        stmt = select(ChargeBudget).where(ChargeBudget.association_id == association_id, ChargeBudget.year == year)
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    async def demands(self, budget_id: uuid.UUID) -> list[ChargeDemand]:
        stmt = (
            select(ChargeDemand)
            .where(ChargeDemand.budget_id == budget_id)
            .order_by(ChargeDemand.period, ChargeDemand.unit_ref)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def reconciliation(self, budget_id: uuid.UUID) -> YearEndReconciliation | None:
        stmt = select(YearEndReconciliation).where(YearEndReconciliation.budget_id == budget_id)
        return (await self.session.execute(stmt.limit(1))).scalars().first()
