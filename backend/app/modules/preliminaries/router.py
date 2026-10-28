# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Preliminaries API routes.

Endpoints (mounted at ``/api/v1/preliminaries``):

    GET    /starter-checklist/                   - Suggested item labels
    GET    /items/?project_id=X                  - List a project's items
    POST   /items/                               - Create an item
    GET    /projects/{project_id}/summary/       - Per-category + grand total
    GET    /items/{item_id}/                      - Get one item
    PATCH  /items/{item_id}/                      - Update an item
    DELETE /items/{item_id}/                      - Delete an item

Every project-scoped endpoint enforces project access (IDOR-safe: 404 on both
missing and forbidden) and the preliminaries RBAC permissions.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.preliminaries import prelim_math
from app.modules.preliminaries.models import PrelimItem
from app.modules.preliminaries.schemas import (
    PrelimCategorySummary,
    PreliminariesSummary,
    PrelimItemCreate,
    PrelimItemResponse,
    PrelimItemUpdate,
    StarterChecklistItem,
    StarterChecklistResponse,
)
from app.modules.preliminaries.seed import starter_checklist
from app.modules.preliminaries.service import PreliminariesService

router = APIRouter(tags=["preliminaries"])


def _get_service(session: SessionDep) -> PreliminariesService:
    return PreliminariesService(session)


def _to_response(item: PrelimItem) -> PrelimItemResponse:
    """Build an item response, deriving the priced line total."""
    line_total = prelim_math.line_total(PreliminariesService.to_mapping(item))
    return PrelimItemResponse(
        id=item.id,
        project_id=item.project_id,
        label=item.label or "",
        category=item.category or prelim_math.DEFAULT_CATEGORY,
        item_type=item.item_type or prelim_math.TIME_RELATED,
        rate_per_period=item.rate_per_period if item.rate_per_period is not None else prelim_math.to_decimal(0),
        periods=item.periods if item.periods is not None else prelim_math.to_decimal(0),
        fixed_amount=item.fixed_amount if item.fixed_amount is not None else prelim_math.to_decimal(0),
        sort_order=item.sort_order or 0,
        line_total=line_total,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _authorized_item(
    service: PreliminariesService,
    session: SessionDep,
    item_id: uuid.UUID,
    user_id: str,
) -> PrelimItem:
    """Load an item and assert the caller may access its project (404 else)."""
    item = await service.get_item(item_id)
    await verify_project_access(item.project_id, user_id, session)
    return item


# ── Static / collection routes (before /items/{id}/) ─────────────────────────


@router.get("/starter-checklist/", response_model=StarterChecklistResponse)
async def get_starter_checklist(
    _perm: None = Depends(RequirePermission("preliminaries.read")),
) -> StarterChecklistResponse:
    """Return the starter checklist of common preliminaries item labels."""
    return StarterChecklistResponse(
        items=[StarterChecklistItem(**suggestion) for suggestion in starter_checklist()],
    )


@router.get("/items/", response_model=list[PrelimItemResponse])
async def list_items(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("preliminaries.read")),
    service: PreliminariesService = Depends(_get_service),
) -> list[PrelimItemResponse]:
    """List a project's preliminaries items."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_items(project_id)
    return [_to_response(item) for item in items]


@router.post("/items/", response_model=PrelimItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: PrelimItemCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("preliminaries.create")),
    service: PreliminariesService = Depends(_get_service),
) -> PrelimItemResponse:
    """Create a preliminaries item on a project."""
    await verify_project_access(payload.project_id, user_id, session)
    item = await service.create_item(payload)
    return _to_response(item)


@router.get("/projects/{project_id}/summary/", response_model=PreliminariesSummary)
async def get_summary(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("preliminaries.read")),
    service: PreliminariesService = Depends(_get_service),
) -> PreliminariesSummary:
    """Return the per-category and grand-total preliminaries roll-up."""
    await verify_project_access(project_id, user_id, session)
    rollup = await service.get_summary(project_id)
    return PreliminariesSummary(
        project_id=project_id,
        categories=[
            PrelimCategorySummary(
                category=category.category,
                time_related_total=category.time_related_total,
                fixed_total=category.fixed_total,
                total=category.total,
                item_count=category.item_count,
            )
            for category in rollup.categories
        ],
        time_related_total=rollup.time_related_total,
        fixed_total=rollup.fixed_total,
        grand_total=rollup.grand_total,
        item_count=rollup.item_count,
    )


# ── Item routes ──────────────────────────────────────────────────────────────


@router.get("/items/{item_id}/", response_model=PrelimItemResponse)
async def get_item(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("preliminaries.read")),
    service: PreliminariesService = Depends(_get_service),
) -> PrelimItemResponse:
    """Get a single preliminaries item."""
    item = await _authorized_item(service, session, item_id, user_id)
    return _to_response(item)


@router.patch("/items/{item_id}/", response_model=PrelimItemResponse)
async def update_item(
    item_id: uuid.UUID,
    payload: PrelimItemUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("preliminaries.update")),
    service: PreliminariesService = Depends(_get_service),
) -> PrelimItemResponse:
    """Update a preliminaries item."""
    await _authorized_item(service, session, item_id, user_id)
    item = await service.update_item(item_id, payload)
    return _to_response(item)


@router.delete("/items/{item_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("preliminaries.delete")),
    service: PreliminariesService = Depends(_get_service),
) -> None:
    """Delete a preliminaries item."""
    await _authorized_item(service, session, item_id, user_id)
    await service.delete_item(item_id)
