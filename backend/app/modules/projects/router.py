"""Projects API routes.

Endpoints:
    POST /                   — Create project (auth required)
    GET  /                   — List my projects (auth required)
    GET  /{project_id}       — Get project (auth required)
    PATCH /{project_id}      — Update project (auth required)
    DELETE /{project_id}     — Archive project (auth required)
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, CurrentUserPayload, SessionDep, SettingsDep
from app.modules.projects.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from app.modules.projects.service import ProjectService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep, settings: SettingsDep) -> ProjectService:
    return ProjectService(session, settings)


async def _verify_project_owner(
    service: ProjectService,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> object:
    """Load a project and verify the current user is the owner.

    Admins (role=admin in JWT payload) bypass the ownership check.
    Returns the project object on success, raises 403 if not owner.
    """
    project = await service.get_project(project_id)
    # Admin bypass
    if payload and payload.get("role") == "admin":
        return project
    if str(project.owner_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )
    return project


# ── Create ────────────────────────────────────────────────────────────────


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    user_id: CurrentUserId,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Create a new project."""
    try:
        project = await service.create_project(data, uuid.UUID(user_id))
        return ProjectResponse.model_validate(project)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create project")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project",
        )


# ── List ──────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status: str | None = Query(default=None, pattern=r"^(active|archived|template)$"),
) -> list[ProjectResponse]:
    """List projects. Admins see all, others see only own projects."""
    is_admin = payload.get("role") == "admin"
    projects, _ = await service.list_projects(
        uuid.UUID(user_id),
        offset=offset,
        limit=limit,
        status_filter=status,
        is_admin=is_admin,
    )
    return [ProjectResponse.model_validate(p) for p in projects]


# ── Get ───────────────────────────────────────────────────────────────────


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Get project by ID. Verifies ownership."""
    project = await _verify_project_owner(service, project_id, user_id, payload)
    return ProjectResponse.model_validate(project)


# ── Update ────────────────────────────────────────────────────────────────


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Update project fields. Verifies ownership."""
    await _verify_project_owner(service, project_id, user_id, payload)
    project = await service.update_project(project_id, data)
    return ProjectResponse.model_validate(project)


