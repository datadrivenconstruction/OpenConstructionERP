# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requirements & Quality Gates API routes.

Endpoints:
    POST   /                                          - Create requirement set
    GET    /?project_id=X                             - List sets for project
    GET    /{set_id}                                  - Get set with requirements
    DELETE /{set_id}                                  - Delete set
    GET    /{set_id}/export                           - Export requirements (CSV/JSON)
    POST   /{set_id}/requirements                     - Add requirement
    PATCH  /{set_id}/requirements/{req_id}            - Update requirement
    DELETE /{set_id}/requirements/{req_id}            - Delete requirement
    POST   /{set_id}/requirements/bulk                - Bulk add requirements
    POST   /{set_id}/gates/{gate_number}/run          - Run quality gate
    GET    /{set_id}/gates                            - List gate results
    POST   /{set_id}/requirements/{req_id}/link/{pos} - Link to BOQ position
    POST   /{set_id}/import/text                      - Import from text
    GET    /stats?project_id=X                        - Requirement statistics
"""

import csv
import io
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.requirements.intl import PRIORITY_ORDER, priority_label
from app.modules.requirements.lifecycle import (
    CYCLE_QUESTIONS,
    DEFAULT_VOCABULARY,
    ORIGINATOR_ROLES,
    PHASE_SPINE,
    PHASE_SYSTEMS,
    VERIFICATION_METHODS,
    VOCABULARIES,
    VOCABULARY_TERMS,
    originator_role_label,
    phase_label,
    phase_rank,
    verification_label,
    vocabulary_term,
)
from app.modules.requirements.schemas import (
    CycleVocabularyResponse,
    DeliverableCoverage,
    DeliverableCreate,
    DeliverableResponse,
    DeliverableTypeCoverage,
    DeliverableUpdate,
    GateResultResponse,
    MatrixCell,
    MatrixResponse,
    MatrixRow,
    PhaseOption,
    PositionLinkCreate,
    PositionLinkResponse,
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
    VocabularyTerm,
)
from app.modules.requirements.service import RequirementsService

router = APIRouter(tags=["requirements"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> RequirementsService:
    return RequirementsService(session)


def _set_to_response(item: object) -> RequirementSetResponse:
    """Build a RequirementSetResponse from a RequirementSet ORM object.

    Validated from the object for the same reason as ``_req_to_response``: a
    hand-written column list silently drops whatever was added after it.
    """
    return RequirementSetResponse.model_validate(item, from_attributes=True)


def _req_to_response(item: object) -> RequirementResponse:
    """Build a RequirementResponse from a Requirement ORM object.

    Validated from the object rather than assembled field by field. The list
    written out here used to be the third copy of the column set in this module,
    and the copies had no way of noticing each other: a field added to the
    schema was accepted, stored, and then dropped on the way back out, so the
    API answered with a default and nothing failed.

    The one conversion this needed - the confidence column stores the text of a
    float - now lives on the schema, where every other reader gets it too.
    """
    return RequirementResponse.model_validate(item, from_attributes=True)


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

    detail = RequirementSetDetail.model_validate(item, from_attributes=True)
    # The two collections are assigned rather than left to the nested schemas:
    # both children need the same conversions their own builders apply, and
    # routing them through those builders keeps one definition of each.
    detail.requirements = [_req_to_response(r) for r in reqs]
    detail.gate_results = [_gate_to_response(g) for g in gates]
    return detail


# ── Stats ───────────────────────────────────────────────────────────────────


@router.get("/stats/", response_model=RequirementStats)
async def get_stats(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementStats:
    """Aggregated requirement stats for a project."""
    # IDOR guard: the global requirements.read role is not project-scoped, so
    # verify the caller can access this project before leaking its aggregate
    # requirement counts/statuses (cross-tenant leak otherwise).
    await verify_project_access(project_id, str(user_id), session)
    data = await service.get_stats(project_id)
    return RequirementStats(**data)


# ── The cycle vocabulary ────────────────────────────────────────────────────


@router.get("/vocabulary/", response_model=CycleVocabularyResponse)
async def get_cycle_vocabulary(
    vocabulary: str = Query(default=DEFAULT_VOCABULARY),
    lang: str = Query(default="en"),
    _perm: None = Depends(RequirePermission("requirements.read")),
) -> CycleVocabularyResponse:
    """Every controlled word the requirements cycle uses, in one language.

    Served rather than shipped in the frontend bundle. The phase spine, the
    verification methods and the party roles are domain data that moves with
    the platform, not with the design, and a screen that hard-coded them would
    have to be rebuilt to learn a new phase.

    ``lang`` accepts a full locale. ``es-CL`` falls back to ``es`` before it
    falls back to English, so the regional locales the platform ships do not
    skip a perfectly good Spanish label.
    """
    return CycleVocabularyResponse(
        vocabulary=vocabulary if vocabulary in VOCABULARIES else DEFAULT_VOCABULARY,
        language=lang,
        terms=[VocabularyTerm(key=term, label=vocabulary_term(term, vocabulary, lang)) for term in VOCABULARY_TERMS],
        phases=[
            PhaseOption(
                key=phase,
                label=phase_label(phase, lang),
                rank=phase_rank(phase),
                # A system that does not name this phase separately is left
                # out, so the caller can tell that apart from an empty name.
                systems={
                    system: names[phase] for system, names in PHASE_SYSTEMS.items() if names.get(phase) is not None
                },
            )
            for phase in PHASE_SPINE
        ],
        verification_methods=[
            VocabularyTerm(key=method, label=verification_label(method, lang)) for method in VERIFICATION_METHODS
        ],
        originator_roles=[
            VocabularyTerm(key=role, label=originator_role_label(role, lang)) for role in ORIGINATOR_ROLES
        ],
        priorities=[VocabularyTerm(key=p, label=priority_label(p, lang)) for p in PRIORITY_ORDER],
        questions=[question for question, _field in CYCLE_QUESTIONS],
    )


# ── Create set ──────────────────────────────────────────────────────────────


class _RequirementSetCreateBody(BaseModel):
    """Body schema for create_set when project_id is supplied via query.

    Mirrors RequirementSetCreate but with project_id optional so SDK users
    can pass it either in the body OR as ``?project_id=...`` (audit P2-2).
    The handler merges both into the canonical RequirementSetCreate before
    calling the service, so downstream code is unchanged.
    """

    project_id: uuid.UUID | None = None
    name: str = ""
    description: str = ""
    source_type: str = "manual"
    source_filename: str = ""
    vocabulary: str = DEFAULT_VOCABULARY
    metadata: dict[str, Any] = {}


@router.post("/", response_model=RequirementSetResponse, status_code=201)
async def create_set(
    data: _RequirementSetCreateBody,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetResponse:
    """Create a new requirement set.

    ``project_id`` may be supplied in the request body OR as a query
    parameter. Body wins when both are present.
    """
    effective_project_id = data.project_id or project_id
    if effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="project_id is required (body or ?project_id= query parameter)",
        )
    # IDOR guard: this route reads no row, so the project is whatever the
    # caller wrote, in the body or in the query string, and requirements.create
    # is a global role rather than a project-scoped one. Without this any
    # holder of it could plant a set inside another tenant's project, where it
    # appears in that tenant's set list under a name a stranger chose. The
    # check sits on the merged value so it cannot be bypassed by spelling.
    await verify_project_access(effective_project_id, str(user_id), session)
    effective_name = (data.name or "").strip()
    if not effective_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name is required and must be at least 1 character",
        )
    try:
        payload = RequirementSetCreate(
            project_id=effective_project_id,
            name=effective_name,
            description=data.description,
            source_type=data.source_type,
            source_filename=data.source_filename,
            vocabulary=data.vocabulary,
            metadata=data.metadata,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_url=False),
        ) from exc
    try:
        item = await service.create_set(payload, user_id=user_id)
        return _set_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create requirement set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create requirement set - operation aborted",
        )


# ── List sets ───────────────────────────────────────────────────────────────


@router.get("/", response_model=list[RequirementSetResponse])
async def list_sets(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
) -> list[RequirementSetResponse]:
    """List requirement sets for a project."""
    # IDOR guard: the global requirements.read role is not project-scoped, so
    # verify the caller can access this project before listing its sets
    # (names/descriptions/statuses) - cross-tenant leak otherwise.
    await verify_project_access(project_id, str(user_id), session)
    items, _ = await service.list_sets(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
    )
    return [_set_to_response(i) for i in items]


# ── Export helpers ──────────────────────────────────────────────────────────

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


def _export_rows(item: object) -> list[dict[str, Any]]:
    """Project requirements onto the canonical export column set."""
    reqs = getattr(item, "requirements", [])
    out: list[dict[str, Any]] = []
    for raw in reqs:
        resp = _req_to_response(raw)
        out.append({col: getattr(resp, col, "") or "" for col in _EXPORT_COLUMNS})
    return out


# IMPORTANT: ``/template.xlsx`` MUST come before ``/{set_id}`` so FastAPI
# matches the literal route first. Otherwise ``set_id: uuid.UUID`` swallows
# the literal and 422s on ``"template.xlsx"`` (surfacing as a 400 via the
# project-wide validation handler).
@router.get("/template.xlsx", response_model=None)
async def download_requirements_template(
    _user_id: CurrentUserId,
) -> Response:
    """Download an Excel template with headers, hints, and an operator legend."""
    from app.modules.requirements.excel_io import build_template_xlsx

    payload = build_template_xlsx()
    return Response(
        content=payload,
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={
            "Content-Disposition": 'attachment; filename="requirements_template.xlsx"',
        },
    )


@router.get(
    "/by-bim-element/",
    response_model=list[RequirementResponse],
)
async def list_requirements_by_bim_element(
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
    bim_element_id: str = Query(..., description="UUID of the BIM element"),
    project_id: uuid.UUID = Query(..., description="Project scope for the search"),
) -> list[RequirementResponse]:
    """Reverse query: every requirement that pins ``bim_element_id``.

    Used by the BIM viewer's element details panel and the AI advisor's
    structured project state to surface requirements relevant to the
    currently selected element.  ``project_id`` is required and the caller
    must have access to it: requirements.read is a global role, so a
    tenant-wide scan without a project gate would let any holder enumerate
    every requirement across all projects (IDOR). This mirrors the sibling
    schedule module's ``/activities/by-bim-element/`` endpoint.
    """
    await verify_project_access(project_id, str(user_id), session)
    rows = await service.list_by_bim_element(bim_element_id, project_id=project_id)
    return [_req_to_response(r) for r in rows]


# ── Get set detail ──────────────────────────────────────────────────────────


@router.get("/{set_id}", response_model=RequirementSetDetail)
async def get_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetDetail:
    """Get a requirement set with all its requirements and gate results."""
    item = await service.get_set(set_id)
    await verify_project_access(item.project_id, str(user_id), session)
    return _set_to_detail(item)


@router.get("/{set_id}/export/", response_model=None)
async def export_requirements_legacy(
    set_id: uuid.UUID,
    session: SessionDep,
    format: str = Query(default="csv", pattern="^(csv|json|xlsx)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RequirementsService = Depends(_get_service),
):
    """Export all requirements (legacy ``?format=`` flavour kept for callers)."""
    return await _export_dispatch(set_id, format, service, str(user_id), session)


@router.get("/{set_id}/export.{ext}", response_model=None)
async def export_requirements(
    set_id: uuid.UUID,
    ext: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RequirementsService = Depends(_get_service),
):
    """Export all requirements as ``csv | json | xlsx``.

    The extension drives the format so callers can hard-code the URL
    (``/sets/abc/export.xlsx``) and Excel will pick the right opener.
    """
    if ext not in {"csv", "json", "xlsx"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format '{ext}'. Use csv, json, or xlsx.",
        )
    return await _export_dispatch(set_id, ext, service, str(user_id), session)


async def _export_dispatch(
    set_id: uuid.UUID,
    fmt: str,
    service: RequirementsService,
    user_id: str,
    session: SessionDep,
):
    item = await service.get_set(set_id)
    # IDOR guard: gate the export on the set's owning project. The global
    # requirements role is not project-scoped, so without this any holder
    # could dump another tenant's requirement data via the set UUID.
    await verify_project_access(item.project_id, user_id, session)
    rows = _export_rows(item)
    safe_name = (getattr(item, "name", None) or f"requirements_{set_id}").replace("/", "_").replace(
        "\\", "_"
    ).strip() or f"requirements_{set_id}"

    if fmt == "json":
        return JSONResponse(
            content=rows,
            headers={
                "Content-Disposition": attachment_disposition(f"{safe_name}.json"),
            },
        )

    if fmt == "xlsx":
        from app.modules.requirements.excel_io import export_xlsx

        payload = export_xlsx(rows, title=safe_name)
        return Response(
            content=payload,
            media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            headers={
                "Content-Disposition": attachment_disposition(f"{safe_name}.xlsx"),
            },
        )

    # csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_COLUMNS)
    for r in rows:
        writer.writerow([r.get(col, "") for col in _EXPORT_COLUMNS])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": attachment_disposition(f"{safe_name}.csv"),
        },
    )


# ── Excel / CSV import ──────────────────────────────────────────────────────


class ImportFromFileResponse(BaseModel):
    """Response from POST /{set_id}/import/file."""

    set_id: uuid.UUID
    imported: int
    skipped: int
    warnings: list[str] = []


@router.post(
    "/{set_id}/import/file/",
    response_model=ImportFromFileResponse,
    status_code=200,
)
async def import_requirements_file(
    set_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(...),
    service: RequirementsService = Depends(_get_service),
    _perm: None = Depends(RequirePermission("requirements.update")),
) -> ImportFromFileResponse:
    """Import requirements from an Excel or CSV file into an existing set.

    The file's extension picks the parser. Each row is added to the
    set; rows missing both ``entity`` and ``attribute`` are skipped.
    Warnings (unknown operators, missing optional columns) are
    surfaced in the response so the UI can render a banner.
    """
    from app.modules.requirements.excel_io import parse_csv, parse_xlsx

    item = await service.get_set(set_id)
    await verify_project_access(item.project_id, str(user_id), session)

    # Bound the upload size in-memory. v2.9.12 removed the global file-size
    # cap, so a 500 MB CSV would OOM the worker before we even start parsing.
    # 50 MB is generous for requirement spreadsheets - typical real-world
    # files are <2 MB. Streaming + chunked parse is a future improvement.
    MAX_IMPORT_BYTES = 100 * 1024 * 1024  # 100 MB
    payload = await file.read()
    if len(payload) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Requirements import file is too large "
                f"({len(payload) // (1024 * 1024)} MB). "
                f"Maximum supported size: {MAX_IMPORT_BYTES // (1024 * 1024)} MB."
            ),
        )

    name = (file.filename or "").lower()

    # Magic-byte sniff - filename is hostile-supplied. Reject any payload
    # whose first bytes don't match the declared format before we hand the
    # buffer to openpyxl / csv.reader. Mirrors the contacts importer.
    head = payload[:8]
    if name.endswith(".xlsx"):
        if not head.startswith(b"PK\x03\x04"):
            raise HTTPException(
                status_code=415,
                detail="File does not look like a valid .xlsx (missing ZIP signature).",
            )
    elif name.endswith(".xls"):
        if not head.startswith(b"\xd0\xcf\x11\xe0"):
            raise HTTPException(
                status_code=415,
                detail="File does not look like a valid .xls (missing OLE signature).",
            )
    elif name.endswith(".csv"):
        for sig in (b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"PK\x03\x04", b"\xd0\xcf\x11\xe0"):
            if head.startswith(sig):
                raise HTTPException(
                    status_code=415,
                    detail="File does not look like CSV (binary signature detected).",
                )

    if name.endswith(".csv"):
        rows, warnings = parse_csv(payload)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        rows, warnings = parse_xlsx(payload)
    else:
        # Best-effort: if no extension, try Excel first then CSV
        rows, warnings = parse_xlsx(payload)
        if not rows and not warnings:
            rows, warnings = parse_csv(payload)

    imported = 0
    skipped = 0
    for row in rows:
        try:
            create = RequirementCreate(
                entity=row["entity"],
                attribute=row["attribute"],
                constraint_type=row["constraint_type"],
                constraint_value=row.get("constraint_value", ""),
                unit=row.get("unit", ""),
                category=row.get("category", "general"),
                priority=row.get("priority", "must"),
                source_ref=row.get("source_ref", ""),
                notes=row.get("notes", ""),
            )
        except Exception as exc:  # noqa: BLE001 - record but keep going
            skipped += 1
            warnings.append(f"Skipped row '{row.get('entity', '')}.{row.get('attribute', '')}': {exc}")
            continue
        await service.add_requirement(set_id, create, user_id=str(user_id) if user_id else "")
        imported += 1

    return ImportFromFileResponse(
        set_id=set_id,
        imported=imported,
        skipped=skipped,
        warnings=warnings,
    )


# ── Update set (PATCH) ──────────────────────────────────────────────────────


@router.patch("/{set_id}", response_model=RequirementSetResponse)
async def update_set(
    set_id: uuid.UUID,
    data: RequirementSetUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetResponse:
    """Patch fields on a requirement set after creation.

    Lets users rename a set, edit its description, change the source
    type, or update the workflow status without having to delete and
    recreate (which would lose history and any BIM/BOQ links the set's
    requirements own).  Project re-assignment is intentionally NOT
    supported here - sets are project-scoped at creation.
    """
    existing = await service.get_set(set_id)
    await verify_project_access(existing.project_id, str(user_id), session)
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
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> None:
    """Delete a requirement set and all its data."""
    existing = await service.get_set(set_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_set(set_id)


# ── Bulk delete requirements ────────────────────────────────────────────────


@router.post(
    "/{set_id}/requirements/bulk-delete/",
    response_model=RequirementBulkDeleteResult,
)
async def bulk_delete_requirements(
    set_id: uuid.UUID,
    data: RequirementBulkDeleteRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementBulkDeleteResult:
    """Delete every requirement whose id is in the list (single transaction).

    Ids that do not exist OR belong to a different set are silently
    skipped - the response carries the actual delete count and skipped
    count so the UI can show "deleted N of M" if there is a mismatch.
    Each successful delete fires the standard
    ``requirements.requirement.deleted`` event so vector indexes stay
    in sync.
    """
    # IDOR guard: gate on the set's owning project. The service only scopes
    # the deletes to set_id; without the project check any requirements.delete
    # holder could wipe another tenant's set by UUID (the per-row set-membership
    # check inside the service keeps the blast radius to this set only).
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
    try:
        deleted, skipped = await service.bulk_delete_requirements(set_id, data.requirement_ids)
        return RequirementBulkDeleteResult(deleted_count=deleted, skipped_count=skipped)
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
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Add a requirement to a set."""
    # IDOR guard: gate on the target set's project before inserting into it.
    # requirements.create is a global role, so without this any holder could
    # write requirements into another tenant's set by its UUID.
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
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
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> list[RequirementResponse]:
    """Bulk add requirements to a set."""
    # IDOR guard: requirements.create is a global role; gate on the target set's
    # project before bulk-inserting into it (cross-tenant write otherwise).
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
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
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Update a requirement."""
    # IDOR guard: gate on the requirement's REAL project (requirements.update
    # is a global role, and the service ignores set_id when resolving req_id).
    project_id = await service.get_requirement_project_id(req_id)
    await verify_project_access(project_id, str(user_id), session)
    item = await service.update_requirement(req_id, data)
    return _req_to_response(item)


# ── Delete requirement ──────────────────────────────────────────────────────


@router.delete("/{set_id}/requirements/{req_id}", status_code=204)
async def delete_requirement(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> None:
    """Delete a requirement from a set."""
    # IDOR guard: gate on the set's project (the service additionally enforces
    # that req_id belongs to set_id, so this covers the requirement too).
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
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
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> GateResultResponse:
    """Execute a quality gate on a requirement set."""
    # IDOR guard: requirements.update is a global role; gate on the set's owning
    # project before running the gate (which writes a GateResult row and
    # overwrites the set's gate_status). Cross-tenant write otherwise.
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
    try:
        result = await service.run_gate(set_id, gate_number, user_id=user_id)
        return _gate_to_response(result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to run gate %d for set %s", gate_number, set_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to run quality gate - evaluation incomplete",
        )


# ── List gate results ───────────────────────────────────────────────────────


@router.get("/{set_id}/gates/", response_model=list[GateResultResponse])
async def list_gates(
    set_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
) -> list[GateResultResponse]:
    """List all gate results for a requirement set."""
    # IDOR guard: requirements.read is a global role; gate on the set's owning
    # project before returning its gate findings (constraint values, BOQ
    # position_ids). Cross-tenant read otherwise; also adds the missing RBAC.
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
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
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Link a requirement to a BOQ position."""
    # IDOR guard: gate on the requirement's real project.
    project_id = await service.get_requirement_project_id(req_id)
    await verify_project_access(project_id, str(user_id), session)
    item = await service.link_to_position(req_id, position_id)
    return _req_to_response(item)


