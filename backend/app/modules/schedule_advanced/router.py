# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced API routes.

Mounted at ``/api/v1/schedule-advanced/`` by the module loader.

All write endpoints are gated by :class:`RequirePermission`. Every
project-scoped read/write/delete endpoint additionally enforces
:func:`verify_project_access` (added in v3.0.x IDOR sweep - closes the
cross-tenant exfil hole where any authenticated user could read or
mutate Last-Planner-System records belonging to another tenant's
project just by guessing UUIDs).

For nested resources (phase plans, look-aheads, constraints, weekly
plans, commitments, RNCs, baselines) the project_id is resolved by
walking the parent chain up to the owning ``MasterSchedule``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule_advanced.delay_service import DelayAnalysisService
from app.modules.schedule_advanced.resource_leveling_schemas import (
    LevelApplyResponse,
    LevelPreviewRequest,
    LevelPreviewResponse,
    LevelPreviewSegment,
    LevelPreviewSegmentRun,
    LevelPreviewShift,
    LevelPreviewUnresolvable,
)
from app.modules.schedule_advanced.schemas import (
    AutoFragnetRequest,
    BaselineCreate,
    BaselineDeltaResponse,
    BaselineResponse,
    BaselineUpdate,
    CalendarCreate,
    CalendarResponse,
    CalendarUpdate,
    CommitmentCreate,
    CommitmentResponse,
    CommitmentUpdate,
    ConstraintCreate,
    ConstraintReadinessResponse,
    ConstraintResponse,
    ConstraintUpdate,
    CPMActivityResult,
    CPMComputeSummary,
    CPMRequest,
    CPMResponse,
    DelayAnalysisCreate,
    DelayAnalysisListItem,
    DelayAnalysisPatch,
    DelayAnalysisResponse,
    DelayComputeRequest,
    DelayEventCreate,
    DelayEventPatch,
    DelayEventResponse,
    DelayWindowResponse,
    EVMRequest,
    EVMResponse,
    FragnetResponse,
    FragnetUpsert,
    LevelResourcesRequest,
    LevelResourcesResponse,
    LevelResourcesShift,
    LevelResourcesUnresolvable,
    LineOfBalanceResponse,
    LocationCreate,
    LocationResponse,
    LookAheadCreate,
    LookAheadResponse,
    LookAheadUpdate,
    LPSDashboardResponse,
    MasterScheduleCreate,
    MasterScheduleResponse,
    MasterScheduleUpdate,
    PhasePlanCreate,
    PhasePlanResponse,
    PhasePlanUpdate,
    PPCResponse,
    PPCWeeklyResponse,
    RaiseEotClaimResponse,
    RNCCreate,
    RNCParetoResponse,
    RNCParetoSortedResponse,
    RNCResponse,
    RNCUpdate,
    ScheduleQualityResponse,
    ScheduleRiskRequest,
    ScheduleRiskResponse,
    TaktActivityImport,
    TaktActivityResponse,
    TaktActivityUpdate,
    TaktScheduleCreate,
    TaktScheduleResponse,
    TaktScheduleUpdate,
    TaktViolation,
    TIARequest,
    TIAResponse,
    WeeklyCommitmentCreate,
    WeeklyCommitmentResponse,
    WeeklyWorkPlanCreate,
    WeeklyWorkPlanResponse,
    WeeklyWorkPlanUpdate,
)
from app.modules.schedule_advanced.service import (
    ScheduleAdvancedService,
    TaktScheduleService,
    compute_evm,
    cpm_forward_backward_pass,
    time_impact_analysis,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schedule_advanced"])


def _get_service(session: SessionDep) -> ScheduleAdvancedService:
    return ScheduleAdvancedService(session)


def _get_takt_service(session: SessionDep) -> TaktScheduleService:
    return TaktScheduleService(session)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# ── Project-id resolvers for nested resources ─────────────────────────────


async def _project_id_for_master(
    master_id: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    master = await service.master_repo.get_by_id(master_id)
    if master is None:
        raise _not_found("MasterSchedule not found")
    return master.project_id


async def _project_id_for_phase(
    phase_id: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    phase = await service.phase_repo.get_by_id(phase_id)
    if phase is None:
        raise _not_found("PhasePlan not found")
    return await _project_id_for_master(phase.master_schedule_id, service)


async def _project_id_for_look_ahead(
    la_id: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    la = await service.look_ahead_repo.get_by_id(la_id)
    if la is None:
        raise _not_found("LookAheadPlan not found")
    return await _project_id_for_master(la.master_schedule_id, service)


async def _project_id_for_constraint(
    cid: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    c = await service.constraint_repo.get_by_id(cid)
    if c is None:
        raise _not_found("Constraint not found")
    if c.look_ahead_id is None:
        # Detached constraint - no project to verify against. Raise 404
        # rather than silently grant access (defence-in-depth).
        raise _not_found("Constraint not found")
    return await _project_id_for_look_ahead(c.look_ahead_id, service)


async def _project_id_for_weekly(
    wp_id: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    w = await service.weekly_repo.get_by_id(wp_id)
    if w is None:
        raise _not_found("WeeklyWorkPlan not found")
    return await _project_id_for_master(w.master_schedule_id, service)


async def _project_id_for_commitment(
    cid: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    c = await service.commitment_repo.get_by_id(cid)
    if c is None:
        raise _not_found("Commitment not found")
    return await _project_id_for_weekly(c.week_plan_id, service)


async def _project_id_for_rnc(
    rid: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    r = await service.rnc_repo.get_by_id(rid)
    if r is None:
        raise _not_found("RNC not found")
    return await _project_id_for_commitment(r.commitment_id, service)


async def _project_id_for_baseline(
    bid: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    b = await service.baseline_repo.get_by_id(bid)
    if b is None:
        raise _not_found("Baseline not found")
    return await _project_id_for_master(b.master_schedule_id, service)


async def _project_id_for_calendar(
    cid: uuid.UUID,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    cal = await service.calendar_repo.get_by_id(cid)
    if cal is None:
        raise _not_found("Calendar not found")
    return cal.project_id


# ── Master schedules ──────────────────────────────────────────────────────


@router.get("/master-schedules/", response_model=list[MasterScheduleResponse])
async def list_master_schedules(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[MasterScheduleResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.master_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return [MasterScheduleResponse.model_validate(i) for i in items]


@router.post("/master-schedules/", response_model=MasterScheduleResponse, status_code=201)
async def create_master_schedule(
    data: MasterScheduleCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> MasterScheduleResponse:
    await verify_project_access(data.project_id, user_id, session)
    m = await service.create_master_schedule(data, user_id=user_id)
    return MasterScheduleResponse.model_validate(m)


@router.get("/master-schedules/{master_id}", response_model=MasterScheduleResponse)
async def get_master_schedule(
    master_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> MasterScheduleResponse:
    project_id = await _project_id_for_master(master_id, service)
    await verify_project_access(project_id, user_id, session)
    m = await service.get_master_schedule(master_id)
    return MasterScheduleResponse.model_validate(m)


@router.patch("/master-schedules/{master_id}", response_model=MasterScheduleResponse)
async def update_master_schedule(
    master_id: uuid.UUID,
    data: MasterScheduleUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> MasterScheduleResponse:
    project_id = await _project_id_for_master(master_id, service)
    await verify_project_access(project_id, user_id, session)
    m = await service.update_master_schedule(master_id, data)
    return MasterScheduleResponse.model_validate(m)


@router.delete("/master-schedules/{master_id}", status_code=204)
async def delete_master_schedule(
    master_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_master(master_id, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_master_schedule(master_id)


@router.get("/master-schedules/{master_id}/dashboard", response_model=LPSDashboardResponse)
async def master_schedule_dashboard(
    master_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LPSDashboardResponse:
    project_id = await _project_id_for_master(master_id, service)
    await verify_project_access(project_id, user_id, session)
    m = await service.get_master_schedule(master_id)
    payload = await service.lps_dashboard_for_project(m.project_id)
    return LPSDashboardResponse(**payload)


# ── Phase plans ───────────────────────────────────────────────────────────


@router.get("/phase-plans/", response_model=list[PhasePlanResponse])
async def list_phase_plans(
    session: SessionDep,
    user_id: CurrentUserId,
    master_schedule_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[PhasePlanResponse]:
    project_id = await _project_id_for_master(master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.phase_repo.list_for_master(master_schedule_id)
    return [PhasePlanResponse.model_validate(i) for i in items]


@router.post("/phase-plans/", response_model=PhasePlanResponse, status_code=201)
async def create_phase_plan(
    data: PhasePlanCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> PhasePlanResponse:
    project_id = await _project_id_for_master(data.master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    p = await service.create_phase_plan(data)
    return PhasePlanResponse.model_validate(p)


@router.get("/phase-plans/{phase_id}", response_model=PhasePlanResponse)
async def get_phase_plan(
    phase_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> PhasePlanResponse:
    project_id = await _project_id_for_phase(phase_id, service)
    await verify_project_access(project_id, user_id, session)
    p = await service.get_phase_plan(phase_id)
    return PhasePlanResponse.model_validate(p)


@router.patch("/phase-plans/{phase_id}", response_model=PhasePlanResponse)
async def update_phase_plan(
    phase_id: uuid.UUID,
    data: PhasePlanUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> PhasePlanResponse:
    project_id = await _project_id_for_phase(phase_id, service)
    await verify_project_access(project_id, user_id, session)
    p = await service.update_phase_plan(phase_id, data)
    return PhasePlanResponse.model_validate(p)


@router.delete("/phase-plans/{phase_id}", status_code=204)
async def delete_phase_plan(
    phase_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_phase(phase_id, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_phase_plan(phase_id)


@router.post("/phase-plans/{phase_id}/pull", response_model=PhasePlanResponse)
async def pull_phase(
    phase_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.pull_phase")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> PhasePlanResponse:
    project_id = await _project_id_for_phase(phase_id, service)
    await verify_project_access(project_id, user_id, session)
    p = await service.pull_phase(phase_id, user_id=user_id)
    return PhasePlanResponse.model_validate(p)


@router.post("/phase-plans/{phase_id}/start", response_model=PhasePlanResponse)
async def start_phase(
    phase_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> PhasePlanResponse:
    project_id = await _project_id_for_phase(phase_id, service)
    await verify_project_access(project_id, user_id, session)
    p = await service.start_phase(phase_id)
    return PhasePlanResponse.model_validate(p)


@router.post("/phase-plans/{phase_id}/complete", response_model=PhasePlanResponse)
async def complete_phase(
    phase_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> PhasePlanResponse:
    project_id = await _project_id_for_phase(phase_id, service)
    await verify_project_access(project_id, user_id, session)
    p = await service.complete_phase(phase_id)
    return PhasePlanResponse.model_validate(p)


# ── Look-ahead plans ──────────────────────────────────────────────────────


@router.get("/look-aheads/", response_model=list[LookAheadResponse])
async def list_look_aheads(
    session: SessionDep,
    user_id: CurrentUserId,
    master_schedule_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[LookAheadResponse]:
    project_id = await _project_id_for_master(master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.look_ahead_repo.list_for_master(master_schedule_id)
    return [LookAheadResponse.model_validate(i) for i in items]


@router.get("/look-aheads/current", response_model=LookAheadResponse | None)
async def current_look_ahead(
    session: SessionDep,
    user_id: CurrentUserId,
    master_schedule_id: uuid.UUID = Query(...),
    today: date | None = Query(default=None),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LookAheadResponse | None:
    from datetime import UTC, datetime

    project_id = await _project_id_for_master(master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    effective = today or datetime.now(UTC).date()
    la = await service.look_ahead_repo.current_for_master(master_schedule_id, effective)
    return LookAheadResponse.model_validate(la) if la is not None else None


@router.post("/look-aheads/", response_model=LookAheadResponse, status_code=201)
async def create_look_ahead(
    data: LookAheadCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LookAheadResponse:
    project_id = await _project_id_for_master(data.master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    la = await service.create_look_ahead(data)
    return LookAheadResponse.model_validate(la)


@router.get("/look-aheads/{la_id}", response_model=LookAheadResponse)
async def get_look_ahead(
    la_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LookAheadResponse:
    project_id = await _project_id_for_look_ahead(la_id, service)
    await verify_project_access(project_id, user_id, session)
    la = await service.get_look_ahead(la_id)
    return LookAheadResponse.model_validate(la)


@router.patch("/look-aheads/{la_id}", response_model=LookAheadResponse)
async def update_look_ahead(
    la_id: uuid.UUID,
    data: LookAheadUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LookAheadResponse:
    project_id = await _project_id_for_look_ahead(la_id, service)
    await verify_project_access(project_id, user_id, session)
    la = await service.update_look_ahead(la_id, data)
    return LookAheadResponse.model_validate(la)


@router.delete("/look-aheads/{la_id}", status_code=204)
async def delete_look_ahead(
    la_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_look_ahead(la_id, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_look_ahead(la_id)


@router.post("/look-aheads/{la_id}/publish", response_model=LookAheadResponse)
async def publish_look_ahead(
    la_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LookAheadResponse:
    project_id = await _project_id_for_look_ahead(la_id, service)
    await verify_project_access(project_id, user_id, session)
    la = await service.publish_look_ahead(la_id)
    return LookAheadResponse.model_validate(la)


# ── Constraints ───────────────────────────────────────────────────────────


@router.get("/constraints/", response_model=list[ConstraintResponse])
async def list_constraints(
    session: SessionDep,
    user_id: CurrentUserId,
    look_ahead_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[ConstraintResponse]:
    project_id = await _project_id_for_look_ahead(look_ahead_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.constraint_repo.list_for_look_ahead(look_ahead_id)
    return [ConstraintResponse.model_validate(i) for i in items]


@router.post("/constraints/", response_model=ConstraintResponse, status_code=201)
async def create_constraint(
    data: ConstraintCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> ConstraintResponse:
    # ``look_ahead_id`` is the only link a constraint has to a project, so it is
    # the sole thing we can authorise against. The schema permits ``None`` (the
    # service layer supports detached constraints for internal/derived flows),
    # but a constraint created over HTTP with no look-ahead would be an
    # unauthorised, orphaned row that no project owner can ever read back (the
    # nested resolvers 404 detached constraints). Require it here so an API
    # caller cannot pollute the table with rows that bypass project access.
    if data.look_ahead_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="look_ahead_id is required to create a constraint",
        )
    project_id = await _project_id_for_look_ahead(data.look_ahead_id, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.create_constraint(data)
    return ConstraintResponse.model_validate(c)


@router.get("/constraints/{cid}", response_model=ConstraintResponse)
async def get_constraint(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> ConstraintResponse:
    project_id = await _project_id_for_constraint(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.get_constraint(cid)
    return ConstraintResponse.model_validate(c)


@router.patch("/constraints/{cid}", response_model=ConstraintResponse)
async def update_constraint(
    cid: uuid.UUID,
    data: ConstraintUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> ConstraintResponse:
    project_id = await _project_id_for_constraint(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.update_constraint(cid, data)
    return ConstraintResponse.model_validate(c)


@router.delete("/constraints/{cid}", status_code=204)
async def delete_constraint(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_constraint(cid, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_constraint(cid)


@router.post("/constraints/{cid}/clear", response_model=ConstraintResponse)
async def clear_constraint_endpoint(
    cid: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.clear_constraint")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> ConstraintResponse:
    project_id = await _project_id_for_constraint(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.clear_constraint(cid, user_id=user_id)
    return ConstraintResponse.model_validate(c)


@router.post("/constraints/{cid}/escalate", response_model=ConstraintResponse)
async def escalate_constraint_endpoint(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> ConstraintResponse:
    project_id = await _project_id_for_constraint(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.escalate_constraint(cid)
    return ConstraintResponse.model_validate(c)


@router.post("/constraints/{cid}/cannot-clear", response_model=ConstraintResponse)
async def cannot_clear_constraint_endpoint(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> ConstraintResponse:
    project_id = await _project_id_for_constraint(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.cannot_clear_constraint(cid)
    return ConstraintResponse.model_validate(c)


# ── Weekly work plans ─────────────────────────────────────────────────────


@router.get("/weekly-work-plans/", response_model=list[WeeklyWorkPlanResponse])
async def list_weekly_work_plans(
    session: SessionDep,
    user_id: CurrentUserId,
    master_schedule_id: uuid.UUID = Query(...),
    limit: int = Query(default=52, ge=1, le=520),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[WeeklyWorkPlanResponse]:
    project_id = await _project_id_for_master(master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.weekly_repo.list_for_master(master_schedule_id, limit=limit)
    return [WeeklyWorkPlanResponse.model_validate(i) for i in items]


@router.post("/weekly-work-plans/", response_model=WeeklyWorkPlanResponse, status_code=201)
async def create_weekly_work_plan(
    data: WeeklyWorkPlanCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> WeeklyWorkPlanResponse:
    project_id = await _project_id_for_master(data.master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    w = await service.create_weekly_plan(data)
    return WeeklyWorkPlanResponse.model_validate(w)


@router.get("/weekly-work-plans/{wp_id}", response_model=WeeklyWorkPlanResponse)
async def get_weekly_work_plan(
    wp_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> WeeklyWorkPlanResponse:
    project_id = await _project_id_for_weekly(wp_id, service)
    await verify_project_access(project_id, user_id, session)
    w = await service.get_weekly_plan(wp_id)
    return WeeklyWorkPlanResponse.model_validate(w)


@router.patch("/weekly-work-plans/{wp_id}", response_model=WeeklyWorkPlanResponse)
async def update_weekly_work_plan(
    wp_id: uuid.UUID,
    data: WeeklyWorkPlanUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> WeeklyWorkPlanResponse:
    project_id = await _project_id_for_weekly(wp_id, service)
    await verify_project_access(project_id, user_id, session)
    w = await service.update_weekly_plan(wp_id, data)
    return WeeklyWorkPlanResponse.model_validate(w)


@router.delete("/weekly-work-plans/{wp_id}", status_code=204)
async def delete_weekly_work_plan(
    wp_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_weekly(wp_id, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_weekly_plan(wp_id)


@router.post("/weekly-work-plans/{wp_id}/commit", response_model=WeeklyWorkPlanResponse)
async def commit_weekly_plan_endpoint(
    wp_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.commit")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> WeeklyWorkPlanResponse:
    project_id = await _project_id_for_weekly(wp_id, service)
    await verify_project_access(project_id, user_id, session)
    w = await service.commit_weekly_plan(wp_id)
    return WeeklyWorkPlanResponse.model_validate(w)


@router.post("/weekly-work-plans/{wp_id}/close", response_model=WeeklyWorkPlanResponse)
async def close_weekly_plan_endpoint(
    wp_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.close_weekly")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> WeeklyWorkPlanResponse:
    project_id = await _project_id_for_weekly(wp_id, service)
    await verify_project_access(project_id, user_id, session)
    w = await service.close_weekly_plan(wp_id)
    return WeeklyWorkPlanResponse.model_validate(w)


# ── Commitments ───────────────────────────────────────────────────────────


@router.get("/commitments/", response_model=list[CommitmentResponse])
async def list_commitments(
    session: SessionDep,
    user_id: CurrentUserId,
    week_plan_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[CommitmentResponse]:
    project_id = await _project_id_for_weekly(week_plan_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.commitment_repo.commitments_for_week(week_plan_id)
    return [CommitmentResponse.model_validate(i) for i in items]


@router.post("/commitments/", response_model=CommitmentResponse, status_code=201)
async def create_commitment(
    data: CommitmentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CommitmentResponse:
    project_id = await _project_id_for_weekly(data.week_plan_id, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.create_commitment(data)
    return CommitmentResponse.model_validate(c)


@router.get("/commitments/{cid}", response_model=CommitmentResponse)
async def get_commitment(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CommitmentResponse:
    project_id = await _project_id_for_commitment(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.get_commitment(cid)
    return CommitmentResponse.model_validate(c)


@router.patch("/commitments/{cid}", response_model=CommitmentResponse)
async def update_commitment(
    cid: uuid.UUID,
    data: CommitmentUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CommitmentResponse:
    project_id = await _project_id_for_commitment(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.update_commitment(cid, data)
    return CommitmentResponse.model_validate(c)


@router.delete("/commitments/{cid}", status_code=204)
async def delete_commitment(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_commitment(cid, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_commitment(cid)


@router.post("/commitments/{cid}/commit", response_model=CommitmentResponse)
async def commit_commitment_endpoint(
    cid: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.commit")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CommitmentResponse:
    project_id = await _project_id_for_commitment(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.commit_to_week(cid, user_id=user_id)
    return CommitmentResponse.model_validate(c)


@router.post("/commitments/{cid}/complete", response_model=CommitmentResponse)
async def complete_commitment_endpoint(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    actual_qty: str | None = Body(default=None, embed=True),
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CommitmentResponse:
    from decimal import Decimal, InvalidOperation

    project_id = await _project_id_for_commitment(cid, service)
    await verify_project_access(project_id, user_id, session)
    qty: Decimal | None = None
    if actual_qty is not None:
        try:
            qty = Decimal(str(actual_qty))
        except (InvalidOperation, ValueError):
            qty = None
    c = await service.mark_commitment_complete(cid, actual_qty=qty)
    return CommitmentResponse.model_validate(c)


@router.post("/commitments/{cid}/miss", response_model=CommitmentResponse)
async def miss_commitment_endpoint(
    cid: uuid.UUID,
    rnc: RNCCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CommitmentResponse:
    project_id = await _project_id_for_commitment(cid, service)
    await verify_project_access(project_id, user_id, session)
    # Caller passes a full RNCCreate body - overwrite the commitment_id
    # with the URL value to ensure consistency.
    rnc_payload = rnc.model_copy(update={"commitment_id": cid})
    c, _r = await service.mark_commitment_missed(cid, rnc_payload, user_id=user_id)
    return CommitmentResponse.model_validate(c)


# ── RNCs ──────────────────────────────────────────────────────────────────


@router.get("/rncs/", response_model=list[RNCResponse])
async def list_rncs(
    session: SessionDep,
    user_id: CurrentUserId,
    commitment_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[RNCResponse]:
    project_id = await _project_id_for_commitment(commitment_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.rnc_repo.list_for_commitment(commitment_id)
    return [RNCResponse.model_validate(i) for i in items]


@router.post("/rncs/", response_model=RNCResponse, status_code=201)
async def create_rnc(
    data: RNCCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> RNCResponse:
    project_id = await _project_id_for_commitment(data.commitment_id, service)
    await verify_project_access(project_id, user_id, session)
    r = await service.create_rnc(data, user_id=user_id)
    return RNCResponse.model_validate(r)


@router.get("/rncs/pareto", response_model=RNCParetoResponse)
async def rnc_pareto_endpoint(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    period_start: date = Query(...),
    period_end: date = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> RNCParetoResponse:
    await verify_project_access(project_id, user_id, session)
    counts = await service.rnc_pareto_for_project(project_id, period_start, period_end)
    return RNCParetoResponse(
        period_start=period_start,
        period_end=period_end,
        counts=counts,
        total=sum(counts.values()),
    )


@router.get("/rncs/{rid}", response_model=RNCResponse)
async def get_rnc(
    rid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> RNCResponse:
    project_id = await _project_id_for_rnc(rid, service)
    await verify_project_access(project_id, user_id, session)
    r = await service.get_rnc(rid)
    return RNCResponse.model_validate(r)


@router.patch("/rncs/{rid}", response_model=RNCResponse)
async def update_rnc(
    rid: uuid.UUID,
    data: RNCUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> RNCResponse:
    project_id = await _project_id_for_rnc(rid, service)
    await verify_project_access(project_id, user_id, session)
    r = await service.update_rnc(rid, data)
    return RNCResponse.model_validate(r)


@router.delete("/rncs/{rid}", status_code=204)
async def delete_rnc(
    rid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_rnc(rid, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_rnc(rid)


# ── Baselines ─────────────────────────────────────────────────────────────


@router.get("/baselines/", response_model=list[BaselineResponse])
async def list_baselines(
    session: SessionDep,
    user_id: CurrentUserId,
    master_schedule_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[BaselineResponse]:
    project_id = await _project_id_for_master(master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await service.baseline_repo.list_for_master(master_schedule_id)
    return [BaselineResponse.model_validate(i) for i in items]


@router.post("/baselines/", response_model=BaselineResponse, status_code=201)
async def create_baseline(
    data: BaselineCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.capture_baseline")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> BaselineResponse:
    project_id = await _project_id_for_master(data.master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    b = await service.create_baseline(data, user_id=user_id)
    return BaselineResponse.model_validate(b)


@router.post("/baselines/capture", response_model=BaselineResponse, status_code=201)
async def capture_baseline_endpoint(
    data: BaselineCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("schedule_advanced.capture_baseline")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> BaselineResponse:
    project_id = await _project_id_for_master(data.master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    b = await service.create_baseline(data, user_id=user_id)
    return BaselineResponse.model_validate(b)


@router.get("/baselines/{bid}", response_model=BaselineResponse)
async def get_baseline(
    bid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> BaselineResponse:
    project_id = await _project_id_for_baseline(bid, service)
    await verify_project_access(project_id, user_id, session)
    b = await service.get_baseline(bid)
    return BaselineResponse.model_validate(b)


@router.patch("/baselines/{bid}", response_model=BaselineResponse)
async def update_baseline(
    bid: uuid.UUID,
    data: BaselineUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> BaselineResponse:
    project_id = await _project_id_for_baseline(bid, service)
    await verify_project_access(project_id, user_id, session)
    b = await service.update_baseline(bid, data)
    return BaselineResponse.model_validate(b)


@router.delete("/baselines/{bid}", status_code=204)
async def delete_baseline(
    bid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_baseline(bid, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_baseline(bid)


# The delta endpoint carries the current task list in the request body. A GET
# with a body is non-standard and triggers a 405 from the frontend (which POSTs
# the array via ``baselineDelta`` in ``schedule-advanced/api.ts``). Register
# POST as the canonical verb and keep GET registered on the same handler for
# back-compat with any existing callers.
@router.post("/baselines/{bid}/delta", response_model=BaselineDeltaResponse)
@router.get("/baselines/{bid}/delta", response_model=BaselineDeltaResponse)
async def baseline_delta_endpoint(
    bid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    current_tasks: list[dict] = Body(default_factory=list),
    # Read-only delta computation, but exposed via POST (to carry the task
    # list in a body), so it must still declare an explicit permission gate -
    # a bare POST otherwise bypasses the permission registry entirely (RBAC
    # defence-in-depth). ``schedule_advanced.read`` matches its read nature.
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> BaselineDeltaResponse:
    project_id = await _project_id_for_baseline(bid, service)
    await verify_project_access(project_id, user_id, session)
    return await service.compute_baseline_delta_for_schedule(bid, current_tasks)


# ── Calendars ─────────────────────────────────────────────────────────────


@router.get("/calendars/", response_model=list[CalendarResponse])
async def list_calendars(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[CalendarResponse]:
    await verify_project_access(project_id, user_id, session)
    items = await service.calendar_repo.list_for_project(project_id)
    return [CalendarResponse.model_validate(i) for i in items]


@router.post("/calendars/", response_model=CalendarResponse, status_code=201)
async def create_calendar(
    data: CalendarCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CalendarResponse:
    await verify_project_access(data.project_id, user_id, session)
    c = await service.create_calendar(data)
    return CalendarResponse.model_validate(c)


@router.get("/calendars/{cid}", response_model=CalendarResponse)
async def get_calendar(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CalendarResponse:
    project_id = await _project_id_for_calendar(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.get_calendar(cid)
    return CalendarResponse.model_validate(c)


@router.patch("/calendars/{cid}", response_model=CalendarResponse)
async def update_calendar(
    cid: uuid.UUID,
    data: CalendarUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> CalendarResponse:
    project_id = await _project_id_for_calendar(cid, service)
    await verify_project_access(project_id, user_id, session)
    c = await service.update_calendar(cid, data)
    return CalendarResponse.model_validate(c)


@router.delete("/calendars/{cid}", status_code=204)
async def delete_calendar(
    cid: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> None:
    project_id = await _project_id_for_calendar(cid, service)
    await verify_project_access(project_id, user_id, session)
    await service.delete_calendar(cid)


# ── Project-wide dashboard ────────────────────────────────────────────────


@router.get("/dashboard/project/{project_id}", response_model=LPSDashboardResponse)
async def project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> LPSDashboardResponse:
    await verify_project_access(project_id, user_id, session)
    payload = await service.lps_dashboard_for_project(project_id)
    return LPSDashboardResponse(**payload)


@router.get("/dashboard/project/{project_id}/ppc-trend", response_model=list[PPCResponse])
async def project_ppc_trend(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    weeks: int = Query(default=12, ge=1, le=104),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[PPCResponse]:
    await verify_project_access(project_id, user_id, session)
    recent_weekly = await service.weekly_repo.last_n_weeks_ppc(project_id, n=weeks)
    from decimal import Decimal

    return [
        PPCResponse(
            week_start_date=w.week_start_date,
            total_commitments=0,
            completed_commitments=0,
            ppc_percent=w.ppc_percent or Decimal("0"),
        )
        for w in reversed(recent_weekly)
    ]


# ── CPM / EVM / TIA - stateless analysis endpoints ────────────────────────


@router.post("/cpm", response_model=CPMResponse)
async def run_cpm(
    data: CPMRequest,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> CPMResponse:
    """Run a CPM forward+backward pass on a supplied activity list.

    Stateless - no DB I/O. Useful for what-if scheduling experiments,
    importing schedules from external interchange formats (XER, P6 XML,
    .mpp), and powering the EoT/TIA analytic in
    :mod:`app.modules.variations`.
    """
    acts = [a.model_dump() for a in data.activities]
    deps = [d.model_dump() for d in data.dependencies] if data.dependencies else None
    raw = cpm_forward_backward_pass(acts, deps)
    activities = [CPMActivityResult(**v) for v in raw.values()]
    project_finish = max((v.ef for v in activities), default=0)
    critical_count = sum(1 for v in activities if v.is_critical)
    return CPMResponse(
        project_finish_workday=project_finish,
        critical_path_count=critical_count,
        activities=activities,
    )


@router.post("/tia", response_model=TIAResponse)
async def run_tia(
    data: TIARequest,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> TIAResponse:
    """Time-Impact-Analysis - recompute completion date after a delay.

    Stateless - no DB I/O. Inputs are the full schedule + a single delay
    event (impacted activity id + delay in working days). Used by the
    Variations EoT-claim workflow to drive granted-days decisions.
    """
    acts = [a.model_dump() for a in data.activities]
    deps = [d.model_dump() for d in data.dependencies] if data.dependencies else None
    result = time_impact_analysis(
        acts,
        deps,
        data.impacted_activity_id,
        data.delay_days,
    )
    return TIAResponse(**result)


@router.post("/evm", response_model=EVMResponse)
async def run_evm(
    data: EVMRequest,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> EVMResponse:
    """Earned Value Management - compute PV/EV/AC + SPI/CPI/EAC.

    Stateless - no DB I/O. Each activity contributes its BAC × PV-ramp
    to the project Planned Value at ``today_workday``. EV = BAC × %
    complete; AC is reported directly.
    """
    acts = [a.model_dump() for a in data.activities]
    result = compute_evm(acts, data.today_workday)
    return EVMResponse(**result)


# ── Constraint readiness + Pareto-sorted RNC ──────────────────────────────


@router.get(
    "/look-aheads/{la_id}/readiness",
    response_model=list[ConstraintReadinessResponse],
)
async def look_ahead_readiness(
    la_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
) -> list[ConstraintReadinessResponse]:
    """Return ready/not-ready summary per task for the look-ahead window."""
    project_id = await _project_id_for_look_ahead(la_id, service)
    await verify_project_access(project_id, user_id, session)
    rows = await service.look_ahead_readiness(la_id)
    return [ConstraintReadinessResponse(**r) for r in rows]


@router.get(
    "/dashboard/project/{project_id}/rnc-pareto",
    response_model=RNCParetoSortedResponse,
)
async def project_rnc_pareto_sorted(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    period_start: date = Query(...),
    period_end: date = Query(...),
    service: ScheduleAdvancedService = Depends(_get_service),
) -> RNCParetoSortedResponse:
    """Sorted-desc RNC Pareto with cumulative percentage column."""
    await verify_project_access(project_id, user_id, session)
    payload = await service.rnc_pareto_sorted_for_project(
        project_id,
        period_start,
        period_end,
    )
    return RNCParetoSortedResponse(**payload)


# ── CPM Slice 1 - persisted compute + leveling + weekly commitments ───────


async def _project_id_for_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
) -> uuid.UUID:
    """Resolve project_id for a ``oe_schedule_schedule`` row.

    Kept out of :class:`ScheduleAdvancedService` because that service only
    owns LPS tables - Schedule lives in the sister ``schedule`` module.
    """
    from app.modules.schedule.models import Schedule as _Schedule

    sched = await session.get(_Schedule, schedule_id)
    if sched is None:
        raise _not_found("Schedule not found")
    return sched.project_id


@router.post(
    "/{schedule_id}/compute-cpm",
    response_model=CPMComputeSummary,
)
async def compute_cpm_for_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> CPMComputeSummary:
    """Recompute CPM for ``schedule_id`` and persist ES/EF/LS/LF/float on each Activity.

    Forward + backward pass implemented in
    :mod:`app.modules.schedule_advanced.cpm` (pure Python, no scipy /
    networkx). FS dependencies only in Slice 1.
    """
    from sqlalchemy import select

    from app.modules.schedule.models import Activity as _Activity
    from app.modules.schedule.models import ScheduleRelationship as _Rel
    from app.modules.schedule_advanced.cpm import (
        Activity as _CPMActivity,
    )
    from app.modules.schedule_advanced.cpm import (
        TaskNetwork as _CPMNetwork,
    )
    from app.modules.schedule_advanced.cpm import (
        compute_cpm as _compute_cpm,
    )
    from app.modules.schedule_advanced.cpm import (
        critical_path as _critical_path,
    )

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    act_rows = (
        (
            await session.execute(
                select(_Activity).where(_Activity.schedule_id == schedule_id),
            )
        )
        .scalars()
        .all()
    )
    rel_rows = (
        (
            await session.execute(
                select(_Rel).where(_Rel.schedule_id == schedule_id),
            )
        )
        .scalars()
        .all()
    )

    # Build the pure-Python network.
    cpm_acts: list[_CPMActivity] = []
    rel_index: dict[uuid.UUID, list[tuple[uuid.UUID, str, int]]] = {}
    for r in rel_rows:
        rel_index.setdefault(r.successor_id, []).append(
            (r.predecessor_id, r.relationship_type or "FS", int(r.lag_days or 0)),
        )
    for a in act_rows:
        preds = rel_index.get(a.id, [])
        cpm_acts.append(
            _CPMActivity(
                id=a.id,
                duration=int(a.duration_days or 0),
                predecessors=preds,
                required_resources={},
            ),
        )

    network = _CPMNetwork(cpm_acts)
    results = _compute_cpm(network)

    # Persist back onto Activity rows.
    activity_by_id = {a.id: a for a in act_rows}
    project_duration = 0
    num_critical = 0
    for aid, res in results.items():
        a = activity_by_id.get(aid)
        if a is None:
            continue
        a.early_start = str(res.es)
        a.early_finish = str(res.ef)
        a.late_start = str(res.ls)
        a.late_finish = str(res.lf)
        a.total_float = int(res.total_float)
        a.free_float = int(res.free_float)
        a.is_critical = bool(res.is_critical)
        if res.ef > project_duration:
            project_duration = res.ef
        if res.is_critical:
            num_critical += 1
    await session.flush()

    cp_ids = _critical_path(network, results)
    return CPMComputeSummary(
        schedule_id=schedule_id,
        critical_path=[uuid.UUID(str(x)) for x in cp_ids],
        project_duration_days=project_duration,
        num_critical=num_critical,
        num_activities=len(results),
    )


@router.post(
    "/{schedule_id}/level-resources",
    response_model=LevelResourcesResponse,
)
async def level_resources_for_schedule(
    schedule_id: uuid.UUID,
    data: LevelResourcesRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> LevelResourcesResponse:
    """Run serial-greedy resource leveling - returns shifted ES for changed activities only.

    The arithmetic is the same engine ``/level-preview`` and ``/level-apply``
    run. This endpoint used to call an FS-only leveler, which meant a schedule
    built on SS, FF or SF links was leveled as if those links did not exist and
    the shifted dates came back breaking the schedule's own logic without
    saying so. FS-only networks are unaffected: the two produce identical
    diffs, and a test pins that.

    Nothing is split here. Splitting is offered by ``/level-preview``, which
    can report the resulting day-runs; this response carries starts alone, so a
    split activity would be described by a start that is only part of the
    truth.
    """
    from sqlalchemy import select

    from app.modules.resources.resource_engine import level_preview as _level_preview
    from app.modules.schedule.models import Activity as _Activity
    from app.modules.schedule.models import ScheduleRelationship as _Rel
    from app.modules.schedule_advanced.cpm import (
        Activity as _CPMActivity,
    )
    from app.modules.schedule_advanced.cpm import (
        TaskNetwork as _CPMNetwork,
    )

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    act_rows = (
        (
            await session.execute(
                select(_Activity).where(_Activity.schedule_id == schedule_id),
            )
        )
        .scalars()
        .all()
    )
    rel_rows = (
        (
            await session.execute(
                select(_Rel).where(_Rel.schedule_id == schedule_id),
            )
        )
        .scalars()
        .all()
    )

    rel_index: dict[uuid.UUID, list[tuple[uuid.UUID, str, int]]] = {}
    for r in rel_rows:
        rel_index.setdefault(r.successor_id, []).append(
            (r.predecessor_id, r.relationship_type or "FS", int(r.lag_days or 0)),
        )

    cpm_acts: list[_CPMActivity] = []
    for a in act_rows:
        # Resources are stored as ``[{"name": "...", "type": "...",
        # "allocation_pct": ...}, ...]`` on Activity.resources. Use the
        # ``name`` as the resource code and ``1`` as the unit demand
        # (Slice 1 limits to integer counts). Callers passing a richer
        # shape will be supported in Slice 2.
        required: dict[str, int] = {}
        for r in a.resources or []:
            if isinstance(r, dict) and r.get("name"):
                required[str(r["name"])] = int(r.get("count", 1) or 1)
        cpm_acts.append(
            _CPMActivity(
                id=a.id,
                duration=int(a.duration_days or 0),
                predecessors=rel_index.get(a.id, []),
                required_resources=required,
            ),
        )

    network = _CPMNetwork(cpm_acts)
    preview = _level_preview(network, dict(data.resource_limits or {}), splittable=set())

    rows = [
        LevelResourcesShift(
            activity_id=uuid.UUID(str(s.activity_id)),
            original_es=s.base_es,
            shifted_es=s.new_es,
            delta_days=s.delta,
        )
        for s in preview.shifts
    ]
    return LevelResourcesResponse(
        schedule_id=schedule_id,
        shifts=rows,
        num_shifted=len(rows),
        unresolvable=[
            LevelResourcesUnresolvable(
                activity_id=uuid.UUID(str(u.activity_id)),
                resource=u.resource,
                required=u.required,
                limit=u.limit,
            )
            for u in preview.unresolvable
        ],
    )


@router.post(
    "/{schedule_id}/level-preview",
    response_model=LevelPreviewResponse,
)
async def level_preview_for_schedule(
    schedule_id: uuid.UUID,
    data: LevelPreviewRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> LevelPreviewResponse:
    """Resource-leveling PREVIEW honouring SS/FF/SF, splits, and fractional units.

    Read-only. Returns the shifted starts, any split day-runs, the explicit
    single-activity self-overloads, the per-resource peak demand before/after,
    and - the headline differentiator - the honest finish-date impact computed
    from a copy of the network, before anything is committed. The arithmetic is
    the pure :func:`app.modules.resources.resource_engine.level_preview`; the
    older ``/level-resources`` endpoint (FS-only, no finish impact) is kept for
    back-compat.
    """
    from sqlalchemy import select

    from app.modules.resources.resource_engine import level_preview as _level_preview
    from app.modules.schedule.models import Activity as _Activity
    from app.modules.schedule.models import ScheduleRelationship as _Rel
    from app.modules.schedule_advanced.cpm import Activity as _CPMActivity
    from app.modules.schedule_advanced.cpm import TaskNetwork as _CPMNetwork

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    act_rows = (
        (
            await session.execute(
                select(_Activity).where(_Activity.schedule_id == schedule_id),
            )
        )
        .scalars()
        .all()
    )
    rel_rows = (
        (
            await session.execute(
                select(_Rel).where(_Rel.schedule_id == schedule_id),
            )
        )
        .scalars()
        .all()
    )

    rel_index: dict[uuid.UUID, list[tuple[uuid.UUID, str, int]]] = {}
    for r in rel_rows:
        rel_index.setdefault(r.successor_id, []).append(
            (r.predecessor_id, r.relationship_type or "FS", int(r.lag_days or 0)),
        )

    cpm_acts: list[_CPMActivity] = []
    for a in act_rows:
        required: dict[str, int] = {}
        for res in a.resources or []:
            if isinstance(res, dict) and res.get("name"):
                required[str(res["name"])] = int(res.get("count", 1) or 1)
        cpm_acts.append(
            _CPMActivity(
                id=a.id,
                duration=int(a.duration_days or 0),
                predecessors=rel_index.get(a.id, []),
                required_resources=required,
            ),
        )

    network = _CPMNetwork(cpm_acts)
    preview = _level_preview(network, dict(data.resource_limits or {}), splittable=set(data.splittable))

    return LevelPreviewResponse(
        schedule_id=schedule_id,
        num_shifted=len(preview.shifts),
        finish_delta_days=preview.finish_delta_days,
        base_finish_workday=preview.base_finish_workday,
        leveled_finish_workday=preview.leveled_finish_workday,
        shifts=[
            LevelPreviewShift(
                activity_id=uuid.UUID(str(s.activity_id)),
                base_es=s.base_es,
                new_es=s.new_es,
                delta=s.delta,
            )
            for s in preview.shifts
        ],
        segments=[
            LevelPreviewSegment(
                activity_id=uuid.UUID(str(aid)),
                runs=[LevelPreviewSegmentRun(start=run_start, finish=run_finish) for (run_start, run_finish) in runs],
            )
            for aid, runs in preview.segments.items()
        ],
        unresolvable=[
            LevelPreviewUnresolvable(
                activity_id=uuid.UUID(str(u.activity_id)),
                resource=u.resource,
                required=u.required,
                limit=u.limit,
            )
            for u in preview.unresolvable
        ],
        peak_before=preview.peak_before,
        peak_after=preview.peak_after,
    )


def _shift_iso_date(value: str | None, delta_days: int) -> str | None:
    """Shift an ISO date string by ``delta_days`` calendar days.

    Returns the new ``YYYY-MM-DD`` string, or ``None`` when the input is empty
    or unparseable (the caller leaves such a row untouched).
    """
    from datetime import date, timedelta

    if not value:
        return None
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return (parsed + timedelta(days=delta_days)).isoformat()


@router.post(
    "/{schedule_id}/level-apply",
    response_model=LevelApplyResponse,
)
async def level_apply_for_schedule(
    schedule_id: uuid.UUID,
    data: LevelPreviewRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> LevelApplyResponse:
    """Run resource leveling and COMMIT it: persist each shifted activity's
    start / end dates (moved by its leveling delta in calendar days, span
    preserved). Same pure arithmetic as ``/level-preview``; this one writes.

    Calendar-day shift keeps the result consistent with the calendar-day CPM; a
    working-day-aware shift is a later refinement (tracked with CPM calendar
    wiring).
    """
    from sqlalchemy import select

    from app.modules.resources.resource_engine import level_preview as _level_preview
    from app.modules.schedule.models import Activity as _Activity
    from app.modules.schedule.models import ScheduleRelationship as _Rel
    from app.modules.schedule_advanced.cpm import Activity as _CPMActivity
    from app.modules.schedule_advanced.cpm import TaskNetwork as _CPMNetwork

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    act_rows = (await session.execute(select(_Activity).where(_Activity.schedule_id == schedule_id))).scalars().all()
    rel_rows = (await session.execute(select(_Rel).where(_Rel.schedule_id == schedule_id))).scalars().all()

    rel_index: dict[uuid.UUID, list[tuple[uuid.UUID, str, int]]] = {}
    for r in rel_rows:
        rel_index.setdefault(r.successor_id, []).append(
            (r.predecessor_id, r.relationship_type or "FS", int(r.lag_days or 0)),
        )

    cpm_acts: list[_CPMActivity] = []
    for a in act_rows:
        required: dict[str, int] = {}
        for res in a.resources or []:
            if isinstance(res, dict) and res.get("name"):
                required[str(res["name"])] = int(res.get("count", 1) or 1)
        cpm_acts.append(
            _CPMActivity(
                id=a.id,
                duration=int(a.duration_days or 0),
                predecessors=rel_index.get(a.id, []),
                required_resources=required,
            ),
        )

    network = _CPMNetwork(cpm_acts)
    preview = _level_preview(network, dict(data.resource_limits or {}), splittable=set(data.splittable))

    shift_by_id = {str(s.activity_id): int(s.delta) for s in preview.shifts if int(s.delta) != 0}
    applied = 0
    skipped = 0
    for a in act_rows:
        delta = shift_by_id.get(str(a.id))
        if not delta:
            continue
        new_start = _shift_iso_date(a.start_date, delta)
        new_end = _shift_iso_date(a.end_date, delta)
        if new_start is None or new_end is None:
            skipped += 1
            continue
        a.start_date = new_start
        a.end_date = new_end
        applied += 1

    await session.flush()

    return LevelApplyResponse(
        schedule_id=schedule_id,
        num_shifted=len(preview.shifts),
        num_applied=applied,
        num_skipped=skipped,
        finish_delta_days=preview.finish_delta_days,
        base_finish_workday=preview.base_finish_workday,
        leveled_finish_workday=preview.leveled_finish_workday,
    )


@router.post(
    "/{schedule_id}/commitments",
    response_model=WeeklyCommitmentResponse,
    status_code=201,
)
async def create_weekly_commitment(
    schedule_id: uuid.UUID,
    data: WeeklyCommitmentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.commit")),
) -> WeeklyCommitmentResponse:
    """Record a Last-Planner weekly commitment and auto-compute PPC."""
    from decimal import Decimal as _Decimal

    from app.modules.schedule_advanced.models import (
        WeeklyCommitment as _WeeklyCommitment,
    )

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    planned = data.planned_complete_pct or _Decimal("0")
    actual = data.actual_complete_pct or _Decimal("0")
    if planned > 0:
        ppc = actual / planned
        if ppc > 1:
            ppc = _Decimal("1")
        if ppc < 0:
            ppc = _Decimal("0")
    else:
        ppc = _Decimal("0")
    # Truncate to 4 decimal places to fit Numeric(6, 4).
    ppc = ppc.quantize(_Decimal("0.0001"))

    committed_by_uuid: uuid.UUID | None
    try:
        committed_by_uuid = uuid.UUID(str(user_id)) if user_id else None
    except (ValueError, TypeError):
        committed_by_uuid = None

    row = _WeeklyCommitment(
        schedule_id=schedule_id,
        activity_id=data.activity_id,
        week_start=data.week_start,
        committed_by=committed_by_uuid,
        planned_complete_pct=planned,
        actual_complete_pct=actual,
        ppc=ppc,
    )
    session.add(row)
    await session.flush()
    return WeeklyCommitmentResponse.model_validate(row)


@router.get(
    "/{schedule_id}/ppc",
    response_model=PPCWeeklyResponse,
)
async def get_weekly_ppc(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    week: date = Query(...),
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> PPCWeeklyResponse:
    """Roll-up Percent-Plan-Complete for a single week.

    PPC is the unweighted mean of per-commitment PPC values for the week.
    Used by the CPM frontend to drive the weekly Last-Planner card.
    """
    from decimal import Decimal as _Decimal

    from sqlalchemy import select

    from app.modules.schedule_advanced.models import (
        WeeklyCommitment as _WeeklyCommitment,
    )

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    rows = (
        (
            await session.execute(
                select(_WeeklyCommitment).where(
                    _WeeklyCommitment.schedule_id == schedule_id,
                    _WeeklyCommitment.week_start == week,
                ),
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return PPCWeeklyResponse(
            schedule_id=schedule_id,
            week_start=week,
            num_commitments=0,
            avg_planned_pct=_Decimal("0"),
            avg_actual_pct=_Decimal("0"),
            ppc=_Decimal("0"),
        )

    n = _Decimal(len(rows))
    sum_planned = sum((r.planned_complete_pct or _Decimal("0") for r in rows), _Decimal("0"))
    sum_actual = sum((r.actual_complete_pct or _Decimal("0") for r in rows), _Decimal("0"))
    sum_ppc = sum((r.ppc or _Decimal("0") for r in rows), _Decimal("0"))
    return PPCWeeklyResponse(
        schedule_id=schedule_id,
        week_start=week,
        num_commitments=len(rows),
        avg_planned_pct=(sum_planned / n).quantize(_Decimal("0.0001")),
        avg_actual_pct=(sum_actual / n).quantize(_Decimal("0.0001")),
        ppc=(sum_ppc / n).quantize(_Decimal("0.0001")),
    )


# ── Takt / line-of-balance scheduling ─────────────────────────────────────


def _takt_response(ts: object, locations: list[object]) -> TaktScheduleResponse:
    """Build a TaktScheduleResponse with its nested locations."""
    payload = TaktScheduleResponse.model_validate(ts)
    payload.locations = [LocationResponse.model_validate(loc) for loc in locations]
    return payload


async def _project_id_for_takt(
    takt_id: uuid.UUID,
    takt_service: TaktScheduleService,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    ts = await takt_service.takt_repo.get_by_id(takt_id)
    if ts is None:
        raise _not_found("TaktSchedule not found")
    return await _project_id_for_master(ts.master_schedule_id, service)


async def _project_id_for_takt_activity(
    activity_id: uuid.UUID,
    takt_service: TaktScheduleService,
    service: ScheduleAdvancedService,
) -> uuid.UUID:
    a = await takt_service.activity_repo.get_by_id(activity_id)
    if a is None:
        raise _not_found("TaktActivity not found")
    return await _project_id_for_takt(a.takt_schedule_id, takt_service, service)


@router.get(
    "/masters/{master_id}/takt-schedules",
    response_model=list[TaktScheduleResponse],
)
async def list_takt_schedules(
    master_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> list[TaktScheduleResponse]:
    """List takt schedules for a master schedule (with nested locations)."""
    project_id = await _project_id_for_master(master_id, service)
    await verify_project_access(project_id, user_id, session)
    items = await takt_service.list_for_master(master_id)
    locations_by_takt = await takt_service.list_locations_for_takts([ts.id for ts in items])
    return [_takt_response(ts, locations_by_takt.get(ts.id, [])) for ts in items]


@router.post(
    "/takt-schedules",
    response_model=TaktScheduleResponse,
    status_code=201,
)
async def create_takt_schedule(
    data: TaktScheduleCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> TaktScheduleResponse:
    project_id = await _project_id_for_master(data.master_schedule_id, service)
    await verify_project_access(project_id, user_id, session)
    ts = await takt_service.create_takt_schedule(data, user_id=user_id)
    locations = await takt_service.list_locations(ts.id)
    return _takt_response(ts, locations)


@router.get("/takt-schedules/{takt_id}", response_model=TaktScheduleResponse)
async def get_takt_schedule(
    takt_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> TaktScheduleResponse:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    ts = await takt_service.get_takt_schedule(takt_id)
    locations = await takt_service.list_locations(takt_id)
    return _takt_response(ts, locations)


@router.patch("/takt-schedules/{takt_id}", response_model=TaktScheduleResponse)
async def update_takt_schedule(
    takt_id: uuid.UUID,
    data: TaktScheduleUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> TaktScheduleResponse:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    ts = await takt_service.update_takt_schedule(takt_id, data)
    locations = await takt_service.list_locations(takt_id)
    return _takt_response(ts, locations)


@router.delete("/takt-schedules/{takt_id}", status_code=204)
async def delete_takt_schedule(
    takt_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> None:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    await takt_service.delete_takt_schedule(takt_id)


@router.post(
    "/takt-schedules/{takt_id}/locations",
    response_model=LocationResponse,
    status_code=201,
)
async def add_takt_location(
    takt_id: uuid.UUID,
    data: LocationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> LocationResponse:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    loc = await takt_service.add_location(takt_id, data)
    return LocationResponse.model_validate(loc)


# ── Takt activities ───────────────────────────────────────────────────────


@router.get(
    "/takt-schedules/{takt_id}/activities",
    response_model=list[TaktActivityResponse],
)
async def list_takt_activities(
    takt_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> list[TaktActivityResponse]:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    items = await takt_service.list_activities(takt_id)
    return [TaktActivityResponse.model_validate(a) for a in items]


@router.post(
    "/takt-schedules/{takt_id}/activities/import",
    response_model=list[TaktActivityResponse],
    status_code=201,
)
async def import_takt_activities(
    takt_id: uuid.UUID,
    data: TaktActivityImport,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> list[TaktActivityResponse]:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    items = await takt_service.import_activities(takt_id, data.activities)
    return [TaktActivityResponse.model_validate(a) for a in items]


@router.patch(
    "/takt-schedules/{takt_id}/activities/{activity_id}",
    response_model=TaktActivityResponse,
)
async def update_takt_activity(
    takt_id: uuid.UUID,
    activity_id: uuid.UUID,
    data: TaktActivityUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> TaktActivityResponse:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    activity = await takt_service.get_activity(activity_id)
    if activity.takt_schedule_id != takt_id:
        raise _not_found("TaktActivity not found")
    a = await takt_service.update_activity(activity_id, data)
    return TaktActivityResponse.model_validate(a)


@router.delete(
    "/takt-schedules/{takt_id}/activities/{activity_id}",
    status_code=204,
)
async def delete_takt_activity(
    takt_id: uuid.UUID,
    activity_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> None:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    activity = await takt_service.get_activity(activity_id)
    if activity.takt_schedule_id != takt_id:
        raise _not_found("TaktActivity not found")
    await takt_service.delete_activity(activity_id)


# ── Line-of-balance computation ───────────────────────────────────────────


@router.post(
    "/takt-schedules/{takt_id}/compute-lob",
    response_model=LineOfBalanceResponse,
)
async def compute_takt_line_of_balance(
    takt_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> LineOfBalanceResponse:
    """Compute line-of-balance geometry, violations and critical path."""
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    return await takt_service.compute_line_of_balance(takt_id)


@router.get(
    "/takt-schedules/{takt_id}/line-of-balance",
    response_model=LineOfBalanceResponse,
)
async def get_takt_line_of_balance(
    takt_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> LineOfBalanceResponse:
    """Read the line-of-balance geometry (recomputed deterministically)."""
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    return await takt_service.compute_line_of_balance(takt_id)


@router.get(
    "/takt-schedules/{takt_id}/violations",
    response_model=list[TaktViolation],
)
async def get_takt_violations(
    takt_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
    service: ScheduleAdvancedService = Depends(_get_service),
    takt_service: TaktScheduleService = Depends(_get_takt_service),
) -> list[TaktViolation]:
    project_id = await _project_id_for_takt(takt_id, takt_service, service)
    await verify_project_access(project_id, user_id, session)
    return await takt_service.detect_violations(takt_id)


# ── Claims-grade CPM analytics (T1.2) + Monte-Carlo schedule risk (T2.1) ─────
#
# Both read the schedule's activities + relationships, build the shared pure
# ``cpm.TaskNetwork`` and run a pure engine over it. Neither mutates the
# schedule, so both are gated by ``schedule_advanced.read`` (plus the usual
# project-access check).


async def _load_schedule_rows(schedule_id: uuid.UUID, session: SessionDep) -> tuple[list, list]:
    """Load all Activity + ScheduleRelationship rows for a schedule."""
    from sqlalchemy import select

    from app.modules.schedule.models import Activity as _Activity
    from app.modules.schedule.models import ScheduleRelationship as _Rel

    act_rows = (await session.execute(select(_Activity).where(_Activity.schedule_id == schedule_id))).scalars().all()
    rel_rows = (await session.execute(select(_Rel).where(_Rel.schedule_id == schedule_id))).scalars().all()
    return list(act_rows), list(rel_rows)


def _build_cpm_network(act_rows: list, rel_rows: list):
    """Build a pure ``cpm.TaskNetwork`` from ORM Activity + relationship rows.

    Predecessor links carry their relationship type (FS/SS/FF/SF) and lag, so
    all four PDM link types flow into the engine. Resource demand is read from
    each activity's ``resources`` JSON (``name`` -> integer ``count``).
    """
    from app.modules.schedule_advanced.cpm import Activity as _CPMActivity
    from app.modules.schedule_advanced.cpm import TaskNetwork as _CPMNetwork

    rel_index: dict[uuid.UUID, list[tuple[uuid.UUID, str, int]]] = {}
    for r in rel_rows:
        rel_index.setdefault(r.successor_id, []).append(
            (r.predecessor_id, r.relationship_type or "FS", int(r.lag_days or 0)),
        )

    cpm_acts: list = []
    for a in act_rows:
        required: dict[str, int] = {}
        for res in a.resources or []:
            if isinstance(res, dict) and res.get("name"):
                required[str(res["name"])] = int(res.get("count", 1) or 1)
        cpm_acts.append(
            _CPMActivity(
                id=a.id,
                duration=int(a.duration_days or 0),
                predecessors=rel_index.get(a.id, []),
                required_resources=required,
            ),
        )
    return _CPMNetwork(cpm_acts)


@router.post(
    "/{schedule_id}/schedule-quality",
    response_model=ScheduleQualityResponse,
)
async def schedule_quality_for_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> ScheduleQualityResponse:
    """Claims-grade read-only schedule analysis for ``schedule_id``.

    Returns the Longest Path, the ranked float-path decomposition, the
    scheduling QA log (open ends, hard constraints, out-of-sequence, lag
    issues) and per-activity explain strings - all from a single CPM pass over
    the four PDM link types. Nothing is written back to the schedule.
    """
    from app.modules.schedule_advanced.cpm import CycleError, QAOptions
    from app.modules.schedule_advanced.cpm_report import quality_report

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    act_rows, rel_rows = await _load_schedule_rows(schedule_id, session)
    network = _build_cpm_network(act_rows, rel_rows)

    # Mandatory date constraints surface as HARD_CONSTRAINT findings.
    hard = {a.id for a in act_rows if (a.constraint_type or "") in {"must_start_on", "must_finish_on"}}
    options = QAOptions(hard_constrained=hard)

    try:
        report = quality_report(network, options=options)
    except CycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ScheduleQualityResponse(schedule_id=schedule_id, **report)


def _risk_result_to_dict(result) -> dict:
    """Map a pure ``ScheduleRiskResult`` dataclass into a response dict.

    Note ``cpm`` ids are stringified, and the cost-engine CDF point's ``cost``
    field carries the finish-day x-value for a schedule run (the engine reuses
    the cost-engine CDF container), so it maps to ``x`` here.

    The headline cost figures (``target_cost`` / ``cost_mean``) are emitted as
    money (Decimal-as-string, v3 §10); the engine produces them as floats so we
    convert via ``Decimal(str(...))`` to avoid binary-float artefacts.
    """
    from decimal import Decimal

    jc = result.joint_confidence
    return {
        "iterations": result.iterations,
        "deterministic_finish": result.deterministic_finish,
        "mean": result.mean,
        "std_dev": result.std_dev,
        "cv_pct": result.cv_pct,
        "percentiles": result.percentiles,
        "contingency": result.contingency,
        "contingency_pct": result.contingency_pct,
        "recommended_finish": result.recommended_finish,
        "target_confidence": result.target_confidence,
        "prob_within_deterministic": result.prob_within_deterministic,
        "correlation": result.correlation,
        "seed": result.seed,
        "convergence_status": result.convergence_status,
        "convergence_margin_pct": result.convergence_margin_pct,
        "histogram": [{"bin_start": h.bin_start, "bin_end": h.bin_end, "count": h.count} for h in result.histogram],
        "cdf": [{"x": c.cost, "cumulative_prob": c.cumulative_prob} for c in result.cdf],
        "criticality": [
            {
                "activity_id": str(s.activity_id),
                "criticality_index": s.criticality_index,
                "cruciality": s.cruciality,
                "duration_sensitivity": s.duration_sensitivity,
                "mean_duration": s.mean_duration,
            }
            for s in result.criticality
        ],
        "drivers": [
            {
                "activity_id": str(d.activity_id),
                "rank_correlation": d.rank_correlation,
                "swing_low": d.swing_low,
                "swing_high": d.swing_high,
            }
            for d in result.drivers
        ],
        "joint_confidence": None
        if jc is None
        else {
            "target_finish": jc.target_finish,
            "target_cost": Decimal(str(jc.target_cost)),
            "jcl": jc.jcl,
            "prob_on_time": jc.prob_on_time,
            "prob_on_budget": jc.prob_on_budget,
            "cost_mean": Decimal(str(jc.cost_mean)),
            "cost_percentiles": jc.cost_percentiles,
            "correlation": jc.correlation,
            "scatter": [{"finish": p.finish, "cost": p.cost} for p in jc.scatter],
        },
    }


@router.post(
    "/{schedule_id}/schedule-risk",
    response_model=ScheduleRiskResponse,
)
async def schedule_risk_for_schedule(
    schedule_id: uuid.UUID,
    data: ScheduleRiskRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> ScheduleRiskResponse:
    """Run a correlated Monte-Carlo schedule-risk simulation for ``schedule_id``.

    Activity durations are sampled (Latin Hypercube by default) around their
    stored value using the run's optimistic / pessimistic band, or an explicit
    three-point override per activity. Returns finish-date percentiles, an
    S-curve, the per-activity criticality index, a duration tornado and - when
    ``cost_inputs`` is supplied - the Joint Confidence Level. Read-only.
    """
    from app.modules.schedule_advanced.cpm import CycleError
    from app.modules.schedule_advanced.schedule_risk_engine import (
        ActivityDurationInput,
        CostInputs,
        simulate_schedule,
    )

    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    act_rows, rel_rows = await _load_schedule_rows(schedule_id, session)
    if not act_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Schedule has no activities to analyse.",
        )

    network = _build_cpm_network(act_rows, rel_rows)
    base_by_id = {a.id: a.duration for a in network.activities}
    valid_ids = set(network.ids())

    risks: list[ActivityDurationInput] = []
    for r in data.activity_risks:
        if r.activity_id in valid_ids:
            risks.append(
                ActivityDurationInput(
                    activity_id=r.activity_id,
                    base=float(base_by_id.get(r.activity_id, 0)),
                    low=r.low,
                    mode=r.mode,
                    high=r.high,
                    distribution=r.distribution,
                ),
            )

    cost_inputs = None
    if data.cost_inputs is not None:
        ci = data.cost_inputs
        # The pure engine does float math; the schema carries Decimal money
        # (v3 §10), so coerce to float at the engine boundary.
        cost_inputs = CostInputs(
            base_cost=float(ci.base_cost),
            cost_low=float(ci.cost_low) if ci.cost_low is not None else None,
            cost_mode=float(ci.cost_mode) if ci.cost_mode is not None else None,
            cost_high=float(ci.cost_high) if ci.cost_high is not None else None,
            cost_target=float(ci.cost_target) if ci.cost_target is not None else None,
            distribution=ci.distribution,
            optimistic_pct=data.optimistic_pct,
            pessimistic_pct=data.pessimistic_pct,
        )

    try:
        result = simulate_schedule(
            network.activities,
            None,
            risks,
            None,
            iterations=data.iterations,
            correlation=data.correlation,
            seed=data.seed,
            sampling=data.sampling,
            target_confidence=data.target_confidence,
            optimistic_pct=data.optimistic_pct,
            pessimistic_pct=data.pessimistic_pct,
            cost_inputs=cost_inputs,
        )
    except CycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ScheduleRiskResponse(schedule_id=schedule_id, **_risk_result_to_dict(result))


# ════════════════════════════════════════════════════════════════════════════
# Forensic delay analysis (T2.2) - persisted, exhibit-producing flow
# ────────────────────────────────────────────────────────────────────────────
# CRUD over the delay-analysis spine + the compute endpoint that runs the pure
# delay engine and persists windows + the exhibit ``result_json``. Read-only
# what-if stays on ``POST /tia`` / ``/compute-cpm``; this is the persisted path.
# Access control mirrors the compute-cpm IDOR pattern: resolve the analysis,
# then ``verify_project_access`` against its ``project_id``.
# ════════════════════════════════════════════════════════════════════════════


def _get_delay_service(session: SessionDep) -> DelayAnalysisService:
    return DelayAnalysisService(session)


def _build_str_network(act_rows: list, rel_rows: list):
    """Build a ``cpm.TaskNetwork`` keyed by STRING activity ids.

    Fragnet ``host_id`` / event ``insert_at`` are stored as strings, so the
    delay engine must compare them against string activity ids (the
    UUID-keyed :func:`_build_cpm_network` would never match a stored ref).
    """
    from app.modules.schedule_advanced.cpm import Activity as _CPMActivity
    from app.modules.schedule_advanced.cpm import TaskNetwork as _CPMNetwork

    rel_index: dict[str, list[tuple[str, str, int]]] = {}
    for r in rel_rows:
        rel_index.setdefault(str(r.successor_id), []).append(
            (str(r.predecessor_id), r.relationship_type or "FS", int(r.lag_days or 0)),
        )
    cpm_acts: list = []
    for a in act_rows:
        cpm_acts.append(
            _CPMActivity(
                id=str(a.id),
                duration=int(a.duration_days or 0),
                predecessors=rel_index.get(str(a.id), []),
            ),
        )
    return _CPMNetwork(cpm_acts)


async def _load_delay_analysis(
    analysis_id: uuid.UUID,
    svc: DelayAnalysisService,
    user_id: CurrentUserId,
    session: SessionDep,
):
    """Load an analysis, enforce project access (IDOR), or 404."""
    analysis = await svc.get_analysis(analysis_id)
    if analysis is None:
        raise _not_found("Delay analysis not found")
    await verify_project_access(analysis.project_id, user_id, session)
    return analysis


def _assert_draft(analysis) -> None:
    if analysis.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Delay analysis is {analysis.status!r}; only a draft can be edited.",
        )


async def _delay_response(svc: DelayAnalysisService, analysis) -> DelayAnalysisResponse:
    resp = DelayAnalysisResponse.model_validate(analysis)
    ev_resps: list[DelayEventResponse] = []
    for ev in await svc.list_events(analysis.id):
        ev_resp = DelayEventResponse.model_validate(ev)
        ev_resp.fragnets = [FragnetResponse.model_validate(f) for f in await svc.list_fragnets(ev.id)]
        ev_resps.append(ev_resp)
    resp.events = ev_resps
    resp.windows = [DelayWindowResponse.model_validate(w) for w in await svc.list_windows(analysis.id)]
    return resp


@router.post("/delay-analyses", response_model=DelayAnalysisResponse, status_code=status.HTTP_201_CREATED)
async def create_delay_analysis(
    data: DelayAnalysisCreate,
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.create")),
) -> DelayAnalysisResponse:
    """Create a draft forensic delay analysis under ``project_id``."""
    await verify_project_access(project_id, user_id, session)
    if data.schedule_id is not None:
        # Anti-IDOR: the targeted schedule must belong to this project. Without
        # this check a caller could point schedule_id at another tenant's
        # schedule and have /compute and /auto-fragnet read its activities and
        # relationships. 404 (not 403) so it cannot be used as an existence
        # oracle, matching verify_project_access's convention.
        if await _project_id_for_schedule(data.schedule_id, session) != project_id:
            raise _not_found("Schedule not found")
    svc = _get_delay_service(session)
    analysis = await svc.create_analysis(project_id, data, user_id)
    return await _delay_response(svc, analysis)


@router.get("/delay-analyses", response_model=list[DelayAnalysisListItem])
async def list_delay_analyses(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> list[DelayAnalysisListItem]:
    """List the delay analyses for a project."""
    await verify_project_access(project_id, user_id, session)
    svc = _get_delay_service(session)
    return [DelayAnalysisListItem.model_validate(a) for a in await svc.list_analyses(project_id)]


@router.get("/delay-analyses/{analysis_id}", response_model=DelayAnalysisResponse)
async def get_delay_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.read")),
) -> DelayAnalysisResponse:
    """Fetch an analysis with its events, fragnets, windows and result."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    return await _delay_response(svc, analysis)


@router.patch("/delay-analyses/{analysis_id}", response_model=DelayAnalysisResponse)
async def patch_delay_analysis(
    analysis_id: uuid.UUID,
    data: DelayAnalysisPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> DelayAnalysisResponse:
    """Edit a draft analysis (only a draft is mutable)."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    _assert_draft(analysis)
    await svc.patch_analysis(analysis, data)
    return await _delay_response(svc, analysis)


@router.delete("/delay-analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_delay_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.delete")),
) -> None:
    """Delete a draft analysis (issued analyses are immutable)."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    if analysis.status == "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An issued analysis cannot be deleted.")
    await svc.refuse_if_eot_claim_raised(analysis, doing="be deleted")
    await svc.delete_analysis(analysis)


@router.post(
    "/delay-analyses/{analysis_id}/events",
    response_model=DelayEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_delay_event(
    analysis_id: uuid.UUID,
    data: DelayEventCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> DelayEventResponse:
    """Add a causative event to a draft analysis."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    _assert_draft(analysis)
    event = await svc.add_event(analysis.id, data)
    return DelayEventResponse.model_validate(event)


@router.patch("/delay-analyses/{analysis_id}/events/{event_id}", response_model=DelayEventResponse)
async def patch_delay_event(
    analysis_id: uuid.UUID,
    event_id: uuid.UUID,
    data: DelayEventPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> DelayEventResponse:
    """Edit an event on a draft analysis."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    _assert_draft(analysis)
    event = await svc.get_event(event_id)
    if event is None or event.analysis_id != analysis.id:
        raise _not_found("Delay event not found")
    await svc.patch_event(event, data)
    ev_resp = DelayEventResponse.model_validate(event)
    ev_resp.fragnets = [FragnetResponse.model_validate(f) for f in await svc.list_fragnets(event.id)]
    return ev_resp


@router.delete(
    "/delay-analyses/{analysis_id}/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_delay_event(
    analysis_id: uuid.UUID,
    event_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> None:
    """Delete an event (and its fragnet) from a draft analysis."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    _assert_draft(analysis)
    event = await svc.get_event(event_id)
    if event is None or event.analysis_id != analysis.id:
        raise _not_found("Delay event not found")
    await svc.delete_event(event)


@router.put("/delay-analyses/{analysis_id}/events/{event_id}/fragnet", response_model=FragnetResponse)
async def set_delay_fragnet(
    analysis_id: uuid.UUID,
    event_id: uuid.UUID,
    data: FragnetUpsert,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> FragnetResponse:
    """Define (replace) the fragnet for an event on a draft analysis."""
    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    _assert_draft(analysis)
    event = await svc.get_event(event_id)
    if event is None or event.analysis_id != analysis.id:
        raise _not_found("Delay event not found")
    frag = await svc.set_fragnet(event.id, data)
    return FragnetResponse.model_validate(frag)


@router.post("/delay-analyses/{analysis_id}/auto-fragnet", response_model=FragnetResponse)
async def auto_delay_fragnet(
    analysis_id: uuid.UUID,
    data: AutoFragnetRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> FragnetResponse:
    """Wizard helper: synthesise a default fragnet and attach it to an event."""
    from app.modules.schedule_advanced.delay_engine import auto_fragnet as _auto_fragnet

    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    _assert_draft(analysis)
    event = await svc.get_event(data.delay_event_id)
    if event is None or event.analysis_id != analysis.id:
        raise _not_found("Delay event not found")
    if analysis.schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis has no schedule to synthesise a fragnet against.",
        )
    act_rows, rel_rows = await _load_schedule_rows(analysis.schedule_id, session)
    network = _build_str_network(act_rows, rel_rows)
    frag = _auto_fragnet(network, data.insert_at_activity_ref, data.insert_mode, data.added_days)
    upsert = FragnetUpsert(
        insert_mode=frag.insert_mode,
        insert_at_activity_ref=str(frag.host_id),
        added_duration_days=frag.added_duration_days,
        fragnet_activities=list(frag.new_activities),
        rewires=[
            {
                "successor_id": rw.successor_id,
                "pred_id": rw.pred_id,
                "op": rw.op,
                "dep_type": rw.dep_type,
                "lag": rw.lag,
            }
            for rw in frag.rewires
        ],
    )
    saved = await svc.set_fragnet(event.id, upsert)
    return FragnetResponse.model_validate(saved)


@router.post("/delay-analyses/{analysis_id}/compute", response_model=DelayAnalysisResponse)
async def compute_delay_analysis(
    analysis_id: uuid.UUID,
    data: DelayComputeRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> DelayAnalysisResponse:
    """Run the analysis method, persist the windows + totals + exhibit result."""
    from app.modules.schedule_advanced.cpm import CycleError
    from app.modules.schedule_advanced.delay_report import run_analysis

    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    if analysis.status == "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An issued analysis is immutable.")
    if analysis.schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis has no schedule to compute against.",
        )
    act_rows, rel_rows = await _load_schedule_rows(analysis.schedule_id, session)
    if not act_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Schedule has no activities to analyse.",
        )
    network = _build_str_network(act_rows, rel_rows)
    baseline = network.activities
    event_specs = await svc.build_event_specs(analysis.id)
    apportionment = data.apportionment_method or analysis.apportionment_method
    try:
        result = run_analysis(
            analysis.method,
            baseline_activities=baseline,
            asbuilt_activities=baseline,
            events=event_specs,
            apportionment=apportionment,
            snapshots=[baseline, baseline],
        )
    except CycleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await svc.persist_compute(analysis, result)
    return await _delay_response(svc, analysis)


@router.post("/delay-analyses/{analysis_id}/issue", response_model=DelayAnalysisResponse)
async def issue_delay_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> DelayAnalysisResponse:
    """Freeze + e-sign a computed analysis (issued analyses are immutable)."""
    from datetime import UTC, datetime

    from app.modules.construction_control.signing import snapshot_sha256

    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    if analysis.status == "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Analysis already issued.")
    if analysis.status != "computed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a computed analysis can be issued.",
        )
    snapshot = {
        "id": str(analysis.id),
        "project_id": str(analysis.project_id),
        "method": analysis.method,
        "name": analysis.name,
        "total_entitlement_days": analysis.total_entitlement_days,
        "result_json": analysis.result_json,
    }
    sha = snapshot_sha256(snapshot)
    await svc.issue(
        analysis,
        user_id=user_id,
        signature_sha256=sha,
        signature_snapshot=snapshot,
        issued_at=datetime.now(UTC).isoformat(),
    )
    return await _delay_response(svc, analysis)


@router.post("/delay-analyses/{analysis_id}/raise-eot-claim", response_model=RaiseEotClaimResponse)
async def raise_eot_claim(
    analysis_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule_advanced.update")),
) -> RaiseEotClaimResponse:
    """Create an Extension-of-Time claim pre-filled from a computed analysis."""
    from datetime import UTC, datetime

    from app.modules.variations.models import ExtensionOfTimeClaim

    svc = _get_delay_service(session)
    analysis = await _load_delay_analysis(analysis_id, svc, user_id, session)
    if analysis.status not in ("computed", "issued"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Compute the analysis before raising an EOT claim.",
        )
    await svc.refuse_if_eot_claim_raised(analysis, doing="raise another")
    claim = ExtensionOfTimeClaim(
        project_id=analysis.project_id,
        raised_at=datetime.now(UTC).isoformat(),
        raised_by=str(user_id) if user_id is not None else None,
        description=f"Raised from forensic delay analysis '{analysis.name}' ({analysis.method}).",
        root_cause_category="employer",
        requested_days=analysis.total_entitlement_days,
        critical_path_impact=bool(analysis.total_entitlement_days > 0),
        status="draft",
        tia_delta_days=analysis.total_entitlement_days,
        tia_computed_at=datetime.now(UTC).isoformat(),
        delay_analysis_id=analysis.id,
    )
    session.add(claim)
    await session.flush()
    await svc.set_eot_claim(analysis, claim.id)
    return RaiseEotClaimResponse(
        eot_claim_id=claim.id,
        delay_analysis_id=analysis.id,
        requested_days=analysis.total_entitlement_days,
    )
