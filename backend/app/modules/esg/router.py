# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ESG Site Performance API routes.

Endpoints (mounted at /api/v1/esg):
    GET    /metrics                 - list the metric-definition catalogue
    GET    /summary?project_id=X    - per-metric KPI + trend, grouped by pillar
    GET    /entries?project_id=X    - list readings (optionally filtered by metric)
    POST   /entries                 - record a reading
    GET    /entries/{entry_id}      - get a single reading
    PATCH  /entries/{entry_id}      - update a reading's value / target / note
    DELETE /entries/{entry_id}      - delete a reading

Reads require ``esg.read`` (viewer); every mutation requires ``esg.write``
(editor). Collection routes are mirrored on the slash-less path (hidden from the
schema) so a reverse proxy that strips trailing slashes still gets a coherent
response under ``redirect_slashes=False`` (same rationale as the CDE module).
"""

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.esg.schemas import (
    EsgEntryCreate,
    EsgEntryResponse,
    EsgEntryUpdate,
    EsgSummaryResponse,
    MetricDefinitionResponse,
)
from app.modules.esg.service import EsgService

router = APIRouter(tags=["esg"])


def _get_service(session: SessionDep) -> EsgService:
    return EsgService(session)


# ── Metric catalogue ──────────────────────────────────────────────────────────


@router.get(
    "/metrics",
    response_model=list[MetricDefinitionResponse],
    dependencies=[Depends(RequirePermission("esg.read"))],
    include_in_schema=False,
)
@router.get(
    "/metrics/",
    response_model=list[MetricDefinitionResponse],
    dependencies=[Depends(RequirePermission("esg.read"))],
)
async def list_metric_definitions(
    service: EsgService = Depends(_get_service),
) -> list[MetricDefinitionResponse]:
    """Return the fixed catalogue of operational ESG metrics."""
    return service.list_metric_definitions()


# ── Summary ───────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=EsgSummaryResponse,
    dependencies=[Depends(RequirePermission("esg.read"))],
    include_in_schema=False,
)
@router.get(
    "/summary/",
    response_model=EsgSummaryResponse,
    dependencies=[Depends(RequirePermission("esg.read"))],
)
async def esg_summary(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    trend_periods: int = Query(default=6, ge=1, le=24),
    service: EsgService = Depends(_get_service),
) -> EsgSummaryResponse:
    """Per-metric KPI and short trend for a project, grouped by ESG pillar."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_summary(project_id, trend_periods=trend_periods)


# ── Entry list ────────────────────────────────────────────────────────────────


@router.get(
    "/entries",
    response_model=list[EsgEntryResponse],
    dependencies=[Depends(RequirePermission("esg.read"))],
    include_in_schema=False,
)
@router.get(
    "/entries/",
    response_model=list[EsgEntryResponse],
    dependencies=[Depends(RequirePermission("esg.read"))],
)
async def list_entries(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    metric_key: str | None = Query(default=None, alias="metric"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: EsgService = Depends(_get_service),
) -> list[EsgEntryResponse]:
    """List ESG readings for a project, optionally filtered to one metric."""
    await verify_project_access(project_id, user_id, session)
    entries, _ = await service.list_entries(
        project_id,
        metric_key=metric_key,
        offset=offset,
        limit=limit,
    )
    return [EsgEntryResponse.model_validate(e) for e in entries]


# ── Entry create ──────────────────────────────────────────────────────────────


@router.post(
    "/entries/",
    response_model=EsgEntryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("esg.write"))],
)
async def create_entry(
    data: EsgEntryCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EsgService = Depends(_get_service),
) -> EsgEntryResponse:
    """Record a new ESG reading for a metric in a period."""
    await verify_project_access(data.project_id, user_id, session)
    entry = await service.create_entry(data, user_id=user_id)
    await session.commit()
    return EsgEntryResponse.model_validate(entry)


# ── Entry get ─────────────────────────────────────────────────────────────────


@router.get(
    "/entries/{entry_id}",
    response_model=EsgEntryResponse,
    dependencies=[Depends(RequirePermission("esg.read"))],
)
async def get_entry(
    entry_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EsgService = Depends(_get_service),
) -> EsgEntryResponse:
    """Get a single ESG reading."""
    entry = await service.get_entry(entry_id)
    await verify_project_access(entry.project_id, user_id, session)
    return EsgEntryResponse.model_validate(entry)


# ── Entry update ──────────────────────────────────────────────────────────────


@router.patch(
    "/entries/{entry_id}",
    response_model=EsgEntryResponse,
    dependencies=[Depends(RequirePermission("esg.write"))],
)
async def update_entry(
    entry_id: uuid.UUID,
    data: EsgEntryUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EsgService = Depends(_get_service),
) -> EsgEntryResponse:
    """Update a reading's value, target or note."""
    existing = await service.get_entry(entry_id)
    await verify_project_access(existing.project_id, user_id, session)
    entry = await service.update_entry(entry_id, data)
    await session.commit()
    return EsgEntryResponse.model_validate(entry)


# ── Entry delete ──────────────────────────────────────────────────────────────


@router.delete(
    "/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("esg.write"))],
)
async def delete_entry(
    entry_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EsgService = Depends(_get_service),
) -> None:
    """Delete an ESG reading."""
    existing = await service.get_entry(entry_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_entry(entry_id)
    await session.commit()
