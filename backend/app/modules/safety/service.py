"""Safety service — business logic for incident and observation management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.safety.repository import IncidentRepository, ObservationRepository
from app.modules.safety.schemas import (
    IncidentCreate,
    IncidentUpdate,
    ObservationCreate,
    ObservationUpdate,
)

logger = logging.getLogger(__name__)


class SafetyService:
    """Business logic for safety incidents and observations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incident_repo = IncidentRepository(session)
        self.observation_repo = ObservationRepository(session)

    # ── Incidents ─────────────────────────────────────────────────────────

    async def create_incident(
        self,
        data: IncidentCreate,
        user_id: str | None = None,
    ) -> SafetyIncident:
        """Create a new safety incident."""
        incident_number = await self.incident_repo.next_incident_number(data.project_id)

        corrective_actions = [entry.model_dump() for entry in data.corrective_actions]

        incident = SafetyIncident(
            project_id=data.project_id,
            incident_number=incident_number,
            incident_date=data.incident_date,
            location=data.location,
            incident_type=data.incident_type,
            description=data.description,
            injured_person_details=data.injured_person_details,
            treatment_type=data.treatment_type,
            days_lost=data.days_lost,
            root_cause=data.root_cause,
            corrective_actions=corrective_actions,
            reported_to_regulator=data.reported_to_regulator,
            status=data.status,
            created_by=user_id,
            metadata_=data.metadata,
        )
        incident = await self.incident_repo.create(incident)
        logger.info(
            "Safety incident created: %s (%s) for project %s",
            incident_number,
            data.incident_type,
            data.project_id,
        )
        return incident

    async def get_incident(self, incident_id: uuid.UUID) -> SafetyIncident:
        incident = await self.incident_repo.get_by_id(incident_id)
        if incident is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Safety incident not found",
            )
        return incident

    async def list_incidents(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        incident_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[SafetyIncident], int]:
        return await self.incident_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            incident_type=incident_type,
            status=status_filter,
        )

    async def update_incident(
        self,
        incident_id: uuid.UUID,
        data: IncidentUpdate,
    ) -> SafetyIncident:
        incident = await self.get_incident(incident_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "corrective_actions" in fields and fields["corrective_actions"] is not None:
            fields["corrective_actions"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry
                for entry in fields["corrective_actions"]
            ]

        if not fields:
            return incident

        await self.incident_repo.update_fields(incident_id, **fields)
        await self.session.refresh(incident)
        logger.info("Safety incident updated: %s", incident_id)
        return incident

    async def delete_incident(self, incident_id: uuid.UUID) -> None:
        await self.get_incident(incident_id)
        await self.incident_repo.delete(incident_id)
        logger.info("Safety incident deleted: %s", incident_id)

    # ── Observations ─────────────────────────────────────────────────────

    async def create_observation(
        self,
        data: ObservationCreate,
        user_id: str | None = None,
    ) -> SafetyObservation:
        """Create a new safety observation with computed risk score."""
        observation_number = await self.observation_repo.next_observation_number(
            data.project_id
        )
        risk_score = data.severity * data.likelihood

        observation = SafetyObservation(
            project_id=data.project_id,
            observation_number=observation_number,
            observation_type=data.observation_type,
            description=data.description,
            location=data.location,
            severity=data.severity,
            likelihood=data.likelihood,
            risk_score=risk_score,
            immediate_action=data.immediate_action,
            corrective_action=data.corrective_action,
            status=data.status,
            created_by=user_id,
            metadata_=data.metadata,
        )
        observation = await self.observation_repo.create(observation)
        logger.info(
            "Safety observation created: %s (%s) for project %s",
            observation_number,
            data.observation_type,
            data.project_id,
        )
        return observation

    async def get_observation(self, observation_id: uuid.UUID) -> SafetyObservation:
        observation = await self.observation_repo.get_by_id(observation_id)
        if observation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Safety observation not found",
            )
        return observation

    async def list_observations(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        observation_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[SafetyObservation], int]:
        return await self.observation_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            observation_type=observation_type,
            status=status_filter,
        )

    async def update_observation(
        self,
        observation_id: uuid.UUID,
        data: ObservationUpdate,
    ) -> SafetyObservation:
        observation = await self.get_observation(observation_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recompute risk score if severity or likelihood changed
        severity = fields.get("severity", observation.severity)
        likelihood = fields.get("likelihood", observation.likelihood)
        if "severity" in fields or "likelihood" in fields:
            fields["risk_score"] = severity * likelihood

        if not fields:
            return observation

        await self.observation_repo.update_fields(observation_id, **fields)
        await self.session.refresh(observation)
        logger.info("Safety observation updated: %s", observation_id)
        return observation

    async def delete_observation(self, observation_id: uuid.UUID) -> None:
        await self.get_observation(observation_id)
        await self.observation_repo.delete(observation_id)
        logger.info("Safety observation deleted: %s", observation_id)
