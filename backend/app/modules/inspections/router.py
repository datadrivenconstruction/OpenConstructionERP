"""Inspections API routes.

Endpoints:
    GET    /                         - List inspections for a project
    POST   /                         - Create inspection
    GET    /{inspection_id}          - Get single inspection
    PATCH  /{inspection_id}          - Update inspection
    DELETE /{inspection_id}          - Delete inspection
    POST   /{inspection_id}/complete - Mark inspection as completed
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.inspections.schemas import (
    InspectionCreate,
    InspectionResponse,
    InspectionUpdate,
)
from app.modules.inspections.service import InspectionService

router = APIRouter()
logger = logging.getLogger(__name__)


class CompleteInspectionRequest(BaseModel):
    """Request body for completing an inspection."""

    result: str = Field(default="pass", pattern=r"^(pass|fail|partial)$")


def _get_service(session: SessionDep) -> InspectionService:
    return InspectionService(session)


def _to_response(item: object) -> InspectionResponse:
    """Build an InspectionResponse from a QualityInspection ORM object."""
    return InspectionResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        inspection_number=item.inspection_number,  # type: ignore[attr-defined]
        inspection_type=item.inspection_type,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        location=item.location,  # type: ignore[attr-defined]
        wbs_id=item.wbs_id,  # type: ignore[attr-defined]
        inspector_id=str(item.inspector_id) if item.inspector_id else None,  # type: ignore[attr-defined]
        inspection_date=item.inspection_date,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        result=item.result,  # type: ignore[attr-defined]
        checklist_data=item.checklist_data or [],  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[InspectionResponse])
async def list_inspections(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    service: InspectionService = Depends(_get_service),
) -> list[InspectionResponse]:
    """List inspections for a project with optional filters."""
    inspections, _ = await service.list_inspections(
        project_id,
        offset=offset,
        limit=limit,
        inspection_type=type_filter,
        status_filter=status_filter,
    )
    return [_to_response(i) for i in inspections]


@router.post("/", response_model=InspectionResponse, status_code=201)
async def create_inspection(
    data: InspectionCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("inspections.create")),
    service: InspectionService = Depends(_get_service),
) -> InspectionResponse:
    """Create a new quality inspection."""
    inspection = await service.create_inspection(data, user_id=user_id)
    return _to_response(inspection)


@router.get("/{inspection_id}", response_model=InspectionResponse)
async def get_inspection(
    inspection_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: InspectionService = Depends(_get_service),
) -> InspectionResponse:
    """Get a single inspection."""
    inspection = await service.get_inspection(inspection_id)
    return _to_response(inspection)


@router.patch("/{inspection_id}", response_model=InspectionResponse)
async def update_inspection(
    inspection_id: uuid.UUID,
    data: InspectionUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("inspections.update")),
    service: InspectionService = Depends(_get_service),
) -> InspectionResponse:
    """Update an inspection."""
    inspection = await service.update_inspection(inspection_id, data)
    return _to_response(inspection)


@router.delete("/{inspection_id}", status_code=204)
async def delete_inspection(
    inspection_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("inspections.delete")),
    service: InspectionService = Depends(_get_service),
) -> None:
    """Delete an inspection."""
    await service.delete_inspection(inspection_id)


@router.post("/{inspection_id}/complete", response_model=InspectionResponse)
async def complete_inspection(
    inspection_id: uuid.UUID,
    body: CompleteInspectionRequest | None = None,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("inspections.update")),
    service: InspectionService = Depends(_get_service),
) -> InspectionResponse:
    """Mark an inspection as completed with a pass/fail/partial result."""
    result = body.result if body else "pass"
    inspection = await service.complete_inspection(inspection_id, result=result)
    return _to_response(inspection)
