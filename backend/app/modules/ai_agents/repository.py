"""AI Agents data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.models import AgentRun, AgentStep


class AgentRunRepository:
    """CRUD-style helpers for :class:`AgentRun`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, run: AgentRun) -> AgentRun:
        """Insert a new run row and flush so it has an id."""
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> AgentRun | None:
        stmt = select(AgentRun).where(AgentRun.id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_runs(
        self,
        *,
        user_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        """Return runs ordered newest-first, scoped by user/project."""
        stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if project_id is not None:
            stmt = stmt.where(AgentRun.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def update_fields(self, run_id: uuid.UUID, **fields: object) -> None:
        """Patch arbitrary scalar fields on a run row."""
        stmt = update(AgentRun).where(AgentRun.id == run_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class AgentStepRepository:
    """CRUD-style helpers for :class:`AgentStep`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, step: AgentStep) -> AgentStep:
        self.session.add(step)
        await self.session.flush()
        return step

    async def list_for_run(self, run_id: uuid.UUID) -> list[AgentStep]:
        """Return every step for a run in chronological order."""
        stmt = select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_idx.asc())
        return list((await self.session.execute(stmt)).scalars().all())
