# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formwork API routes.

Mounted at ``/api/v1/formwork/`` by the module loader.

Endpoint groups:
    /systems/                              - catalogue CRUD + seed + usage
    /systems/compare                       - price one area in every system at once
    /systems/{id}/reprice                  - re-price everything using a system
    /assignments/                          - per-project assignment CRUD
    /assignments/{id}/cycle                - reuse economics of the pour schedule
    /assignments/{id}/derive-from-schedule - write the derived area + reuse count
    /assignments/{id}/validate             - the ``formwork`` rule set, one assignment
    /assignments/{id}/push-to-boq          - write the priced result into a bill
    /assignments/{id}/schedule-lines/      - pour-cycle sub-resource
    /schedule-lines/{id}                   - schedule-line update + delete
    /summary                               - project rollup with the reuse saving
    /validate                              - the ``formwork`` rule set, whole project
    /reprice                               - bulk re-price one project

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
    FormworkAssignmentDetail,
    FormworkAssignmentResponse,
    FormworkAssignmentUpdate,
    FormworkBoqPushRequest,
    FormworkBoqPushResult,
    FormworkCompareRequest,
    FormworkCompareResult,
    FormworkCycleAnalysis,
    FormworkDeriveResult,
    FormworkProjectSummary,
    FormworkRepriceResult,
    FormworkScheduleLineCreate,
    FormworkScheduleLineResponse,
    FormworkScheduleLineUpdate,
    FormworkSystemCreate,
    FormworkSystemResponse,
    FormworkSystemSeedResult,
    FormworkSystemUpdate,
    FormworkSystemUpdateResult,
    FormworkSystemUsage,
    FormworkValidationReport,
)
from app.modules.formwork.service import (
    BoqProjectMismatchError,
    FieldNotNullableError,
    FormworkService,
    OrdinalSpaceExhaustedError,
    ReuseCountExceedsMaxError,
)

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


def _assignment_to_detail(
    item: FormworkAssignment,
    system: FormworkSystem | None,
) -> FormworkAssignmentDetail:
    """Build the enriched row the catalogue-aware screens read.

    ``system`` must already be loaded (``selectinload``); the relationship is
    ``raise_on_sql`` precisely so this cannot become one lazy query per row.
    """
    detail = FormworkAssignmentDetail.model_validate(item)
    detail.schedule_line_count = len(item.schedule_lines)
    if system is not None:
        detail.system_name = system.name
        detail.system_type = system.system_type
        detail.material = system.material
        detail.supplier = system.supplier
        detail.reuses_max = system.reuses_max
        detail.system_unit_rate = system.unit_rate
        detail.erect_strike_rate = system.erect_strike_rate
        detail.strip_time_days = system.strip_time_days
        detail.rate_basis = system.rate_basis
        detail.typical_reuses = system.typical_reuses
        detail.cycle_days = system.cycle_days
        detail.currency = system.currency
    return detail


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


async def _assignment_with_system(
    service: FormworkService,
    assignment_id: uuid.UUID,
) -> tuple[FormworkAssignment, FormworkSystem]:
    """Load an assignment together with the catalogue row that prices it.

    Every rate-aware endpoint needs both, and the system relationship refuses
    lazy SQL, so resolving them in one place keeps the eager load honest.
    """
    obj = await service.assignment_repo.get_with_system(assignment_id)
    if obj is None:
        raise HTTPException(
            status_code=404,
            detail="Formwork assignment not found",
        )
    if obj.system is None:
        # The FK is NOT NULL with ondelete=RESTRICT, so this is unreachable
        # through the API; it can only mean the row was orphaned outside it.
        raise HTTPException(status_code=404, detail="Formwork system not found")
    return obj, obj.system


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


