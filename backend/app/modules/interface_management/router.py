# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-register API routes (mounted at ``/api/v1/interface-management``).

Multi-package / multi-contractor coordination: the per-project register of
interfaces (the handshakes where one party's work meets another's), the actions
needed to close each one, and the derived register rollup and per-work-package
health view.

Every endpoint is scoped to a project in its path and gated twice, exactly like
the sibling modules: a ``RequirePermission`` dependency enforces the read/write
permission, and ``verify_project_access`` (which raises 404 on both "missing" and
"denied") is awaited as the first line of every handler so a stranger can never
read or mutate another project's interface data. Any referenced ``interface_id``
is additionally re-checked in the service layer against the same project, so an
action can never be attached across projects.
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
from app.modules.interface_management.register import (
    ALL_ACTION_STATUSES,
    ALL_INTERFACE_STATUSES,
    ALL_INTERFACE_TYPES,
    ALL_PRIORITIES,
)
from app.modules.interface_management.schemas import (
    InterfaceActionCreate,
    InterfaceActionResponse,
    InterfaceActionUpdate,
    InterfaceCreate,
    InterfaceRegisterResponse,
    InterfaceResponse,
    InterfaceUpdate,
    WorkPackageHealthReportResponse,
)
from app.modules.interface_management.service import InterfaceManagementService

router = APIRouter(tags=["interface-management"])

_READ = Depends(RequirePermission("interface_management.read"))
_WRITE = Depends(RequirePermission("interface_management.write"))


def _get_service(session: SessionDep) -> InterfaceManagementService:
    return InterfaceManagementService(session)


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


# -- Interfaces -------------------------------------------------------------


@router.post(
    "/projects/{project_id}/interfaces",
    response_model=InterfaceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_interface(
    project_id: uuid.UUID,
    payload: InterfaceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InterfaceResponse:
    """Create an interface on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_interface(project_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/interfaces",
    response_model=list[InterfaceResponse],
    dependencies=[_READ],
)
async def list_interfaces(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    interface_status: str | None = Query(default=None, alias="status"),
    owner_subcontractor_id: uuid.UUID | None = Query(default=None),
    work_package: str | None = Query(default=None),
    interface_type: str | None = Query(default=None),
    priority: str | None = Query(default=None),
) -> list[InterfaceResponse]:
    """List a project's interfaces, optionally filtered by status / owner / package / type / priority."""
    await verify_project_access(project_id, user_id, session)
    interface_status = _validate_filter(interface_status, ALL_INTERFACE_STATUSES, "status")
    interface_type = _validate_filter(interface_type, ALL_INTERFACE_TYPES, "interface_type")
    priority = _validate_filter(priority, ALL_PRIORITIES, "priority")
    service = _get_service(session)
    return await service.list_interfaces(  # type: ignore[return-value]
        project_id,
        interface_status=interface_status,
        owner_subcontractor_id=owner_subcontractor_id,
        work_package=work_package,
        interface_type=interface_type,
        priority=priority,
    )


@router.get(
    "/projects/{project_id}/interfaces/{interface_id}",
    response_model=InterfaceResponse,
    dependencies=[_READ],
)
async def get_interface(
    project_id: uuid.UUID,
    interface_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InterfaceResponse:
    """Get one interface, scoped to the project (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.require_interface(project_id, interface_id)  # type: ignore[return-value]


@router.patch(
    "/projects/{project_id}/interfaces/{interface_id}",
    response_model=InterfaceResponse,
    dependencies=[_WRITE],
)
async def update_interface(
    project_id: uuid.UUID,
    interface_id: uuid.UUID,
    payload: InterfaceUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InterfaceResponse:
    """Patch an interface (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_interface(project_id, interface_id, payload)  # type: ignore[return-value]


@router.delete(
    "/projects/{project_id}/interfaces/{interface_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_WRITE],
)
async def delete_interface(
    project_id: uuid.UUID,
    interface_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete an interface and its actions (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.delete_interface(project_id, interface_id)


# -- Actions ----------------------------------------------------------------


@router.post(
    "/projects/{project_id}/interfaces/{interface_id}/actions",
    response_model=InterfaceActionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_action(
    project_id: uuid.UUID,
    interface_id: uuid.UUID,
    payload: InterfaceActionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InterfaceActionResponse:
    """Add an action to an interface (service re-verifies the interface in-project)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_action(project_id, interface_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/actions",
    response_model=list[InterfaceActionResponse],
    dependencies=[_READ],
)
async def list_actions(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    interface_id: uuid.UUID | None = Query(default=None),
    action_status: str | None = Query(default=None, alias="status"),
) -> list[InterfaceActionResponse]:
    """List a project's actions, optionally filtered by interface / status."""
    await verify_project_access(project_id, user_id, session)
    action_status = _validate_filter(action_status, ALL_ACTION_STATUSES, "status")
    service = _get_service(session)
    return await service.list_actions(  # type: ignore[return-value]
        project_id,
        interface_id=interface_id,
        action_status=action_status,
    )


@router.patch(
    "/projects/{project_id}/actions/{action_id}",
    response_model=InterfaceActionResponse,
    dependencies=[_WRITE],
)
async def update_action(
    project_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: InterfaceActionUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> InterfaceActionResponse:
    """Patch (or close) an action (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_action(project_id, action_id, payload)  # type: ignore[return-value]


# -- Derived register views -------------------------------------------------


@router.get(
    "/projects/{project_id}/register",
    response_model=InterfaceRegisterResponse,
    dependencies=[_READ],
)
async def get_register(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> InterfaceRegisterResponse:
    """Full interface register rollup: counts, agreement, overdue, disputes, health."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.build_register(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/work-package-health",
    response_model=WorkPackageHealthReportResponse,
    dependencies=[_READ],
)
async def get_work_package_health(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> WorkPackageHealthReportResponse:
    """Per-work-package health plus the overdue and disputed interface lists."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.get_work_package_health(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]
