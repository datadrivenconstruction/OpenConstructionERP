# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for stockpiles. Writes only ``oe_stockpile*``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stockpiles.models import Stockpile, StockpileAdjustment, StockpileSurvey


class StockpileRepository:
    """Queries behind the stockpile service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    # ── Stockpiles ─────────────────────────────────────────────────────────

    async def list_stockpiles(self, project_id: uuid.UUID) -> list[Stockpile]:
        rows = await self.session.execute(
            select(Stockpile).where(Stockpile.project_id == project_id).order_by(Stockpile.code)
        )
        return list(rows.scalars().all())

    async def get_stockpile(self, stockpile_id: uuid.UUID) -> Stockpile | None:
        return await self.session.get(Stockpile, stockpile_id)

    async def codes(self, project_id: uuid.UUID) -> list[str]:
        rows = await self.session.execute(select(Stockpile.code).where(Stockpile.project_id == project_id))
        return [str(c) for (c,) in rows.all()]

    # ── Surveys ────────────────────────────────────────────────────────────

    async def surveys_of(self, stockpile_id: uuid.UUID) -> list[StockpileSurvey]:
        """Newest first: survey date, then creation order."""
        rows = await self.session.execute(
            select(StockpileSurvey)
            .where(StockpileSurvey.stockpile_id == stockpile_id)
            .order_by(StockpileSurvey.surveyed_on.desc(), StockpileSurvey.created_at.desc())
        )
        return list(rows.scalars().all())

    async def surveys_of_project(self, project_id: uuid.UUID) -> list[StockpileSurvey]:
        rows = await self.session.execute(
            select(StockpileSurvey)
            .where(StockpileSurvey.project_id == project_id)
            .order_by(StockpileSurvey.surveyed_on.desc(), StockpileSurvey.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_survey(self, survey_id: uuid.UUID) -> StockpileSurvey | None:
        return await self.session.get(StockpileSurvey, survey_id)

    # ── Adjustments ────────────────────────────────────────────────────────

    async def adjustments_of(self, survey_ids: list[uuid.UUID]) -> dict[uuid.UUID, StockpileAdjustment]:
        """The latest adjustment per survey."""
        if not survey_ids:
            return {}
        rows = await self.session.execute(
            select(StockpileAdjustment)
            .where(StockpileAdjustment.survey_id.in_(survey_ids))
            .order_by(StockpileAdjustment.created_at, StockpileAdjustment.id)
        )
        return {a.survey_id: a for a in rows.scalars().all()}

    async def get_adjustment(self, adjustment_id: uuid.UUID) -> StockpileAdjustment | None:
        return await self.session.get(StockpileAdjustment, adjustment_id)

    async def open_adjustment(self, survey_id: uuid.UUID) -> StockpileAdjustment | None:
        rows = await self.session.execute(
            select(StockpileAdjustment).where(
                StockpileAdjustment.survey_id == survey_id, StockpileAdjustment.status == "proposed"
            )
        )
        return rows.scalars().first()

    # ── Other modules, read only ───────────────────────────────────────────

    async def user_name(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return ""
        try:
            from app.modules.users.models import User  # noqa: PLC0415
        except ImportError:  # pragma: no cover - users is core
            return ""
        row = (await self.session.execute(select(User.full_name, User.email).where(User.id == user_id))).first()
        if row is None:
            return ""
        return str(row[0] or row[1] or "")
