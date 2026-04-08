"""Inspections API routes.

Endpoints:
    GET    /                         - List inspections for a project
    POST   /                         - Create inspection
    GET    /export                   - Export inspections as Excel
    GET    /{inspection_id}          - Get single inspection
    PATCH  /{inspection_id}          - Update inspection
    DELETE /{inspection_id}          - Delete inspection
    POST   /{inspection_id}/complete - Mark inspection as completed
"""

import io
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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


@router.get("/export")
async def export_inspections(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    _user: CurrentUserId = None,  # type: ignore[assignment]
) -> StreamingResponse:
    """Export inspections for a project as Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from sqlalchemy import select

    from app.modules.inspections.models import QualityInspection

    result = await session.execute(
        select(QualityInspection)
        .where(QualityInspection.project_id == project_id)
        .order_by(QualityInspection.inspection_number)
        .limit(50000)
    )
    items = result.scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Inspections"

    headers = [
        "Inspection #",
        "Title",
        "Type",
        "Inspector",
        "Date",
        "Location",
        "Status",
        "Result",
        "Checklist Items (pass/fail)",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True)

    for row_idx, item in enumerate(items, 2):
        ws.cell(row=row_idx, column=1, value=item.inspection_number)
        ws.cell(row=row_idx, column=2, value=item.title)
        ws.cell(row=row_idx, column=3, value=item.inspection_type)
        ws.cell(row=row_idx, column=4, value=str(item.inspector_id) if item.inspector_id else "")
        ws.cell(row=row_idx, column=5, value=item.inspection_date or "")
        ws.cell(row=row_idx, column=6, value=item.location or "")
        ws.cell(row=row_idx, column=7, value=item.status)
        ws.cell(row=row_idx, column=8, value=item.result or "")
        # Checklist pass/fail count
        checklist = item.checklist_data or []
        passed = sum(
            1 for ci in checklist if isinstance(ci, dict) and ci.get("passed")
        )
        failed = len(checklist) - passed
        ws.cell(row=row_idx, column=9, value=f"{passed}/{failed}")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="inspections.xlsx"'},
    )


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


@router.post("/{inspection_id}/create-defect")
async def create_defect_from_inspection(
    inspection_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("inspections.update")),
    service: InspectionService = Depends(_get_service),
) -> dict:
    """Create a punchlist item pre-filled from a failed inspection.

    The inspection must have result='fail' or 'partial'. Pre-fills the
    punchlist item with the inspection's title, location, and checklist
    details for failed items.
    """
    inspection = await service.get_inspection(inspection_id)
    if inspection.result not in ("fail", "partial"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Only failed or partial inspections can create defects.",
        )

    # Build description from failed checklist items
    checklist = inspection.checklist_data or []
    failed_items = [
        ci.get("description", ci.get("question", "Unknown item"))
        for ci in checklist
        if isinstance(ci, dict) and not ci.get("passed", True)
    ]
    description_parts = [
        f"Defect from inspection {inspection.inspection_number}: {inspection.title}",
    ]
    if failed_items:
        description_parts.append("Failed items:")
        for item in failed_items:
            description_parts.append(f"  - {item}")

    description = "\n".join(description_parts)

    # Lazy import punchlist module
    try:
        from app.modules.punchlist.models import PunchItem

        punch_item = PunchItem(
            project_id=inspection.project_id,
            title=f"Defect: {inspection.title}",
            description=description,
            priority="high" if inspection.result == "fail" else "medium",
            status="open",
            category=inspection.inspection_type if inspection.inspection_type in (
                "structural", "electrical", "plumbing", "fire_safety", "general"
            ) else "general",
            trade=inspection.inspection_type,
            created_by=str(user_id),
            metadata_={
                "source": "inspection",
                "inspection_id": str(inspection_id),
                "inspection_number": inspection.inspection_number,
            },
        )
        # Copy location if available
        if inspection.location:
            punch_item.title = f"Defect: {inspection.title} @ {inspection.location}"
        session.add(punch_item)
        await session.flush()

        logger.info(
            "Created punchlist item %s from inspection %s",
            punch_item.id,
            inspection_id,
        )
        return {
            "punch_item_id": str(punch_item.id),
            "inspection_id": str(inspection_id),
            "title": punch_item.title,
        }
    except ImportError:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=501,
            detail="Punchlist module is not available.",
        )
    except Exception as exc:
        logger.exception("Failed to create defect from inspection %s: %s", inspection_id, exc)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail="Failed to create punchlist item from inspection.",
        )


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
