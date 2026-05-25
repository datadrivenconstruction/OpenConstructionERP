"""‌⁠‍Projects API routes.

Endpoints:
    POST /                   — Create project (auth required)
    GET  /                   — List my projects (auth required)
    GET  /{project_id}       — Get project (auth required)
    PATCH /{project_id}      — Update project (auth required)
    DELETE /{project_id}     — Archive project (auth required)
"""

import logging
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.dependencies import CurrentUserId, CurrentUserPayload, SessionDep, SettingsDep
from app.modules.projects.bundle_export import (
    export_bundle as fm_export_bundle,
)
from app.modules.projects.bundle_export import (
    filename_for_bundle as fm_bundle_filename,
)
from app.modules.projects.bundle_export import (
    preview_bundle as fm_preview_bundle,
)
from app.modules.projects.bundle_import import (
    BundleError,
)
from app.modules.projects.bundle_import import (
    import_bundle as fm_import_bundle,
)
from app.modules.projects.bundle_import import (
    validate_bundle as fm_validate_bundle,
)
from app.modules.projects.file_manager_schemas import (
    EmailLinkResponse,
    ExportOptions,
    ExportPreview,
    FileKind,
    FileListResponse,
    FileTreeNode,
    ImportMode,
    ImportPreview,
    ImportResult,
    StorageLocations,
)
from app.modules.projects.file_manager_service import (
    file_tree as fm_file_tree,
)
from app.modules.projects.file_manager_service import (
    list_project_files as fm_list_files,
)
from app.modules.projects.file_manager_service import (
    resolve_storage_locations as fm_resolve_locations,
)
from app.modules.projects.member_schemas import (
    AddProjectMemberRequest,
    ProjectMemberResponse,
)
from app.modules.projects import profile_service
from app.modules.projects.module_presence import probe_project_modules
from app.modules.projects.schemas import (
    FocusModePatch,
    MatchProjectSettingsRead,
    MatchProjectSettingsUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    PresetRead,
    ProfileSpec,
    ProjectModulePresence,
    ProjectModuleRead,
    ProjectCreate,
    ProjectProfileResult,
    ProjectResponse,
    ProjectUpdate,
    WBSCreate,
    WBSResponse,
    WBSUpdate,
)
from app.modules.projects.service import (
    ProjectService,
    get_or_create_match_settings,
    reset_match_settings,
    update_match_settings,
)

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
    """‌⁠‍Load a project and verify the current user is the owner.

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
    """‌⁠‍Create a new project."""
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
        raise HTTPException(
            status_code=500,
            detail="Failed to archive project. Check server logs for details.",
        ) from exc


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


# ── Duplicate (deep clone) ───────────────────────────────────────────────


@router.post(
    "/{project_id}/duplicate/",
    response_model=ProjectResponse,
    status_code=201,
    summary="Duplicate project (deep clone)",
    description="Server-side deep-clone of a project including WBS tree, "
    "milestones, match-settings, custom fields, validation rule sets, "
    "address, fx_rates, custom_units, VAT and metadata. The whole copy "
    "runs in a single transaction — any child insert failure rolls back "
    "the parent insert too. The caller becomes the owner of the clone.",
)
async def duplicate_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Deep-clone a project. Verifies the caller has access to the source.

    The clone is created with ``name = f"{source.name} (Copy)"``, a fresh
    UUID + fresh ``project_code``, the calling user as owner, and every
    other column copied verbatim. Child collections (WBS / milestones /
    match-settings) are re-keyed onto the new project id with fresh UUIDs.
    """
    # Ownership / admin check on the SOURCE project so a viewer cannot
    # clone someone else's project.
    await _verify_project_owner(service, project_id, user_id, payload)
    try:
        new_project = await service.duplicate_project(
            project_id, uuid.UUID(user_id),
        )
        return ProjectResponse.model_validate(new_project)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to duplicate project %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to duplicate project",
        )


# ── Project Members (Team Strip) ───────────────────────────────────────
# These three endpoints back the avatar strip shown above the tab bar on
# /projects/{id}. They delegate to ``member_service`` which uses the
# project's auto-created Default Team as the storage backend so we don't
# need a new table or migration.


