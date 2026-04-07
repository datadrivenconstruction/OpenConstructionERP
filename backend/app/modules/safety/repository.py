"""Safety data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SafetyIncident, SafetyObservation


class IncidentRepository:
    """Data access for SafetyIncident models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, incident_id: uuid.UUID) -> SafetyIncident | None:
        return await self.session.get(SafetyIncident, incident_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        incident_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[SafetyIncident], int]:
        base = select(SafetyIncident).where(SafetyIncident.project_id == project_id)
        if incident_type is not None:
            base = base.where(SafetyIncident.incident_type == incident_type)
        if status is not None:
            base = base.where(SafetyIncident.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(SafetyIncident.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_incident_number(self, project_id: uuid.UUID) -> str:
        stmt = (
            select(func.count())
            .select_from(SafetyIncident)
            .where(SafetyIncident.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"INC-{count + 1:03d}"

    async def create(self, incident: SafetyIncident) -> SafetyIncident:
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def update_fields(self, incident_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(SafetyIncident)
            .where(SafetyIncident.id == incident_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, incident_id: uuid.UUID) -> None:
        incident = await self.get_by_id(incident_id)
        if incident is not None:
            await self.session.delete(incident)
            await self.session.flush()


class ObservationRepository:
    """Data access for SafetyObservation models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, observation_id: uuid.UUID) -> SafetyObservation | None:
        return await self.session.get(SafetyObservation, observation_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        observation_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[SafetyObservation], int]:
        base = select(SafetyObservation).where(
            SafetyObservation.project_id == project_id
        )
        if observation_type is not None:
            base = base.where(SafetyObservation.observation_type == observation_type)
        if status is not None:
            base = base.where(SafetyObservation.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(SafetyObservation.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def next_observation_number(self, project_id: uuid.UUID) -> str:
        stmt = (
            select(func.count())
            .select_from(SafetyObservation)
            .where(SafetyObservation.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"OBS-{count + 1:03d}"

    async def create(self, observation: SafetyObservation) -> SafetyObservation:
        self.session.add(observation)
        await self.session.flush()
        return observation

    async def update_fields(self, observation_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(SafetyObservation)
            .where(SafetyObservation.id == observation_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, observation_id: uuid.UUID) -> None:
        observation = await self.get_by_id(observation_id)
        if observation is not None:
            await self.session.delete(observation)
            await self.session.flush()
