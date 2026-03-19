"""AI module data access layer.

All database queries for AI settings and estimate jobs live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def update_fields(
        self, settings_id: uuid.UUID, **fields: object
    ) -> None:
        """Update specific fields on AI settings."""
        stmt = (
            update(AISettings)
            .where(AISettings.id == settings_id)
            .values(**fields)
        )
        await self.session.execute(stmt)


class AIEstimateJobRepository:
    """Data access for AIEstimateJob model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, job_id: uuid.UUID) -> AIEstimateJob | None:
        """Get an estimate job by ID."""
        return await self.session.get(AIEstimateJob, job_id)

    async def create(self, job: AIEstimateJob) -> AIEstimateJob:
        """Insert a new estimate job."""
        self.session.add(job)
        await self.session.flush()
        return job

    async def update_fields(
        self, job_id: uuid.UUID, **fields: object
    ) -> None:
        """Update specific fields on an estimate job."""
        stmt = (
            update(AIEstimateJob)
            .where(AIEstimateJob.id == job_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
