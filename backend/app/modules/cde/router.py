"""‌⁠‍CDE (Common Data Environment) API routes.

Endpoints:
    GET    /suitability-codes                     - ISO 19650 suitability codes
    GET    /containers?project_id=X              - List containers
    POST   /containers                           - Create container
    GET    /containers/{container_id}             - Get single container
    PATCH  /containers/{container_id}             - Update container
    POST   /containers/{container_id}/transition  - CDE state transition
    GET    /containers/{container_id}/history     - State transition audit log
    GET    /containers/{container_id}/transmittals - Transmittals carrying revisions
    GET    /containers/{container_id}/revisions   - List revisions
    POST   /containers/{container_id}/revisions   - Create new revision
    GET    /revisions/{revision_id}               - Get single revision
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.cde.schemas import (
    CDEStatsResponse,
    ContainerCreate,
    ContainerResponse,
    ContainerTransmittalLink,
    ContainerUpdate,
    RevisionCreate,
    RevisionResponse,
    StateTransitionEntry,
    StateTransitionRequest,
    SuitabilityCodeEntry,
    SuitabilityCodesResponse,
)
from app.modules.cde.service import CDEService
from app.modules.cde.suitability import SUITABILITY_CODES

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CDEService:
    return CDEService(session)


def _container_to_response(container: object) -> ContainerResponse:
    """‌⁠‍Build a ContainerResponse from a DocumentContainer ORM object."""
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
    """‌⁠‍Build a RevisionResponse from a DocumentRevision ORM object."""
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
        document_id=getattr(revision, "document_id", None),
        created_by=revision.created_by,  # type: ignore[attr-defined]
        metadata=getattr(revision, "metadata_", {}),
        created_at=revision.created_at,  # type: ignore[attr-defined]
        updated_at=revision.updated_at,  # type: ignore[attr-defined]
    )


# ── Suitability codes (ISO 19650 lookup) ─────────────────────────────────────


@router.get(
    "/suitability-codes",
    response_model=SuitabilityCodesResponse,
    include_in_schema=False,
)
@router.get("/suitability-codes/", response_model=SuitabilityCodesResponse)
async def list_suitability_codes() -> SuitabilityCodesResponse:
    """Return the ISO 19650 suitability-code table.

    Used by the frontend container-create/edit dropdown to drive a state-aware
    picker. Labels here are English defaults — the frontend runs them through
    i18n using the code as the key (``cde.suitability_<code>``).
    """
    all_entries: list[SuitabilityCodeEntry] = []
    by_state: dict[str, list[SuitabilityCodeEntry]] = {}
    for state, entries in SUITABILITY_CODES.items():
        bucket: list[SuitabilityCodeEntry] = []
        for code, label in entries:
            entry = SuitabilityCodeEntry(code=code, label=label, state=state)
            bucket.append(entry)
            all_entries.append(entry)
        by_state[state] = bucket
    return SuitabilityCodesResponse(codes=all_entries, by_state=by_state)


# ── Stats ────────────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=CDEStatsResponse,
    dependencies=[Depends(RequirePermission("cde.read"))],
    include_in_schema=False,
)
@router.get(
    "/stats/",
    response_model=CDEStatsResponse,
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def cde_stats(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: CDEService = Depends(_get_service),
) -> CDEStatsResponse:
    """Aggregate CDE statistics for a project.

    Returns total containers, breakdown by CDE state and discipline,
    and count of containers with at least one revision.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_stats(project_id)


# ── Container List ────────────────────────────────────────────────────────────


