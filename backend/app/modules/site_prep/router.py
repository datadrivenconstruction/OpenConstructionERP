# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-prep API routes (mounted at ``/api/v1/site-prep``).

Pre-construction mobilisation and site-setup readiness: a per-project plan, the
readiness items grouped by mobilisation category, and the derived readiness
rollup and commencement-gate status.

Every endpoint is scoped to a project in its path and gated twice, exactly like
the sibling modules: a ``RequirePermission`` dependency enforces the read/write
permission, and ``verify_project_access`` (which raises 404 on both "missing" and
"denied") is awaited as the first line of every handler so a stranger can never
read or mutate another project's mobilisation data. Any referenced ``plan_id`` is
additionally re-checked in the service layer against the same project.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.site_prep.readiness import ALL_CATEGORIES, ALL_STATUSES
from app.modules.site_prep.schemas import (
    GateStatusResponse,
    ReadinessReportResponse,
    SitePrepItemCreate,
    SitePrepItemResponse,
    SitePrepItemUpdate,
    SitePrepPlanCreate,
    SitePrepPlanResponse,
    SitePrepPlanUpdate,
)
from app.modules.site_prep.service import SitePrepService

router = APIRouter(tags=["site-prep"])

_READ = Depends(RequirePermission("site_prep.read"))
_WRITE = Depends(RequirePermission("site_prep.write"))


def _get_service(session: SessionDep) -> SitePrepService:
    return SitePrepService(session)


def _validate_filter(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    """Reject an out-of-vocabulary filter value with 422, pass ``None`` through."""
    if value is None:
        return None
    if value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {field}: {value!r}",
        )
    return value


def _parse_as_of(value: str | None) -> date | None:
    """Parse an optional ``as_of`` ISO date query param (422 on garbage)."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid as_of date (expected YYYY-MM-DD): {value!r}",
        ) from exc


# -- Plan -------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/plan",
    response_model=SitePrepPlanResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_plan(
    project_id: uuid.UUID,
    payload: SitePrepPlanCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SitePrepPlanResponse:
    """Create the project's single pre-construction mobilisation plan."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_plan(project_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/plan",
    response_model=SitePrepPlanResponse,
    dependencies=[_READ],
)
async def get_plan(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SitePrepPlanResponse:
    """Get the project's mobilisation plan (404 if not created yet)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.require_plan(project_id)  # type: ignore[return-value]


@router.patch(
    "/projects/{project_id}/plan",
    response_model=SitePrepPlanResponse,
    dependencies=[_WRITE],
)
async def update_plan(
    project_id: uuid.UUID,
    payload: SitePrepPlanUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SitePrepPlanResponse:
    """Patch the project's mobilisation plan (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_plan(project_id, payload)  # type: ignore[return-value]


# -- Items ------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/items",
    response_model=SitePrepItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_item(
    project_id: uuid.UUID,
    payload: SitePrepItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SitePrepItemResponse:
    """Create a readiness item on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_item(project_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/items",
    response_model=list[SitePrepItemResponse],
    dependencies=[_READ],
)
async def list_items(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    category: str | None = Query(default=None),
    item_status: str | None = Query(default=None, alias="status"),
) -> list[SitePrepItemResponse]:
    """List a project's readiness items, optionally filtered by category / status."""
    await verify_project_access(project_id, user_id, session)
    category = _validate_filter(category, ALL_CATEGORIES, "category")
    item_status = _validate_filter(item_status, ALL_STATUSES, "status")
    service = _get_service(session)
    return await service.list_items(  # type: ignore[return-value]
        project_id,
        category=category,
        item_status=item_status,
    )


@router.get(
    "/projects/{project_id}/items/{item_id}",
    response_model=SitePrepItemResponse,
    dependencies=[_READ],
)
async def get_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SitePrepItemResponse:
    """Get one readiness item, scoped to the project (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.require_item(project_id, item_id)  # type: ignore[return-value]


@router.patch(
    "/projects/{project_id}/items/{item_id}",
    response_model=SitePrepItemResponse,
    dependencies=[_WRITE],
)
async def update_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: SitePrepItemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SitePrepItemResponse:
    """Patch a readiness item (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_item(project_id, item_id, payload)  # type: ignore[return-value]


@router.delete(
    "/projects/{project_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_WRITE],
)
async def delete_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete a readiness item, scoped to the project (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.delete_item(project_id, item_id)


# -- Derived readiness ------------------------------------------------------


@router.get(
    "/projects/{project_id}/readiness",
    response_model=ReadinessReportResponse,
    dependencies=[_READ],
)
async def get_readiness(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> ReadinessReportResponse:
    """Full mobilisation readiness rollup: overall, per category, gates, lists."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.get_readiness(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/gate-status",
    response_model=GateStatusResponse,
    dependencies=[_READ],
)
async def get_gate_status(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> GateStatusResponse:
    """Commencement-gate status: are all hard prerequisites to start satisfied."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.get_gate_status(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]
