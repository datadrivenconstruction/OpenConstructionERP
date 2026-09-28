# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Safety API routes.

Endpoints:
    GET    /stats                       - Project safety KPI dashboard
    GET    /trends                      - Incident/observation counts per period
    GET    /trends/extended             - Rolling LTIFR/TRIR time series + trend
    GET    /threshold-alert             - Current LTIFR/TRIR vs safe-baseline status
    GET    /indicators                  - Leading vs lagging safety indicators rollup
    GET    /incidents                   - List incidents for a project
    POST   /incidents                   - Create incident
    GET    /incidents/{id}              - Get single incident
    PATCH  /incidents/{id}              - Update incident
    DELETE /incidents/{id}              - Delete incident
    GET    /incidents/export            - Export incidents as Excel
    GET    /observations                - List observations for a project
    POST   /observations                - Create observation
    GET    /observations/{id}           - Get single observation
    PATCH  /observations/{id}           - Update observation
    DELETE /observations/{id}           - Delete observation
    GET    /observations/export         - Export observations as Excel
"""

import asyncio
import io
import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.safety.schemas import (
    IncidentCreate,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdate,
    ObservationCreate,
    ObservationResponse,
    ObservationUpdate,
    SafetyIndicatorsResponse,
    SafetyStatsResponse,
    SafetyThresholdAlertResponse,
    SafetyTrendsExtendedResponse,
    SafetyTrendsResponse,
)
from app.modules.safety.service import SafetyService

router = APIRouter(tags=["safety"])
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
        severity=item.severity,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        injured_person_details=item.injured_person_details,  # type: ignore[attr-defined]
        treatment_type=item.treatment_type,  # type: ignore[attr-defined]
        days_lost=item.days_lost,  # type: ignore[attr-defined]
        root_cause=item.root_cause,  # type: ignore[attr-defined]
        corrective_actions=item.corrective_actions or [],  # type: ignore[attr-defined]
        reported_to_regulator=item.reported_to_regulator,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        geo_lat=getattr(item, "geo_lat", None),
        geo_lon=getattr(item, "geo_lon", None),
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _observation_to_response(item: object) -> ObservationResponse:
    from app.modules.safety.service import _compute_risk_tier

    risk_score = item.risk_score  # type: ignore[attr-defined]
    return ObservationResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        observation_number=item.observation_number,  # type: ignore[attr-defined]
        observation_type=item.observation_type,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        location=item.location,  # type: ignore[attr-defined]
        severity=item.severity,  # type: ignore[attr-defined]
        likelihood=item.likelihood,  # type: ignore[attr-defined]
        risk_score=risk_score,
        risk_tier=_compute_risk_tier(risk_score),
        immediate_action=item.immediate_action,  # type: ignore[attr-defined]
        corrective_action=item.corrective_action,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Stats & Trends ──────────────────────────────────────────────────────


@router.get("/stats/", response_model=SafetyStatsResponse)
async def safety_stats(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> SafetyStatsResponse:
    """Return dashboard KPIs: incident counts, days without incident,
    observations by risk tier, open corrective actions, etc.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_stats(project_id)


