"""Schedule Intelligence data access layer.

Pure queries — no HTTP, no business logic. Each method takes an
``AsyncSession`` and returns model instances or primitives. The ``service``
layer composes these into the governance workflows (lock / unlock / verify /
configure). Phase 0 covers only the two governance tables; insight
repositories (readiness, risk, decision) arrive with their engines.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule_intelligence.models import ConfidenceConfig, LockedFigure


class LockedFigureRepository:
    """Access to :class:`LockedFigure` rows (E5.2 backing store)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, figure_id: uuid.UUID) -> LockedFigure | None:
        return await self.session.get(LockedFigure, figure_id)

    async def get_active_by_path(self, project_id: uuid.UUID, path: str) -> LockedFigure | None:
        stmt = select(LockedFigure).where(
            LockedFigure.project_id == project_id,
            LockedFigure.path == path,
            LockedFigure.active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_active_for_project(self, project_id: uuid.UUID) -> list[LockedFigure]:
        stmt = select(LockedFigure).where(
            LockedFigure.project_id == project_id,
            LockedFigure.active.is_(True),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project(self, project_id: uuid.UUID, *, include_inactive: bool = False) -> list[LockedFigure]:
        stmt = select(LockedFigure).where(LockedFigure.project_id == project_id)
        if not include_inactive:
            stmt = stmt.where(LockedFigure.active.is_(True))
        stmt = stmt.order_by(LockedFigure.locked_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, row: LockedFigure) -> LockedFigure:
        self.session.add(row)
        await self.session.flush()
        return row


class ConfidenceConfigRepository:
    """Access to :class:`ConfidenceConfig` rows (E5.3 config-as-data)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_for_project(self, project_id: uuid.UUID) -> ConfidenceConfig | None:
        stmt = select(ConfidenceConfig).where(
            ConfidenceConfig.project_id == project_id,
            ConfidenceConfig.active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active_global(self) -> ConfidenceConfig | None:
        stmt = select(ConfidenceConfig).where(
            ConfidenceConfig.project_id.is_(None),
            ConfidenceConfig.active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def max_version_for_project(self, project_id: uuid.UUID) -> int:
        stmt = select(ConfidenceConfig.version).where(ConfidenceConfig.project_id == project_id)
        result = await self.session.execute(stmt)
        versions = [v for v in result.scalars().all() if v is not None]
        return max(versions, default=0)

    async def list_active_for_project(self, project_id: uuid.UUID) -> list[ConfidenceConfig]:
        """All currently-active rows for a project (should be at most one).

        Returned so the service can deactivate any stragglers before creating
        a new version.
        """
        stmt = select(ConfidenceConfig).where(
            ConfidenceConfig.project_id == project_id,
            ConfidenceConfig.active.is_(True),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, row: ConfidenceConfig) -> ConfidenceConfig:
        self.session.add(row)
        await self.session.flush()
        return row
