"""Safety API routes.

Endpoints:
    GET    /incidents                   - List incidents for a project
    POST   /incidents                   - Create incident
    GET    /incidents/{id}              - Get single incident
    PATCH  /incidents/{id}              - Update incident
    DELETE /incidents/{id}              - Delete incident
    GET    /observations                - List observations for a project
    POST   /observations                - Create observation
    GET    /observations/{id}           - Get single observation
    PATCH  /observations/{id}           - Update observation
    DELETE /observations/{id}           - Delete observation
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.safety.schemas import (
    IncidentCreate,
    IncidentResponse,
    IncidentUpdate,
    ObservationCreate,
    ObservationResponse,
    ObservationUpdate,
)
from app.modules.safety.service import SafetyService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> SafetyService:
    return SafetyService(session)


def _incident_to_response(item: object) -> IncidentResponse:
    return IncidentResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        incident_number=item.incident_number,  # type: ignore[attr-defined]
        incident_date=item.incident_date,  # type: ignore[attr-defined]
        location=item.location,  # type: ignore[attr-defined]
        incident_type=item.incident_type,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        injured_person_details=item.injured_person_details,  # type: ignore[attr-defined]
        treatment_type=item.treatment_type,  # type: ignore[attr-defined]
        days_lost=item.days_lost,  # type: ignore[attr-defined]
        root_cause=item.root_cause,  # type: ignore[attr-defined]
        corrective_actions=item.corrective_actions or [],  # type: ignore[attr-defined]
        reported_to_regulator=item.reported_to_regulator,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _observation_to_response(item: object) -> ObservationResponse:
    return ObservationResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        observation_number=item.observation_number,  # type: ignore[attr-defined]
        observation_type=item.observation_type,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        location=item.location,  # type: ignore[attr-defined]
        severity=item.severity,  # type: ignore[attr-defined]
        likelihood=item.likelihood,  # type: ignore[attr-defined]
        risk_score=item.risk_score,  # type: ignore[attr-defined]
        immediate_action=item.immediate_action,  # type: ignore[attr-defined]
        corrective_action=item.corrective_action,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Incidents ────────────────────────────────────────────────────────────


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    service: SafetyService = Depends(_get_service),
) -> list[IncidentResponse]:
    items, _ = await service.list_incidents(
        project_id,
        offset=offset,
        limit=limit,
        incident_type=type_filter,
        status_filter=status_filter,
    )
    return [_incident_to_response(i) for i in items]


@router.post("/incidents", response_model=IncidentResponse, status_code=201)
async def create_incident(
    data: IncidentCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("safety.create")),
    service: SafetyService = Depends(_get_service),
) -> IncidentResponse:
    incident = await service.create_incident(data, user_id=user_id)
    return _incident_to_response(incident)


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SafetyService = Depends(_get_service),
) -> IncidentResponse:
    incident = await service.get_incident(incident_id)
    return _incident_to_response(incident)


@router.patch("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: uuid.UUID,
    data: IncidentUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.update")),
    service: SafetyService = Depends(_get_service),
) -> IncidentResponse:
    incident = await service.update_incident(incident_id, data)
    return _incident_to_response(incident)


@router.delete("/incidents/{incident_id}", status_code=204)
async def delete_incident(
    incident_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.delete")),
    service: SafetyService = Depends(_get_service),
) -> None:
    await service.delete_incident(incident_id)


# ── Observations ─────────────────────────────────────────────────────────


@router.get("/observations", response_model=list[ObservationResponse])
async def list_observations(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    service: SafetyService = Depends(_get_service),
) -> list[ObservationResponse]:
    items, _ = await service.list_observations(
        project_id,
        offset=offset,
        limit=limit,
        observation_type=type_filter,
        status_filter=status_filter,
    )
    return [_observation_to_response(i) for i in items]


@router.post("/observations", response_model=ObservationResponse, status_code=201)
async def create_observation(
    data: ObservationCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("safety.create")),
    service: SafetyService = Depends(_get_service),
) -> ObservationResponse:
    observation = await service.create_observation(data, user_id=user_id)
    return _observation_to_response(observation)


@router.get("/observations/{observation_id}", response_model=ObservationResponse)
async def get_observation(
    observation_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SafetyService = Depends(_get_service),
) -> ObservationResponse:
    observation = await service.get_observation(observation_id)
    return _observation_to_response(observation)


@router.patch("/observations/{observation_id}", response_model=ObservationResponse)
async def update_observation(
    observation_id: uuid.UUID,
    data: ObservationUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.update")),
    service: SafetyService = Depends(_get_service),
) -> ObservationResponse:
    observation = await service.update_observation(observation_id, data)
    return _observation_to_response(observation)


@router.delete("/observations/{observation_id}", status_code=204)
async def delete_observation(
    observation_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.delete")),
    service: SafetyService = Depends(_get_service),
) -> None:
    await service.delete_observation(observation_id)
