"""‌⁠‍Markups & Annotations API routes.

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

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.markups.schemas import (
    BoqLinkRequest,
    MarkupBulkCreate,
    MarkupCommentCreate,
    MarkupCommentResponse,
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
    """‌⁠‍Build a MarkupResponse from a Markup ORM object."""
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
    """‌⁠‍Build a ScaleConfigResponse from a ScaleConfig ORM object."""
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
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> MarkupSummary:
    """Aggregated markup stats for a project."""
    await verify_project_access(project_id, str(user_id), session)
    data = await service.get_summary(project_id)
    return MarkupSummary(**data)


# ── Export ───────────────────────────────────────────────────────────────────


@router.get("/export/")
async def export_markups(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    format: str = Query(default="csv", pattern=r"^csv$"),
    type: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> PlainTextResponse:
    """Export markups to CSV."""
    await verify_project_access(project_id, str(user_id), session)
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
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    document_id: str | None = Query(default=None),
    document_page: int | None = Query(
        default=None,
        ge=1,
        description="Filter by drawing/PDF page number (the document's intrinsic page).",
    ),
    page: int | None = Query(
        default=None,
        ge=1,
        deprecated=True,
        description="Deprecated alias for document_page; prefer document_page.",
    ),
    type: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    layer: str | None = Query(default=None),
    query: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> list[MarkupResponse]:
    """List markups for a project with filters.

    Pagination follows the platform standard ``offset`` + ``limit`` (max 200).
    The pre-existing ``page`` query param meant *drawing page* and collided
    with the platform's "page-of-results" convention — it is preserved as a
    deprecated alias for one release. Use ``document_page`` going forward.

    Project membership is verified before returning anything — a non-member
    cannot enumerate markup ids by guessing project_ids (404 maps both
    "no such project" and "not your project" to the same response shape).
    """
    await verify_project_access(project_id, str(user_id), session)

    if query:
        items = await service.search_markups(project_id, query)
        return [_markup_to_response(i) for i in items]

    # Resolve the document-page filter (new name wins, old aliased for compat).
    page_filter = document_page if document_page is not None else page

    items, _ = await service.list_markups(
        project_id,
        offset=offset,
        limit=limit,
        type_filter=type,
        status_filter=status_filter,
        document_id=document_id,
        page=page_filter,
        layer=layer,
    )
    return [_markup_to_response(i) for i in items]


@router.get("/{markup_id}", response_model=MarkupResponse)
async def get_markup(
    markup_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Get a single markup."""
    item = await service.get_markup(markup_id)
    await verify_project_access(item.project_id, str(user_id), session)
    return _markup_to_response(item)


