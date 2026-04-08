"""Safety service — business logic for incident and observation management."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.safety.repository import IncidentRepository, ObservationRepository
from app.modules.safety.schemas import (
    IncidentCreate,
    IncidentUpdate,
    ObservationCreate,
    ObservationUpdate,
    SafetyStatsResponse,
    SafetyTrendsResponse,
)

logger = logging.getLogger(__name__)


def _compute_risk_tier(risk_score: int) -> str:
    """Derive risk tier from risk_score.

    Tiers: low (1-5), medium (6-10), high (11-15), critical (16-25).
    """
    if risk_score >= 16:
        return "critical"
    if risk_score >= 11:
        return "high"
    if risk_score >= 6:
        return "medium"
    return "low"


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
            title=data.title,
            incident_date=data.incident_date,
            location=data.location,
            incident_type=data.incident_type,
            severity=data.severity,
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
        """Create a new safety observation with computed risk score and tier.

        Emits ``safety.observation.high_risk`` event when risk_score > 15.
        """
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
            "Safety observation created: %s (%s, risk=%d) for project %s",
            observation_number,
            data.observation_type,
            risk_score,
            data.project_id,
        )

        # Emit high-risk event for notifications (cross-module handler)
        if risk_score > 15:
            await event_bus.publish(
                "safety.observation.high_risk",
                data={
                    "project_id": str(data.project_id),
                    "observation_id": str(observation.id),
                    "observation_number": observation_number,
                    "risk_score": risk_score,
                    "description": data.description[:200],
                    "notify_user_ids": [],  # Populated by handler from project team
                },
                source_module="safety",
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

        # Emit high-risk event if risk_score crossed the critical threshold
        new_risk_score = fields.get("risk_score", observation.risk_score)
        if new_risk_score > 15:
            await event_bus.publish(
                "safety.observation.high_risk",
                data={
                    "project_id": str(observation.project_id),
                    "observation_id": str(observation_id),
                    "observation_number": observation.observation_number,
                    "risk_score": new_risk_score,
                    "description": (observation.description or "")[:200],
                    "notify_user_ids": [],
                },
                source_module="safety",
            )

        logger.info("Safety observation updated: %s (risk=%d)", observation_id, new_risk_score)
        return observation

    async def delete_observation(self, observation_id: uuid.UUID) -> None:
        await self.get_observation(observation_id)
        await self.observation_repo.delete(observation_id)
        logger.info("Safety observation deleted: %s", observation_id)

    # ── Stats & Trends ──────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> SafetyStatsResponse:
        """Compute safety KPIs for a project dashboard.

        Includes incident/observation counts, days without incident,
        LTIFR, TRIR, and breakdowns by type/status/risk tier.
        """
        from collections import defaultdict
        from datetime import UTC, datetime

        from sqlalchemy import select

        # Fetch all incidents
        inc_result = await self.session.execute(
            select(SafetyIncident).where(SafetyIncident.project_id == project_id)
        )
        incidents = list(inc_result.scalars().all())

        # Fetch all observations
        obs_result = await self.session.execute(
            select(SafetyObservation).where(SafetyObservation.project_id == project_id)
        )
        observations = list(obs_result.scalars().all())

        total_incidents = len(incidents)
        total_observations = len(observations)
        total_days_lost = 0
        recordable_incidents = 0
        lost_time_incidents = 0
        incidents_by_type: dict[str, int] = defaultdict(int)
        incidents_by_status: dict[str, int] = defaultdict(int)
        open_corrective_actions = 0
        latest_incident_date: str | None = None

        recordable_treatments = {"medical", "hospital", "fatality"}

        for inc in incidents:
            total_days_lost += inc.days_lost or 0
            incidents_by_type[inc.incident_type] += 1
            incidents_by_status[inc.status] += 1

            if inc.treatment_type in recordable_treatments:
                recordable_incidents += 1
            if inc.days_lost and inc.days_lost > 0:
                lost_time_incidents += 1

            # Track latest incident date
            if inc.incident_date:
                if latest_incident_date is None or inc.incident_date > latest_incident_date:
                    latest_incident_date = inc.incident_date

            # Count open corrective actions
            for ca in inc.corrective_actions or []:
                if isinstance(ca, dict) and ca.get("status") in ("open", "in_progress"):
                    open_corrective_actions += 1

        # Days without incident
        days_without_incident: int | None = None
        if latest_incident_date:
            try:
                last_inc = datetime.fromisoformat(latest_incident_date)
                if last_inc.tzinfo is None:
                    last_inc = last_inc.replace(tzinfo=UTC)
                now = datetime.now(UTC)
                days_without_incident = max(0, (now - last_inc).days)
            except (ValueError, TypeError):
                pass

        # Observations by risk tier
        observations_by_risk_tier: dict[str, int] = defaultdict(int)
        for obs in observations:
            tier = _compute_risk_tier(obs.risk_score)
            observations_by_risk_tier[tier] += 1

        # LTIFR and TRIR -- require man-hours to compute properly
        # Convention: if any incident has metadata.man_hours_total, use it
        # Otherwise return None (not enough data)
        ltifr: float | None = None
        trir: float | None = None

        return SafetyStatsResponse(
            total_incidents=total_incidents,
            total_observations=total_observations,
            days_without_incident=days_without_incident,
            total_days_lost=total_days_lost,
            recordable_incidents=recordable_incidents,
            ltifr=ltifr,
            trir=trir,
            incidents_by_type=dict(incidents_by_type),
            incidents_by_status=dict(incidents_by_status),
            observations_by_risk_tier=dict(observations_by_risk_tier),
            open_corrective_actions=open_corrective_actions,
        )

    async def get_trends(
        self,
        project_id: uuid.UUID,
        period: str = "monthly",
    ) -> SafetyTrendsResponse:
        """Compute time-series safety data grouped by month or week.

        Args:
            project_id: Target project.
            period: 'monthly' (default) or 'weekly'.

        Returns:
            SafetyTrendsResponse with ordered entries.
        """
        from collections import defaultdict

        from sqlalchemy import select

        from app.modules.safety.schemas import SafetyTrendEntry

        # Fetch incidents
        inc_result = await self.session.execute(
            select(SafetyIncident).where(SafetyIncident.project_id == project_id)
        )
        incidents = list(inc_result.scalars().all())

        # Fetch observations
        obs_result = await self.session.execute(
            select(SafetyObservation).where(SafetyObservation.project_id == project_id)
        )
        observations = list(obs_result.scalars().all())

        buckets: dict[str, dict[str, int]] = defaultdict(
            lambda: {"incident_count": 0, "observation_count": 0, "days_lost": 0}
        )

        def _bucket_key(date_str: str) -> str:
            """Derive period key from an ISO date string."""
            if period == "weekly":
                try:
                    from datetime import date as dt_date

                    d = dt_date.fromisoformat(date_str[:10])
                    # ISO week: YYYY-Wnn
                    iso_year, iso_week, _ = d.isocalendar()
                    return f"{iso_year}-W{iso_week:02d}"
                except (ValueError, TypeError):
                    return "unknown"
            else:
                # monthly: YYYY-MM
                return date_str[:7] if date_str and len(date_str) >= 7 else "unknown"

        for inc in incidents:
            key = _bucket_key(inc.incident_date)
            buckets[key]["incident_count"] += 1
            buckets[key]["days_lost"] += inc.days_lost or 0

        for obs in observations:
            # Observations use created_at for trending
            if obs.created_at:
                key = _bucket_key(str(obs.created_at)[:10])
                buckets[key]["observation_count"] += 1

        # Sort by period key
        entries = [
            SafetyTrendEntry(
                period=k,
                incident_count=v["incident_count"],
                observation_count=v["observation_count"],
                days_lost=v["days_lost"],
            )
            for k, v in sorted(buckets.items())
        ]

        return SafetyTrendsResponse(period_type=period, entries=entries)