# NOTE on the no-trailing-slash alias below:
# The app runs with ``redirect_slashes=False`` (see app.main), so a request
# to ``/api/v1/cde/containers`` (no trailing slash) does NOT auto-redirect
# to ``/containers/`` — it 404s outright. The real frontend always calls
# ``/v1/cde/containers/`` (with the slash), so the module is fully
# functional in-app; the 404 only bites bare-path probes, crawlers, and
# any reverse proxy that strips trailing slashes. We mirror the canonical
# handler on the slash-less path (hidden from the schema) so those callers
# get a coherent, authorised 200/empty-state instead of a misleading
# "module is dead" 404. (CRAWL-CDE-404 root cause.)
@router.get(
    "/containers",
    response_model=list[ContainerResponse],
    dependencies=[Depends(RequirePermission("cde.read"))],
    include_in_schema=False,
)
@router.get(
    "/containers/",
    response_model=list[ContainerResponse],
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def list_containers(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    cde_state: str | None = Query(default=None, alias="state"),
    discipline: str | None = Query(default=None, alias="discipline"),
    service: CDEService = Depends(_get_service),
) -> list[ContainerResponse]:
    """List document containers for a project."""
    await verify_project_access(project_id, user_id, session)
    containers, _ = await service.list_containers(
        project_id,
        offset=offset,
        limit=limit,
        cde_state=cde_state,
        discipline_code=discipline,
    )
    return [_container_to_response(c) for c in containers]


# ── Container Create ──────────────────────────────────────────────────────────


@router.post(
    "/containers/",
    response_model=ContainerResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("cde.create"))],
)
async def create_container(
    data: ContainerCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Create a new document container."""
    from fastapi import HTTPException
    from fastapi import status as _status

    await verify_project_access(data.project_id, user_id, session)
    logger.info(
        "CDE create_container request: project=%s code=%s state=%s user=%s",
        data.project_id,
        data.container_code,
        data.cde_state,
        user_id,
    )
    try:
        container = await service.create_container(data, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CDE create_container failed for project=%s", data.project_id)
        raise HTTPException(
            status_code=_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Create failed: {exc.__class__.__name__}: {exc}",
        ) from exc
    return _container_to_response(container)


# ── Container Get ─────────────────────────────────────────────────────────────


@router.get(
    "/containers/{container_id}",
    response_model=ContainerResponse,
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def get_container(
    container_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Get a single document container."""
    container = await service.get_container(container_id)
    await verify_project_access(container.project_id, user_id, session)
    return _container_to_response(container)


# ── Container Update ──────────────────────────────────────────────────────────


@router.patch(
    "/containers/{container_id}",
    response_model=ContainerResponse,
    dependencies=[Depends(RequirePermission("cde.update"))],
)
async def update_container(
    container_id: uuid.UUID,
    data: ContainerUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Update a document container."""
    existing = await service.get_container(container_id)
    await verify_project_access(existing.project_id, user_id, session)
    container = await service.update_container(container_id, data)
    return _container_to_response(container)


# ── State Transition ──────────────────────────────────────────────────────────


@router.post(
    "/containers/{container_id}/transition/",
    response_model=ContainerResponse,
    dependencies=[Depends(RequirePermission("cde.update"))],
)
async def transition_state(
    container_id: uuid.UUID,
    data: StateTransitionRequest,
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> ContainerResponse:
    """Transition a container's CDE state (wip -> shared -> published -> archived).

    Role-based gate validation is performed via the ISO 19650 CDEStateMachine.
    Gate B (SHARED → PUBLISHED) also requires ``approver_signature`` in the
    request body.
    """
    user_role = user_payload.get("role", "editor")
    user_id = user_payload.get("sub")
    existing = await service.get_container(container_id)
    await verify_project_access(existing.project_id, user_id, session)
    container = await service.transition_state(
        container_id,
        data,
        user_role=user_role,
        user_id=user_id,
    )
    return _container_to_response(container)


# ── Container History (audit log) ────────────────────────────────────────────


@router.get(
    "/containers/{container_id}/history/",
    response_model=list[StateTransitionEntry],
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def get_container_history(
    container_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> list[StateTransitionEntry]:
    """Return the state-transition audit log for a container, newest first."""
    container = await service.get_container(container_id)
    await verify_project_access(container.project_id, user_id, session)
    rows = await service.get_container_history(container_id)
    return [StateTransitionEntry.model_validate(r) for r in rows]


# ── Container Transmittals (backlink) ────────────────────────────────────────


@router.get(
    "/containers/{container_id}/transmittals/",
    response_model=list[ContainerTransmittalLink],
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def get_container_transmittals(
    container_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> list[ContainerTransmittalLink]:
    """Return transmittals that carry any revision from this container."""
    container = await service.get_container(container_id)
    await verify_project_access(container.project_id, user_id, session)
    return await service.get_container_transmittals(container_id)


# ── Revision List ─────────────────────────────────────────────────────────────


@router.get(
    "/containers/{container_id}/revisions/",
    response_model=list[RevisionResponse],
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def list_revisions(
    container_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: CDEService = Depends(_get_service),
) -> list[RevisionResponse]:
    """List revisions for a document container."""
    container = await service.get_container(container_id)
    await verify_project_access(container.project_id, user_id, session)
    revisions, _ = await service.list_revisions(
        container_id,
        offset=offset,
        limit=limit,
    )
    return [_revision_to_response(r) for r in revisions]


# ── Revision Create ───────────────────────────────────────────────────────────


@router.post(
    "/containers/{container_id}/revisions/",
    response_model=RevisionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("cde.create"))],
)
async def create_revision(
    container_id: uuid.UUID,
    data: RevisionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> RevisionResponse:
    """Create a new revision within a container."""
    container = await service.get_container(container_id)
    await verify_project_access(container.project_id, user_id, session)
    revision = await service.create_revision(container_id, data, user_id=user_id)
    return _revision_to_response(revision)


# ── Revision Get ──────────────────────────────────────────────────────────────


@router.get(
    "/revisions/{revision_id}",
    response_model=RevisionResponse,
    dependencies=[Depends(RequirePermission("cde.read"))],
)
async def get_revision(
    revision_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CDEService = Depends(_get_service),
) -> RevisionResponse:
    """Get a single document revision."""
    revision = await service.get_revision(revision_id)
    container = await service.get_container(revision.container_id)
    await verify_project_access(container.project_id, user_id, session)
    return _revision_to_response(revision)
