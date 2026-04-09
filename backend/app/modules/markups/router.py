"""Markups & Annotations API routes.

Endpoints:
    Markups:
        POST   /                            — Create markup
        GET    /?project_id=X&...           — List with filters
        GET    /{id}                        — Get single markup
        PATCH  /{id}                        — Update markup
        DELETE /{id}                        — Delete markup
        POST   /bulk                        — Bulk create markups
        GET    /export?project_id=X&format= — Export to CSV
        GET    /summary?project_id=X        — Aggregated stats

    Scales:
        POST   /scales/                     — Save scale config
        GET    /scales/?document_id=X       — List scales
        DELETE /scales/{id}                 — Delete scale

    Stamps:
        POST   /stamps/templates            — Create stamp template
        GET    /stamps/templates?project_id= — List templates
        PATCH  /stamps/templates/{id}       — Update template
        DELETE /stamps/templates/{id}       — Delete template

    BOQ Link:
        POST   /{id}/link-to-boq           — Link markup to BOQ position
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.markups.schemas import (
    BoqLinkRequest,
    MarkupBulkCreate,
    MarkupCreate,
    MarkupResponse,
    MarkupSummary,
    MarkupUpdate,
    ScaleConfigCreate,
    ScaleConfigResponse,
    StampTemplateCreate,
    StampTemplateResponse,
    StampTemplateUpdate,
)
from app.modules.markups.service import MarkupsService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> MarkupsService:
    return MarkupsService(session)


def _markup_to_response(item: object) -> MarkupResponse:
    """Build a MarkupResponse from a Markup ORM object."""
    return MarkupResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        document_id=item.document_id,  # type: ignore[attr-defined]
        page=item.page,  # type: ignore[attr-defined]
        type=item.type,  # type: ignore[attr-defined]
        geometry=item.geometry,  # type: ignore[attr-defined]
        text=item.text,  # type: ignore[attr-defined]
        color=item.color,  # type: ignore[attr-defined]
        line_width=item.line_width,  # type: ignore[attr-defined]
        opacity=item.opacity,  # type: ignore[attr-defined]
        author_id=item.author_id,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        label=item.label,  # type: ignore[attr-defined]
        measurement_value=item.measurement_value,  # type: ignore[attr-defined]
        measurement_unit=item.measurement_unit,  # type: ignore[attr-defined]
        stamp_template_id=item.stamp_template_id,  # type: ignore[attr-defined]
        linked_boq_position_id=item.linked_boq_position_id,  # type: ignore[attr-defined]
        layer=getattr(item, "layer", "default"),  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _scale_to_response(item: object) -> ScaleConfigResponse:
    """Build a ScaleConfigResponse from a ScaleConfig ORM object."""
    return ScaleConfigResponse(
        id=item.id,  # type: ignore[attr-defined]
        document_id=item.document_id,  # type: ignore[attr-defined]
        page=item.page,  # type: ignore[attr-defined]
        pixels_per_unit=item.pixels_per_unit,  # type: ignore[attr-defined]
        unit_label=item.unit_label,  # type: ignore[attr-defined]
        calibration_points=item.calibration_points,  # type: ignore[attr-defined]
        real_distance=item.real_distance,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _stamp_to_response(item: object) -> StampTemplateResponse:
    """Build a StampTemplateResponse from a StampTemplate ORM object."""
    return StampTemplateResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        owner_id=item.owner_id,  # type: ignore[attr-defined]
        name=item.name,  # type: ignore[attr-defined]
        category=item.category,  # type: ignore[attr-defined]
        text=item.text,  # type: ignore[attr-defined]
        color=item.color,  # type: ignore[attr-defined]
        background_color=item.background_color,  # type: ignore[attr-defined]
        icon=item.icon,  # type: ignore[attr-defined]
        include_date=item.include_date,  # type: ignore[attr-defined]
        include_name=item.include_name,  # type: ignore[attr-defined]
        is_active=item.is_active,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary/", response_model=MarkupSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> MarkupSummary:
    """Aggregated markup stats for a project."""
    data = await service.get_summary(project_id)
    return MarkupSummary(**data)


# ── Export ───────────────────────────────────────────────────────────────────


@router.get("/export/")
async def export_markups(
    project_id: uuid.UUID = Query(...),
    format: str = Query(default="csv", pattern=r"^csv$"),
    type: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> PlainTextResponse:
    """Export markups to CSV."""
    csv_content = await service.export_to_csv(
        project_id,
        type_filter=type,
        status_filter=status_filter,
    )
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=markups.csv"},
    )


# ── Bulk Create ──────────────────────────────────────────────────────────────


@router.post("/bulk/", response_model=list[MarkupResponse], status_code=201)
async def bulk_create_markups(
    data: MarkupBulkCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("markups.create")),
    service: MarkupsService = Depends(_get_service),
) -> list[MarkupResponse]:
    """Bulk create multiple markups at once."""
    try:
        items = await service.bulk_create_markups(data.markups, user_id)
        return [_markup_to_response(i) for i in items]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to bulk create markups")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to bulk create markups — operation aborted",
        )


# ── Markup CRUD ──────────────────────────────────────────────────────────────


@router.post("/", response_model=MarkupResponse, status_code=201)
async def create_markup(
    data: MarkupCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("markups.create")),
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Create a new markup annotation."""
    try:
        item = await service.create_markup(data, user_id)
        return _markup_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create markup")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create markup — please try again",
        )