@router.get(
    "/{project_id}/members/",
    response_model=list[ProjectMemberResponse],
    summary="List project members",
    description="Returns every user assigned to this project (owner + invited "
    "collaborators) with email, full name, and role. Used by the Team Strip "
    "to render avatar circles + tooltip metadata.",
)
@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    include_in_schema=False,
)
async def list_project_members_endpoint(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> list[ProjectMemberResponse]:
    """List members of a project. Owner / admin only — 403 otherwise."""
    await _verify_project_owner(service, project_id, user_id, payload)
    from app.modules.projects.member_service import list_project_members

    return await list_project_members(session, project_id)


@router.post(
    "/{project_id}/members/",
    response_model=ProjectMemberResponse,
    status_code=201,
    summary="Add a project member",
    description="Add an existing user to the project. 409 if the user is "
    "already a member; 404 if the user doesn't exist.",
)
@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=201,
    include_in_schema=False,
)
async def add_project_member_endpoint(
    project_id: uuid.UUID,
    data: AddProjectMemberRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> ProjectMemberResponse:
    """Add a member to the project."""
    await _verify_project_owner(service, project_id, user_id, payload)
    from app.modules.projects.member_service import add_project_member

    return await add_project_member(session, project_id, data)


@router.delete(
    "/{project_id}/members/{member_user_id}/",
    status_code=204,
    summary="Remove a project member",
    description="Remove a user from the project. Cannot remove the project "
    "owner — use the ownership transfer flow for that.",
)
@router.delete(
    "/{project_id}/members/{member_user_id}",
    status_code=204,
    include_in_schema=False,
)
async def remove_project_member_endpoint(
    project_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Remove a member from the project."""
    await _verify_project_owner(service, project_id, user_id, payload)
    from app.modules.projects.member_service import remove_project_member

    await remove_project_member(session, project_id, member_user_id)


# ── Per-folder permissions (owner-only) ────────────────────────────────
#
# These live on the projects router (rather than the documents router)
# because they are project-scoped and only the project owner can
# manage them. The router prefix gives us:
#
#     GET    /api/v1/projects/{project_id}/folder-permissions/
#     POST   /api/v1/projects/{project_id}/folder-permissions/
#     DELETE /api/v1/projects/{project_id}/folder-permissions/{permission_id}/


@router.get(
    "/{project_id}/folder-permissions/",
    summary="List folder permissions",
    description="List all non-revoked folder permissions for the project. "
    "Owner / admin only.",
)
async def list_folder_permissions(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    scope_kind: str | None = Query(default=None),
    scope_path: str | None = Query(default=None),
    service: ProjectService = Depends(_get_service),
) -> list[dict]:
    """List grants for a project, optionally narrowed by ``scope_kind``
    (+ ``scope_path``).
    """
    from sqlalchemy import select as _select

    from app.modules.documents.folder_permissions_service import list_permissions
    from app.modules.users.models import User

    await _verify_project_owner(service, project_id, user_id, payload)

    rows = await list_permissions(
        session,
        project_id,
        scope_kind=scope_kind,
        scope_path=scope_path,
    )

    # Pre-join user details so the modal doesn't have to make N lookups.
    user_ids = {r.user_id for r in rows}
    user_map: dict[uuid.UUID, User] = {}
    if user_ids:
        users = (
            await session.execute(_select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
        user_map = {u.id: u for u in users}

    out: list[dict] = []
    for r in rows:
        u = user_map.get(r.user_id)
        out.append(
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "user_id": str(r.user_id),
                "scope_kind": r.scope_kind,
                "scope_path": r.scope_path,
                "role": r.role,
                "granted_by": str(r.granted_by),
                "granted_at": r.granted_at.isoformat() if r.granted_at else None,
                "revoked": r.revoked,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "user_email": (u.email if u is not None else None),
                "user_full_name": (
                    u.full_name if u is not None and u.full_name else None
                ),
            }
        )
    return out


@router.post(
    "/{project_id}/folder-permissions/",
    status_code=201,
    summary="Grant folder permission",
    description="Grant a project member viewer / editor / owner role on a "
    "specific (scope_kind, scope_path) folder. Owner / admin only.",
)
async def grant_folder_permission_endpoint(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
    body: dict = Body(...),  # type: ignore[assignment]
) -> dict:
    """Mint a new grant. 409 on duplicate (scope, user). 400 on bad role."""
    from app.modules.documents.folder_permissions_service import (
        grant_permission,
        is_project_member,
    )
    from app.modules.documents.schemas import FolderPermissionCreate

    await _verify_project_owner(service, project_id, user_id, payload)

    data = FolderPermissionCreate(**body)

    # Refuse to grant to a non-member — leaks "this user doesn't exist
    # on this project" but is more useful than a downstream FK error.
    if not await is_project_member(session, project_id, data.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a member of this project",
        )

    grant = await grant_permission(
        session,
        project_id=project_id,
        user_id=data.user_id,
        scope_kind=data.scope_kind,
        scope_path=data.scope_path,
        role=data.role,
        granted_by=uuid.UUID(user_id),
    )
    return {
        "id": str(grant.id),
        "project_id": str(grant.project_id),
        "user_id": str(grant.user_id),
        "scope_kind": grant.scope_kind,
        "scope_path": grant.scope_path,
        "role": grant.role,
        "granted_by": str(grant.granted_by),
        "granted_at": grant.granted_at.isoformat() if grant.granted_at else None,
        "revoked": grant.revoked,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
        "updated_at": grant.updated_at.isoformat() if grant.updated_at else None,
    }


@router.delete(
    "/{project_id}/folder-permissions/{permission_id}/",
    status_code=204,
    summary="Revoke folder permission",
    description="Soft-revoke a folder permission. Owner / admin only.",
)
async def revoke_folder_permission_endpoint(
    project_id: uuid.UUID,
    permission_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Revoke a grant. 404 when the grant id is unknown or belongs to
    a different project (cross-project IDOR defence)."""
    from app.modules.documents.folder_permissions_service import revoke_permission

    await _verify_project_owner(service, project_id, user_id, payload)
    await revoke_permission(session, project_id=project_id, permission_id=permission_id)


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
    # A-DASH-05: every monetary field is a fixed 2-decimal string and
    # consumed_pct a fixed 1-decimal string, so the default ("empty
    # project") and computed branches encode numbers identically — no
    # more "0" vs "0.0" vs "52.1" typing skew for the frontend parser.
    def _money(x: float) -> str:  # noqa: ANN001
        return f"{round(float(x or 0.0), 2):.2f}"

    def _pct(x: float) -> str:  # noqa: ANN001
        return f"{round(float(x or 0.0), 1):.1f}"

    budget_section: dict = {
        "original": _money(0),
        "revised": _money(0),
        "committed": _money(0),
        "actual": _money(0),
        "forecast": _money(0),
        "consumed_pct": _pct(0),
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

        # A-DASH-02: the BOQ total is the estimate baseline ("original").
        # The 5D cost-model BudgetLine.planned is a *separate* figure (in
        # seed data it is exactly half the BOQ total), so using it as the
        # "revised" budget made revised always 0.5×original and doubled
        # the reported consumed %. There is no formal budget-revision
        # entity in the data model, so with no revision the revised budget
        # equals the original, and consumed % is actual / original.
        original = boq_total_value if boq_total_value > 0 else planned_total
        revised = original
        forecast = revised if revised > 0 else original

        # A-DASH-04: committed = real purchase-order commitments (sum of
        # non-draft/cancelled PO totals), not a fabricated 0.8×actual. Same
        # source as procurement_section.total_committed; degrades to 0 if
        # the procurement module/table is absent.
        committed_total = 0.0
        try:
            from app.modules.procurement.models import PurchaseOrder

            committed_total = float(
                (
                    await session.execute(
                        select(func.sum(cast(PurchaseOrder.amount_total, Float))).where(
                            PurchaseOrder.project_id == project_id,
                            PurchaseOrder.status.notin_(["draft", "cancelled"]),
                        )
                    )
                ).scalar_one()
                or 0.0
            )
        except Exception:
            logger.debug("Dashboard: committed PO sum unavailable", exc_info=True)

        budget_section = {
            "original": _money(original),
            "revised": _money(revised),
            "committed": _money(committed_total),
            "actual": _money(actual_total),
            "forecast": _money(forecast),
            "consumed_pct": _pct(actual_total / revised * 100 if revised > 0 else 0),
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
            budget_section["original"] = _money(boq_total_value)
            budget_section["revised"] = _money(boq_total_value)
            budget_section["forecast"] = _money(boq_total_value)

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
        from app.modules.projects.schemas import parse_flexible_date

        # A-DASH-03: planned_date is a free-form String column (ISO / EU
        # DD.MM.YYYY / US MM/DD/YYYY). The previous string ``>= today_str``
        # filter + string order_by never selected non-ISO dates and even
        # mis-ordered valid ISO ones. Pull pending/in-progress milestones
        # and pick the soonest *future* one by parsed date in Python.
        today = datetime.combine(date.today(), datetime.min.time())
        ms_rows = (
            await session.execute(
                select(ProjectMilestone.name, ProjectMilestone.planned_date).where(
                    ProjectMilestone.project_id == project_id,
                    ProjectMilestone.status.in_(["pending", "in_progress"]),
                )
            )
        ).all()
        upcoming: list[tuple[datetime, str, str]] = []
        for ms_name, ms_date in ms_rows:
            parsed = parse_flexible_date(ms_date)
            if parsed is not None and parsed >= today:
                upcoming.append((parsed, ms_name, ms_date))
        if upcoming:
            upcoming.sort(key=lambda t: t[0])
            schedule_section["next_milestone"] = {
                "name": upcoming[0][1],
                "date": upcoming[0][2],
            }
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
                    func.coalesce(FieldReport.work_performed, FieldReport.report_type).label("title"),
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
                "currency": p.currency or "",
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

    # A-DASH-01: each project carries its own currency (EUR/GBP/USD/AED…).
    # A single scalar total mixes them into a financially meaningless
    # number. Group planned/actual by the project's currency so the
    # frontend can render per-currency subtotals; ``multi_currency`` flags
    # when the flat scalar must not be shown as a single headline figure.
    currency_of: dict[str, str] = {str(p.id): (p.currency or "") for p in all_projects}
    by_currency: dict[str, dict[str, float]] = {}
    for pid_str, (planned_v, actual_v) in budget_map.items():
        cur = currency_of.get(pid_str) or "UNKNOWN"
        bucket = by_currency.setdefault(cur, {"planned": 0.0, "actual": 0.0})
        bucket["planned"] += planned_v
        bucket["actual"] += actual_v
    totals_by_currency = [
        {
            "currency": cur,
            "total_planned": round(v["planned"], 2),
            "total_actual": round(v["actual"], 2),
            "total_variance": round(v["planned"] - v["actual"], 2),
        }
        for cur, v in sorted(by_currency.items())
    ]
    multi_currency = len(by_currency) > 1

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
        # Legacy flat scalars kept for backward compatibility. When
        # ``multi_currency`` is true these mix currencies and must NOT be
        # rendered as a single headline figure — use ``totals_by_currency``.
        "total_planned": round(total_planned, 2),
        "total_actual": round(total_actual, 2),
        "total_variance": round(total_planned - total_actual, 2),
        "multi_currency": multi_currency,
        "totals_by_currency": totals_by_currency,
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
    from app.modules.projects.schemas import parse_flexible_date

    stmt = select(ProjectMilestone).where(ProjectMilestone.project_id == project_id)
    result = await session.execute(stmt)
    milestones = list(result.scalars().all())

    # A-PROJ-06: planned_date is a free-form String accepting ISO / EU
    # (DD.MM.YYYY) / US (MM/DD/YYYY). A SQL string order_by interleaves
    # the formats wrongly, so sort chronologically in Python by the
    # parsed date. Undated milestones sort last (datetime.max), then by
    # created_at for a stable order.
    from datetime import datetime as _dt

    milestones.sort(
        key=lambda m: (
            parse_flexible_date(m.planned_date) or _dt.max,
            m.created_at,
        )
    )
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


# ── Match-settings (v2.8.0) ─────────────────────────────────────────────


@router.get(
    "/{project_id}/match-settings",
    response_model=MatchProjectSettingsRead,
    summary="Get per-project match settings",
    description=(
        "Return the element-to-CWICR match settings for the project. "
        "On first read for a project (e.g. one created before v2.8.0), a "
        "default row is created and returned."
    ),
)
async def get_match_settings(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> MatchProjectSettingsRead:
    """Read (or lazily initialise) the project's match settings."""
    await _verify_project_owner(service, project_id, user_id, payload)
    row = await get_or_create_match_settings(session, project_id)
    return MatchProjectSettingsRead.model_validate(row)


@router.patch(
    "/{project_id}/match-settings",
    response_model=MatchProjectSettingsRead,
    summary="Update per-project match settings",
    description=(
        "Partially update match settings. Validates classifier, mode, and "
        "sources against allow-lists; clamps auto_link_threshold to [0,1]. "
        "Audit-logs the change with before/after snapshots."
    ),
)
async def patch_match_settings(
    project_id: uuid.UUID,
    data: MatchProjectSettingsUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> MatchProjectSettingsRead:
    """PATCH the project's match settings (audit-logged)."""
    await _verify_project_owner(service, project_id, user_id, payload)
    row = await update_match_settings(
        session, project_id, data, user_id=user_id,
    )
    return MatchProjectSettingsRead.model_validate(row)


@router.post(
    "/{project_id}/match-settings/reset",
    response_model=MatchProjectSettingsRead,
    summary="Reset per-project match settings",
    description="Reset all match settings to factory defaults. Audit-logged.",
)
async def post_reset_match_settings(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> MatchProjectSettingsRead:
    """Reset match settings to defaults (audit-logged)."""
    await _verify_project_owner(service, project_id, user_id, payload)
    row = await reset_match_settings(session, project_id, user_id=user_id)
    return MatchProjectSettingsRead.model_validate(row)


# ── File manager (Issue #109) ─────────────────────────────────────────────


@router.get(
    "/{project_id}/files/tree/",
    response_model=list[FileTreeNode],
    summary="File-manager category tree",
)
async def file_manager_tree(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
    q: str | None = Query(default=None, max_length=200),
    extension: str | None = Query(default=None, max_length=10),
) -> list[FileTreeNode]:
    """Return the left-pane category tree for the file manager.

    Accepts the same ``q`` / ``extension`` filters as the file-list
    endpoint so the sidebar counts match what the user actually sees
    in the right pane after a search.
    """
    await _verify_project_owner(service, project_id, user_id, payload)
    return await fm_file_tree(
        session, str(project_id), query=q, extension=extension,
    )


@router.get(
    "/{project_id}/files/",
    response_model=FileListResponse,
    summary="File-manager flat listing",
)
async def file_manager_list(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
    category: FileKind | None = Query(default=None),
    extension: str | None = Query(default=None, max_length=10),
    q: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="modified", pattern="^(modified|name|size|kind)$"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> FileListResponse:
    """Flat listing of every file attached to ``project_id``.

    Cross-module: documents, photos, sheets, BIM models, DWG drawings.
    Each row carries the *real* on-disk path so the UI can ground users
    on where their data actually lives.
    """
    await _verify_project_owner(service, project_id, user_id, payload)
    return await fm_list_files(
        session,
        str(project_id),
        category=category,
        extension=extension,
        query=q,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@router.get(
    "/{project_id}/files/locations/",
    response_model=StorageLocations,
    summary="Resolved on-disk storage roots for the project",
)
async def file_manager_locations(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    settings: SettingsDep,
    service: ProjectService = Depends(_get_service),
) -> StorageLocations:
    """Return the absolute filesystem paths used by the project.

    Powers the path bar in the file manager so users can copy the path,
    open the containing folder (Tauri-only), or just understand where
    their attachments live.
    """
    project = await _verify_project_owner(service, project_id, user_id, payload)
    return fm_resolve_locations(
        str(project_id), getattr(project, "name", ""), settings=settings,
    )


# ── Bundle export / import (Issue #109) ───────────────────────────────────


@router.post(
    "/{project_id}/export/preview/",
    response_model=ExportPreview,
    summary="Preview a bundle export — sizes & counts only",
)
async def post_export_preview(
    project_id: uuid.UUID,
    options: ExportOptions,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> ExportPreview:
    """Cheap dry-run: returns the table-row counts and an attachment-size
    estimate for the chosen scope. Lets the wizard show "we'll pack 12 MB"
    before the user clicks Download.

    Note: this endpoint accepts a body (``ExportOptions``) and is therefore
    POST-only. Probing it with a plain ``GET`` will return 405. A
    convenience GET alias exists immediately below — it returns the same
    shape using ``ExportOptions()`` defaults (``scope="metadata_only"``,
    no attachments) so curl users / link previews have something to look
    at without crafting a JSON body.
    """
    await _verify_project_owner(service, project_id, user_id, payload)
    return await fm_preview_bundle(session, str(project_id), options)


@router.get(
    "/{project_id}/export/preview/",
    response_model=ExportPreview,
    summary="Preview a bundle export with default options (GET alias of POST)",
)
async def get_export_preview(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> ExportPreview:
    """GET alias of ``POST /export/preview/`` for ergonomic URL probing.

    Uses ``ExportOptions()`` defaults — ``scope="metadata_only"`` with
    every ``include_*`` flag off. The wizard always sends POST with
    explicit options; this alias exists so opening the URL in a browser
    or hitting it from curl returns a useful 200 instead of 405.
    """
    await _verify_project_owner(service, project_id, user_id, payload)
    return await fm_preview_bundle(session, str(project_id), ExportOptions())


@router.post(
    "/{project_id}/export/",
    summary="Pack the project into a .ocep bundle",
    responses={200: {"content": {"application/zip": {}}}},
)
async def post_export_bundle(
    project_id: uuid.UUID,
    options: ExportOptions,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> Response:
    """Stream the .ocep bundle as a Content-Disposition: attachment.

    The wizard hits ``/export/preview/`` first to show sizes; this endpoint
    does the real packing and may take several seconds for large BIM scopes.
    """
    project = await _verify_project_owner(service, project_id, user_id, payload)
    user_email = (payload or {}).get("email") if payload else None
    raw = await fm_export_bundle(
        session,
        str(project_id),
        getattr(project, "name", "project"),
        getattr(project, "currency", None),
        user_email,
        options,
    )
    fname = fm_bundle_filename(getattr(project, "name", "project"), options.scope)
    return Response(
        content=raw,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Bundle-Format": "ocep",
            "X-Bundle-Scope": options.scope,
        },
    )


@router.post(
    "/import/validate/",
    response_model=ImportPreview,
    summary="Inspect a .ocep bundle without committing",
)
async def post_import_validate(
    user_id: CurrentUserId,
    file: UploadFile = File(..., description=".ocep bundle to inspect"),
) -> ImportPreview:
    _ = user_id  # gate: any authenticated user can preview a bundle
    """Read the manifest, sanity-check format/version compatibility, and
    return what the bundle *would* import. The frontend uses this to drive
    the import wizard's confirmation screen."""
    raw = await file.read()
    try:
        return fm_validate_bundle(raw)
    except BundleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc


@router.post(
    "/import/",
    response_model=ImportResult,
    summary="Import a .ocep bundle into a fresh or existing project",
)
async def post_import_bundle(
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(..., description=".ocep bundle"),
    mode: ImportMode = Form(default="new_project"),
    target_project_id: str | None = Form(default=None),
    new_project_name: str | None = Form(default=None),
) -> ImportResult:
    """Unpack the bundle and write rows + attachments.

    Three modes:

    * ``new_project`` — fresh UUIDs, attachments land in the new project's
      storage roots. The new project's owner is the importing user.
    * ``merge_into_existing`` — keep source UUIDs, skip rows that already
      exist (idempotent re-import). Requires ``target_project_id``.
    * ``replace_existing`` — wipe ``target_project_id``'s rows for every
      bundled table, then insert the bundle verbatim. Destructive — the
      UI must confirm.
    """
    raw = await file.read()
    try:
        result = await fm_import_bundle(
            session,
            raw,
            mode=mode,
            target_project_id=target_project_id,
            new_project_name=new_project_name,
        )
    except BundleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc

    # ``new_project`` mode created a project row; make the importing user
    # its owner so it shows up in their dashboard.
    if mode == "new_project":
        try:
            from app.modules.projects.models import Project

            proj = (
                await session.execute(
                    select(Project).where(Project.id == result.project_id),
                )
            ).scalar_one_or_none()
            if proj is not None and not getattr(proj, "owner_id", None):
                proj.owner_id = user_id
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not assign owner_id to imported project %s", result.project_id,
            )

    return result


# ── Signed share URL (Issue #109) ─────────────────────────────────────────


def _share_token_secret(settings) -> str:
    secret = getattr(settings, "jwt_secret", None) or getattr(settings, "secret_key", "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing a JWT secret; cannot mint share tokens.",
        )
    return str(secret)


@router.post(
    "/files/{file_id}/email-link/",
    response_model=EmailLinkResponse,
    summary="Mint a time-limited public download link for a project file",
)
async def post_email_link(
    file_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    settings: SettingsDep,
    ttl_hours: int = Query(default=72, ge=1, le=24 * 14),
) -> EmailLinkResponse:
    """Build an HMAC-signed download link the user can paste into an email.

    The token is opaque to the client — server-side it carries only the
    file id + expiry. The download endpoint (``GET /files/share/{token}``)
    decodes it, verifies signature, and streams the file. No DB row is
    written, so there's nothing to clean up after expiry.
    """
    import base64
    import hashlib
    import hmac
    import time

    from app.modules.projects.models import Project as ProjectModel

    target_project_id: str | None = None
    file_kinds: list[tuple[str, str, str]] = [
        ("app.modules.documents.models", "Document", "document"),
        ("app.modules.documents.models", "ProjectPhoto", "photo"),
        ("app.modules.documents.models", "Sheet", "sheet"),
        ("app.modules.bim_hub.models", "BIMModel", "bim_model"),
        ("app.modules.dwg_takeoff.models", "DwgDrawing", "dwg_drawing"),
    ]
    found_kind: str | None = None
    found_row = None
    for mod, cls_name, kind in file_kinds:
        try:
            import importlib
            cls = getattr(importlib.import_module(mod), cls_name, None)
        except ImportError:
            continue
        if cls is None:
            continue
        row = (
            await session.execute(select(cls).where(cls.id == file_id))
        ).scalar_one_or_none()
        if row is not None:
            found_row = row
            found_kind = kind
            target_project_id = str(getattr(row, "project_id", "") or "")
            break

    if found_row is None or not target_project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found",
        )

    # Project ownership gate.
    project = (
        await session.execute(
            select(ProjectModel).where(ProjectModel.id == target_project_id),
        )
    ).scalar_one_or_none()
    if project is None or str(project.owner_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own the project this file belongs to",
        )

    # Build token: base64url(payload).hmac
    expiry = int(time.time()) + ttl_hours * 3600
    payload_obj = {
        "fid": str(file_id),
        "kind": found_kind,
        "exp": expiry,
        "uid": user_id,
    }
    import json as _json
    payload_bytes = _json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
    sig = hmac.new(
        _share_token_secret(settings).encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
    token = f"{payload_b64}.{sig_b64}"

    name = (
        getattr(found_row, "name", None)
        or getattr(found_row, "filename", None)
        or str(file_id)
    )
    size_bytes = int(
        getattr(found_row, "file_size", None)
        or getattr(found_row, "size_bytes", None)
        or 0,
    )
    if not size_bytes:
        try:
            size_bytes = os.path.getsize(
                getattr(found_row, "file_path", None)
                or getattr(found_row, "canonical_file_path", None)
                or "",
            )
        except OSError:
            size_bytes = 0

    return EmailLinkResponse(
        url=f"/api/v1/projects/files/share/{token}",
        expires_at=datetime.fromtimestamp(expiry, tz=UTC),
        file_id=str(file_id),
        file_name=str(name),
        size_bytes=size_bytes,
    )


@router.get(
    "/files/share/{token}",
    summary="Public file download via signed share token",
    include_in_schema=True,
)
async def get_share_file(
    token: str,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """Public download endpoint — no auth, just HMAC verification.

    Token format: ``base64url(payload).base64url(signature)``. Payload
    encodes file id, kind, expiry, owner. We re-derive the signature from
    the payload and the server secret, constant-time compare, then stream
    the file straight from disk. No DB rows are written or updated.
    """
    import base64
    import hashlib
    import hmac
    import time

    if "." not in token:
        raise HTTPException(status_code=400, detail="Malformed share token")
    payload_b64, sig_b64 = token.split(".", 1)
    expected = hmac.new(
        _share_token_secret(settings).encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        provided = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed share token") from exc
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid share token signature")

    try:
        payload_bytes = base64.urlsafe_b64decode(
            payload_b64 + "=" * (-len(payload_b64) % 4),
        )
        import json as _json
        payload_obj = _json.loads(payload_bytes)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed share token") from exc

    if int(payload_obj.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=410, detail="Share link has expired")

    fid = payload_obj.get("fid")
    kind = payload_obj.get("kind")
    if not fid or not kind:
        raise HTTPException(status_code=400, detail="Token is missing fid/kind")

    # Resolve the file again — we never trust the token to carry the path.
    import importlib
    kind_to_class = {
        "document": ("app.modules.documents.models", "Document", "file_path", "name"),
        "photo": ("app.modules.documents.models", "ProjectPhoto", "file_path", "filename"),
        "sheet": ("app.modules.documents.models", "Sheet", "thumbnail_path", "sheet_title"),
        "bim_model": ("app.modules.bim_hub.models", "BIMModel", "canonical_file_path", "name"),
        "dwg_drawing": ("app.modules.dwg_takeoff.models", "DwgDrawing", "file_path", "filename"),
    }
    if kind not in kind_to_class:
        raise HTTPException(status_code=400, detail=f"Unknown file kind '{kind}'")
    mod, cls_name, path_attr, name_attr = kind_to_class[kind]
    try:
        cls = getattr(importlib.import_module(mod), cls_name, None)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="File module not loaded") from exc
    if cls is None:
        raise HTTPException(status_code=503, detail="File class not loaded")

    row = (
        await session.execute(select(cls).where(cls.id == fid))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="File no longer exists")

    path = getattr(row, path_attr, None)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=410, detail="File is no longer on disk")

    fname = getattr(row, name_attr, None) or os.path.basename(path)

    def _iter_file(p: str):
        with open(p, "rb") as fh:
            while True:
                chunk = fh.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        _iter_file(path),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Bundle-Format": "share-link",
        },
    )


# ── Project setup wizard / profile (Slice 1) ──────────────────────────────
#
# Presentation-only module gating. Writing a ``ProjectProfile`` +
# ``ProjectModule`` rows never unloads a module or blocks its API — it
# only feeds the sidebar's visual emphasis (numbered route line for
# enabled modules, greyed for the rest) and the wizard's live preview.
# ``focus_mode_enabled=False`` returns the project to the legacy
# "everything ungreyed" view. ``/wizard/presets`` is a two-segment
# literal so it can never be shadowed by the one-segment
# ``GET /{project_id}`` route above.


def _user_uuid(user_id: str | None) -> uuid.UUID | None:
    """Best-effort JWT-sub → UUID for the ``created_by`` audit column."""
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None


@router.get(
    "/wizard/presets",
    response_model=list[PresetRead],
    summary="List setup-wizard presets",
    description="The deterministic preset library (BIM QC, Cost Estimation, "
    "Full Lifecycle, …). Each preset resolves to its full module set so the "
    "wizard's right-pane preview renders without a second call.",
)
async def list_wizard_presets(
    user_id: CurrentUserId,
) -> list[PresetRead]:
    return profile_service.list_presets()


@router.get(
    "/{project_id}/profile",
    response_model=ProjectProfileResult,
    summary="Get a project's setup profile + resolved modules",
    description="Returns the saved wizard profile if one exists. For "
    "projects created before the wizard existed (or never run through it), "
    "this auto-retrofits a default profile (focus mode off — legacy view, "
    "every module enabled) so the caller always gets a usable response. "
    "Idempotent: repeat calls return the same profile without duplicating "
    "rows. Matches the retrofit done by /profile/focus-mode and /modules.",
)
async def get_project_profile(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectProfileResult:
    await _verify_project_owner(service, project_id, user_id, payload)
    result = await profile_service.get_profile(service.session, project_id)
    if result is None:
        # Auto-retrofit a default profile (same as /profile/focus-mode and
        # /modules already do) so callers never see a 404 for an old project.
        # ensure_default_profile is idempotent — a concurrent caller that
        # already created the profile will short-circuit at the existence
        # check.
        result = await profile_service.ensure_default_profile(
            service.session, project_id,
        )
    return result


@router.post(
    "/{project_id}/profile",
    response_model=ProjectProfileResult,
    summary="Apply wizard answers to a project",
    description="Upsert the profile and replace the project's module "
    "assignment rows. Idempotent — re-posting recomputes from scratch.",
)
async def apply_project_profile(
    project_id: uuid.UUID,
    spec: ProfileSpec,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectProfileResult:
    await _verify_project_owner(service, project_id, user_id, payload)
    return await profile_service.apply_profile(
        service.session, project_id, spec, _user_uuid(user_id),
    )


@router.post(
    "/{project_id}/profile/recompute",
    response_model=ProjectProfileResult,
    summary="Re-run scoring with the stored profile",
    description="Use after a module is added to the platform or scoring "
    "weights are recalibrated. Keeps the saved wizard answers.",
)
async def recompute_project_profile(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectProfileResult:
    await _verify_project_owner(service, project_id, user_id, payload)
    try:
        return await profile_service.recompute(service.session, project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc


@router.patch(
    "/{project_id}/profile/focus-mode",
    response_model=ProjectProfileResult,
    summary="Toggle the numbered/greyed sidebar focus mode",
    description="Master switch. False = legacy view (every module ungreyed, "
    "no route line). Auto-retrofits a default profile if none exists.",
)
async def set_project_focus_mode(
    project_id: uuid.UUID,
    body: FocusModePatch,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> ProjectProfileResult:
    await _verify_project_owner(service, project_id, user_id, payload)
    return await profile_service.set_focus_mode(
        service.session, project_id, body.focus_mode_enabled,
    )


@router.get(
    "/{project_id}/modules",
    response_model=list[ProjectModuleRead],
    summary="Resolved module assignments for the sidebar",
    description="Phase-ordered, ordinal-numbered module rows. Retrofits a "
    "default profile (focus mode off — legacy view) for projects created "
    "before the wizard existed, so the sidebar always has data.",
)
async def list_project_modules(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: ProjectService = Depends(_get_service),
) -> list[ProjectModuleRead]:
    await _verify_project_owner(service, project_id, user_id, payload)
    result = await profile_service.get_profile(service.session, project_id)
    if result is None:
        result = await profile_service.ensure_default_profile(
            service.session, project_id,
        )
    return result.modules


# ── Module presence (sidebar dimming hint) ─────────────────────────────────


@router.get(
    "/{project_id}/module-presence",
    response_model=ProjectModulePresence,
    response_model_by_alias=True,
    summary="Module presence per project",
    description=(
        "Cheap per-module 'has any row?' probe used by the sidebar to dim "
        "empty modules. Each field is True iff the corresponding module's "
        "primary project-scoped table has at least one row for this "
        "project. Missing tables (fresh DB) read as False. Cached for "
        "60 seconds per project. Probes run concurrently — typical "
        "latency is well under 200 ms even with 50+ modules."
    ),
)
async def get_module_presence(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ProjectService = Depends(_get_service),
) -> ProjectModulePresence:
    """Return ``ProjectModulePresence`` for ``project_id``.

    Auth: requires a valid JWT (``CurrentUserId``) plus project
    ownership / admin (via :func:`_verify_project_owner`). The probe
    itself runs against the request session — no extra connection.
    """
    await _verify_project_owner(service, project_id, user_id, payload)
    presence = await probe_project_modules(session, project_id)
    # ``probe_project_modules`` returns sidebar slugs (incl. "5d");
    # ``model_validate`` resolves the ``5d`` → ``five_d`` alias.
    return ProjectModulePresence.model_validate(presence)