@router.get("/systems/{system_id}/usage", response_model=FormworkSystemUsage)
async def get_system_usage(
    system_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkSystemUsage:
    """How many priced assignments depend on this catalogue row.

    Read before re-rating or deleting: a rate change moves every one of these
    totals, and the delete is refused while any of them exist.
    """
    await _load_system_or_404(session, system_id)
    service = FormworkService(session)
    return await service.system_usage(system_id)


@router.patch(
    "/systems/{system_id}",
    response_model=FormworkSystemUpdateResult,
    dependencies=[Depends(RequirePermission("formwork.manage_catalogue"))],
)
async def update_system(
    system_id: uuid.UUID,
    data: FormworkSystemUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkSystemUpdateResult:
    """Patch a catalogue system; every assignment using it is re-priced.

    The response carries the re-pricing counts because the edit is not local:
    changing a rate here changes the formwork total on every project that
    picked this system.
    """
    await _load_system_or_404(session, system_id)
    service = FormworkService(session)
    try:
        obj, reprice = await service.update_system(system_id, data)
    except FieldNotNullableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    assert obj is not None  # the load_or_404 above proved existence
    return FormworkSystemUpdateResult(system=_system_to_response(obj), reprice=reprice)


@router.post(
    "/systems/{system_id}/reprice",
    response_model=FormworkRepriceResult,
    dependencies=[Depends(RequirePermission("formwork.manage_catalogue"))],
)
async def reprice_system(
    system_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkRepriceResult:
    """Recompute every assignment priced off this system.

    The repair path for rows that went stale outside the API - a restore, a
    direct SQL correction, a catalogue import. Idempotent: a second run over
    consistent data reports everything unchanged.
    """
    system = await _load_system_or_404(session, system_id)
    service = FormworkService(session)
    return await service.reprice_for_system(system)


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
    # The FK is ondelete=RESTRICT, so deleting a system that still prices
    # assignments raises an IntegrityError deep in the flush and surfaces as a
    # 500. Check first and answer 409 with the count, which is actionable.
    usage = await service.system_usage(system_id)
    if usage.assignment_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Formwork system is used by {usage.assignment_count} assignment(s) "
                f"across {usage.project_count} project(s) and cannot be deleted"
            ),
        )
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
    response_model=list[FormworkAssignmentDetail],
)
async def list_assignments(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FormworkAssignmentDetail]:
    """Formwork assignments on one project, newest first.

    Each row carries the catalogue facts behind its rate (system name,
    material, reuse cap, currency) so the list reads as a rate build-up rather
    than a column of opaque totals. The systems are loaded eagerly in one
    extra query, not one per row.
    """
    await verify_project_access(project_id, user_id, session)
    service = FormworkService(session)
    items = await service.assignment_repo.list_for_project(
        project_id,
        with_system=True,
        offset=offset,
        limit=limit,
    )
    return [_assignment_to_detail(it, it.system) for it in items]


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _assignment_to_response(obj)


@router.get(
    "/assignments/{assignment_id}",
    response_model=FormworkAssignmentDetail,
)
async def get_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkAssignmentDetail:
    obj = await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    obj, system = await _assignment_with_system(service, obj.id)
    return _assignment_to_detail(obj, system)


