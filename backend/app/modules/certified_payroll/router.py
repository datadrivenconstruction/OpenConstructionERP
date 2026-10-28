# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Certified payroll API routes (mounted at ``/api/v1/certified_payroll``).

Endpoints (all manager-scoped and project-access checked):

    Wage determinations
    POST   /projects/{project_id}/determinations/           - record one
    GET    /projects/{project_id}/determinations/           - list them
    GET    /determinations/{determination_id}                - one with its crafts
    PATCH  /determinations/{determination_id}                - edit an unlocked one
    DELETE /determinations/{determination_id}                - remove an unlocked one
    POST   /determinations/{determination_id}/classifications/ - add a craft

    Worker classification
    POST   /projects/{project_id}/assignments/              - classify a worker
    GET    /projects/{project_id}/assignments/              - list them
    PATCH  /assignments/{assignment_id}                      - edit one
    DELETE /assignments/{assignment_id}                      - remove one

    Weekly payroll
    POST   /projects/{project_id}/weeks/                    - open a draft week
    GET    /projects/{project_id}/weeks/                    - list weeks
    GET    /weeks/{week_id}                                  - week with its lines
    PATCH  /weeks/{week_id}                                  - edit a draft week
    DELETE /weeks/{week_id}                                  - remove a draft week
    GET    /weeks/{week_id}/validate/                        - run the compliance rules
    POST   /weeks/{week_id}/certify/                         - sign and freeze
    GET    /weeks/{week_id}/form.json                        - the weekly form
    GET    /weeks/{week_id}/form.csv                         - the weekly form as CSV
"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.certified_payroll.schemas import (
    AssignmentCreate,
    AssignmentResponse,
    AssignmentUpdate,
    CertifiedLineResponse,
    CertifiedWeekCreate,
    CertifiedWeekDetailResponse,
    CertifiedWeekResponse,
    CertifiedWeekUpdate,
    CertifyRequest,
    ValidationFindingResponse,
    WageClassificationCreate,
    WageClassificationResponse,
    WageDeterminationCreate,
    WageDeterminationResponse,
    WageDeterminationUpdate,
    WeekValidationResponse,
)
from app.modules.certified_payroll.service import CertifiedPayrollService
from app.modules.certified_payroll.wh347 import render_csv

router = APIRouter(tags=["certified_payroll"])


def _get_service(session: SessionDep) -> CertifiedPayrollService:
    return CertifiedPayrollService(session)