@router.get("/", response_model=list[MarkupResponse])
async def list_markups(
    project_id: uuid.UUID = Query(...),
    document_id: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    type: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    layer: str | None = Query(default=None),
    query: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> list[MarkupResponse]:
    """List markups for a project with filters."""
    if query:
        items = await service.search_markups(project_id, query)
        return [_markup_to_response(i) for i in items]

    items, _ = await service.list_markups(
        project_id,
        offset=offset,
        limit=limit,
        type_filter=type,
        status_filter=status_filter,
        document_id=document_id,
        page=page,
        layer=layer,
    )
    return [_markup_to_response(i) for i in items]


@router.get("/{markup_id}", response_model=MarkupResponse)
async def get_markup(
    markup_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Get a single markup."""
    item = await service.get_markup(markup_id)
    return _markup_to_response(item)


@router.patch("/{markup_id}", response_model=MarkupResponse)
async def update_markup(
    markup_id: uuid.UUID,
    data: MarkupUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.update")),
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Update a markup."""
    item = await service.update_markup(markup_id, data)
    return _markup_to_response(item)


@router.delete("/{markup_id}", status_code=204)
async def delete_markup(
    markup_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.delete")),
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a markup."""
    await service.delete_markup(markup_id)


# ── BOQ Link ─────────────────────────────────────────────────────────────────


@router.post("/{markup_id}/link-to-boq/", response_model=MarkupResponse)
async def link_to_boq(
    markup_id: uuid.UUID,
    data: BoqLinkRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.update")),
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Link a measurement markup to a BOQ position."""
    item = await service.link_to_boq(markup_id, data.position_id)
    return _markup_to_response(item)


# ── Scale Config ─────────────────────────────────────────────────────────────


@router.post("/scales/", response_model=ScaleConfigResponse, status_code=201)
async def create_scale(
    data: ScaleConfigCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("markups.create")),
    service: MarkupsService = Depends(_get_service),
) -> ScaleConfigResponse:
    """Save a scale calibration config."""
    try:
        item = await service.create_scale(data, user_id)
        return _scale_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create scale config")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create scale config — calibration failed",
        )


@router.get("/scales/", response_model=list[ScaleConfigResponse])
async def list_scales(
    document_id: str = Query(...),
    page: int | None = Query(default=None, ge=1),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> list[ScaleConfigResponse]:
    """List scale configs for a document."""
    items = await service.list_scales(document_id, page=page)
    return [_scale_to_response(i) for i in items]


@router.delete("/scales/{config_id}", status_code=204)
async def delete_scale(
    config_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.delete")),
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a scale config."""
    await service.delete_scale(config_id)


# ── Stamp Templates ──────────────────────────────────────────────────────────


@router.post("/stamps/templates/", response_model=StampTemplateResponse, status_code=201)
async def create_stamp_template(
    data: StampTemplateCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("markups.create")),
    service: MarkupsService = Depends(_get_service),
) -> StampTemplateResponse:
    """Create a new stamp template."""
    try:
        item = await service.create_stamp(data, user_id)
        return _stamp_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create stamp template")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create stamp template",
        )


@router.get("/stamps/templates/", response_model=list[StampTemplateResponse])
async def list_stamp_templates(
    project_id: uuid.UUID | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> list[StampTemplateResponse]:
    """List stamp templates (predefined + project-specific)."""
    items = await service.list_stamps(project_id)
    return [_stamp_to_response(i) for i in items]


@router.patch("/stamps/templates/{template_id}", response_model=StampTemplateResponse)
async def update_stamp_template(
    template_id: uuid.UUID,
    data: StampTemplateUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.update")),
    service: MarkupsService = Depends(_get_service),
) -> StampTemplateResponse:
    """Update a stamp template."""
    item = await service.update_stamp(template_id, data)
    return _stamp_to_response(item)


@router.delete("/stamps/templates/{template_id}", status_code=204)
async def delete_stamp_template(
    template_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.delete")),
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a stamp template."""
    await service.delete_stamp(template_id)
