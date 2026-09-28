# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Temporary-works API routes (mounted at ``/api/v1/temporary-works``).

Safety-critical temporary-works governance: the per-project register of items
(falsework, propping, excavation support, facade retention, crane bases, ...),
the permits a Temporary Works Coordinator issues against them (permit to load /
strike / dismantle), and the derived clearance rollup and load-status view.

Every endpoint is scoped to a project in its path and gated twice, exactly like
the sibling modules: a ``RequirePermission`` dependency enforces the read/write
permission, and ``verify_project_access`` (which raises 404 on both "missing" and
"denied") is awaited as the first line of every handler so a stranger can never
read or mutate another project's temporary-works data. Any referenced ``item_id``
is additionally re-checked in the service layer against the same project, so a
permit can never be attached across projects.
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
from app.modules.temporary_works.register import (
    ALL_DESIGN_CHECK_CATEGORIES,
    ALL_ITEM_STATUSES,
    ALL_PERMIT_STATUSES,
    ALL_TW_TYPES,
)
from app.modules.temporary_works.schemas import (
    TemporaryWorksItemCreate,
    TemporaryWorksItemResponse,
    TemporaryWorksItemUpdate,
    TemporaryWorksLoadStatusResponse,
    TemporaryWorksPermitCreate,
    TemporaryWorksPermitResponse,
    TemporaryWorksPermitUpdate,
    TemporaryWorksRegisterResponse,
)
from app.modules.temporary_works.service import TemporaryWorksService

router = APIRouter(tags=["temporary-works"])

_READ = Depends(RequirePermission("temporary_works.read"))
_WRITE = Depends(RequirePermission("temporary_works.write"))


def _get_service(session: SessionDep) -> TemporaryWorksService:
    return TemporaryWorksService(session)


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


# -- Items ------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/items",
    response_model=TemporaryWorksItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_item(
    project_id: uuid.UUID,
    payload: TemporaryWorksItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TemporaryWorksItemResponse:
    """Create a temporary-works item on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_item(project_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/items",
    response_model=list[TemporaryWorksItemResponse],
    dependencies=[_READ],
)
async def list_items(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    tw_type: str | None = Query(default=None),
    item_status: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
) -> list[TemporaryWorksItemResponse]:
    """List a project's items, optionally filtered by type / status / category."""
    await verify_project_access(project_id, user_id, session)
    tw_type = _validate_filter(tw_type, ALL_TW_TYPES, "tw_type")
    item_status = _validate_filter(item_status, ALL_ITEM_STATUSES, "status")
    category = _validate_filter(category, ALL_DESIGN_CHECK_CATEGORIES, "category")
    service = _get_service(session)
    return await service.list_items(  # type: ignore[return-value]
        project_id,
        tw_type=tw_type,
        item_status=item_status,
        category=category,
    )


@router.get(
    "/projects/{project_id}/items/{item_id}",
    response_model=TemporaryWorksItemResponse,
    dependencies=[_READ],
)
async def get_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TemporaryWorksItemResponse:
    """Get one temporary-works item, scoped to the project (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.require_item(project_id, item_id)  # type: ignore[return-value]


@router.patch(
    "/projects/{project_id}/items/{item_id}",
    response_model=TemporaryWorksItemResponse,
    dependencies=[_WRITE],
)
async def update_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: TemporaryWorksItemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TemporaryWorksItemResponse:
    """Patch a temporary-works item (only provided fields change)."""
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
    """Delete a temporary-works item and its permits (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.delete_item(project_id, item_id)


# -- Permits ----------------------------------------------------------------


@router.post(
    "/projects/{project_id}/items/{item_id}/permits",
    response_model=TemporaryWorksPermitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_permit(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: TemporaryWorksPermitCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TemporaryWorksPermitResponse:
    """Issue a permit against an item (service re-verifies the item in-project)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_permit(project_id, item_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/permits",
    response_model=list[TemporaryWorksPermitResponse],
    dependencies=[_READ],
)
async def list_permits(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    item_id: uuid.UUID | None = Query(default=None),
    permit_status: str | None = Query(default=None, alias="status"),
) -> list[TemporaryWorksPermitResponse]:
    """List a project's permits, optionally filtered by item / status."""
    await verify_project_access(project_id, user_id, session)
    permit_status = _validate_filter(permit_status, ALL_PERMIT_STATUSES, "status")
    service = _get_service(session)
    return await service.list_permits(  # type: ignore[return-value]
        project_id,
        item_id=item_id,
        permit_status=permit_status,
    )


@router.patch(
    "/projects/{project_id}/permits/{permit_id}",
    response_model=TemporaryWorksPermitResponse,
    dependencies=[_WRITE],
)
async def update_permit(
    project_id: uuid.UUID,
    permit_id: uuid.UUID,
    payload: TemporaryWorksPermitUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TemporaryWorksPermitResponse:
    """Patch (or close) a permit (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_permit(project_id, permit_id, payload)  # type: ignore[return-value]


# -- Derived register views -------------------------------------------------


@router.get(
    "/projects/{project_id}/register",
    response_model=TemporaryWorksRegisterResponse,
    dependencies=[_READ],
)
async def get_register(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> TemporaryWorksRegisterResponse:
    """Full temporary-works register rollup: counts, clearance, overdue, breaches."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.build_register(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/load-status",
    response_model=TemporaryWorksLoadStatusResponse,
    dependencies=[_READ],
)
async def get_load_status(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> TemporaryWorksLoadStatusResponse:
    """Per-item load / strike gate summary plus the safety compliance-breach list."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.get_load_status(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]