@router.patch("/{markup_id}", response_model=MarkupResponse)
async def update_markup(
    markup_id: uuid.UUID,
    data: MarkupUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.update")),
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Update a markup."""
    existing = await service.get_markup(markup_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    item = await service.update_markup(markup_id, data)
    return _markup_to_response(item)


@router.delete("/{markup_id}", status_code=204)
async def delete_markup(
    markup_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.delete")),
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a markup."""
    existing = await service.get_markup(markup_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_markup(markup_id)


# ── BOQ Link ─────────────────────────────────────────────────────────────────


@router.post("/{markup_id}/link-to-boq/", response_model=MarkupResponse)
async def link_to_boq(
    markup_id: uuid.UUID,
    data: BoqLinkRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.update")),
    service: MarkupsService = Depends(_get_service),
) -> MarkupResponse:
    """Link a measurement markup to a BOQ position."""
    existing = await service.get_markup(markup_id)
    await verify_project_access(existing.project_id, str(user_id), session)
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
    session: SessionDep,
    document_id: str = Query(...),
    project_id: uuid.UUID = Query(
        ...,
        description="Project that owns the document. Used for IDOR guard.",
    ),
    document_page: int | None = Query(
        default=None,
        ge=1,
        description="Filter by drawing/PDF page number.",
    ),
    page: int | None = Query(
        default=None,
        ge=1,
        deprecated=True,
        description="Deprecated alias for document_page.",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> list[ScaleConfigResponse]:
    """List scale configs for a document.

    ``project_id`` is required and verified via :func:`verify_project_access`
    so a caller cannot enumerate another tenant's calibration data by
    supplying an arbitrary ``document_id`` (A-MRK-01 IDOR fix).
    ``page`` is the deprecated alias for ``document_page``;
    pagination uses platform-standard ``offset``+``limit``.
    """
    await verify_project_access(project_id, str(user_id), session)
    page_filter = document_page if document_page is not None else page
    items = await service.list_scales(document_id, page=page_filter)
    # Apply offset/limit at the API edge so the route matches platform shape
    # without churning the repo signature for a small list.
    return [_scale_to_response(i) for i in items[offset : offset + limit]]


@router.delete("/scales/{config_id}", status_code=204)
async def delete_scale(
    config_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.delete")),
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a scale config.

    Scales are scoped per document, not per project. Until documents
    grow a project FK we restrict deletion to the user who calibrated
    the scale — anyone else gets 403.
    """
    existing = await service.scale_repo.get_by_id(config_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scale config not found")
    if not existing.created_by or existing.created_by != str(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your scale")
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


async def _authorize_stamp_mutation(
    template_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    service: MarkupsService,
) -> None:
    """Reject cross-tenant mutation of stamp templates.

    Project-scoped templates (project_id set) require project membership.
    User-private templates (project_id null) only the owner can mutate —
    seed stamps stored with owner_id='' are read-only via this gate.
    """
    existing = await service.stamp_repo.get_by_id(template_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stamp template not found")
    if existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
        return
    if not existing.owner_id or existing.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your stamp template")


@router.patch("/stamps/templates/{template_id}", response_model=StampTemplateResponse)
async def update_stamp_template(
    template_id: uuid.UUID,
    data: StampTemplateUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.update")),
    service: MarkupsService = Depends(_get_service),
) -> StampTemplateResponse:
    """Update a stamp template."""
    await _authorize_stamp_mutation(template_id, str(user_id), session, service)
    item = await service.update_stamp(template_id, data)
    return _stamp_to_response(item)


@router.delete("/stamps/templates/{template_id}", status_code=204)
async def delete_stamp_template(
    template_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("markups.delete")),
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a stamp template."""
    await _authorize_stamp_mutation(template_id, str(user_id), session, service)
    await service.delete_stamp(template_id)


# ── Markup Comments (threaded) ───────────────────────────────────────────────


def _comment_to_response(item: object) -> MarkupCommentResponse:
    """Build a MarkupCommentResponse from a MarkupComment ORM object."""
    return MarkupCommentResponse(
        id=item.id,  # type: ignore[attr-defined]
        markup_id=item.markup_id,  # type: ignore[attr-defined]
        user_id=item.user_id,  # type: ignore[attr-defined]
        body=item.body,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/{markup_id}/comments/", response_model=list[MarkupCommentResponse])
async def list_markup_comments(
    markup_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> list[MarkupCommentResponse]:
    """List threaded comments on a markup (project members only)."""
    parent = await service.get_markup(markup_id)
    await verify_project_access(parent.project_id, str(user_id), session)
    items = await service.list_comments(markup_id)
    return [_comment_to_response(c) for c in items]


@router.post("/{markup_id}/comments/", response_model=MarkupCommentResponse, status_code=201)
async def create_markup_comment(
    markup_id: uuid.UUID,
    data: MarkupCommentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: MarkupsService = Depends(_get_service),
) -> MarkupCommentResponse:
    """Append a threaded comment to a markup.

    Any project member (including viewers) can comment — comment authoring
    is intentionally not gated behind ``markups.create`` because reviewers
    must be able to leave feedback without write access to drawings.
    """
    parent = await service.get_markup(markup_id)
    await verify_project_access(parent.project_id, str(user_id), session)
    try:
        item = await service.create_comment(markup_id, data, str(user_id))
        return _comment_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create markup comment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create comment — please try again",
        )


@router.delete("/{markup_id}/comments/{comment_id}/", status_code=204)
async def delete_markup_comment(
    markup_id: uuid.UUID,
    comment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: MarkupsService = Depends(_get_service),
) -> None:
    """Delete a comment.

    Only the comment author OR the parent project's owner may delete. A
    non-author viewer hits 403 here even though they can post — symmetric
    with how comment threads work elsewhere in the app.
    """
    parent = await service.get_markup(markup_id)
    await verify_project_access(parent.project_id, str(user_id), session)
    comment = await service.get_comment(comment_id)
    if comment.markup_id != markup_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    # Permission gate: author OR project owner.
    if comment.user_id == str(user_id):
        await service.delete_comment(comment_id)
        return

    # Re-fetch project to compare owner_id.
    from app.modules.projects.repository import ProjectRepository

    proj_repo = ProjectRepository(session)
    project = await proj_repo.get_by_id(parent.project_id)
    if project is not None and str(project.owner_id) == str(user_id):
        await service.delete_comment(comment_id)
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the comment author or project owner can delete this comment",
    )
