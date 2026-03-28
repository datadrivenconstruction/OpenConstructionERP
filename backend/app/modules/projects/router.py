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
    await _verify_project_owner(service, project_id, user_id, payload)
    await service.delete_project(project_id)
