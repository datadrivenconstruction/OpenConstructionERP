"""DWG Takeoff API routes.

Endpoints:
    Drawings:
        POST   /drawings/upload               — Upload DWG/DXF file
        GET    /drawings/?project_id=X        — List drawings
        GET    /drawings/{id}                 — Get single drawing with latest version
        DELETE /drawings/{id}                 — Delete drawing
        GET    /drawings/{id}/entities        — Parsed entities (filtered by layers)
        GET    /drawings/{id}/thumbnail       — SVG thumbnail
        PATCH  /drawings/{id}/layers          — Toggle layer visibility

    Annotations:
        POST   /annotations/                  — Create annotation
        GET    /annotations/?drawing_id=X     — List annotations
        PATCH  /annotations/{id}              — Update annotation
        DELETE /annotations/{id}              — Delete annotation
        POST   /annotations/{id}/link-boq     — Link to BOQ position

    Pins:
        GET    /pins/?drawing_id=X            — Task/punchlist pins
"""

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.core.rate_limiter import approval_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.dwg_takeoff.schemas import (
    BoqLinkRequest,
    DwgAnnotationCreate,
    DwgAnnotationResponse,
    DwgAnnotationUpdate,
    DwgDrawingResponse,
    DwgDrawingVersionResponse,
    DwgLayerVisibilityUpdate,
)
from app.modules.dwg_takeoff.service import DwgTakeoffService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> DwgTakeoffService:
    return DwgTakeoffService(session)


def _drawing_to_response(
    item: object,
    latest_version: object | None = None,
) -> DwgDrawingResponse:
    """Build a DwgDrawingResponse from a DwgDrawing ORM object."""
    version_resp = None
    if latest_version is not None:
        version_resp = _version_to_response(latest_version)
    return DwgDrawingResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        name=item.name,  # type: ignore[attr-defined]
        filename=item.filename,  # type: ignore[attr-defined]
        file_format=item.file_format,  # type: ignore[attr-defined]
        size_bytes=item.size_bytes,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        discipline=item.discipline,  # type: ignore[attr-defined]
        sheet_number=item.sheet_number,  # type: ignore[attr-defined]
        thumbnail_key=item.thumbnail_key,  # type: ignore[attr-defined]
        error_message=item.error_message,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
        latest_version=version_resp,
    )


def _version_to_response(item: object) -> DwgDrawingVersionResponse:
    """Build a DwgDrawingVersionResponse from a DwgDrawingVersion ORM object."""
    return DwgDrawingVersionResponse(
        id=item.id,  # type: ignore[attr-defined]
        drawing_id=item.drawing_id,  # type: ignore[attr-defined]
        version_number=item.version_number,  # type: ignore[attr-defined]
        layers=item.layers,  # type: ignore[attr-defined]
        entities_key=item.entities_key,  # type: ignore[attr-defined]
        entity_count=item.entity_count,  # type: ignore[attr-defined]
        extents=item.extents,  # type: ignore[attr-defined]
        units=item.units,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _annotation_to_response(item: object) -> DwgAnnotationResponse:
    """Build a DwgAnnotationResponse from a DwgAnnotation ORM object."""
    return DwgAnnotationResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        drawing_id=item.drawing_id,  # type: ignore[attr-defined]
        drawing_version_id=item.drawing_version_id,  # type: ignore[attr-defined]
        annotation_type=item.annotation_type,  # type: ignore[attr-defined]
        geometry=item.geometry,  # type: ignore[attr-defined]
        text=item.text,  # type: ignore[attr-defined]
        color=item.color,  # type: ignore[attr-defined]
        line_width=item.line_width,  # type: ignore[attr-defined]
        measurement_value=item.measurement_value,  # type: ignore[attr-defined]
        measurement_unit=item.measurement_unit,  # type: ignore[attr-defined]
        linked_boq_position_id=item.linked_boq_position_id,  # type: ignore[attr-defined]
        linked_task_id=item.linked_task_id,  # type: ignore[attr-defined]
        linked_punch_item_id=item.linked_punch_item_id,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Drawing Upload ──────────────────────────────────────────────────────────


_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/drawings/upload/", response_model=DwgDrawingResponse, status_code=201)
async def upload_drawing(
    file: UploadFile,
    project_id: uuid.UUID = Query(...),
    name: str | None = Query(default=None, max_length=500),
    discipline: str | None = Query(default=None),
    sheet_number: str | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.create")),
    service: DwgTakeoffService = Depends(_get_service),
) -> DwgDrawingResponse:
    """Upload a DWG/DXF file and trigger processing."""
    # Rate-limit uploads
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )

    # Validate file extension
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("dwg", "dxf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only .dwg and .dxf files are accepted.",
        )

    # Validate file size (Content-Length header, if available)
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    try:
        drawing = await service.upload_drawing(
            project_id,
            file,
            user_id,
            name=name,
            discipline=discipline,
            sheet_number=sheet_number,
        )
        version = await service.get_latest_version(drawing.id)
        return _drawing_to_response(drawing, version)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to upload drawing")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to upload drawing — please try again",
        )


# ── Drawing CRUD ────────────────────────────────────────────────────────────


