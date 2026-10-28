# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Work-type route classifier data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_route.models import RouteAssessment


class RouteAssessmentRepository:
    """Data access for :class:`RouteAssessment` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, assessment_id: uuid.UUID) -> RouteAssessment | None:
        return await self.session.get(RouteAssessment, assessment_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        work_type: str | None = None,
    ) -> list[RouteAssessment]:
        stmt = select(RouteAssessment).where(RouteAssessment.project_id == project_id)
        if status is not None:
            stmt = stmt.where(RouteAssessment.status == status)
        if work_type is not None:
            stmt = stmt.where(RouteAssessment.work_type == work_type)
        # Most-recently classified first - the latest decision leads.
        stmt = stmt.order_by(RouteAssessment.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, assessment: RouteAssessment) -> RouteAssessment:
        self.session.add(assessment)
        await self.session.flush()
        return assessment

    async def delete(self, assessment_id: uuid.UUID) -> None:
        row = await self.get_by_id(assessment_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()