# ── Delete (archive) ─────────────────────────────────────────────────────


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Archive a project (soft delete). Verifies ownership."""
    import logging as _log
    try:
        await _verify_project_owner(service, project_id, user_id, payload)
        await service.delete_project(project_id)
    except HTTPException:
        raise
    except Exception as exc:
        _log.getLogger(__name__).exception("Failed to archive project %s", project_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Project Dashboard (cross-module aggregation) ───────────────────────


@router.get("/{project_id}/dashboard")
async def project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> dict:
    """Cross-module dashboard — aggregated KPIs for a single project.

    Queries every module (BOQ, requirements, markups, punch list,
    field reports, photos, measurements, documents, schedule, risk,
    change orders) in one API call to give a full project overview.
    """
    from datetime import date, timedelta

    from sqlalchemy import Float, func, select
    from sqlalchemy.sql.expression import cast

    from app.modules.boq.models import BOQ, BOQMarkup, Position
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.documents.models import Document, ProjectPhoto
    from app.modules.fieldreports.models import FieldReport
    from app.modules.markups.models import Markup
    from app.modules.punchlist.models import PunchItem
    from app.modules.requirements.models import Requirement, RequirementSet
    from app.modules.risk.models import RiskItem
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.takeoff.models import TakeoffMeasurement

    # Verify ownership / admin access
    await _verify_project_owner(service, project_id, user_id, payload)

    # ── BOQ ──────────────────────────────────────────────────────────
    boq_count = (
        await session.execute(
            select(func.count(BOQ.id)).where(BOQ.project_id == project_id)
        )
    ).scalar_one()

    boq_ids_result = await session.execute(
        select(BOQ.id).where(BOQ.project_id == project_id)
    )
    boq_ids = [row[0] for row in boq_ids_result.all()]

    position_count = 0
    boq_total_value = 0.0
    markups_from_boq = 0
    if boq_ids:
        position_count = (
            await session.execute(
                select(func.count(Position.id)).where(Position.boq_id.in_(boq_ids))
            )
        ).scalar_one()

        total_result = (
            await session.execute(
                select(func.sum(cast(Position.total, Float))).where(
                    Position.boq_id.in_(boq_ids)
                )
            )
        ).scalar_one()
        boq_total_value = round(total_result or 0.0, 2)

        markups_from_boq = (
            await session.execute(
                select(func.count(BOQMarkup.id)).where(
                    BOQMarkup.boq_id.in_(boq_ids)
                )
            )
        ).scalar_one()

    # ── Requirements ─────────────────────────────────────────────────
    requirement_sets = (
        await session.execute(
            select(func.count(RequirementSet.id)).where(
                RequirementSet.project_id == project_id
            )
        )
    ).scalar_one()

    req_set_ids_result = await session.execute(
        select(RequirementSet.id).where(RequirementSet.project_id == project_id)
    )
    req_set_ids = [row[0] for row in req_set_ids_result.all()]

    requirements_total = 0
    requirements_coverage = 0
    if req_set_ids:
        requirements_total = (
            await session.execute(
                select(func.count(Requirement.id)).where(
                    Requirement.requirement_set_id.in_(req_set_ids)
                )
            )
        ).scalar_one()

        linked_count = (
            await session.execute(
                select(func.count(Requirement.id)).where(
                    Requirement.requirement_set_id.in_(req_set_ids),
                    Requirement.linked_position_id.isnot(None),
                )
            )
        ).scalar_one()
        requirements_coverage = (
            round(linked_count / requirements_total * 100)
            if requirements_total > 0
            else 0
        )

    # ── Markups (drawing annotations) ────────────────────────────────
    markups_count = (
        await session.execute(
            select(func.count(Markup.id)).where(Markup.project_id == project_id)
        )
    ).scalar_one()

    # ── Punch List ───────────────────────────────────────────────────
    punch_rows = (
        await session.execute(
            select(PunchItem.status, func.count(PunchItem.id))
            .where(PunchItem.project_id == project_id)
            .group_by(PunchItem.status)
        )
    ).all()
    punch_items = {
        "open": 0,
        "in_progress": 0,
        "resolved": 0,
        "verified": 0,
        "closed": 0,
    }
    for row_status, cnt in punch_rows:
        if row_status in punch_items:
            punch_items[row_status] = cnt

    # ── Field Reports ────────────────────────────────────────────────
    field_reports_total = (
        await session.execute(
            select(func.count(FieldReport.id)).where(
                FieldReport.project_id == project_id
            )
        )
    ).scalar_one()

    week_ago = date.today() - timedelta(days=7)
    field_reports_this_week = (
        await session.execute(
            select(func.count(FieldReport.id)).where(
                FieldReport.project_id == project_id,
                FieldReport.report_date >= week_ago,
            )
        )
    ).scalar_one()

    # ── Photos ───────────────────────────────────────────────────────
    photos_count = (
        await session.execute(
            select(func.count(ProjectPhoto.id)).where(
                ProjectPhoto.project_id == project_id
            )
        )
    ).scalar_one()

    # ── Measurements ─────────────────────────────────────────────────
    measurements_count = (
        await session.execute(
            select(func.count(TakeoffMeasurement.id)).where(
                TakeoffMeasurement.project_id == project_id
            )
        )
    ).scalar_one()

    # ── Documents ────────────────────────────────────────────────────
    documents_count = (
        await session.execute(
            select(func.count(Document.id)).where(
                Document.project_id == project_id
            )
        )
    ).scalar_one()

    # ── Schedule ─────────────────────────────────────────────────────
    sched_ids_result = await session.execute(
        select(Schedule.id).where(Schedule.project_id == project_id)
    )
    sched_ids = [row[0] for row in sched_ids_result.all()]

    schedule_activities = 0
    if sched_ids:
        schedule_activities = (
            await session.execute(
                select(func.count(Activity.id)).where(
                    Activity.schedule_id.in_(sched_ids)
                )
            )
        ).scalar_one()

    # ── Risk ─────────────────────────────────────────────────────────
    risk_total = (
        await session.execute(
            select(func.count(RiskItem.id)).where(
                RiskItem.project_id == project_id
            )
        )
    ).scalar_one()

    risk_high = (
        await session.execute(
            select(func.count(RiskItem.id)).where(
                RiskItem.project_id == project_id,
                RiskItem.impact_severity == "high",
            )
        )
    ).scalar_one()

    # ── Change Orders ────────────────────────────────────────────────
    co_total = (
        await session.execute(
            select(func.count(ChangeOrder.id)).where(
                ChangeOrder.project_id == project_id
            )
        )
    ).scalar_one()

    co_approved = (
        await session.execute(
            select(func.count(ChangeOrder.id)).where(
                ChangeOrder.project_id == project_id,
                ChangeOrder.status == "approved",
            )
        )
    ).scalar_one()

    return {
        "project_id": str(project_id),
        "boq_count": boq_count,
        "boq_total_value": boq_total_value,
        "position_count": position_count,
        "requirement_sets": requirement_sets,
        "requirements_total": requirements_total,
        "requirements_coverage": requirements_coverage,
        "markups_count": markups_count + markups_from_boq,
        "punch_items": punch_items,
        "field_reports": {
            "total": field_reports_total,
            "this_week": field_reports_this_week,
        },
        "photos_count": photos_count,
        "measurements_count": measurements_count,
        "documents_count": documents_count,
        "schedule_activities": schedule_activities,
        "risks": {"total": risk_total, "high": risk_high},
        "change_orders": {"total": co_total, "approved": co_approved},
    }


# ── Cross-Project Analytics ─────────────────────────────────────────────


@router.get("/analytics/overview")
async def analytics_overview(
    session: SessionDep,
    _user_id: CurrentUserId,
) -> dict:
    """Cross-project analytics — aggregated KPIs across all projects."""
    from sqlalchemy import Float, func, select
    from sqlalchemy.sql.expression import cast

    from app.modules.boq.models import BOQ
    from app.modules.costmodel.models import BudgetLine
    from app.modules.projects.models import Project

    # Count projects
    proj_count = (await session.execute(select(func.count(Project.id)))).scalar_one()

    # Total budget across all projects
    budget_stmt = select(
        BudgetLine.project_id,
        func.sum(cast(BudgetLine.planned_amount, Float)).label("planned"),
        func.sum(cast(BudgetLine.actual_amount, Float)).label("actual"),
    ).group_by(BudgetLine.project_id)
    budget_result = await session.execute(budget_stmt)
    budget_rows = budget_result.all()

    total_planned = sum(r.planned or 0 for r in budget_rows)
    total_actual = sum(r.actual or 0 for r in budget_rows)

    # Projects with budget
    projects_with_budget = len(budget_rows)

    # Per-project summary
    projects_data = []
    proj_stmt = select(Project).order_by(Project.name)
    proj_result = await session.execute(proj_stmt)
    all_projects = proj_result.scalars().all()

    for p in all_projects:
        pid = str(p.id)
        pname = p.name
        pregion = p.region
        pcurrency = p.currency

        # Find budget for this project
        budget_row = next((r for r in budget_rows if str(r.project_id) == pid), None)
        planned = float(budget_row.planned or 0) if budget_row else 0
        actual = float(budget_row.actual or 0) if budget_row else 0
        variance = planned - actual if planned > 0 else 0
        variance_pct = round((variance / planned * 100), 1) if planned > 0 else 0

        # BOQ count
        boq_count_stmt = select(func.count(BOQ.id)).where(BOQ.project_id == p.id)
        boq_count = (await session.execute(boq_count_stmt)).scalar_one()

        projects_data.append(
            {
                "id": pid,
                "name": pname,
                "region": pregion,
                "currency": pcurrency,
                "budget": round(planned, 2),
                "actual": round(actual, 2),
                "variance": round(variance, 2),
                "variance_pct": variance_pct,
                "boq_count": boq_count,
                "status": "on_budget" if variance >= 0 else "over_budget",
            }
        )

    # Aggregate
    over_budget_count = sum(1 for p in projects_data if p["status"] == "over_budget")

    return {
        "total_projects": proj_count,
        "projects_with_budget": projects_with_budget,
        "total_planned": round(total_planned, 2),
        "total_actual": round(total_actual, 2),
        "total_variance": round(total_planned - total_actual, 2),
        "over_budget_count": over_budget_count,
        "projects": projects_data,
    }
