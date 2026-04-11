"""Requirements & Quality Gates API routes.

Endpoints:
    POST   /                                          — Create requirement set
    GET    /?project_id=X                             — List sets for project
    GET    /{set_id}                                  — Get set with requirements
    DELETE /{set_id}                                  — Delete set
    GET    /{set_id}/export                           — Export requirements (CSV/JSON)
    POST   /{set_id}/requirements                     — Add requirement
    PATCH  /{set_id}/requirements/{req_id}            — Update requirement
    DELETE /{set_id}/requirements/{req_id}            — Delete requirement
    POST   /{set_id}/requirements/bulk                — Bulk add requirements
    POST   /{set_id}/gates/{gate_number}/run          — Run quality gate
    GET    /{set_id}/gates                            — List gate results
    POST   /{set_id}/requirements/{req_id}/link/{pos} — Link to BOQ position
    POST   /{set_id}/import/text                      — Import from text
    GET    /stats?project_id=X                        — Requirement statistics
"""

import csv
import io
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.requirements.schemas import (
    GateResultResponse,
    RequirementBulkDeleteRequest,
    RequirementBulkDeleteResult,
    RequirementCreate,
    RequirementResponse,
    RequirementSetCreate,
    RequirementSetDetail,
    RequirementSetResponse,
    RequirementSetUpdate,
    RequirementStats,
    RequirementUpdate,
    TextImportRequest,
)
from app.modules.requirements.service import RequirementsService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> RequirementsService:
    return RequirementsService(session)


def _set_to_response(item: object) -> RequirementSetResponse:
    """Build a RequirementSetResponse from a RequirementSet ORM object."""
    return RequirementSetResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        name=item.name,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        source_type=item.source_type,  # type: ignore[attr-defined]
        source_filename=item.source_filename,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        gate_status=item.gate_status,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _req_to_response(item: object) -> RequirementResponse:
    """Build a RequirementResponse from a Requirement ORM object."""
    confidence_raw = getattr(item, "confidence", None)
    confidence_val: float | None = None
    if confidence_raw is not None:
        try:
            confidence_val = float(confidence_raw)
        except (ValueError, TypeError):
            confidence_val = None

    return RequirementResponse(
        id=item.id,  # type: ignore[attr-defined]
        requirement_set_id=item.requirement_set_id,  # type: ignore[attr-defined]
        entity=item.entity,  # type: ignore[attr-defined]
        attribute=item.attribute,  # type: ignore[attr-defined]
        constraint_type=item.constraint_type,  # type: ignore[attr-defined]
        constraint_value=item.constraint_value,  # type: ignore[attr-defined]
        unit=item.unit,  # type: ignore[attr-defined]
        category=item.category,  # type: ignore[attr-defined]
        priority=item.priority,  # type: ignore[attr-defined]
        confidence=confidence_val,
        source_ref=item.source_ref,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        linked_position_id=item.linked_position_id,  # type: ignore[attr-defined]
        notes=item.notes,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _gate_to_response(item: object) -> GateResultResponse:
    """Build a GateResultResponse from a GateResult ORM object."""
    score_raw = getattr(item, "score", "0")
    try:
        score_val = float(score_raw)
    except (ValueError, TypeError):
        score_val = 0.0

    return GateResultResponse(
        id=item.id,  # type: ignore[attr-defined]
        requirement_set_id=item.requirement_set_id,  # type: ignore[attr-defined]
        gate_number=item.gate_number,  # type: ignore[attr-defined]
        gate_name=item.gate_name,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        score=score_val,
        findings=item.findings,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
    )


def _set_to_detail(item: object) -> RequirementSetDetail:
    """Build a RequirementSetDetail from a RequirementSet ORM with relationships."""
    reqs = getattr(item, "requirements", [])
    gates = getattr(item, "gate_results", [])

    return RequirementSetDetail(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        name=item.name,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        source_type=item.source_type,  # type: ignore[attr-defined]
        source_filename=item.source_filename,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        gate_status=item.gate_status,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        requirements=[_req_to_response(r) for r in reqs],
        gate_results=[_gate_to_response(g) for g in gates],
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Stats ───────────────────────────────────────────────────────────────────


@router.get("/stats/", response_model=RequirementStats)
async def get_stats(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RequirementsService = Depends(_get_service),
) -> RequirementStats:
    """Aggregated requirement stats for a project."""
    data = await service.get_stats(project_id)
    return RequirementStats(**data)


# ── Create set ──────────────────────────────────────────────────────────────


@router.post("/", response_model=RequirementSetResponse, status_code=201)
async def create_set(
    data: RequirementSetCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetResponse:
    """Create a new requirement set."""
    try:
        item = await service.create_set(data, user_id=user_id)
        return _set_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create requirement set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create requirement set — operation aborted",
        )


# ── List sets ───────────────────────────────────────────────────────────────


@router.get("/", response_model=list[RequirementSetResponse])
async def list_sets(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: RequirementsService = Depends(_get_service),
) -> list[RequirementSetResponse]:
    """List requirement sets for a project."""
    items, _ = await service.list_sets(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
    )
    return [_set_to_response(i) for i in items]


# ── Get set detail ──────────────────────────────────────────────────────────


@router.get("/{set_id}", response_model=RequirementSetDetail)
async def get_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetDetail:
    """Get a requirement set with all its requirements and gate results."""
    item = await service.get_set(set_id)
    return _set_to_detail(item)


# ── Export requirements ─────────────────────────────────────────────────────

_EXPORT_COLUMNS = [
    "entity",
    "attribute",
    "constraint_type",
    "constraint_value",
    "unit",
    "category",
    "priority",
    "status",
    "confidence",
    "source_ref",
    "notes",
]


@router.get("/{set_id}/export/", response_model=None)
async def export_requirements(
    set_id: uuid.UUID,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RequirementsService = Depends(_get_service),
):
    """Export all requirements for a set as CSV or JSON."""
    item = await service.get_set(set_id)
    reqs = getattr(item, "requirements", [])
    rows = [_req_to_response(r) for r in reqs]

    if format == "json":
        data = [{col: getattr(r, col, "") for col in _EXPORT_COLUMNS} for r in rows]
        return JSONResponse(
            content=data,
            headers={
                "Content-Disposition": f'attachment; filename="requirements_{set_id}.json"',
            },
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_COLUMNS)
    for r in rows:
        writer.writerow([getattr(r, col, "") for col in _EXPORT_COLUMNS])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="requirements_{set_id}.csv"',
        },
    )


