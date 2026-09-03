# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Data access for the Comms Intelligence module."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comms_intelligence.models import CommsAnalysis, CommsDraft


class CommsAnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, analysis_id: uuid.UUID) -> CommsAnalysis | None:
        return await self.session.get(CommsAnalysis, analysis_id)

    async def get_for_correspondence(self, correspondence_id: str) -> CommsAnalysis | None:
        stmt = select(CommsAnalysis).where(CommsAnalysis.correspondence_id == str(correspondence_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[CommsAnalysis]:
        stmt = select(CommsAnalysis).where(CommsAnalysis.project_id == project_id)
        if status:
            stmt = stmt.where(CommsAnalysis.status == status)
        stmt = stmt.order_by(CommsAnalysis.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_project(self, project_id: uuid.UUID, *, status: str | None = None) -> int:
        """How many rows the same filters match, ignoring the window."""
        stmt = select(func.count()).select_from(CommsAnalysis).where(CommsAnalysis.project_id == project_id)
        if status:
            stmt = stmt.where(CommsAnalysis.status == status)
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, row: CommsAnalysis) -> CommsAnalysis:
        self.session.add(row)
        await self.session.flush()
        return row


class CommsDraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, draft_id: uuid.UUID) -> CommsDraft | None:
        return await self.session.get(CommsDraft, draft_id)

    async def list_for_correspondence(self, correspondence_id: str) -> list[CommsDraft]:
        stmt = (
            select(CommsDraft)
            .where(CommsDraft.correspondence_id == str(correspondence_id))
            .order_by(CommsDraft.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, row: CommsDraft) -> CommsDraft:
        self.session.add(row)
        await self.session.flush()
        return row
