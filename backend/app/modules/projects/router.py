"""Projects API routes.

Endpoints:
    POST /                   — Create project (auth required)
    GET  /                   — List my projects (auth required)
    GET  /{project_id}       — Get project (auth required)
    PATCH /{project_id}      — Update project (auth required)
    DELETE /{project_id}     — Archive project (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep, SettingsDep
from app.modules.projects.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from app.modules.projects.service import ProjectService

router = APIRouter()


def _get_service(session: SessionDep, settings: SettingsDep) -> ProjectService:
    return ProjectService(session, settings)


# ── Create ────────────────────────────────────────────────────────────────


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    user_id: CurrentUserId,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Create a new project."""
    project = await service.create_project(data, uuid.UUID(user_id))
    return ProjectResponse.model_validate(project)


# ── List ──────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    user_id: CurrentUserId,
    service: ProjectService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status: str | None = Query(default=None, pattern=r"^(active|archived|template)$"),
) -> list[ProjectResponse]:
    """List projects for the current user."""
    projects, _ = await service.list_projects(
        uuid.UUID(user_id),
        offset=offset,
        limit=limit,
        status_filter=status,
    )
    return [ProjectResponse.model_validate(p) for p in projects]


# ── Get ───────────────────────────────────────────────────────────────────


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Get project by ID."""
    project = await service.get_project(project_id)
    return ProjectResponse.model_validate(project)


# ── Update ────────────────────────────────────────────────────────────────


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    user_id: CurrentUserId,
    service: ProjectService = Depends(_get_service),
) -> ProjectResponse:
    """Update project fields."""
    project = await service.update_project(project_id, data)
    return ProjectResponse.model_validate(project)


# ── Delete (archive) ─────────────────────────────────────────────────────


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProjectService = Depends(_get_service),
) -> None:
    """Archive a project (soft delete)."""
    await service.delete_project(project_id)
