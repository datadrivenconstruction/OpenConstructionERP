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
from app.modules.projects.schemas import (
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    WBSCreate,
    WBSResponse,
    WBSUpdate,
)
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


@router.post(
    "/",
    response_model=ProjectResponse,
    status_code=201,
    summary="Create project",
    description="Create a new construction project. Sets the current user as owner. "
    "Configure region, classification standard, and currency for the project context.",
)
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


@router.get(
    "/",
    response_model=list[ProjectResponse],
    summary="List projects",
    description="List projects visible to the current user. Admins see all projects; "
    "regular users see only their own. Supports pagination and status filter.",
)
async def list_projects(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    # Raised cap from 100 → 500 so the Header project switcher can fetch
    # the full list in one call (it calls ``limit=500``). Prior cap caused
    # a 422 that silently wiped the projects dropdown across every page.
    limit: int = Query(default=50, ge=1, le=500),
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


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project",
    description="Retrieve a single project by its UUID. Verifies ownership or admin role.",
)
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


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
    description="Partially update project fields (name, description, region, currency, etc.). "
    "Only provided fields are modified. Verifies ownership.",
)
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


@router.delete(
    "/{project_id}/",
    status_code=204,
    summary="Archive project",
    description="Soft-delete (archive) a project. The project and its data are retained "
    "but hidden from default queries. Use POST /{project_id}/restore to un-archive.",
)
@router.delete(
    "/{project_id}",
    status_code=204,
    include_in_schema=False,
)
async def delete_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Archive a project (soft delete) and cascade-archive child records.

    Verifies ownership. Marks the project and all its child tasks, RFIs,
    and other linked entities as archived/inactive so they no longer appear
    in default queries.
    """
    import logging as _log

    try:
        await _verify_project_owner(service, project_id, user_id, payload)
        await service.delete_project(project_id)
    except HTTPException:
        raise
    except Exception as exc:
        _log.getLogger(__name__).exception("Failed to archive project %s", project_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Restore (un-archive) ────────────────────────────────────────────────


@router.post(
    "/{project_id}/restore/",
    response_model=ProjectResponse,
    summary="Restore archived project",
    description="Restore an archived project back to active status. "
    "Only the project owner or admin can restore.",
)
async def restore_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Restore an archived project back to active status.

    Only the project owner or admin can restore. Returns the restored project.
    """
    # Use include_archived=True so we can find the archived project
    project = await service.get_project(project_id, include_archived=True)
    is_admin = bool(payload and payload.get("role") == "admin")
    if not is_admin and str(project.owner_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )
    restored = await service.restore_project(project_id)
    return ProjectResponse.model_validate(restored)


# ── Project Dashboard (cross-module aggregation) ───────────────────────


