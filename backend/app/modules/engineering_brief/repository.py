# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the engineering brief. Every child lookup is by ``(project_id, id)``, so a foreign id is absent."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engineering_brief.models import (
    ConceptItem,
    EngineeringBrief,
    FrameMilestone,
    ProgrammeLine,
    SpecificationIssue,
    Study,
)


class EngineeringBriefRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def brief(self, project_id: uuid.UUID, *, lock: bool = False) -> EngineeringBrief | None:
        stmt = select(EngineeringBrief).where(EngineeringBrief.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def briefs_for_document(self, document_id: uuid.UUID) -> list[EngineeringBrief]:
        stmt = select(EngineeringBrief).where(EngineeringBrief.governance_document_id == document_id).with_for_update()
        return list((await self.session.execute(stmt)).scalars())

    async def child(self, model: type, project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False) -> Any:
        stmt = select(model).where(model.project_id == project_id, model.id == row_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _list(self, model: type, project_id: uuid.UUID, *order: Any) -> list[Any]:
        stmt = select(model).where(model.project_id == project_id).order_by(*order)
        return list((await self.session.execute(stmt)).scalars())

    async def concepts(self, project_id: uuid.UUID) -> list[ConceptItem]:
        return await self._list(ConceptItem, project_id, ConceptItem.sort_order, ConceptItem.code)

    async def programme(self, project_id: uuid.UUID) -> list[ProgrammeLine]:
        return await self._list(ProgrammeLine, project_id, ProgrammeLine.sort_order, ProgrammeLine.code)

    async def milestones(self, project_id: uuid.UUID) -> list[FrameMilestone]:
        return await self._list(FrameMilestone, project_id, FrameMilestone.sort_order, FrameMilestone.code)

    async def studies(self, project_id: uuid.UUID) -> list[Study]:
        return await self._list(Study, project_id, Study.sort_order, Study.code)

    async def issues(self, project_id: uuid.UUID) -> list[SpecificationIssue]:
        return await self._list(SpecificationIssue, project_id, SpecificationIssue.version_no.desc())
