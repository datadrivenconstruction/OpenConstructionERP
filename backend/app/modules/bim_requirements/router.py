"""BIM Requirements Import/Export API routes.

Endpoints:
    POST   /import/upload/                    -- Upload and import a requirements file
    GET    /sets/                              -- List requirement sets for a project
    GET    /sets/{set_id}/                     -- Get set with requirements
    DELETE /sets/{set_id}/                     -- Delete a requirement set
    GET    /template/                          -- Download Excel template
    POST   /export/{set_id}/excel/             -- Export set as Excel
    POST   /export/{set_id}/ids/              -- Export set as IDS XML
    POST   /validate/{set_id}/                -- Validate BIM model against requirement set
"""

import logging
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.bim_requirements.schemas import (
    BIMRequirementResponse,
    BIMRequirementSetDetail,
    BIMRequirementSetResponse,
    ImportResultResponse,
    ParseError,
    RequirementValidationResponse,
)
from app.modules.bim_requirements.service import BIMRequirementService

router = APIRouter()
logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    """Sanitize a user-provided name for use in Content-Disposition headers.

    Removes characters that could enable header injection or path traversal.
    """
    # Strip control characters (CR, LF, tab, etc.), quotes, slashes, backslashes
    clean = "".join(c for c in name if c.isprintable() and c not in '"/\\')
    return clean.strip()[:50] or "export"


def _get_service(session: SessionDep) -> BIMRequirementService:
    return BIMRequirementService(session)


def _set_to_response(item: object) -> BIMRequirementSetResponse:
    """Build a BIMRequirementSetResponse from an ORM object."""
    return BIMRequirementSetResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        name=item.name,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        source_format=item.source_format,  # type: ignore[attr-defined]
        source_filename=item.source_filename,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _req_to_response(item: object) -> BIMRequirementResponse:
    """Build a BIMRequirementResponse from an ORM object."""
    return BIMRequirementResponse(
        id=item.id,  # type: ignore[attr-defined]
        requirement_set_id=item.requirement_set_id,  # type: ignore[attr-defined]
        element_filter=item.element_filter,  # type: ignore[attr-defined]
        property_group=item.property_group,  # type: ignore[attr-defined]
        property_name=item.property_name,  # type: ignore[attr-defined]
        constraint_def=item.constraint_def,  # type: ignore[attr-defined]
        context=item.context,  # type: ignore[attr-defined]
        source_format=item.source_format,  # type: ignore[attr-defined]
        source_ref=item.source_ref,  # type: ignore[attr-defined]
        is_active=item.is_active,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


def _set_to_detail(item: object) -> BIMRequirementSetDetail:
    """Build a BIMRequirementSetDetail from an ORM object with relationships."""
    reqs = getattr(item, "requirements", [])
    return BIMRequirementSetDetail(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        name=item.name,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        source_format=item.source_format,  # type: ignore[attr-defined]
        source_filename=item.source_filename,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        requirements=[_req_to_response(r) for r in reqs],
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Import ─────────────────────────────────────────────────────────────────


@router.post("/import/upload/", response_model=ImportResultResponse, status_code=201)
async def import_requirements_file(
    project_id: uuid.UUID = Query(...),
    file: UploadFile = File(...),
    name: str | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim_requirements.create")),
    service: BIMRequirementService = Depends(_get_service),
) -> ImportResultResponse:
    """Upload and import a BIM requirements file.

    Supports: IDS XML, COBie Excel, generic Excel/CSV, Revit Shared Parameters,
    BIMQ JSON. Format is auto-detected from file extension and content.
    """
    content = await file.read()
    filename = file.filename or "unknown"

    req_set, parse_result = await service.import_file(
        project_id=project_id,
        file_content=content,
        filename=filename,
        name=name,
        user_id=user_id or "",
    )

    return ImportResultResponse(
        requirement_set_id=req_set.id,
        name=req_set.name,
        source_format=req_set.source_format,
        total_requirements=len(parse_result.requirements),
        errors=[ParseError(**e) for e in parse_result.errors],
        warnings=[ParseError(**w) for w in parse_result.warnings],
        metadata=parse_result.metadata,
    )


# ── List sets ──────────────────────────────────────────────────────────────


@router.get("/sets/", response_model=list[BIMRequirementSetResponse])
async def list_sets(
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMRequirementService = Depends(_get_service),
) -> list[BIMRequirementSetResponse]:
    """List BIM requirement sets for a project."""
    items = await service.list_sets(project_id, offset=offset, limit=limit)
    return [_set_to_response(i) for i in items]


# ── Get set detail ─────────────────────────────────────────────────────────


@router.get("/sets/{set_id}/", response_model=BIMRequirementSetDetail)
async def get_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMRequirementService = Depends(_get_service),
) -> BIMRequirementSetDetail:
    """Get a BIM requirement set with all its requirements."""
    item = await service.get_set(set_id)
    return _set_to_detail(item)


# ── Delete set ─────────────────────────────────────────────────────────────


@router.delete("/sets/{set_id}/", status_code=204)
async def delete_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim_requirements.delete")),
    service: BIMRequirementService = Depends(_get_service),
) -> None:
    """Delete a BIM requirement set and all its requirements."""
    await service.delete_set(set_id)


# ── Download template ──────────────────────────────────────────────────────


@router.get("/template/")
async def download_template(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> Response:
    """Download an Excel template for BIM requirements import."""
    from app.modules.bim_requirements.exporters.excel_exporter import generate_template

    content = generate_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="bim_requirements_template.xlsx"',
        },
    )


# ── Export as Excel ────────────────────────────────────────────────────────


@router.post("/export/{set_id}/excel/")
async def export_excel(
    set_id: uuid.UUID,
    language: str = Query(default="en", pattern="^(en|de)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMRequirementService = Depends(_get_service),
) -> Response:
    """Export a BIM requirement set as a formatted Excel file."""
    content = await service.export_excel(set_id, language=language)
    req_set = await service.get_set(set_id)
    safe_name = _sanitize_filename(req_set.name)

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.xlsx"',
        },
    )


# ── Export as IDS XML ──────────────────────────────────────────────────────


@router.post("/export/{set_id}/ids/")
async def export_ids(
    set_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMRequirementService = Depends(_get_service),
) -> Response:
    """Export a BIM requirement set as IDS XML."""
    content = await service.export_ids(set_id)
    req_set = await service.get_set(set_id)
    safe_name = _sanitize_filename(req_set.name)

    return Response(
        content=content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.ids"',
        },
    )


# ── Validate against BIM model ────────────────────────────────────────────


@router.post("/validate/{set_id}/", response_model=RequirementValidationResponse)
async def validate_against_model(
    set_id: uuid.UUID,
    model_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMRequirementService = Depends(_get_service),
) -> RequirementValidationResponse:
    """Validate a BIM model's elements against a requirement set.

    For each requirement:
    - Finds elements that match the requirement's ``element_filter``
    - Checks if those elements have the required property/value per ``constraint_def``
    - Returns a compliance report with pass/fail/not_applicable counts
    """
    report = await service.validate_against_model(set_id, model_id)
    return RequirementValidationResponse(**report)