@router.get(
    "/assignments/{assignment_id}/cycle",
    response_model=FormworkCycleAnalysis,
)
async def get_assignment_cycle(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkCycleAnalysis:
    """What the pour schedule says about this assignment's reuse economics.

    Read-only. Reports the panel set the largest pour requires, how many times
    that set turns around, whether the typed reuse count is supported, and any
    pair of pours scheduled closer together than the striking time allows.
    """
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    obj, system = await _assignment_with_system(service, assignment_id)
    return await service.analyse_cycle(obj, system)


@router.post(
    "/systems/compare",
    response_model=FormworkCompareResult,
)
async def compare_systems(
    data: FormworkCompareRequest,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> FormworkCompareResult:
    """Price one contact area in every candidate system at once.

    The endpoint behind choosing a system. The client sends the area, the
    waste allowance and the reuse count it intends to assume, and gets back
    one priced row per catalogue system, sorted cheapest first.

    It is a POST because it takes a body of estimating assumptions, not
    because it writes anything: nothing is persisted here.

    Deliberately server-side. The alternative - shipping the rate build-up to
    the client and computing the preview there - puts a second implementation
    of the formula next to the first, in a language whose numbers are floats,
    and the two drift. The visible symptom of that drift would be the rate on
    the chooser disagreeing with the rate that lands in the bill, which is
    exactly the sort of thing nobody reports and everybody stops trusting.
    """
    service = FormworkService(session)
    return await service.compare_systems(data)


@router.post(
    "/assignments/{assignment_id}/push-to-boq",
    response_model=FormworkBoqPushResult,
    status_code=status.HTTP_200_OK,
)
async def push_assignment_to_boq(
    assignment_id: uuid.UUID,
    data: FormworkBoqPushRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkBoqPushResult:
    """Send a priced assignment to a bill of quantities as a position.

    The contact area becomes the quantity, the reuse-aware unit cost becomes
    the rate, and the position is stamped ``source="formwork"`` so the number
    can be traced back to the system and the assumptions that produced it.

    Idempotent by design: a second push re-prices the position the first one
    created instead of adding another. Returns ``created=false`` in that case,
    so the caller can say "updated" rather than implying a new line.
    """
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    try:
        return await service.push_assignment_to_boq(assignment_id, data, actor_id=user_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Formwork assignment not found",
        ) from exc
    except BoqProjectMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The target BOQ belongs to a different project",
        ) from exc
    except OrdinalSpaceExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No free formwork position number is left in this BOQ",
        ) from exc


@router.post(
    "/assignments/{assignment_id}/derive-from-schedule",
    response_model=FormworkDeriveResult,
)
async def derive_assignment_from_schedule(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> FormworkDeriveResult:
    """Replace the typed area and reuse count with the ones the cycle delivers.

    The estimator stops guessing the turnaround: the schedule's total pour area
    becomes the priced area, and the total divided by the largest single pour
    becomes the reuse count. Re-prices the assignment in the same call.
    """
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    obj, system = await _assignment_with_system(service, assignment_id)
    try:
        analysis, changed = await service.derive_from_schedule(obj, system)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Formwork assignment has no pour schedule to derive from",
        ) from exc
    return FormworkDeriveResult(
        assignment=_assignment_to_response(obj),
        analysis=analysis,
        changed=changed,
    )


@router.post(
    "/assignments/{assignment_id}/validate",
    response_model=FormworkValidationReport,
)
async def validate_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query(default=""),
) -> FormworkValidationReport:
    """Run the ``formwork`` rule set over one assignment and its pour cycle."""
    await _verify_assignment_access(session, assignment_id, user_id)
    service = FormworkService(session)
    obj, system = await _assignment_with_system(service, assignment_id)
    return await service.validate_assignment(obj, system, locale=locale)


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except FieldNotNullableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    try:
        obj = await service.update_schedule_line(line_id, data)
    except FieldNotNullableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
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


# ── Project rollup, validation and bulk re-pricing ───────────────────────


@router.get("/summary", response_model=FormworkProjectSummary)
async def get_project_summary(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
) -> FormworkProjectSummary:
    """The project's formwork totals with the reuse saving made explicit.

    ``single_use_total`` re-prices every assignment at one use, so the gap
    against the real total is exactly the money the reuse assumption is
    claiming - the number a reviewer challenges first.
    """
    await verify_project_access(project_id, user_id, session)
    service = FormworkService(session)
    return await service.project_summary(project_id)


@router.post("/validate", response_model=FormworkValidationReport)
async def validate_project(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    locale: str = Query(default=""),
) -> FormworkValidationReport:
    """Run the project-scope ``formwork`` rules over every assignment.

    Catches what no single assignment can see: formwork priced in more than
    one currency, and two assignments charging the same BOQ position.
    """
    await verify_project_access(project_id, user_id, session)
    service = FormworkService(session)
    return await service.validate_project(project_id, locale=locale)


@router.post("/reprice", response_model=FormworkRepriceResult)
async def reprice_project(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
) -> FormworkRepriceResult:
    """Recompute every formwork assignment on one project from the catalogue.

    The bulk refresh after a catalogue import, a currency correction or a
    restore. Idempotent: a second run over consistent data reports everything
    unchanged and a zero delta.
    """
    await verify_project_access(project_id, user_id, session)
    service = FormworkService(session)
    return await service.reprice_project(project_id)
