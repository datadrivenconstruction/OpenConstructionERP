"""CDE (Common Data Environment) API routes.

Endpoints:
    GET    /containers?project_id=X              - List containers
    POST   /containers                           - Create container
    GET    /containers/{container_id}             - Get single container
    PATCH  /containers/{container_id}             - Update container
    POST   /containers/{container_id}/transition  - CDE state transition
    GET    /containers/{container_id}/revisions   - List revisions
    POST   /containers/{container_id}/revisions   - Create new revision
    GET    /revisions/{revision_id}               - Get single revision
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.cde.schemas import (
    ContainerCreate,
    ContainerResponse,
    ContainerUpdate,
    RevisionCreate,
    RevisionResponse,
    StateTransitionRequest,
)
from app.modules.cde.service import CDEService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CDEService:
    return CDEService(session)


def _container_to_response(container: object) -> ContainerResponse:
    """Build a ContainerResponse from a DocumentContainer ORM object."""
    return ContainerResponse(
        id=container.id,  # type: ignore[attr-defined]
        project_id=container.project_id,  # type: ignore[attr-defined]
        container_code=container.container_code,  # type: ignore[attr-defined]
        originator_code=container.originator_code,  # type: ignore[attr-defined]
        functional_breakdown=container.functional_breakdown,  # type: ignore[attr-defined]
        spatial_breakdown=container.spatial_breakdown,  # type: ignore[attr-defined]
        form_code=container.form_code,  # type: ignore[attr-defined]
        discipline_code=container.discipline_code,  # type: ignore[attr-defined]
        sequence_number=container.sequence_number,  # type: ignore[attr-defined]
        classification_system=container.classification_system,  # type: ignore[attr-defined]
        classification_code=container.classification_code,  # type: ignore[attr-defined]
        cde_state=container.cde_state,  # type: ignore[attr-defined]
        suitability_code=container.suitability_code,  # type: ignore[attr-defined]
        current_revision_id=(
            str(container.current_revision_id) if container.current_revision_id else None  # type: ignore[attr-defined]
        ),
        title=container.title,  # type: ignore[attr-defined]
        description=container.description,  # type: ignore[attr-defined]
        security_classification=container.security_classification,  # type: ignore[attr-defined]
        created_by=container.created_by,  # type: ignore[attr-defined]
        metadata=getattr(container, "metadata_", {}),
        created_at=container.created_at,  # type: ignore[attr-defined]
        updated_at=container.updated_at,  # type: ignore[attr-defined]
    )


def _revision_to_response(revision: object) -> RevisionResponse:
    """Build a RevisionResponse from a DocumentRevision ORM object."""
    return RevisionResponse(
        id=revision.id,  # type: ignore[attr-defined]
        container_id=revision.container_id,  # type: ignore[attr-defined]
        revision_code=revision.revision_code,  # type: ignore[attr-defined]
        revision_number=revision.revision_number,  # type: ignore[attr-defined]
        is_preliminary=revision.is_preliminary,  # type: ignore[attr-defined]
        content_hash=revision.content_hash,  # type: ignore[attr-defined]
        file_name=revision.file_name,  # type: ignore[attr-defined]
        file_size=revision.file_size,  # type: ignore[attr-defined]
        mime_type=revision.mime_type,  # type: ignore[attr-defined]
        storage_key=revision.storage_key,  # type: ignore[attr-defined]
        status=revision.status,  # type: ignore[attr-defined]
        approved_by=(
            str(revision.approved_by) if revision.approved_by else None  # type: ignore[attr-defined]
        ),
        change_summary=revision.change_summary,  # type: ignore[attr-defined]
        created_by=revision.created_by,  # type: ignore[attr-defined]
        metadata=getattr(revision, "metadata_", {}),
        created_at=revision.created_at,  # type: ignore[attr-defined]
        updated_at=revision.updated_at,  # type: ignore[attr-defined]
    )


# ── Container List ────────────────────────────────────────────────────────────


@router.get("/containers", response_model=list[ContainerResponse])
async def list_containers(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    cde_state: str | None = Query(default=None, alias="state"),
    discipline: str | None = Query(default=None, alias="discipline"),
    service: CDEService = Depends(_get_service),
) -> list[ContainerResponse]:
    """List document containers for a project."""
    containers, _ = await service.list_containers(
        project_id,
        offset=offset,
        limit=limit,
        cde_state=cde_state,
        discipline_code=discipline,
    )
    return [_container_to_response(c) for c in containers]


# ── Container Create ──────────────────────────────────────────────────────────


@router.post("/containers", response_model=ContainerResponse, status_code=201)
async def create_container(
    data: ContainerCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("cde.create")),
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Create a new document container."""
    container = await service.create_container(data, user_id=user_id)
    return _container_to_response(container)


# ── Container Get ─────────────────────────────────────────────────────────────


@router.get("/containers/{container_id}", response_model=ContainerResponse)
async def get_container(
    container_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Get a single document container."""
    container = await service.get_container(container_id)
    return _container_to_response(container)


# ── Container Update ──────────────────────────────────────────────────────────


@router.patch("/containers/{container_id}", response_model=ContainerResponse)
async def update_container(
    container_id: uuid.UUID,
    data: ContainerUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cde.update")),
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Update a document container."""
    container = await service.update_container(container_id, data)
    return _container_to_response(container)


# ── State Transition ──────────────────────────────────────────────────────────


@router.post("/containers/{container_id}/transition", response_model=ContainerResponse)
async def transition_state(
    container_id: uuid.UUID,
    data: StateTransitionRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("cde.update")),
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Transition a container's CDE state (wip -> shared -> published -> archived)."""
    container = await service.transition_state(container_id, data)
    return _container_to_response(container)


# ── Revision List ─────────────────────────────────────────────────────────────


@router.get("/containers/{container_id}/revisions", response_model=list[RevisionResponse])
async def list_revisions(
    container_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: CDEService = Depends(_get_service),
) -> list[RevisionResponse]:
    """List revisions for a document container."""
    revisions, _ = await service.list_revisions(
        container_id,
        offset=offset,
        limit=limit,
    )
    return [_revision_to_response(r) for r in revisions]


# ── Revision Create ───────────────────────────────────────────────────────────


@router.post(
    "/containers/{container_id}/revisions",
    response_model=RevisionResponse,
    status_code=201,
)
async def create_revision(
    container_id: uuid.UUID,
    data: RevisionCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("cde.create")),
    service: CDEService = Depends(_get_service),
) -> RevisionResponse:
    """Create a new revision within a container."""
    revision = await service.create_revision(container_id, data, user_id=user_id)
    return _revision_to_response(revision)


# ── Revision Get ──────────────────────────────────────────────────────────────


@router.get("/revisions/{revision_id}", response_model=RevisionResponse)
async def get_revision(
    revision_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: CDEService = Depends(_get_service),
) -> RevisionResponse:
    """Get a single document revision."""
    revision = await service.get_revision(revision_id)
    return _revision_to_response(revision)
