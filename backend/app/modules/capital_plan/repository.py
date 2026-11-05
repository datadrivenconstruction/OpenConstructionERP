# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the capital plan module. Writes flush only; the request middleware commits."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.capital_plan.models import (
    CapitalPlan,
    CapitalPlanEnvelope,
    CapitalPlanItem,
    CapitalPlanScenario,
)


class CapitalPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Plans
    async def get_plan(self, plan_id: uuid.UUID) -> CapitalPlan | None:
        return await self.session.get(CapitalPlan, plan_id)

    async def list_plans(
        self, node_ids: Sequence[uuid.UUID] | None = None, *, offset: int = 0, limit: int | None = None
    ) -> tuple[list[CapitalPlan], int]:
        stmt = select(CapitalPlan).order_by(CapitalPlan.start_year.desc(), CapitalPlan.name, CapitalPlan.id)
        count = select(func.count()).select_from(CapitalPlan)
        if node_ids is not None:
            stmt = stmt.where(CapitalPlan.node_id.in_(list(node_ids)))
            count = count.where(CapitalPlan.node_id.in_(list(node_ids)))
        rows = (await self.session.execute(stmt.offset(offset).limit(limit))).scalars().all()
        return list(rows), int((await self.session.execute(count)).scalar_one())

    async def add(self, row: object) -> None:
        self.session.add(row)
        await self.session.flush()

    async def delete_row(self, row: object) -> None:
        await self.session.delete(row)
        await self.session.flush()

    # Envelopes
    async def list_envelopes(
        self, plan_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> list[CapitalPlanEnvelope]:
        stmt = (
            select(CapitalPlanEnvelope)
            .where(CapitalPlanEnvelope.plan_id == plan_id)
            .order_by(CapitalPlanEnvelope.year, CapitalPlanEnvelope.label)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_envelopes(self, plan_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(CapitalPlanEnvelope).where(CapitalPlanEnvelope.plan_id == plan_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def clear_envelopes(self, plan_id: uuid.UUID) -> None:
        await self.session.execute(delete(CapitalPlanEnvelope).where(CapitalPlanEnvelope.plan_id == plan_id))
        await self.session.flush()

    # Scenarios
    async def get_scenario(self, scenario_id: uuid.UUID) -> CapitalPlanScenario | None:
        return await self.session.get(CapitalPlanScenario, scenario_id)

    async def list_scenarios(
        self, plan_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> list[CapitalPlanScenario]:
        stmt = (
            select(CapitalPlanScenario)
            .where(CapitalPlanScenario.plan_id == plan_id)
            .order_by(CapitalPlanScenario.is_baseline.desc(), CapitalPlanScenario.created_at)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_scenarios(self, plan_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(CapitalPlanScenario).where(CapitalPlanScenario.plan_id == plan_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_baselines(self, plan_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            CapitalPlanScenario.plan_id == plan_id, CapitalPlanScenario.is_baseline.is_(True)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # Items
    async def get_item(self, item_id: uuid.UUID) -> CapitalPlanItem | None:
        return await self.session.get(CapitalPlanItem, item_id)

    async def list_items(
        self, scenario_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> list[CapitalPlanItem]:
        stmt = (
            select(CapitalPlanItem)
            .where(CapitalPlanItem.scenario_id == scenario_id)
            .order_by(CapitalPlanItem.priority, CapitalPlanItem.start_year, CapitalPlanItem.title, CapitalPlanItem.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_items(self, scenario_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(CapitalPlanItem).where(CapitalPlanItem.scenario_id == scenario_id)
        return int((await self.session.execute(stmt)).scalar_one())