@router.get("/trends/", response_model=SafetyTrendsResponse)
async def safety_trends(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    period: str = Query(default="monthly", pattern=r"^(monthly|weekly)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> SafetyTrendsResponse:
    """Return time-series incident and observation data grouped by period."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_trends(project_id, period=period)


@router.get("/trends/extended/", response_model=SafetyTrendsExtendedResponse)
async def safety_trends_extended(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    period: str = Query(default="monthly", pattern=r"^(monthly|weekly)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> SafetyTrendsExtendedResponse:
    """Return a rolling LTIFR/TRIR time series and the trend direction."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_trends_extended(project_id, period=period)


@router.get("/threshold-alert/", response_model=SafetyThresholdAlertResponse)
async def safety_threshold_alert(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    baseline_ltifr: float = Query(default=2.5, ge=0.0),
    baseline_trir: float = Query(default=3.0, ge=0.0),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> SafetyThresholdAlertResponse:
    """Check current LTIFR/TRIR against safe-baselines; return a status band."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_threshold_alert(
        project_id,
        baseline_ltifr=baseline_ltifr,
        baseline_trir=baseline_trir,
    )


@router.get("/indicators/", response_model=SafetyIndicatorsResponse)
async def safety_indicators(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> SafetyIndicatorsResponse:
    """Return leading vs lagging safety indicators for a project over a period.

    Leading (near-misses reported, observations opened/closed, corrective-action
    close rate) is shown side by side with lagging (recordable/lost-time
    incidents, days lost, TRIR/LTIFR/severity rate). ``period_start`` and
    ``period_end`` are optional inclusive ISO date bounds; ``period_end`` is the
    as-of cutoff.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_safety_indicators(
        project_id,
        period_start=period_start,
        period_end=period_end,
    )


# ── Incidents ────────────────────────────────────────────────────────────


@router.get("/incidents/", response_model=IncidentListResponse)
async def list_incidents(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> IncidentListResponse:
    """List one page of safety incidents for a project.

    The repository has counted the matching set since it was written and the
    count was discarded here. Four surfaces read this route and none of them
    sends a limit, so all four took the default fifty and presented it as the
    register.
    """
    await verify_project_access(project_id, user_id, session)
    items, total = await service.list_incidents(
        project_id,
        offset=offset,
        limit=limit,
        incident_type=type_filter,
        status_filter=status_filter,
    )
    return IncidentListResponse(
        items=[_incident_to_response(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/incidents/", response_model=IncidentResponse, status_code=201)
async def create_incident(
    data: IncidentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("safety.create")),
    service: SafetyService = Depends(_get_service),
) -> IncidentResponse:
    """Create a new safety incident."""
    await verify_project_access(data.project_id, user_id, session)
    incident = await service.create_incident(data, user_id=user_id)
    return _incident_to_response(incident)


def _render_register_xlsx(title: str, headers: list[str], rows: list[list[object]]) -> io.BytesIO:
    """Build a one-sheet register workbook from plain cell values (pure CPU, no DB)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.core.xlsx_branding import apply_company_header
    from app.core.xlsx_text import store_strings_as_text

    wb = Workbook()
    ws = wb.active
    ws.title = title

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True)

    for row_idx, values in enumerate(rows, 2):
        for col, value in enumerate(values, 1):
            ws.cell(row=row_idx, column=col, value=value)

    # Company letterhead above the table; a no-op without a company profile.
    store_strings_as_text(ws)
    apply_company_header(ws, title=ws.title)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@router.get("/incidents/export/")
async def export_incidents(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    _user: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
) -> StreamingResponse:
    """Export safety incidents for a project as Excel."""
    await verify_project_access(project_id, _user, session)
    from sqlalchemy import select

    from app.modules.safety.models import SafetyIncident

    result = await session.execute(
        select(SafetyIncident)
        .where(SafetyIncident.project_id == project_id)
        .order_by(SafetyIncident.incident_number)
        .limit(50000)
    )
    items = result.scalars().all()

    headers = [
        "Incident #",
        "Date",
        "Type",
        "Location",
        "Description",
        "Severity",
        "Treatment",
        "Days Lost",
        "Root Cause",
        "Status",
        "Reported to Regulator",
    ]
    rows = [
        [
            item.incident_number,
            item.incident_date,
            item.incident_type,
            item.location or "",
            item.description,
            item.severity,
            item.treatment_type or "",
            item.days_lost,
            item.root_cause or "",
            item.status,
            "Yes" if item.reported_to_regulator else "No",
        ]
        for item in items
    ]

    # Writing the workbook walks every incident and is pure CPU, so it runs in a
    # worker thread instead of holding up every other request on the event loop.
    buf = await asyncio.to_thread(_render_register_xlsx, "Safety Incidents", headers, rows)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="safety_incidents.xlsx"'},
    )


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> IncidentResponse:
    """Get a single safety incident."""
    incident = await service.get_incident(incident_id)
    await verify_project_access(incident.project_id, user_id, session)
    return _incident_to_response(incident)


@router.patch("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: uuid.UUID,
    data: IncidentUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.update")),
    service: SafetyService = Depends(_get_service),
) -> IncidentResponse:
    """Update a safety incident."""
    incident = await service.get_incident(incident_id)
    await verify_project_access(incident.project_id, user_id, session)
    incident = await service.update_incident(incident_id, data)
    return _incident_to_response(incident)


@router.delete("/incidents/{incident_id}", status_code=204)
async def delete_incident(
    incident_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.delete")),
    service: SafetyService = Depends(_get_service),
) -> None:
    """Delete a safety incident."""
    incident = await service.get_incident(incident_id)
    await verify_project_access(incident.project_id, user_id, session)
    await service.delete_incident(incident_id)


# ── Observations ─────────────────────────────────────────────────────────


@router.get("/observations/", response_model=list[ObservationResponse])
async def list_observations(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> list[ObservationResponse]:
    """List safety observations for a project."""
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_observations(
        project_id,
        offset=offset,
        limit=limit,
        observation_type=type_filter,
        status_filter=status_filter,
    )
    return [_observation_to_response(i) for i in items]


@router.post("/observations/", response_model=ObservationResponse, status_code=201)
async def create_observation(
    data: ObservationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("safety.create")),
    service: SafetyService = Depends(_get_service),
) -> ObservationResponse:
    """Create a new safety observation."""
    await verify_project_access(data.project_id, user_id, session)
    observation = await service.create_observation(data, user_id=user_id)
    return _observation_to_response(observation)


@router.get("/observations/export/")
async def export_observations(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    _user: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
) -> StreamingResponse:
    """Export safety observations for a project as Excel."""
    await verify_project_access(project_id, _user, session)
    from sqlalchemy import select

    from app.modules.safety.models import SafetyObservation
    from app.modules.safety.service import _compute_risk_tier

    result = await session.execute(
        select(SafetyObservation)
        .where(SafetyObservation.project_id == project_id)
        .order_by(SafetyObservation.observation_number)
        .limit(50000)
    )
    items = result.scalars().all()

    headers = [
        "Observation #",
        "Date",
        "Type",
        "Location",
        "Description",
        "Severity",
        "Likelihood",
        "Risk Score",
        "Risk Tier",
        "Status",
        "Corrective Action",
    ]
    rows = [
        [
            item.observation_number,
            str(item.created_at) if item.created_at else "",
            item.observation_type,
            item.location or "",
            item.description,
            item.severity,
            item.likelihood,
            item.risk_score,
            # Risk tier derived from risk score (same logic/casing as API responses)
            _compute_risk_tier(item.risk_score),
            item.status,
            item.corrective_action or "",
        ]
        for item in items
    ]

    # Writing the workbook walks every observation and is pure CPU, so it runs in
    # a worker thread instead of holding up every other request on the event loop.
    buf = await asyncio.to_thread(_render_register_xlsx, "Safety Observations", headers, rows)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="safety_observations.xlsx"'},
    )


@router.get("/observations/{observation_id}", response_model=ObservationResponse)
async def get_observation(
    observation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.read")),
    service: SafetyService = Depends(_get_service),
) -> ObservationResponse:
    """Get a single safety observation."""
    observation = await service.get_observation(observation_id)
    await verify_project_access(observation.project_id, user_id, session)
    return _observation_to_response(observation)


@router.patch("/observations/{observation_id}", response_model=ObservationResponse)
async def update_observation(
    observation_id: uuid.UUID,
    data: ObservationUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.update")),
    service: SafetyService = Depends(_get_service),
) -> ObservationResponse:
    """Update a safety observation."""
    observation = await service.get_observation(observation_id)
    await verify_project_access(observation.project_id, user_id, session)
    observation = await service.update_observation(observation_id, data)
    return _observation_to_response(observation)


@router.delete("/observations/{observation_id}", status_code=204)
async def delete_observation(
    observation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("safety.delete")),
    service: SafetyService = Depends(_get_service),
) -> None:
    """Delete a safety observation."""
    observation = await service.get_observation(observation_id)
    await verify_project_access(observation.project_id, user_id, session)
    await service.delete_observation(observation_id)