@router.get("/drawings/", response_model=list[DwgDrawingResponse])
async def list_drawings(
    project_id: uuid.UUID = Query(...),
    status_filter: Literal["uploaded", "processing", "ready", "error"] | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DwgTakeoffService = Depends(_get_service),
) -> list[DwgDrawingResponse]:
    """List drawings for a project."""
    items, _ = await service.list_drawings(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
    )
    return [_drawing_to_response(i) for i in items]


@router.get("/drawings/{drawing_id}", response_model=DwgDrawingResponse)
async def get_drawing(
    drawing_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.read")),
    service: DwgTakeoffService = Depends(_get_service),
) -> DwgDrawingResponse:
    """Get a single drawing with its latest version."""
    drawing = await service.get_drawing(drawing_id)
    version = await service.get_latest_version(drawing_id)
    return _drawing_to_response(drawing, version)


@router.delete("/drawings/{drawing_id}", status_code=204)
async def delete_drawing(
    drawing_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.delete")),
    service: DwgTakeoffService = Depends(_get_service),
) -> None:
    """Delete a drawing."""
    await service.delete_drawing(drawing_id)


# ── Entities & Thumbnail ────────────────────────────────────────────────────


@router.get("/drawings/{drawing_id}/entities/")
async def get_entities(
    drawing_id: uuid.UUID,
    layers: str | None = Query(default=None, description="Comma-separated visible layer names"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.read")),
    service: DwgTakeoffService = Depends(_get_service),
) -> list[dict]:
    """Get parsed entities for a drawing, optionally filtered by visible layers."""
    visible_layers = None
    if layers:
        visible_layers = [l.strip() for l in layers.split(",") if l.strip()]
    return await service.get_entities(drawing_id, visible_layers=visible_layers)


@router.get("/drawings/{drawing_id}/thumbnail/")
async def get_thumbnail(
    drawing_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.read")),
    service: DwgTakeoffService = Depends(_get_service),
) -> Response:
    """Get SVG thumbnail for a drawing."""
    svg_content = await service.get_thumbnail_svg(drawing_id)
    if svg_content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not available",
        )
    return Response(content=svg_content, media_type="image/svg+xml")


# ── Layer Visibility ────────────────────────────────────────────────────────


@router.patch("/drawings/{drawing_id}/layers", response_model=DwgDrawingVersionResponse)
async def update_layer_visibility(
    drawing_id: uuid.UUID,
    data: DwgLayerVisibilityUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.read")),
    service: DwgTakeoffService = Depends(_get_service),
) -> DwgDrawingVersionResponse:
    """Toggle layer visibility in the latest drawing version."""
    version = await service.update_layer_visibility(drawing_id, data.layers)
    return _version_to_response(version)


# ── Annotation CRUD ─────────────────────────────────────────────────────────


@router.post("/annotations/", response_model=DwgAnnotationResponse, status_code=201)
async def create_annotation(
    data: DwgAnnotationCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("dwg_takeoff.create")),
    service: DwgTakeoffService = Depends(_get_service),
) -> DwgAnnotationResponse:
    """Create a new annotation on a drawing."""
    try:
        item = await service.create_annotation(data, user_id)
        return _annotation_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create annotation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create annotation — please try again",
        )


@router.get("/annotations/", response_model=list[DwgAnnotationResponse])
async def list_annotations(
    drawing_id: uuid.UUID = Query(...),
    annotation_type: str | None = Query(default=None, alias="type"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DwgTakeoffService = Depends(_get_service),
) -> list[DwgAnnotationResponse]:
    """List annotations for a drawing."""
    items, _ = await service.list_annotations(
        drawing_id,
        offset=offset,
        limit=limit,
        annotation_type=annotation_type,
    )
    return [_annotation_to_response(i) for i in items]


@router.patch("/annotations/{annotation_id}", response_model=DwgAnnotationResponse)
async def update_annotation(
    annotation_id: uuid.UUID,
    data: DwgAnnotationUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.update")),
    service: DwgTakeoffService = Depends(_get_service),
) -> DwgAnnotationResponse:
    """Update an annotation."""
    item = await service.update_annotation(annotation_id, data)
    return _annotation_to_response(item)


@router.delete("/annotations/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.delete")),
    service: DwgTakeoffService = Depends(_get_service),
) -> None:
    """Delete an annotation."""
    await service.delete_annotation(annotation_id)


# ── BOQ Link ────────────────────────────────────────────────────────────────


@router.post("/annotations/{annotation_id}/link-boq/", response_model=DwgAnnotationResponse)
async def link_to_boq(
    annotation_id: uuid.UUID,
    data: BoqLinkRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("dwg_takeoff.update")),
    service: DwgTakeoffService = Depends(_get_service),
) -> DwgAnnotationResponse:
    """Link an annotation to a BOQ position."""
    item = await service.link_annotation_to_boq(annotation_id, data.position_id)
    return _annotation_to_response(item)


# ── Pins ────────────────────────────────────────────────────────────────────


@router.get("/pins/", response_model=list[DwgAnnotationResponse])
async def get_pins(
    drawing_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DwgTakeoffService = Depends(_get_service),
) -> list[DwgAnnotationResponse]:
    """Get task/punchlist pins for a drawing."""
    items = await service.get_pins(drawing_id)
    return [_annotation_to_response(i) for i in items]
