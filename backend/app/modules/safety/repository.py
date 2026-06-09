"""‌⁠‍Safety data access layer."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SafetyIncident, SafetyObservation

# How many times a colliding number is re-derived before giving up. A handful
# of concurrent writers only ever need one or two retries; the cap stops a
# pathological hot loop.
_NUMBER_RETRY_LIMIT = 5


def _next_suffix(numbers: list[str]) -> int:
    """Return MAX(trailing integer) + 1 over a list of ``PREFIX-NNN`` codes.

    Robust to deletions (the highest issued suffix is never reused) and to
    rows whose number doesn't match the expected ``PREFIX-<int>`` shape
    (those are simply ignored). Returns 1 when nothing parseable exists.
    """
    highest = 0
    for number in numbers:
        if not number:
            continue
        suffix = number.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


class IncidentRepository:
    """‌⁠‍Data access for SafetyIncident models."""

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
        # Derive the next number from MAX(numeric suffix)+1 rather than
        # COUNT(*)+1: a COUNT drops after any delete, so the next create
        # would re-issue an already-used INC- number. Scanning the existing
        # numbers for this project and taking the highest suffix keeps the
        # sequence monotonic across deletions. Numbers are bounded per
        # project, so the column-only fetch is cheap.
        stmt = select(SafetyIncident.incident_number).where(SafetyIncident.project_id == project_id)
        numbers = (await self.session.execute(stmt)).scalars().all()
        return f"INC-{_next_suffix(numbers):03d}"

    async def create(self, incident: SafetyIncident) -> SafetyIncident:
        """Insert an incident, deriving its number with a retry on collision.

        The number comes from MAX(suffix)+1, which can race two concurrent
        creates onto the same value. The per-project unique constraint turns
        that race into an IntegrityError; we roll back the failed insert, re-read
        the MAX and try again.
        """
        # Read project_id once: after a savepoint rollback the instance is
        # expired, so reading it inside the loop could trigger a lazy load.
        project_id = incident.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            incident.incident_number = await self.next_incident_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(incident)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return incident
        raise RuntimeError(f"Could not allocate a unique incident number for project {project_id}")

    async def update_fields(self, incident_id: uuid.UUID, **fields: object) -> None:
        stmt = update(SafetyIncident).where(SafetyIncident.id == incident_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, incident_id: uuid.UUID) -> None:
        incident = await self.get_by_id(incident_id)
        if incident is not None:
            await self.session.delete(incident)
            await self.session.flush()


class ObservationRepository:
    """‌⁠‍Data access for SafetyObservation models."""

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
        base = select(SafetyObservation).where(SafetyObservation.project_id == project_id)
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
        # MAX(numeric suffix)+1 - see next_incident_number for the rationale
        # (COUNT(*)+1 reuses numbers after a delete).
        stmt = select(SafetyObservation.observation_number).where(SafetyObservation.project_id == project_id)
        numbers = (await self.session.execute(stmt)).scalars().all()
        return f"OBS-{_next_suffix(numbers):03d}"

    async def create(self, observation: SafetyObservation) -> SafetyObservation:
        """Insert an observation, deriving its number with a retry on collision.

        The number comes from MAX(suffix)+1, which can race two concurrent
        creates onto the same value. The per-project unique constraint turns
        that race into an IntegrityError; we roll back the failed insert, re-read
        the MAX and try again.
        """
        # Read project_id once: after a savepoint rollback the instance is
        # expired, so reading it inside the loop could trigger a lazy load.
        project_id = observation.project_id
        for _ in range(_NUMBER_RETRY_LIMIT):
            observation.observation_number = await self.next_observation_number(project_id)
            savepoint = await self.session.begin_nested()
            self.session.add(observation)
            try:
                await self.session.flush()
            except IntegrityError:
                await savepoint.rollback()
                continue
            return observation
        raise RuntimeError(f"Could not allocate a unique observation number for project {project_id}")

    async def update_fields(self, observation_id: uuid.UUID, **fields: object) -> None:
        stmt = update(SafetyObservation).where(SafetyObservation.id == observation_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, observation_id: uuid.UUID) -> None:
        observation = await self.get_by_id(observation_id)
        if observation is not None:
            await self.session.delete(observation)
            await self.session.flush()