@router.get(
    "/{project_id}/dashboard/",
    summary="Get project dashboard",
    description="Unified project dashboard with aggregated KPIs from all modules: "
    "budget, schedule, quality (punch items, inspections, NCRs), documents, "
    "communication (RFIs, submittals, tasks), procurement, and recent activity. "
    "Each module section degrades gracefully if its table does not exist.",
)
async def project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> dict:
    """Unified project dashboard ─ aggregated KPIs from all modules.

    Returns a comprehensive overview including budget, schedule, quality,
    documents, communication (RFIs / submittals / tasks), procurement,
    and recent activity.  Each module section is wrapped in try/except
    for graceful degradation if a module table does not exist yet.
    """
    from datetime import date, datetime, timedelta

    from sqlalchemy import Float, func, literal_column, select, union_all
    from sqlalchemy.sql.expression import cast

    # Verify ownership / admin access
    project = await _verify_project_owner(service, project_id, user_id, payload)

    # ── Helper: safe query wrapper ──────────────────────────────
    async def _safe(coro, default=None):  # noqa: ANN001, ANN202
        try:
            return await coro
        except Exception:
            logger.debug("Dashboard query failed (module table may not exist)", exc_info=True)
            return default

    # ── Project header ───────────────────────────────────────────────────────
    project_info = {
        "id": str(project_id),
        "name": project.name,
        "status": project.status,
        "phase": getattr(project, "phase", None),
        "currency": project.currency,
    }

    # ── BOQ / Budget ─────────────────────────────────────────────────────────
    budget_section: dict = {
        "original": "0",
        "revised": "0",
        "committed": "0",
        "actual": "0",
        "forecast": "0",
        "consumed_pct": "0",
        "warning_level": "normal",
    }
    boq_count = 0
    position_count = 0
    boq_total_value = 0.0
    boq_ids: list = []
    markups_from_boq = 0

    try:
        from app.modules.boq.models import BOQ, BOQMarkup, Position

        boq_count = (await session.execute(select(func.count(BOQ.id)).where(BOQ.project_id == project_id))).scalar_one()

        boq_ids_result = await session.execute(select(BOQ.id).where(BOQ.project_id == project_id))
        boq_ids = [row[0] for row in boq_ids_result.all()]

        if boq_ids:
            position_count = (
                await session.execute(select(func.count(Position.id)).where(Position.boq_id.in_(boq_ids)))
            ).scalar_one()

            total_result = (
                await session.execute(select(func.sum(cast(Position.total, Float))).where(Position.boq_id.in_(boq_ids)))
            ).scalar_one()
            boq_total_value = round(total_result or 0.0, 2)

            markups_from_boq = (
                await session.execute(select(func.count(BOQMarkup.id)).where(BOQMarkup.boq_id.in_(boq_ids)))
            ).scalar_one()
    except Exception:
        logger.debug("BOQ query failed", exc_info=True)

    # Fetch 5D cost model budget data
    try:
        from app.modules.costmodel.models import BudgetLine

        budget_stmt = select(
            func.sum(cast(BudgetLine.planned_amount, Float)).label("planned"),
            func.sum(cast(BudgetLine.actual_amount, Float)).label("actual"),
        ).where(BudgetLine.project_id == project_id)
        budget_row = (await session.execute(budget_stmt)).one_or_none()
        planned_total = float(budget_row.planned or 0) if budget_row else 0.0
        actual_total = float(budget_row.actual or 0) if budget_row else 0.0

        original = boq_total_value if boq_total_value > 0 else planned_total
        revised = planned_total if planned_total > 0 else boq_total_value
        forecast = revised if revised > 0 else original

        budget_section = {
            "original": str(round(original, 2)),
            "revised": str(round(revised, 2)),
            "committed": str(round(actual_total * 0.8, 2)) if actual_total > 0 else "0",
            "actual": str(round(actual_total, 2)),
            "forecast": str(round(forecast, 2)),
            "consumed_pct": str(round(actual_total / revised * 100, 1) if revised > 0 else 0),
            "warning_level": (
                "critical"
                if revised > 0 and actual_total > revised
                else "warning"
                if revised > 0 and actual_total > revised * 0.9
                else "normal"
            ),
        }
    except Exception:
        if boq_total_value > 0:
            budget_section["original"] = str(boq_total_value)
            budget_section["revised"] = str(boq_total_value)
            budget_section["forecast"] = str(boq_total_value)

    # ── Schedule ───────────────────────────────────────────────────────────
    schedule_section: dict = {
        "total_activities": 0,
        "completed": 0,
        "in_progress": 0,
        "delayed": 0,
        "progress_pct": "0",
        "critical_activities": 0,
        "next_milestone": None,
    }

    try:
        from app.modules.schedule.models import Activity, Schedule

        sched_ids_result = await session.execute(select(Schedule.id).where(Schedule.project_id == project_id))
        sched_ids = [row[0] for row in sched_ids_result.all()]

        if sched_ids:
            activity_rows = (
                await session.execute(
                    select(Activity.status, func.count(Activity.id))
                    .where(Activity.schedule_id.in_(sched_ids))
                    .group_by(Activity.status)
                )
            ).all()
            status_map: dict[str, int] = {}
            total_acts = 0
            for act_status, cnt in activity_rows:
                status_map[act_status] = cnt
                total_acts += cnt

            completed = status_map.get("completed", 0) + status_map.get("complete", 0)
            in_prog = status_map.get("in_progress", 0)
            today_str = date.today().isoformat()

            delayed_result = await _safe(
                session.execute(
                    select(func.count(Activity.id)).where(
                        Activity.schedule_id.in_(sched_ids),
                        Activity.end_date < today_str,
                        Activity.status.notin_(["completed", "complete"]),
                    )
                ),
                None,
            )
            delayed = delayed_result.scalar_one() if delayed_result else 0

            critical_result = await _safe(
                session.execute(
                    select(func.count(Activity.id)).where(
                        Activity.schedule_id.in_(sched_ids),
                        Activity.is_critical.is_(True),
                    )
                ),
                None,
            )
            critical_count = critical_result.scalar_one() if critical_result else 0

            progress = round(completed / total_acts * 100, 1) if total_acts > 0 else 0

            schedule_section = {
                "total_activities": total_acts,
                "completed": completed,
                "in_progress": in_prog,
                "delayed": delayed,
                "progress_pct": str(progress),
                "critical_activities": critical_count,
                "next_milestone": None,
            }
    except Exception:
        logger.debug("Schedule query failed", exc_info=True)

    # Next milestone
    try:
        from app.modules.projects.models import ProjectMilestone

        today_str = date.today().isoformat()
        milestone_result = await session.execute(
            select(ProjectMilestone.name, ProjectMilestone.planned_date)
            .where(
                ProjectMilestone.project_id == project_id,
                ProjectMilestone.status.in_(["pending", "in_progress"]),
                ProjectMilestone.planned_date >= today_str,
            )
            .order_by(ProjectMilestone.planned_date)
            .limit(1)
        )
        ms_row = milestone_result.one_or_none()
        if ms_row:
            schedule_section["next_milestone"] = {"name": ms_row[0], "date": ms_row[1]}
    except Exception:
        logger.debug("Milestone query failed", exc_info=True)

    # ── Quality ────────────────────────────────────────────────────────────
    quality_section: dict = {
        "open_defects": 0,
        "open_observations": 0,
        "high_risk_observations": 0,
        "pending_inspections": 0,
        "ncrs_open": 0,
        "validation_score": "0",
    }

    punch_items: dict[str, int] = {
        "open": 0,
        "in_progress": 0,
        "resolved": 0,
        "verified": 0,
        "closed": 0,
    }
    try:
        from app.modules.punchlist.models import PunchItem

        punch_rows = (
            await session.execute(
                select(PunchItem.status, func.count(PunchItem.id))
                .where(PunchItem.project_id == project_id)
                .group_by(PunchItem.status)
            )
        ).all()
        for row_status, cnt in punch_rows:
            if row_status in punch_items:
                punch_items[row_status] = cnt
        quality_section["open_defects"] = punch_items["open"] + punch_items["in_progress"]
    except Exception:
        logger.debug("Dashboard: punch items query failed", exc_info=True)

    try:
        from app.modules.inspections.models import QualityInspection

        pending_insp = (
            await session.execute(
                select(func.count(QualityInspection.id)).where(
                    QualityInspection.project_id == project_id,
                    QualityInspection.status == "scheduled",
                )
            )
        ).scalar_one()
        quality_section["pending_inspections"] = pending_insp
    except Exception:
        logger.debug("Dashboard: inspections query failed", exc_info=True)

    try:
        from app.modules.ncr.models import NCR

        ncr_open = (
            await session.execute(
                select(func.count(NCR.id)).where(
                    NCR.project_id == project_id,
                    NCR.status.in_(["identified", "under_review", "in_progress"]),
                )
            )
        ).scalar_one()
        quality_section["ncrs_open"] = ncr_open
    except Exception:
        logger.debug("Dashboard: NCR query failed", exc_info=True)

    try:
        from app.modules.risk.models import RiskItem as _RiskItem

        _risk_high = (
            await session.execute(
                select(func.count(_RiskItem.id)).where(
                    _RiskItem.project_id == project_id,
                    _RiskItem.impact_severity == "high",
                )
            )
        ).scalar_one()
        quality_section["high_risk_observations"] = _risk_high
    except Exception:
        logger.debug("Dashboard: risk items query failed", exc_info=True)

    # Validation score from BOQ positions
    if boq_ids:
        try:
            from app.modules.boq.models import Position as _Pos

            val_total = (
                await session.execute(
                    select(func.count(_Pos.id)).where(
                        _Pos.boq_id.in_(boq_ids),
                        _Pos.validation_status.isnot(None),
                        _Pos.validation_status != "pending",
                    )
                )
            ).scalar_one()
            val_passed = (
                await session.execute(
                    select(func.count(_Pos.id)).where(
                        _Pos.boq_id.in_(boq_ids),
                        _Pos.validation_status == "passed",
                    )
                )
            ).scalar_one()
            if val_total > 0:
                quality_section["validation_score"] = str(round(val_passed / val_total, 2))
        except Exception:
            logger.debug("Dashboard: validation score query failed", exc_info=True)

    # ── Documents ──────────────────────────────────────────────────────────
    documents_section: dict = {
        "total": 0,
        "wip": 0,
        "shared": 0,
        "published": 0,
        "pending_transmittals": 0,
    }
    try:
        from app.modules.documents.models import Document

        doc_rows = (
            await session.execute(
                select(Document.cde_state, func.count(Document.id))
                .where(Document.project_id == project_id)
                .group_by(Document.cde_state)
            )
        ).all()
        doc_total = 0
        for doc_state, cnt in doc_rows:
            doc_total += cnt
            if doc_state == "wip":
                documents_section["wip"] = cnt
            elif doc_state == "shared":
                documents_section["shared"] = cnt
            elif doc_state == "published":
                documents_section["published"] = cnt
        documents_section["total"] = doc_total
    except Exception:
        logger.debug("Dashboard: documents query failed", exc_info=True)

    try:
        from app.modules.transmittals.models import Transmittal

        pending_trans = (
            await session.execute(
                select(func.count(Transmittal.id)).where(
                    Transmittal.project_id == project_id,
                    Transmittal.status.in_(["draft", "pending"]),
                )
            )
        ).scalar_one()
        documents_section["pending_transmittals"] = pending_trans
    except Exception:
        logger.debug("Dashboard: transmittals query failed", exc_info=True)

    # ── Communication (RFIs, Submittals, Tasks) ────────────────────────────
    communication_section: dict = {
        "open_rfis": 0,
        "overdue_rfis": 0,
        "open_submittals": 0,
        "open_tasks": 0,
        "next_meeting": None,
        "unresolved_action_items": 0,
    }

    try:
        from app.modules.rfi.models import RFI

        today_str = date.today().isoformat()
        open_rfis = (
            await session.execute(
                select(func.count(RFI.id)).where(
                    RFI.project_id == project_id,
                    RFI.status.in_(["draft", "open", "in_review"]),
                )
            )
        ).scalar_one()
        communication_section["open_rfis"] = open_rfis

        overdue_rfis = (
            await session.execute(
                select(func.count(RFI.id)).where(
                    RFI.project_id == project_id,
                    RFI.status.in_(["draft", "open", "in_review"]),
                    RFI.response_due_date < today_str,
                    RFI.response_due_date.isnot(None),
                )
            )
        ).scalar_one()
        communication_section["overdue_rfis"] = overdue_rfis
    except Exception:
        logger.debug("Dashboard: RFI query failed", exc_info=True)

    try:
        from app.modules.submittals.models import Submittal

        open_submittals = (
            await session.execute(
                select(func.count(Submittal.id)).where(
                    Submittal.project_id == project_id,
                    Submittal.status.in_(["draft", "submitted", "under_review"]),
                )
            )
        ).scalar_one()
        communication_section["open_submittals"] = open_submittals
    except Exception:
        logger.debug("Dashboard: submittals query failed", exc_info=True)

    try:
        from app.modules.tasks.models import Task

        open_tasks = (
            await session.execute(
                select(func.count(Task.id)).where(
                    Task.project_id == project_id,
                    Task.status.in_(["draft", "open", "in_progress"]),
                )
            )
        ).scalar_one()
        communication_section["open_tasks"] = open_tasks
    except Exception:
        logger.debug("Dashboard: tasks query failed", exc_info=True)

    try:
        from app.modules.meetings.models import Meeting

        today_str = date.today().isoformat()
        nm_row = (
            await session.execute(
                select(Meeting.meeting_date)
                .where(Meeting.project_id == project_id, Meeting.meeting_date >= today_str)
                .order_by(Meeting.meeting_date)
                .limit(1)
            )
        ).scalar_one_or_none()
        if nm_row:
            communication_section["next_meeting"] = nm_row

        all_meetings = (
            (await session.execute(select(Meeting.action_items).where(Meeting.project_id == project_id)))
            .scalars()
            .all()
        )
        unresolved = 0
        for items in all_meetings:
            if isinstance(items, list):
                unresolved += sum(1 for item in items if isinstance(item, dict) and item.get("status") != "completed")
        communication_section["unresolved_action_items"] = unresolved
    except Exception:
        logger.debug("Dashboard: meetings query failed", exc_info=True)

    # ── Procurement ──────────────────────────────────────────────────────────
    procurement_section: dict = {
        "active_pos": 0,
        "pending_delivery": 0,
        "total_committed": "0",
    }
    try:
        from app.modules.procurement.models import PurchaseOrder

        active_pos = (
            await session.execute(
                select(func.count(PurchaseOrder.id)).where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.status.in_(["approved", "issued", "partially_received"]),
                )
            )
        ).scalar_one()
        procurement_section["active_pos"] = active_pos

        pending_delivery = (
            await session.execute(
                select(func.count(PurchaseOrder.id)).where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.status.in_(["issued", "partially_received"]),
                )
            )
        ).scalar_one()
        procurement_section["pending_delivery"] = pending_delivery

        total_committed_result = (
            await session.execute(
                select(func.sum(cast(PurchaseOrder.amount_total, Float))).where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.status.notin_(["draft", "cancelled"]),
                )
            )
        ).scalar_one()
        procurement_section["total_committed"] = str(round(total_committed_result or 0, 2))
    except Exception:
        logger.debug("Dashboard: procurement query failed", exc_info=True)

    # ── Recent Activity (last 10 across modules) ───────────────────────────
    recent_activity: list[dict] = []
    try:
        from app.modules.changeorders.models import ChangeOrder
        from app.modules.documents.models import Document as _Doc
        from app.modules.fieldreports.models import FieldReport
        from app.modules.punchlist.models import PunchItem as _Punch
        from app.modules.rfi.models import RFI as _RFI
        from app.modules.tasks.models import Task as _Task

        activity_queries = []
        try:
            activity_queries.append(
                select(
                    literal_column("'rfi_created'").label("type"), _RFI.subject.label("title"), _RFI.created_at
                ).where(_RFI.project_id == project_id)
            )
        except Exception:
            logger.debug("Dashboard activity: RFI query build failed", exc_info=True)
        try:
            activity_queries.append(
                select(
                    literal_column("'task_created'").label("type"), _Task.title.label("title"), _Task.created_at
                ).where(_Task.project_id == project_id)
            )
        except Exception:
            logger.debug("Dashboard activity: Task query build failed", exc_info=True)
        try:
            activity_queries.append(
                select(
                    literal_column("'change_order'").label("type"),
                    ChangeOrder.title.label("title"),
                    ChangeOrder.created_at,
                ).where(ChangeOrder.project_id == project_id)
            )
        except Exception:
            logger.debug("Dashboard activity: ChangeOrder query build failed", exc_info=True)
        try:
            activity_queries.append(
                select(
                    literal_column("'document_uploaded'").label("type"), _Doc.name.label("title"), _Doc.created_at
                ).where(_Doc.project_id == project_id)
            )
        except Exception:
            logger.debug("Dashboard activity: Document query build failed", exc_info=True)
        try:
            activity_queries.append(
                select(
                    literal_column("'punch_item'").label("type"), _Punch.title.label("title"), _Punch.created_at
                ).where(_Punch.project_id == project_id)
            )
        except Exception:
            logger.debug("Dashboard activity: PunchItem query build failed", exc_info=True)
        try:
            activity_queries.append(
                select(
                    literal_column("'field_report'").label("type"),
                    FieldReport.title.label("title"),
                    FieldReport.created_at,
                ).where(FieldReport.project_id == project_id)
            )
        except Exception:
            logger.debug("Dashboard activity: FieldReport query build failed", exc_info=True)

        if activity_queries:
            combined = union_all(*activity_queries).subquery()
            rows = (await session.execute(select(combined).order_by(combined.c.created_at.desc()).limit(10))).all()
            for row in rows:
                recent_activity.append(
                    {
                        "type": row[0],
                        "title": row[1],
                        "date": row[2].isoformat() if isinstance(row[2], datetime) else str(row[2]),
                    }
                )
    except Exception:
        logger.debug("Recent activity query failed", exc_info=True)

    # ── Legacy compat fields ─────────────────────────────────────────────────────
    requirement_sets_count = 0
    requirements_total = 0
    requirements_coverage = 0
    try:
        from app.modules.requirements.models import Requirement, RequirementSet

        requirement_sets_count = (
            await session.execute(select(func.count(RequirementSet.id)).where(RequirementSet.project_id == project_id))
        ).scalar_one()
        req_set_ids_result = await session.execute(
            select(RequirementSet.id).where(RequirementSet.project_id == project_id)
        )
        req_set_ids = [row[0] for row in req_set_ids_result.all()]
        if req_set_ids:
            requirements_total = (
                await session.execute(
                    select(func.count(Requirement.id)).where(Requirement.requirement_set_id.in_(req_set_ids))
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
            requirements_coverage = round(linked_count / requirements_total * 100) if requirements_total > 0 else 0
    except Exception:
        logger.debug("Dashboard: requirements query failed", exc_info=True)

    markups_count = 0
    try:
        from app.modules.markups.models import Markup

        markups_count = (
            await session.execute(select(func.count(Markup.id)).where(Markup.project_id == project_id))
        ).scalar_one()
    except Exception:
        logger.debug("Dashboard: markups query failed", exc_info=True)

    field_reports_total = 0
    field_reports_this_week = 0
    try:
        from app.modules.fieldreports.models import FieldReport

        field_reports_total = (
            await session.execute(select(func.count(FieldReport.id)).where(FieldReport.project_id == project_id))
        ).scalar_one()
        week_ago = date.today() - timedelta(days=7)
        field_reports_this_week = (
            await session.execute(
                select(func.count(FieldReport.id)).where(FieldReport.project_id == project_id, FieldReport.report_date >= week_ago)
            )
        ).scalar_one()
    except Exception:
        logger.debug("Dashboard: field reports query failed", exc_info=True)

    photos_count = 0
    try:
        from app.modules.documents.models import ProjectPhoto

        photos_count = (
            await session.execute(select(func.count(ProjectPhoto.id)).where(ProjectPhoto.project_id == project_id))
        ).scalar_one()
    except Exception:
        logger.debug("Dashboard: photos query failed", exc_info=True)

    measurements_count = 0
    try:
        from app.modules.takeoff.models import TakeoffMeasurement

        measurements_count = (
            await session.execute(
                select(func.count(TakeoffMeasurement.id)).where(TakeoffMeasurement.project_id == project_id)
            )
        ).scalar_one()
    except Exception:
        logger.debug("Dashboard: takeoff measurements query failed", exc_info=True)

    risk_total = 0
    risk_high_count = 0
    try:
        from app.modules.risk.models import RiskItem

        risk_total = (
            await session.execute(select(func.count(RiskItem.id)).where(RiskItem.project_id == project_id))
        ).scalar_one()
        risk_high_count = (
            await session.execute(
                select(func.count(RiskItem.id)).where(
                    RiskItem.project_id == project_id, RiskItem.impact_severity == "high"
                )
            )
        ).scalar_one()
    except Exception:
        logger.debug("Dashboard: risk items query failed", exc_info=True)

    co_total = 0
    co_approved = 0
    try:
        from app.modules.changeorders.models import ChangeOrder

        co_total = (await session.execute(select(func.count(ChangeOrder.id)).where(ChangeOrder.project_id == project_id))).scalar_one()
        co_approved = (
            await session.execute(
                select(func.count(ChangeOrder.id)).where(ChangeOrder.project_id == project_id, ChangeOrder.status == "approved")
            )
        ).scalar_one()
    except Exception:
        logger.debug("Dashboard: change orders query failed", exc_info=True)

    return {
        # New unified dashboard structure
        "project": project_info,
        "budget": budget_section,
        "schedule": schedule_section,
        "quality": quality_section,
        "documents": documents_section,
        "communication": communication_section,
        "procurement": procurement_section,
        "recent_activity": recent_activity,
        # Legacy flat fields (backward compat)
        "project_id": str(project_id),
        "boq_count": boq_count,
        "boq_total_value": boq_total_value,
        "position_count": position_count,
        "requirement_sets": requirement_sets_count,
        "requirements_total": requirements_total,
        "requirements_coverage": requirements_coverage,
        "markups_count": markups_count + markups_from_boq,
        "punch_items": punch_items,
        "field_reports": {"total": field_reports_total, "this_week": field_reports_this_week},
        "photos_count": photos_count,
        "measurements_count": measurements_count,
        "documents_count": documents_section["total"],
        "schedule_activities": schedule_section["total_activities"],
        "risks": {"total": risk_total, "high": risk_high_count},
        "change_orders": {"total": co_total, "approved": co_approved},
    }


# ── Dashboard Summary Cards (lightweight, single endpoint) ──────────────


@router.get(
    "/dashboard/cards/",
    summary="Get dashboard summary cards for all projects",
    description="Returns lightweight per-project summary metrics for dashboard cards: "
    "BOQ total value, open tasks count, open RFIs count, active safety incidents, "
    "and schedule progress percentage. All modules degrade gracefully.",
)
async def dashboard_cards(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> list[dict]:
    """Dashboard summary cards — lightweight per-project KPIs in a single call.

    Returns a list of project summaries with key metrics aggregated from
    multiple modules. Each module section is wrapped in try/except for
    graceful degradation if a module table does not exist yet.
    """
    from sqlalchemy import Float, func, select
    from sqlalchemy.sql.expression import cast

    from app.modules.projects.models import Project

    # Fetch all projects (admin sees all, regular user sees own)
    is_admin = payload.get("role") == "admin"
    if is_admin:
        proj_result = await session.execute(
            select(Project).where(Project.status != "archived").order_by(Project.updated_at.desc())
        )
    else:
        proj_result = await session.execute(
            select(Project)
            .where(Project.owner_id == uuid.UUID(user_id), Project.status != "archived")
            .order_by(Project.updated_at.desc())
        )
    all_projects = proj_result.scalars().all()

    if not all_projects:
        return []

    project_ids = [p.id for p in all_projects]

    # ── BOQ total value per project ─────────────────────────────────────
    boq_values: dict[str, float] = {}
    boq_counts: dict[str, int] = {}
    position_counts: dict[str, int] = {}
    try:
        from app.modules.boq.models import BOQ, Position

        # BOQ count per project
        boq_count_rows = (
            await session.execute(
                select(BOQ.project_id, func.count(BOQ.id))
                .where(BOQ.project_id.in_(project_ids))
                .group_by(BOQ.project_id)
            )
        ).all()
        for pid, cnt in boq_count_rows:
            boq_counts[str(pid)] = cnt

        # Get all BOQ IDs grouped by project
        boq_rows = (
            await session.execute(
                select(BOQ.id, BOQ.project_id).where(BOQ.project_id.in_(project_ids))
            )
        ).all()
        boq_id_to_project: dict[str, str] = {}
        for bid, pid in boq_rows:
            boq_id_to_project[str(bid)] = str(pid)

        if boq_id_to_project:
            all_boq_ids = [uuid.UUID(bid) for bid in boq_id_to_project]

            # Sum of position totals per BOQ
            pos_rows = (
                await session.execute(
                    select(
                        Position.boq_id,
                        func.sum(cast(Position.total, Float)).label("total_value"),
                        func.count(Position.id).label("pos_count"),
                    )
                    .where(Position.boq_id.in_(all_boq_ids))
                    .group_by(Position.boq_id)
                )
            ).all()
            for boq_id, total_val, pos_cnt in pos_rows:
                pid = boq_id_to_project.get(str(boq_id), "")
                if pid:
                    boq_values[pid] = boq_values.get(pid, 0.0) + (total_val or 0.0)
                    position_counts[pid] = position_counts.get(pid, 0) + (pos_cnt or 0)
    except Exception:
        logger.debug("Dashboard cards: BOQ query failed", exc_info=True)

    # ── Open tasks per project ──────────────────────────────────────────
    open_tasks: dict[str, int] = {}
    try:
        from app.modules.tasks.models import Task

        task_rows = (
            await session.execute(
                select(Task.project_id, func.count(Task.id))
                .where(
                    Task.project_id.in_(project_ids),
                    Task.status.in_(["draft", "open", "in_progress"]),
                )
                .group_by(Task.project_id)
            )
        ).all()
        for pid, cnt in task_rows:
            open_tasks[str(pid)] = cnt
    except Exception:
        logger.debug("Dashboard cards: Tasks query failed", exc_info=True)

    # ── Open RFIs per project ───────────────────────────────────────────
    open_rfis: dict[str, int] = {}
    try:
        from app.modules.rfi.models import RFI

        rfi_rows = (
            await session.execute(
                select(RFI.project_id, func.count(RFI.id))
                .where(
                    RFI.project_id.in_(project_ids),
                    RFI.status.in_(["draft", "open", "in_review"]),
                )
                .group_by(RFI.project_id)
            )
        ).all()
        for pid, cnt in rfi_rows:
            open_rfis[str(pid)] = cnt
    except Exception:
        logger.debug("Dashboard cards: RFI query failed", exc_info=True)

    # ── Active safety incidents per project ─────────────────────────────
    safety_incidents: dict[str, int] = {}
    try:
        from app.modules.safety.models import SafetyIncident

        safety_rows = (
            await session.execute(
                select(SafetyIncident.project_id, func.count(SafetyIncident.id))
                .where(
                    SafetyIncident.project_id.in_(project_ids),
                    SafetyIncident.status.in_(["reported", "under_investigation", "open"]),
                )
                .group_by(SafetyIncident.project_id)
            )
        ).all()
        for pid, cnt in safety_rows:
            safety_incidents[str(pid)] = cnt
    except Exception:
        logger.debug("Dashboard cards: Safety query failed", exc_info=True)

    # ── Schedule progress per project ───────────────────────────────────
    schedule_progress: dict[str, float] = {}
    try:
        from app.modules.schedule.models import Activity, Schedule

        sched_rows = (
            await session.execute(
                select(Schedule.id, Schedule.project_id).where(
                    Schedule.project_id.in_(project_ids)
                )
            )
        ).all()
        sched_to_project: dict[str, str] = {}
        sched_ids = []
        for sid, pid in sched_rows:
            sched_to_project[str(sid)] = str(pid)
            sched_ids.append(sid)

        if sched_ids:
            act_rows = (
                await session.execute(
                    select(
                        Activity.schedule_id,
                        Activity.status,
                        func.count(Activity.id),
                    )
                    .where(Activity.schedule_id.in_(sched_ids))
                    .group_by(Activity.schedule_id, Activity.status)
                )
            ).all()

            # Aggregate per project
            project_totals: dict[str, int] = {}
            project_completed: dict[str, int] = {}
            for sid, act_status, cnt in act_rows:
                pid = sched_to_project.get(str(sid), "")
                if pid:
                    project_totals[pid] = project_totals.get(pid, 0) + cnt
                    if act_status in ("completed", "complete"):
                        project_completed[pid] = project_completed.get(pid, 0) + cnt

            for pid, total in project_totals.items():
                if total > 0:
                    done = project_completed.get(pid, 0)
                    schedule_progress[pid] = round(done / total * 100, 1)
    except Exception:
        logger.debug("Dashboard cards: Schedule query failed", exc_info=True)

    # ── Assemble response ───────────────────────────────────────────────
    result = []
    for p in all_projects:
        pid = str(p.id)
        result.append(
            {
                "id": pid,
                "name": p.name,
                "description": p.description or "",
                "region": p.region or "",
                "currency": p.currency or "EUR",
                "classification_standard": p.classification_standard or "",
                "status": p.status or "active",
                "phase": getattr(p, "phase", None),
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                "boq_total_value": round(boq_values.get(pid, 0.0), 2),
                "boq_count": boq_counts.get(pid, 0),
                "position_count": position_counts.get(pid, 0),
                "open_tasks": open_tasks.get(pid, 0),
                "open_rfis": open_rfis.get(pid, 0),
                "safety_incidents": safety_incidents.get(pid, 0),
                "progress_pct": schedule_progress.get(pid, 0.0),
            }
        )

    return result


# ── Cross-Project Analytics ─────────────────────────────────────────────


@router.get(
    "/analytics/overview/",
    summary="Get cross-project analytics",
    description="Aggregated KPIs across all projects: total budget, actual spend, "
    "variance, over-budget count, and per-project summary with BOQ counts.",
)
async def analytics_overview(
    session: SessionDep,
    _user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict:
    """Cross-project analytics — aggregated KPIs across all projects.

    Scoped to the current user's owned projects; admins see every project.
    """
    from sqlalchemy import Float, func, select
    from sqlalchemy.sql.expression import cast

    from app.modules.boq.models import BOQ
    from app.modules.costmodel.models import BudgetLine
    from app.modules.projects.models import Project

    is_admin = bool(payload and payload.get("role") == "admin")

    # Per-project summary — owner-scoped for non-admins
    proj_stmt = select(Project).order_by(Project.name)
    if not is_admin:
        proj_stmt = proj_stmt.where(Project.owner_id == _user_id)
    proj_result = await session.execute(proj_stmt)
    all_projects = list(proj_result.scalars().all())

    project_ids = [p.id for p in all_projects]
    proj_count = len(all_projects)

    # Single grouped query for budget rows across the user's projects
    if project_ids:
        budget_stmt = (
            select(
                BudgetLine.project_id,
                func.sum(cast(BudgetLine.planned_amount, Float)).label("planned"),
                func.sum(cast(BudgetLine.actual_amount, Float)).label("actual"),
            )
            .where(BudgetLine.project_id.in_(project_ids))
            .group_by(BudgetLine.project_id)
        )
        budget_rows = (await session.execute(budget_stmt)).all()
    else:
        budget_rows = []

    budget_map: dict[str, tuple[float, float]] = {
        str(r.project_id): (float(r.planned or 0), float(r.actual or 0)) for r in budget_rows
    }

    total_planned = sum(p for p, _ in budget_map.values())
    total_actual = sum(a for _, a in budget_map.values())

    # Projects with budget
    projects_with_budget = len(budget_map)

    # Single grouped query for BOQ counts (fixes N+1)
    if project_ids:
        boq_stmt = (
            select(BOQ.project_id, func.count(BOQ.id))
            .where(BOQ.project_id.in_(project_ids))
            .group_by(BOQ.project_id)
        )
        boq_count_rows = (await session.execute(boq_stmt)).all()
        boq_counts_map: dict[str, int] = {str(row[0]): int(row[1]) for row in boq_count_rows}
    else:
        boq_counts_map = {}

    # Per-project summary
    projects_data = []
    for p in all_projects:
        pid = str(p.id)
        pname = p.name
        pregion = p.region
        pcurrency = p.currency

        # Find budget for this project
        planned, actual = budget_map.get(pid, (0.0, 0.0))
        variance = planned - actual if planned > 0 else 0
        variance_pct = round((variance / planned * 100), 1) if planned > 0 else 0

        # BOQ count from pre-fetched map (single grouped query above)
        boq_count = boq_counts_map.get(pid, 0)

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


# ── WBS CRUD ─────────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/wbs/",
    response_model=WBSResponse,
    status_code=201,
    summary="Create WBS node",
    description="Create a Work Breakdown Structure node for a project. "
    "Supports hierarchical nesting via parent_id.",
)
async def create_wbs_node(
    project_id: uuid.UUID,
    data: WBSCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> WBSResponse:
    """Create a WBS node for a project."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from app.modules.projects.models import ProjectWBS

    # Validate parent exists and belongs to same project
    if data.parent_id is not None:
        parent = await session.get(ProjectWBS, data.parent_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent WBS node not found",
            )
        if parent.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent WBS node belongs to a different project",
            )

    node = ProjectWBS(
        project_id=project_id,
        parent_id=data.parent_id,
        code=data.code,
        name=data.name,
        name_translations=data.name_translations,
        level=data.level,
        sort_order=data.sort_order,
        wbs_type=data.wbs_type,
        planned_cost=data.planned_cost,
        planned_hours=data.planned_hours,
        metadata_=data.metadata,
    )
    session.add(node)
    await session.flush()
    return WBSResponse.model_validate(node)


@router.get(
    "/{project_id}/wbs/",
    response_model=list[WBSResponse],
    summary="List WBS nodes",
    description="List all WBS nodes for a project, ordered by sort_order.",
)
async def list_wbs_nodes(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> list[WBSResponse]:
    """List all WBS nodes for a project."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from sqlalchemy import select

    from app.modules.projects.models import ProjectWBS

    stmt = select(ProjectWBS).where(ProjectWBS.project_id == project_id).order_by(ProjectWBS.sort_order)
    result = await session.execute(stmt)
    nodes = list(result.scalars().all())
    return [WBSResponse.model_validate(n) for n in nodes]


@router.patch(
    "/{project_id}/wbs/{wbs_id}",
    response_model=WBSResponse,
    summary="Update WBS node",
    description="Partially update a WBS node. Validates that parent_id does not create a self-reference.",
)
async def update_wbs_node(
    project_id: uuid.UUID,
    wbs_id: uuid.UUID,
    data: WBSUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> WBSResponse:
    """Update a WBS node."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from sqlalchemy import update

    from app.modules.projects.models import ProjectWBS

    fields = data.model_dump(exclude_unset=True)
    if "metadata" in fields:
        fields["metadata_"] = fields.pop("metadata")

    # Validate parent_id if being changed
    if "parent_id" in fields and fields["parent_id"] is not None:
        new_parent_id = fields["parent_id"]
        # Cannot set self as parent
        if new_parent_id == wbs_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A WBS node cannot be its own parent",
            )
        parent = await session.get(ProjectWBS, new_parent_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent WBS node not found",
            )
        if parent.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent WBS node belongs to a different project",
            )

    if fields:
        stmt = update(ProjectWBS).where(ProjectWBS.id == wbs_id, ProjectWBS.project_id == project_id).values(**fields)
        await session.execute(stmt)
        await session.flush()

    node = await session.get(ProjectWBS, wbs_id)
    if node is None:
        raise HTTPException(status_code=404, detail="WBS node not found")
    return WBSResponse.model_validate(node)


@router.delete(
    "/{project_id}/wbs/{wbs_id}",
    status_code=204,
    summary="Delete WBS node",
)
async def delete_wbs_node(
    project_id: uuid.UUID,
    wbs_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Delete a WBS node."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from sqlalchemy import delete

    from app.modules.projects.models import ProjectWBS

    stmt = delete(ProjectWBS).where(ProjectWBS.id == wbs_id, ProjectWBS.project_id == project_id)
    await session.execute(stmt)


# ── Milestone CRUD ───────────────────────────────────────────────────────


@router.post(
    "/{project_id}/milestones/",
    response_model=MilestoneResponse,
    status_code=201,
    summary="Create milestone",
    description="Create a project milestone with planned date. "
    "Can be linked to a payment percentage for progress billing.",
)
async def create_milestone(
    project_id: uuid.UUID,
    data: MilestoneCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> MilestoneResponse:
    """Create a project milestone."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from app.modules.projects.models import ProjectMilestone

    milestone = ProjectMilestone(
        project_id=project_id,
        name=data.name,
        milestone_type=data.milestone_type,
        planned_date=data.planned_date,
        actual_date=data.actual_date,
        status=data.status,
        linked_payment_pct=data.linked_payment_pct,
        metadata_=data.metadata,
    )
    session.add(milestone)
    await session.flush()
    return MilestoneResponse.model_validate(milestone)


@router.get(
    "/{project_id}/milestones/",
    response_model=list[MilestoneResponse],
    summary="List milestones",
    description="List all milestones for a project, ordered by planned date.",
)
async def list_milestones(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> list[MilestoneResponse]:
    """List all milestones for a project."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from sqlalchemy import select

    from app.modules.projects.models import ProjectMilestone

    stmt = (
        select(ProjectMilestone)
        .where(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.planned_date)
    )
    result = await session.execute(stmt)
    milestones = list(result.scalars().all())
    return [MilestoneResponse.model_validate(m) for m in milestones]


@router.patch("/{project_id}/milestones/{milestone_id}", response_model=MilestoneResponse)
async def update_milestone(
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    data: MilestoneUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> MilestoneResponse:
    """Update a project milestone."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from sqlalchemy import update

    from app.modules.projects.models import ProjectMilestone
    from app.modules.projects.schemas import _MILESTONE_TRANSITIONS

    # Validate status transition if status is being changed
    if data.status is not None:
        current = await session.get(ProjectMilestone, milestone_id)
        if current is None or current.project_id != project_id:
            raise HTTPException(status_code=404, detail="Milestone not found")
        current_status = current.status
        if data.status != current_status:
            allowed = _MILESTONE_TRANSITIONS.get(current_status, set())
            if data.status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid status transition: '{current_status}' -> '{data.status}'. "
                        f"Allowed transitions from '{current_status}': {sorted(allowed)}"
                    ),
                )

    fields = data.model_dump(exclude_unset=True)
    if "metadata" in fields:
        fields["metadata_"] = fields.pop("metadata")

    if fields:
        stmt = (
            update(ProjectMilestone)
            .where(
                ProjectMilestone.id == milestone_id,
                ProjectMilestone.project_id == project_id,
            )
            .values(**fields)
        )
        await session.execute(stmt)
        await session.flush()

    milestone = await session.get(ProjectMilestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return MilestoneResponse.model_validate(milestone)


@router.delete("/{project_id}/milestones/{milestone_id}", status_code=204)
async def delete_milestone(
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Delete a project milestone."""
    await _verify_project_owner(service, project_id, user_id, payload)

    from sqlalchemy import delete

    from app.modules.projects.models import ProjectMilestone

    stmt = delete(ProjectMilestone).where(
        ProjectMilestone.id == milestone_id,
        ProjectMilestone.project_id == project_id,
    )
    await session.execute(stmt)