# ── Update set (PATCH) ──────────────────────────────────────────────────────


@router.patch("/{set_id}", response_model=RequirementSetResponse)
async def update_set(
    set_id: uuid.UUID,
    data: RequirementSetUpdate,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetResponse:
    """Patch fields on a requirement set after creation.

    Lets users rename a set, edit its description, change the source
    type, or update the workflow status without having to delete and
    recreate (which would lose history and any BIM/BOQ links the set's
    requirements own).  Project re-assignment is intentionally NOT
    supported here — sets are project-scoped at creation.
    """
    try:
        item = await service.update_set(set_id, data.model_dump(exclude_unset=True))
        return _set_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to update requirement set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update requirement set",
        )


# ── Delete set ──────────────────────────────────────────────────────────────


@router.delete("/{set_id}", status_code=204)
async def delete_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> None:
    """Delete a requirement set and all its data."""
    await service.delete_set(set_id)


# ── Bulk delete requirements ────────────────────────────────────────────────


@router.post(
    "/{set_id}/requirements/bulk-delete/",
    response_model=RequirementBulkDeleteResult,
)
async def bulk_delete_requirements(
    set_id: uuid.UUID,
    data: RequirementBulkDeleteRequest,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementBulkDeleteResult:
    """Delete every requirement whose id is in the list (single transaction).

    Ids that do not exist OR belong to a different set are silently
    skipped — the response carries the actual delete count and skipped
    count so the UI can show "deleted N of M" if there is a mismatch.
    Each successful delete fires the standard
    ``requirements.requirement.deleted`` event so vector indexes stay
    in sync.
    """
    try:
        deleted, skipped = await service.bulk_delete_requirements(
            set_id, data.requirement_ids
        )
        return RequirementBulkDeleteResult(
            deleted_count=deleted, skipped_count=skipped
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to bulk-delete requirements for set %s", set_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to bulk-delete requirements",
        )


# ── Add requirement ─────────────────────────────────────────────────────────


@router.post(
    "/{set_id}/requirements/",
    response_model=RequirementResponse,
    status_code=201,
)
async def add_requirement(
    set_id: uuid.UUID,
    data: RequirementCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Add a requirement to a set."""
    try:
        item = await service.add_requirement(set_id, data, user_id=user_id)
        return _req_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to add requirement")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add requirement",
        )


# ── Bulk add requirements ───────────────────────────────────────────────────


@router.post(
    "/{set_id}/requirements/bulk/",
    response_model=list[RequirementResponse],
    status_code=201,
)
async def bulk_add_requirements(
    set_id: uuid.UUID,
    data: list[RequirementCreate],
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> list[RequirementResponse]:
    """Bulk add requirements to a set."""
    try:
        items = await service.bulk_add_requirements(set_id, data, user_id=user_id)
        return [_req_to_response(i) for i in items]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to bulk add requirements")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to bulk add requirements",
        )


# ── Update requirement ──────────────────────────────────────────────────────


@router.patch(
    "/{set_id}/requirements/{req_id}",
    response_model=RequirementResponse,
)
async def update_requirement(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    data: RequirementUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Update a requirement."""
    item = await service.update_requirement(req_id, data)
    return _req_to_response(item)


# ── Delete requirement ──────────────────────────────────────────────────────


@router.delete("/{set_id}/requirements/{req_id}", status_code=204)
async def delete_requirement(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> None:
    """Delete a requirement from a set."""
    await service.delete_requirement(set_id, req_id)


# ── Run quality gate ────────────────────────────────────────────────────────


@router.post(
    "/{set_id}/gates/{gate_number}/run/",
    response_model=GateResultResponse,
    status_code=200,
)
async def run_gate(
    set_id: uuid.UUID,
    gate_number: int,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> GateResultResponse:
    """Execute a quality gate on a requirement set."""
    try:
        result = await service.run_gate(set_id, gate_number, user_id=user_id)
        return _gate_to_response(result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to run gate %d for set %s", gate_number, set_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to run quality gate — evaluation incomplete",
        )


# ── List gate results ───────────────────────────────────────────────────────


@router.get("/{set_id}/gates/", response_model=list[GateResultResponse])
async def list_gates(
    set_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RequirementsService = Depends(_get_service),
) -> list[GateResultResponse]:
    """List all gate results for a requirement set."""
    results = await service.list_gate_results(set_id)
    return [_gate_to_response(r) for r in results]


# ── Link requirement to BOQ position ────────────────────────────────────────


@router.post(
    "/{set_id}/requirements/{req_id}/link/{position_id}",
    response_model=RequirementResponse,
)
async def link_to_position(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    position_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Link a requirement to a BOQ position."""
    item = await service.link_to_position(req_id, position_id)
    return _req_to_response(item)


# ── Import from text ────────────────────────────────────────────────────────


@router.post(
    "/{set_id}/import/text/",
    response_model=RequirementSetDetail,
    status_code=201,
)
async def import_from_text(
    set_id: uuid.UUID,
    data: TextImportRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetDetail:
    """Import requirements from structured text into a new set.

    The set_id in the URL is used to resolve the project_id.
    A new set is created with the imported requirements.
    """
    try:
        result_set = await service.import_from_text(set_id, data, user_id=user_id)
        return _set_to_detail(result_set)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to import requirements from text")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to import requirements from text — parsing incomplete",
        )


# ── BIM linking endpoints ────────────────────────────────────────────────


class BIMLinkBody(BaseModel):
    """Request body for the requirement → BIM elements link endpoint."""

    bim_element_ids: list[str]
    replace: bool = False


@router.patch(
    "/{set_id}/requirements/{req_id}/bim-links/",
    response_model=RequirementResponse,
)
async def link_requirement_to_bim(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    body: BIMLinkBody,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Pin a requirement to one or more BIM elements.

    By default the new ids are merged with whatever was there
    previously (additive linking — no accidental data loss).  Pass
    ``replace=true`` to overwrite the array entirely.

    The link is stored under ``metadata_["bim_element_ids"]`` so we
    don't need a schema migration.  After mutation we publish the
    standardized ``requirements.requirement.linked_bim`` event so the
    vector indexer refreshes the embedding to reflect the new links.
    """
    item = await service.link_to_bim_elements(
        req_id, body.bim_element_ids, replace=body.replace
    )
    if item.requirement_set_id != set_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requirement does not belong to the specified set",
        )
    return _req_to_response(item)


@router.get(
    "/by-bim-element/",
    response_model=list[RequirementResponse],
)
async def list_requirements_by_bim_element(
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
    bim_element_id: str = Query(..., description="UUID of the BIM element"),
    project_id: uuid.UUID | None = Query(default=None),
) -> list[RequirementResponse]:
    """Reverse query: every requirement that pins ``bim_element_id``.

    Used by the BIM viewer's element details panel and the AI advisor's
    structured project state to surface requirements relevant to the
    currently selected element.  Pass ``project_id`` to scope the
    candidate set; otherwise all requirements the caller has access to
    are scanned (slower but works for tenant-wide queries).
    """
    rows = await service.list_by_bim_element(bim_element_id, project_id=project_id)
    return [_req_to_response(r) for r in rows]


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` are wired via the shared
# factory (see ``include_router`` at the bottom of this file).  The
# similar-requirements endpoint below stays module-specific because it
# needs to validate set/req parent linkage.


@router.get(
    "/{set_id}/requirements/{req_id}/similar/",
    dependencies=[Depends(RequirePermission("requirements.read"))],
)
async def requirement_similar(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=True),
) -> dict[str, Any]:
    """Return requirements semantically similar to the given one.

    Defaults to **cross-project** — that's the highest-value use case
    for the requirements module: estimators want to find how a similar
    constraint was handled on past projects so they can reuse the
    spec text and the linked BOQ rate.
    """
    from sqlalchemy.orm import selectinload

    from app.core.vector_index import find_similar
    from app.modules.requirements.models import Requirement
    from app.modules.requirements.vector_adapter import requirement_vector_adapter

    stmt = (
        select(Requirement)
        .options(selectinload(Requirement.requirement_set))
        .where(Requirement.id == req_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Requirement not found")
    if row.requirement_set_id != set_id:
        raise HTTPException(
            status_code=400,
            detail="Requirement does not belong to the specified set",
        )

    project_id = (
        str(row.requirement_set.project_id)
        if row.requirement_set is not None and row.requirement_set.project_id
        else None
    )
    hits = await find_similar(
        requirement_vector_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
    )
    return {
        "source_id": str(req_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── Mount vector status + reindex via the shared factory ────────────────
#
# Requirements rows are scoped by ``RequirementSet.project_id`` rather
# than a direct column, so we pass a custom loader that performs the
# join for us.
from sqlalchemy.orm import selectinload as _selectinload  # noqa: E402

from app.core.vector_index import COLLECTION_REQUIREMENTS  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.requirements.models import (  # noqa: E402
    Requirement as _Requirement,
)
from app.modules.requirements.models import (  # noqa: E402
    RequirementSet as _RequirementSet,
)
from app.modules.requirements.vector_adapter import (  # noqa: E402
    requirement_vector_adapter as _requirement_vector_adapter,
)


async def _requirements_loader(
    session: Any, project_id: uuid.UUID | None
) -> list[Any]:
    stmt = select(_Requirement).options(
        _selectinload(_Requirement.requirement_set)
    )
    if project_id is not None:
        stmt = stmt.join(
            _RequirementSet,
            _Requirement.requirement_set_id == _RequirementSet.id,
        ).where(_RequirementSet.project_id == project_id)
    return list((await session.execute(stmt)).scalars().all())


router.include_router(
    create_vector_routes(
        collection=COLLECTION_REQUIREMENTS,
        adapter=_requirement_vector_adapter,
        loader=_requirements_loader,
        read_permission="requirements.read",
        write_permission="requirements.update",
    )
)
