"""Formwork API routes.

Mounted at ``/api/v1/formwork/`` by the module loader.

Endpoint groups:
    /systems/                              - catalogue CRUD + seed
    /assignments/                          - per-project assignment CRUD
    /assignments/{id}/schedule-lines/      - pour-cycle sub-resource
    /schedule-lines/{id}                   - schedule-line update + delete

Tenant scoping follows the Wave-5 IDOR posture: requests for an object
the caller cannot see return **404, never 403**, so we never leak the
existence of a row.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.permissions import Role, permission_registry
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.formwork.models import (
    FormworkAssignment,
    FormworkScheduleLine,
    FormworkSystem,
)
from app.modules.formwork.schemas import (
    FormworkAssignmentCreate,
    FormworkAssignmentResponse,
    FormworkAssignmentUpdate,
    FormworkScheduleLineCreate,
    FormworkScheduleLineResponse,
    FormworkScheduleLineUpdate,
    FormworkSystemCreate,
    FormworkSystemResponse,
    FormworkSystemSeedResult,
    FormworkSystemUpdate,
)
from app.modules.formwork.service import FormworkService, ReuseCountExceedsMaxError

router = APIRouter(tags=["formwork"])


# Register the catalogue-management permission at import time. The module
# loader imports this router during ``load_all`` (after
# ``register_core_permissions``), and the registry is never cleared
# afterwards, so this is the formwork equivalent of the
# ``register_*_permissions`` hook every other module ships. The catalogue is
# tenant-wide/shared and mutating a system re-prices every project's
# formwork assignments (FormworkService.create_assignment / update_assignment
# recompute ``computed_total`` from ``system.unit_rate``), so writes are
# gated at MANAGER level rather than left open to every authenticated viewer.
permission_registry.register_module_permissions(
    "formwork",
    {
        "formwork.read": Role.VIEWER,
        "formwork.manage_catalogue": Role.MANAGER,
    },
)


def _system_to_response(item: FormworkSystem) -> FormworkSystemResponse:
    return FormworkSystemResponse.model_validate(item)


def _assignment_to_response(
    item: FormworkAssignment,
) -> FormworkAssignmentResponse:
    return FormworkAssignmentResponse.model_validate(item)


def _line_to_response(
    item: FormworkScheduleLine,
) -> FormworkScheduleLineResponse:
    return FormworkScheduleLineResponse.model_validate(item)


# ── helpers ──────────────────────────────────────────────────────────────


async def _load_system_or_404(session, system_id: uuid.UUID) -> FormworkSystem:
    obj = await session.get(FormworkSystem, system_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Formwork system not found")
    return obj


async def _load_assignment_or_404(
    session,
    assignment_id: uuid.UUID,
) -> FormworkAssignment:
    obj = await session.get(FormworkAssignment, assignment_id)
    if obj is None:
        raise HTTPException(
            status_code=404,
            detail="Formwork assignment not found",
        )
    return obj


async def _verify_assignment_access(
    session,
    assignment_id: uuid.UUID,
    user_id: str,
) -> FormworkAssignment:
    obj = await _load_assignment_or_404(session, assignment_id)
    await verify_project_access(obj.project_id, user_id, session)
    return obj


# ── Systems ──────────────────────────────────────────────────────────────


@router.get("/systems/", response_model=list[FormworkSystemResponse])
async def list_systems(
    session: SessionDep,
    _user_id: CurrentUserId,
    system_type: str | None = Query(default=None),
    material: str | None = Query(default=None),
    supplier: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FormworkSystemResponse]:
    """List formwork systems.

    Catalogue is tenant-wide read for the MVP - every authenticated user
    can see every system. Per-tenant gating ships with the multi-tenant
    sweep.
    """
    service = FormworkService(session)
    items = await service.system_repo.list_filtered(
        system_type=system_type,
        material=material,
        supplier=supplier,
        offset=offset,
        limit=limit,
    )
    return [_system_to_response(it) for it in items]


@router.post(
    "/systems/",
    response_model=FormworkSystemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("formwork.manage_catalogue"))],
)
async def create_system(
    data: FormworkSystemCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkSystemResponse:
    service = FormworkService(session)
    obj = await service.create_system(data)
    return _system_to_response(obj)


@router.get("/systems/{system_id}", response_model=FormworkSystemResponse)
async def get_system(
    system_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkSystemResponse:
    obj = await _load_system_or_404(session, system_id)
    return _system_to_response(obj)


@router.patch(
    "/systems/{system_id}",
    response_model=FormworkSystemResponse,
    dependencies=[Depends(RequirePermission("formwork.manage_catalogue"))],
)
async def update_system(
    system_id: uuid.UUID,
    data: FormworkSystemUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkSystemResponse:
    await _load_system_or_404(session, system_id)
    service = FormworkService(session)
    obj = await service.update_system(system_id, data)
    assert obj is not None  # the load_or_404 above proved existence
    return _system_to_response(obj)


@router.delete(
    "/systems/{system_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("formwork.manage_catalogue"))],
)
async def delete_system(
    system_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    # IDOR posture: a missing row returns 404, never 403, never 422 -
    # so probing the catalogue for a UUID never leaks its existence.
    await _load_system_or_404(session, system_id)
    service = FormworkService(session)
    await service.system_repo.delete(system_id)


@router.post(
    "/systems/seed-defaults",
    response_model=FormworkSystemSeedResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("formwork.manage_catalogue"))],
)
async def seed_default_systems(
    session: SessionDep,
    _user_id: CurrentUserId,
    tenant_id: uuid.UUID | None = Query(default=None),
) -> FormworkSystemSeedResult:
    """Idempotent: re-running this never duplicates a system name."""
    service = FormworkService(session)
    result = await service.seed_defaults(tenant_id=tenant_id)
    return FormworkSystemSeedResult(**result)


# ── Assignments ──────────────────────────────────────────────────────────


@router.get(
    "/assignments/",
    response_model=list[FormworkAssignmentResponse],
)
async def list_assignments(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FormworkAssignmentResponse]:
    await verify_project_access(project_id, user_id, session)
    service = FormworkService(session)
    items = await service.assignment_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
    )
    return [_assignment_to_response(it) for it in items]


@router.post(
    "/assignments/",
    response_model=FormworkAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    data: FormworkAssignmentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkAssignmentResponse:
    await verify_project_access(data.project_id, user_id, session)
    service = FormworkService(session)
    try:
        obj = await service.create_assignment(data)
    except LookupError as exc:
        # Same IDOR rationale as ``/systems/{id}`` - a typo'd system
        # UUID is a 404, never 422.
        raise HTTPException(
            status_code=404,
            detail="Formwork system not found",
        ) from exc
    except ReuseCountExceedsMaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return _assignment_to_response(obj)


@router.get(
    "/assignments/{assignment_id}",
    response_model=FormworkAssignmentResponse,
)
async def get_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkAssignmentResponse:
    obj = await _verify_assignment_access(session, assignment_id, user_id)
    return _assignment_to_response(obj)


@router.patch(
    "/assignments/{assignment_id}",
    response_model=FormworkAssignmentResponse,
)
async def update_assignment(
    assignment_id: uuid.UUID,
    data: FormworkAssignmentUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkAssignmentResponse:
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    try:
        obj = await service.update_assignment(assignment_id, data)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail="Formwork system not found",
        ) from exc
    except ReuseCountExceedsMaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if obj is None:  # defensive - load_or_404 already proved existence
        raise HTTPException(
            status_code=404,
            detail="Formwork assignment not found",
        )
    return _assignment_to_response(obj)


@router.delete(
    "/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    await service.assignment_repo.delete(assignment_id)


# ── Schedule lines ───────────────────────────────────────────────────────


@router.get(
    "/assignments/{assignment_id}/schedule-lines/",
    response_model=list[FormworkScheduleLineResponse],
)
async def list_schedule_lines(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[FormworkScheduleLineResponse]:
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    items = await service.schedule_repo.list_for_assignment(assignment_id)
    return [_line_to_response(it) for it in items]


@router.post(
    "/assignments/{assignment_id}/schedule-lines/",
    response_model=FormworkScheduleLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_schedule_line(
    assignment_id: uuid.UUID,
    data: FormworkScheduleLineCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkScheduleLineResponse:
    assignment = await _verify_assignment_access(
        session,
        assignment_id,
        user_id,
    )
    service = FormworkService(session)
    obj = await service.add_schedule_line(assignment, data)
    return _line_to_response(obj)


async def _verify_schedule_line_access(
    session,
    line_id: uuid.UUID,
    user_id: str,
) -> FormworkScheduleLine:
    obj = await session.get(FormworkScheduleLine, line_id)
    if obj is None:
        # IDOR: probing /schedule-lines/<random-uuid> never leaks existence.
        raise HTTPException(
            status_code=404,
            detail="Formwork schedule line not found",
        )
    # Reuse the assignment's project for the access check.
    parent = await session.get(FormworkAssignment, obj.assignment_id)
    if parent is None:
        raise HTTPException(
            status_code=404,
            detail="Formwork schedule line not found",
        )
    await verify_project_access(parent.project_id, user_id, session)
    return obj


@router.patch(
    "/schedule-lines/{line_id}",
    response_model=FormworkScheduleLineResponse,
)
async def update_schedule_line(
    line_id: uuid.UUID,
    data: FormworkScheduleLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkScheduleLineResponse:
    await _verify_schedule_line_access(session, line_id, user_id)
    service = FormworkService(session)
    obj = await service.update_schedule_line(line_id, data)
    assert obj is not None  # the access check above proved existence
    return _line_to_response(obj)


@router.delete(
    "/schedule-lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule_line(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    await _verify_schedule_line_access(session, line_id, user_id)
    service = FormworkService(session)
    await service.schedule_repo.delete(line_id)