@router.post(
    "/{set_id}/requirements/{req_id}/positions/",
    response_model=PositionLinkResponse,
    status_code=201,
)
async def attach_position(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    data: PositionLinkCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> PositionLinkResponse:
    """Attach a requirement to one more priced position.

    Additive, unlike the older ``/link/{position_id}`` route, which can only
    hold the most recently linked one. Both remain: a caller that genuinely has
    one position keeps working unchanged.
    """
    project_id = await service.get_requirement_project_id(req_id)
    await verify_project_access(project_id, str(user_id), session)
    link = await service.attach_position(req_id, data, user_id=str(user_id or ""))
    return PositionLinkResponse.model_validate(link, from_attributes=True)


@router.get(
    "/{set_id}/requirements/{req_id}/positions/",
    response_model=list[PositionLinkResponse],
)
async def list_position_links(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
) -> list[PositionLinkResponse]:
    """Every priced position this requirement governs."""
    project_id = await service.get_requirement_project_id(req_id)
    await verify_project_access(project_id, str(user_id), session)
    links = await service.list_position_links(req_id)
    return [PositionLinkResponse.model_validate(link, from_attributes=True) for link in links]


@router.delete(
    "/{set_id}/requirements/{req_id}/positions/{position_id}",
    status_code=204,
)
async def detach_position(
    set_id: uuid.UUID,
    req_id: uuid.UUID,
    position_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> None:
    """Detach a requirement from one position."""
    project_id = await service.get_requirement_project_id(req_id)
    await verify_project_access(project_id, str(user_id), session)
    await service.detach_position(req_id, position_id)


@router.get(
    "/positions/{position_id}/requirements/",
    response_model=list[RequirementResponse],
)
async def requirements_for_position(
    position_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
) -> list[RequirementResponse]:
    """Every requirement governing one priced position.

    The direction a quantity surveyor reads. Opening a bill item and asking
    what it has to satisfy used to mean scanning every requirement in the
    project, because the link only pointed one way.
    """
    # IDOR guard: this route is addressed by position, so there is no set to
    # read the project off. Resolve it through the bill the position sits in.
    project_id = await service.get_position_project_id(position_id)
    await verify_project_access(project_id, str(user_id), session)
    items = await service.requirements_for_position(position_id)
    return [_req_to_response(item) for item in items]


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
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.create")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementSetDetail:
    """Import requirements from structured text into an existing set.

    The set_id in the URL names the set the parsed rows are appended to. The
    service resolves that set and adds to it; it does not create a second one.
    The previous wording here claimed a new set was created, which is part of
    why the absent project check below read as harmless.
    """
    # IDOR guard: gate on the set's owning project, as every other set-scoped
    # route in this module does. requirements.create is a global role and is
    # not project-scoped, so without this any holder of it could append rows to
    # another tenant's set by UUID and receive that set's full contents back in
    # the 201 body - a cross-tenant write and read from one call.
    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)
    try:
        result_set = await service.import_from_text(set_id, data, user_id=user_id)
        return _set_to_detail(result_set)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to import requirements from text")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to import requirements from text - parsing incomplete",
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
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> RequirementResponse:
    """Pin a requirement to one or more BIM elements.

    By default the new ids are merged with whatever was there
    previously (additive linking - no accidental data loss).  Pass
    ``replace=true`` to overwrite the array entirely.

    The link is stored under ``metadata_["bim_element_ids"]`` so we
    don't need a schema migration.  After mutation we publish the
    standardized ``requirements.requirement.linked_bim`` event so the
    vector indexer refreshes the embedding to reflect the new links.
    """
    # IDOR guard: requirements.update is a global role and the service resolves
    # by req_id (ignoring set_id), so gate on the requirement's real project
    # BEFORE mutating its links (replace=true can wipe them). The trailing
    # set-membership check runs post-write and does not authorize the project.
    project_id = await service.get_requirement_project_id(req_id)
    await verify_project_access(project_id, str(user_id), session)
    item = await service.link_to_bim_elements(req_id, body.bim_element_ids, replace=body.replace)
    if item.requirement_set_id != set_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requirement does not belong to the specified set",
        )
    return _req_to_response(item)


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` are wired via the shared
# factory (see ``include_router`` at the bottom of this file).  The
# similar-requirements endpoint below stays module-specific because it
# needs to validate set/req parent linkage.


# ── Validate against a BIM model ─────────────────────────────────────────


class ValidateBIMResponse(BaseModel):
    """Compact response from POST /{set_id}/validate-bim/{model_id}."""

    report_id: uuid.UUID
    status: str
    score: float
    total_checks: int
    passed: int
    warnings: int
    errors: int
    skipped_requirements: int
    duration_ms: float


@router.post(
    "/{set_id}/validate-bim/{model_id}",
    response_model=ValidateBIMResponse,
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def validate_set_against_bim_model(
    set_id: uuid.UUID,
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RequirementsService = Depends(_get_service),
) -> ValidateBIMResponse:
    """Run every requirement in a set against every element of a BIM model.

    Persists a regular ``ValidationReport`` (``target_type='bim_model'``) so
    the existing dashboard, BIM viewer badges, and SARIF export all surface
    these results without a discriminator.
    """
    from app.modules.requirements.bim_validator import (
        validate_requirement_set_against_model,
    )

    req_set = await service.get_set(set_id)
    await verify_project_access(req_set.project_id, str(user_id), session)

    requirements = list(getattr(req_set, "requirements", []) or [])
    try:
        report = await validate_requirement_set_against_model(
            session,
            req_set=req_set,
            requirements=requirements,
            model_id=model_id,
            user_id=str(user_id) if user_id else None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    meta = getattr(report, "metadata_", {}) or {}
    return ValidateBIMResponse(
        report_id=report.id,
        status=report.status,
        score=float(report.score) if report.score else 1.0,
        total_checks=report.total_rules,
        passed=report.passed_count,
        warnings=report.warning_count,
        errors=report.error_count,
        skipped_requirements=int(meta.get("requirements_skipped", 0)),
        duration_ms=float(meta.get("duration_ms", 0.0)),
    )


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

    Defaults to **cross-project** - that's the highest-value use case
    for the requirements module: estimators want to find how a similar
    constraint was handled on past projects so they can reuse the
    spec text and the linked BOQ rate.
    """
    from sqlalchemy.orm import selectinload

    from app.core.vector_index import find_similar
    from app.dependencies import allowed_project_ids_for_similar
    from app.modules.requirements.models import Requirement
    from app.modules.requirements.vector_adapter import requirement_vector_adapter

    stmt = select(Requirement).options(selectinload(Requirement.requirement_set)).where(Requirement.id == req_id)
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
    # Cross-tenant guard: you may only seed a similarity search from a
    # requirement whose project you can access (404 on denial), and the
    # cross-project results are restricted to projects the caller may reach
    # (None == admin/unrestricted, mirroring verify_project_access).
    if row.requirement_set is not None and row.requirement_set.project_id is not None:
        await verify_project_access(row.requirement_set.project_id, str(_user_id), session)
    allowed = await allowed_project_ids_for_similar(session, str(_user_id), project_id, cross_project)
    hits = await find_similar(
        requirement_vector_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
        allowed_project_ids=allowed,
    )
    return {
        "source_id": str(req_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── ISO 19650 EIR deliverables (T13) ─────────────────────────────────────


def _deliverable_to_response(item: object) -> DeliverableResponse:
    """Build a DeliverableResponse from a RequirementDeliverable ORM row."""
    accepted_at = getattr(item, "accepted_at", None)
    submitted_at = getattr(item, "submitted_at", None)
    if accepted_at is not None:
        derived_status = "accepted"
    elif submitted_at is not None:
        derived_status = "submitted"
    else:
        derived_status = "missing"
    return DeliverableResponse(
        id=item.id,  # type: ignore[attr-defined]
        requirement_id=item.requirement_id,  # type: ignore[attr-defined]
        deliverable_type=item.deliverable_type,  # type: ignore[attr-defined]
        lod=item.lod,  # type: ignore[attr-defined]
        loi=item.loi,  # type: ignore[attr-defined]
        due_milestone_id=item.due_milestone_id,  # type: ignore[attr-defined]
        submitted_at=submitted_at,
        accepted_at=accepted_at,
        notes=getattr(item, "notes", "") or "",
        status=derived_status,
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get(
    "/requirements/{requirement_id}/deliverables/",
    response_model=list[DeliverableResponse],
)
async def list_requirement_deliverables(
    requirement_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.read")),
    deliverable_type: str | None = Query(default=None, max_length=64),
    service: RequirementsService = Depends(_get_service),
) -> list[DeliverableResponse]:
    """List EIR deliverables attached to a requirement."""
    # IDOR guard: gate on the requirement's real project (requirements.read is a
    # global role, so without this any holder could list deliverables for any
    # requirement by UUID).
    project_id = await service.get_requirement_project_id(requirement_id)
    await verify_project_access(project_id, str(user_id), session)
    items = await service.list_deliverables(requirement_id, deliverable_type=deliverable_type)
    return [_deliverable_to_response(i) for i in items]


@router.post(
    "/requirements/{requirement_id}/deliverables/",
    response_model=DeliverableResponse,
    status_code=201,
)
async def create_requirement_deliverable(
    requirement_id: uuid.UUID,
    data: DeliverableCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> DeliverableResponse:
    """Attach a new EIR deliverable to a requirement."""
    # IDOR guard: gate on the requirement's real project before attaching a
    # deliverable (requirements.update is a global role; cross-tenant write
    # otherwise).
    project_id = await service.get_requirement_project_id(requirement_id)
    await verify_project_access(project_id, str(user_id), session)
    try:
        item = await service.add_deliverable(requirement_id, data)
        return _deliverable_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to add deliverable for requirement %s", requirement_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add deliverable",
        )


@router.patch(
    "/requirements/{requirement_id}/deliverables/{deliverable_id}",
    response_model=DeliverableResponse,
)
async def update_requirement_deliverable(
    requirement_id: uuid.UUID,
    deliverable_id: uuid.UUID,
    data: DeliverableUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.update")),
    service: RequirementsService = Depends(_get_service),
) -> DeliverableResponse:
    """Patch fields on an EIR deliverable row."""
    # IDOR guard: gate on the requirement's real project before patching a
    # deliverable (requirements.update is a global role; cross-tenant write
    # otherwise).
    project_id = await service.get_requirement_project_id(requirement_id)
    await verify_project_access(project_id, str(user_id), session)
    item = await service.update_deliverable(requirement_id, deliverable_id, data)
    return _deliverable_to_response(item)


@router.delete(
    "/requirements/{requirement_id}/deliverables/{deliverable_id}",
    status_code=204,
)
async def delete_requirement_deliverable(
    requirement_id: uuid.UUID,
    deliverable_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.delete")),
    service: RequirementsService = Depends(_get_service),
) -> None:
    """Hard delete an EIR deliverable row."""
    # IDOR guard: gate on the requirement's real project before hard-deleting a
    # deliverable (requirements.delete is a global role; cross-tenant destructive
    # write otherwise).
    project_id = await service.get_requirement_project_id(requirement_id)
    await verify_project_access(project_id, str(user_id), session)
    await service.delete_deliverable(requirement_id, deliverable_id)


@router.get(
    "/requirements/{requirement_id}/deliverables/coverage/",
    response_model=DeliverableCoverage,
)
async def get_requirement_deliverable_coverage(
    requirement_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.read")),
    service: RequirementsService = Depends(_get_service),
) -> DeliverableCoverage:
    """Coverage % roll-up for one requirement's EIR deliverables."""
    # IDOR guard: gate on the requirement's real project (requirements.read is a
    # global role, so without this any holder could read coverage for any
    # requirement by UUID).
    project_id = await service.get_requirement_project_id(requirement_id)
    await verify_project_access(project_id, str(user_id), session)
    payload = await service.get_deliverable_coverage(requirement_id)
    by_type = {t: DeliverableTypeCoverage(**bucket) for t, bucket in payload.get("by_type", {}).items()}
    return DeliverableCoverage(
        requirement_id=payload["requirement_id"] or requirement_id,
        total=payload["total"],
        submitted=payload["submitted"],
        accepted=payload["accepted"],
        missing=payload["missing"],
        coverage_pct=payload["coverage_pct"],
        by_type=by_type,
    )


@router.get(
    "/projects/{project_id}/matrix/",
    response_model=MatrixResponse,
)
async def get_project_eir_matrix(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("requirements.read")),
    deliverable_type: str | None = Query(default=None, max_length=64),
    service: RequirementsService = Depends(_get_service),
) -> MatrixResponse:
    """Return the full project EIR matrix.

    Rows are requirements (one per row, paired with their parent set so
    the UI can group), columns are deliverable types (model, drawing,
    schedule, report, cobie, pset, plus any custom ones present in the
    project's rows), cells carry the LOD/LOI/status triplet.
    """
    await verify_project_access(project_id, str(user_id), session)
    payload = await service.get_project_matrix(project_id, deliverable_type=deliverable_type)
    rows = [
        MatrixRow(
            requirement_id=row["requirement_id"],
            requirement_set_id=row["requirement_set_id"],
            entity=row["entity"],
            attribute=row["attribute"],
            priority=row["priority"],
            linked_position_id=row.get("linked_position_id"),
            cells={k: MatrixCell(**v) for k, v in row["cells"].items()},
            coverage_pct=row["coverage_pct"],
        )
        for row in payload["rows"]
    ]
    return MatrixResponse(
        project_id=project_id,
        deliverable_types=payload["deliverable_types"],
        rows=rows,
        coverage_pct=payload["coverage_pct"],
    )


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


async def _requirements_loader(session: Any, project_id: uuid.UUID | None) -> list[Any]:
    stmt = select(_Requirement).options(_selectinload(_Requirement.requirement_set))
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
