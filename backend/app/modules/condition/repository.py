# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Condition assessment data access (pure CRUD; scoping happens in service and router)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.condition.models import ConditionAction, ConditionAssessment, ConditionScale

#: Hard cap on rows one listing returns.
MAX_ROWS = 5000


class ConditionRepository:
    """Data access for scales, assessments and actions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_scales(self, project_id: uuid.UUID) -> list[ConditionScale]:
        stmt = select(ConditionScale).where(ConditionScale.project_id == project_id).order_by(ConditionScale.key)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_scale(self, project_id: uuid.UUID, key: str) -> ConditionScale | None:
        stmt = select(ConditionScale).where(ConditionScale.project_id == project_id, ConditionScale.key == key)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_assessments_with_scale(self, project_id: uuid.UUID, key: str) -> int:
        stmt = select(func.count()).where(
            ConditionAssessment.project_id == project_id, ConditionAssessment.scale_key == key
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_assessments(
        self,
        project_id: uuid.UUID,
        *,
        inspection_id: str | None = None,
        asset_ref: str | None = None,
        area: str | None = None,
    ) -> list[ConditionAssessment]:
        stmt = select(ConditionAssessment).where(ConditionAssessment.project_id == project_id)
        if inspection_id:
            stmt = stmt.where(ConditionAssessment.inspection_id == inspection_id)
        if asset_ref:
            stmt = stmt.where(ConditionAssessment.asset_ref == asset_ref)
        if area:
            stmt = stmt.where(ConditionAssessment.area == area)
        stmt = stmt.order_by(ConditionAssessment.assessed_at.desc(), ConditionAssessment.created_at.desc()).limit(
            MAX_ROWS
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_assessments(self, project_id: uuid.UUID) -> list[ConditionAssessment]:
        """The newest assessment per asset (or per element name when no asset is referenced)."""
        rows = await self.list_assessments(project_id)
        seen: set[tuple[str, str]] = set()
        out: list[ConditionAssessment] = []
        for row in rows:
            key = ("ref", row.asset_ref) if row.asset_ref else ("name", row.element_name.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    async def derived_keys(self, project_id: uuid.UUID) -> set[tuple[uuid.UUID, str]]:
        """``(assessment_id, action_type)`` of every live derived action."""
        stmt = select(ConditionAction.assessment_id, ConditionAction.action_type).where(
            ConditionAction.project_id == project_id,
            ConditionAction.source == "derived",
            ConditionAction.status != "rejected",
            ConditionAction.assessment_id.is_not(None),
        )
        return {(a, t) for a, t in (await self.session.execute(stmt)).all()}

    async def list_actions(
        self,
        project_id: uuid.UUID,
        *,
        statuses: list[str] | None = None,
        area: str | None = None,
        asset_ref: str | None = None,
    ) -> list[ConditionAction]:
        stmt = select(ConditionAction).where(ConditionAction.project_id == project_id)
        if statuses:
            stmt = stmt.where(ConditionAction.status.in_(statuses))
        if area:
            stmt = stmt.where(ConditionAction.area == area)
        if asset_ref:
            stmt = stmt.where(ConditionAction.asset_ref == asset_ref)
        stmt = stmt.order_by(ConditionAction.first_year, ConditionAction.priority).limit(MAX_ROWS)
        return list((await self.session.execute(stmt)).scalars().all())