# ── Wage determinations ─────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/determinations/",
    response_model=WageDeterminationResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def create_determination(
    project_id: uuid.UUID,
    data: WageDeterminationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> WageDeterminationResponse:
    """Record a wage determination the awarding body issued for this contract."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    determination = await service.create_determination(project_id, data)
    return WageDeterminationResponse.model_validate(determination)


@router.get(
    "/projects/{project_id}/determinations/",
    response_model=list[WageDeterminationResponse],
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def list_determinations(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[WageDeterminationResponse]:
    """List the wage determinations on file for a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    determinations, _total = await service.determination_repo.list_for_project(project_id, offset=offset, limit=limit)
    return [WageDeterminationResponse.model_validate(d) for d in determinations]


@router.get(
    "/determinations/{determination_id}",
    response_model=WageDeterminationResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def get_determination(
    determination_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> WageDeterminationResponse:
    """One determination with the craft lines it fixes rates for."""
    service = _get_service(session)
    determination = await service.get_determination(determination_id)
    await verify_project_access(determination.project_id, user_id, session)
    return WageDeterminationResponse.model_validate(determination)


@router.patch(
    "/determinations/{determination_id}",
    response_model=WageDeterminationResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def update_determination(
    determination_id: uuid.UUID,
    data: WageDeterminationUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> WageDeterminationResponse:
    """Edit a determination that no certified payroll rests on yet."""
    service = _get_service(session)
    existing = await service.get_determination(determination_id)
    await verify_project_access(existing.project_id, user_id, session)
    determination = await service.update_determination(determination_id, data)
    return WageDeterminationResponse.model_validate(determination)


@router.delete(
    "/determinations/{determination_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def delete_determination(
    determination_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Remove a determination that no certified payroll rests on."""
    service = _get_service(session)
    existing = await service.get_determination(determination_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_determination(determination_id)


@router.post(
    "/determinations/{determination_id}/classifications/",
    response_model=WageClassificationResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def add_classification(
    determination_id: uuid.UUID,
    data: WageClassificationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> WageClassificationResponse:
    """Add a craft to a determination, with its basic and fringe rates apart."""
    service = _get_service(session)
    existing = await service.get_determination(determination_id)
    await verify_project_access(existing.project_id, user_id, session)
    classification = await service.add_classification(determination_id, data)
    return WageClassificationResponse.model_validate(classification)


# ── Worker classification ───────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/assignments/",
    response_model=AssignmentResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def create_assignment(
    project_id: uuid.UUID,
    data: AssignmentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> AssignmentResponse:
    """Put a worker under the trade classification they work in."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    assignment = await service.create_assignment(project_id, data)
    return AssignmentResponse.model_validate(assignment)


@router.get(
    "/projects/{project_id}/assignments/",
    response_model=list[AssignmentResponse],
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def list_assignments(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> list[AssignmentResponse]:
    """List which classification each worker on the project works under."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    assignments, _total = await service.assignment_repo.list_for_project(project_id, offset=offset, limit=limit)
    return [AssignmentResponse.model_validate(a) for a in assignments]


@router.patch(
    "/assignments/{assignment_id}",
    response_model=AssignmentResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def update_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> AssignmentResponse:
    """Change a worker's classification or the split of what they are paid."""
    service = _get_service(session)
    existing = await service.assignment_repo.get_by_id(assignment_id)
    if existing is not None:
        await verify_project_access(existing.project_id, user_id, session)
    assignment = await service.update_assignment(assignment_id, data)
    return AssignmentResponse.model_validate(assignment)


@router.delete(
    "/assignments/{assignment_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Remove a worker's classification assignment."""
    service = _get_service(session)
    existing = await service.assignment_repo.get_by_id(assignment_id)
    if existing is not None:
        await verify_project_access(existing.project_id, user_id, session)
    await service.delete_assignment(assignment_id)


# ── Weekly payroll ──────────────────────────────────────────────────────────


async def _build_detail(
    week,  # noqa: ANN001 - CertifiedPayrollWeek, kept untyped to avoid a circular import
    service: CertifiedPayrollService,
) -> CertifiedWeekDetailResponse:
    """Assemble a week response with its lines, derived or frozen."""
    lines, derived = await service.week_lines(week)
    detail = CertifiedWeekDetailResponse.model_validate(week)
    detail.lines = [CertifiedLineResponse.model_validate(line) for line in lines]
    detail.lines_are_derived = derived
    return detail


@router.post(
    "/projects/{project_id}/weeks/",
    response_model=CertifiedWeekDetailResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def create_week(
    project_id: uuid.UUID,
    data: CertifiedWeekCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CertifiedWeekDetailResponse:
    """Open a draft certified payroll week. Its lines come from the payroll."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    week = await service.create_week(project_id, data, user_id=user_id)
    return await _build_detail(week, service)


@router.get(
    "/projects/{project_id}/weeks/",
    response_model=list[CertifiedWeekResponse],
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def list_weeks(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CertifiedWeekResponse]:
    """List the certified payroll weeks for a project, newest week first."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    weeks, _total = await service.week_repo.list_for_project(project_id, offset=offset, limit=limit)
    return [CertifiedWeekResponse.model_validate(w) for w in weeks]


@router.get(
    "/weeks/{week_id}",
    response_model=CertifiedWeekDetailResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def get_week(
    week_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CertifiedWeekDetailResponse:
    """One week with its lines: derived while draft, frozen once certified."""
    service = _get_service(session)
    week = await service.get_week(week_id)
    await verify_project_access(week.project_id, user_id, session)
    return await _build_detail(week, service)


@router.patch(
    "/weeks/{week_id}",
    response_model=CertifiedWeekDetailResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def update_week(
    week_id: uuid.UUID,
    data: CertifiedWeekUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CertifiedWeekDetailResponse:
    """Edit a draft week. A certified week refuses every change."""
    service = _get_service(session)
    existing = await service.get_week(week_id)
    await verify_project_access(existing.project_id, user_id, session)
    week = await service.update_week(week_id, data)
    return await _build_detail(week, service)


@router.delete(
    "/weeks/{week_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("certified_payroll.manage"))],
)
async def delete_week(
    week_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Remove a draft week. A certified week cannot be deleted."""
    service = _get_service(session)
    existing = await service.get_week(week_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_week(week_id)


@router.get(
    "/weeks/{week_id}/validate/",
    response_model=WeekValidationResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def validate_week(
    week_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> WeekValidationResponse:
    """Run the compliance rules over a week and report what they found."""
    service = _get_service(session)
    week = await service.get_week(week_id)
    await verify_project_access(week.project_id, user_id, session)
    findings = await service.validate_week(week)
    failures = [f for f in findings if not f.passed]
    errors = [f for f in failures if str(f.severity) == "error"]
    warnings = [f for f in failures if str(f.severity) == "warning"]
    return WeekValidationResponse(
        week_id=week.id,
        status="errors" if errors else ("warnings" if warnings else "passed"),
        error_count=len(errors),
        warning_count=len(warnings),
        can_certify=not errors and week.status == "draft",
        findings=[
            ValidationFindingResponse(
                rule_id=f.rule_id,
                rule_name=f.rule_name,
                severity=str(f.severity),
                category=str(f.category),
                passed=f.passed,
                message=f.message,
                element_ref=f.element_ref,
                suggestion=f.suggestion,
                details=f.details or {},
            )
            for f in findings
        ],
    )


@router.post(
    "/weeks/{week_id}/certify/",
    response_model=CertifiedWeekDetailResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.certify"))],
)
async def certify_week(
    week_id: uuid.UUID,
    data: CertifyRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CertifiedWeekDetailResponse:
    """Sign the statement of compliance and freeze the week's rows."""
    service = _get_service(session)
    existing = await service.get_week(week_id)
    await verify_project_access(existing.project_id, user_id, session)
    week = await service.certify_week(week_id, data, user_id=user_id)
    return await _build_detail(week, service)


@router.get(
    "/weeks/{week_id}/form.json",
    response_model=None,
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def week_form_json(
    week_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict:
    """The week rendered as the standard weekly payroll form payload."""
    service = _get_service(session)
    week = await service.get_week(week_id)
    await verify_project_access(week.project_id, user_id, session)
    return await service.render_week_form(week)


@router.get(
    "/weeks/{week_id}/form.csv",
    response_class=StreamingResponse,
    dependencies=[Depends(RequirePermission("certified_payroll.read"))],
)
async def week_form_csv(
    week_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> StreamingResponse:
    """The same form as CSV, one row per worker with two columns per day."""
    service = _get_service(session)
    week = await service.get_week(week_id)
    await verify_project_access(week.project_id, user_id, session)
    form = await service.render_week_form(week)
    filename = f"certified-payroll-{week.week_ending or 'week'}.csv"
    return StreamingResponse(
        iter([render_csv(form)]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
