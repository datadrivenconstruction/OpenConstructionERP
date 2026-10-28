# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AI module data access layer.

All database queries for AI settings and estimate jobs live here.
No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.ai.models import AIEstimateJob, AISettings


class AISettingsRepository:
    """Data access for AISettings model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> AISettings | None:
        """Get AI settings for a specific user."""
        stmt = select(AISettings).where(AISettings.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, settings: AISettings) -> AISettings:
        """Insert new AI settings."""
        self.session.add(settings)
        await self.session.flush()
        return settings

    async def update_fields(self, settings_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on AI settings."""
        stmt = update(AISettings).where(AISettings.id == settings_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(AISettings, settings_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)


class AIEstimateJobRepository:
    """Data access for AIEstimateJob model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, job_id: uuid.UUID) -> AIEstimateJob | None:
        """Get an estimate job by ID (fresh SELECT, bypasses identity map)."""
        stmt = select(AIEstimateJob).where(AIEstimateJob.id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, job: AIEstimateJob) -> AIEstimateJob:
        """Insert a new estimate job."""
        self.session.add(job)
        await self.session.flush()
        return job

    async def update_fields(self, job_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an estimate job."""
        stmt = update(AIEstimateJob).where(AIEstimateJob.id == job_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(AIEstimateJob, job_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AIEstimateJob], int]:
        """List a user's estimate jobs, newest first, with a total count.

        Filters are optional and AND-combined. Returns ``(rows, total)`` where
        ``total`` is the unpaginated match count so the caller can render
        pagination controls. The ``user_id`` filter is always applied so one
        tenant never sees another's jobs.
        """
        conditions = [AIEstimateJob.user_id == user_id]
        if project_id is not None:
            conditions.append(AIEstimateJob.project_id == project_id)
        if status:
            conditions.append(AIEstimateJob.status == status)

        count_stmt = select(func.count(AIEstimateJob.id)).where(*conditions)
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)

        rows_stmt = (
            select(AIEstimateJob)
            .where(*conditions)
            .order_by(AIEstimateJob.created_at.desc(), AIEstimateJob.id.desc())
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
        rows = list((await self.session.execute(rows_stmt)).scalars().all())
        return rows, total
