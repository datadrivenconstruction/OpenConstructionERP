# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍FastAPI router for the compliance documents tracker.

All endpoints are owner-scoped via the existing
:func:`app.dependencies.verify_project_access` guard - the same pattern
the :mod:`app.modules.rfi.router` uses. Cross-project access surfaces
as 404 (not 403) so the endpoint can't be turned into a UUID-existence
oracle.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi import status as http_status

from app.core.file_signature import (
    ALLOWED_DOCUMENT_TYPES,
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
    mime_for_signature,
)
from app.core.file_signature import require as require_signature
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.compliance_docs.schemas import (
    ComplianceDocCreate,
    ComplianceDocResponse,
    ComplianceDocUpdate,
)
from app.modules.compliance_docs.service import ComplianceDocService

# Compliance evidence is typically a scanned PDF / image; we accept the
# project-wide document allow-list (PDF / PNG / JPEG / GIF / WebP /
# Office-ZIP / OLE / XML). Tightening further (e.g. PDF-only) is a
# per-tenant policy decision and lives outside this base module.
_ALLOWED_ATTACHMENT_TYPES = ALLOWED_DOCUMENT_TYPES

# Hard cap to keep a runaway upload from filling the disk before the
# request body limit on the reverse proxy catches it. 50 MiB matches the
# documents-module ceiling.
_MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024

# Local storage root for direct uploads. Service-level metadata stores
# the relative path; absolute path lives only inside this router.
_ATTACHMENTS_DIR = Path("data") / "compliance_docs" / "attachments"

logger = logging.getLogger(__name__)
router = APIRouter(tags=["compliance_docs"])


def _get_service(session: SessionDep) -> ComplianceDocService:
    return ComplianceDocService(session)


def _to_response(item: object) -> ComplianceDocResponse:
    """‌⁠‍Build a response model with the computed ``days_until_expiry``."""
    today = datetime.now(UTC).date()
    expires_at = getattr(item, "expires_at", None)
    days_until_expiry = 0
    if expires_at is not None:
        try:
            days_until_expiry = (expires_at - today).days
        except TypeError:  # pragma: no cover - defensive
            days_until_expiry = 0

    resp = ComplianceDocResponse.model_validate(item)
    return resp.model_copy(update={"days_until_expiry": days_until_expiry})


@router.get(
    "/",
    response_model=list[ComplianceDocResponse],
    dependencies=[Depends(RequirePermission("compliance_docs.read"))],
)
async def list_compliance_docs(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    doc_type: str | None = Query(default=None),
    service: ComplianceDocService = Depends(_get_service),
) -> list[ComplianceDocResponse]:
    """‌⁠‍List compliance docs for a project."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_docs(
        project_id,
        status=status_filter,
        doc_type=doc_type,
    )
    return [_to_response(i) for i in items]


@router.get(
    "/expiring-soon/",
    response_model=list[ComplianceDocResponse],
    dependencies=[Depends(RequirePermission("compliance_docs.read"))],
)
async def list_expiring_soon(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    service: ComplianceDocService = Depends(_get_service),
) -> list[ComplianceDocResponse]:
    """Return docs that are already expired or due within their reminder window.

    Designed for the dashboard widget - top N rows by ascending expiry.
    """
    await verify_project_access(project_id, user_id, session)
    items = await service.list_expiring_soon(project_id, limit=limit)
    return [_to_response(i) for i in items]


@router.post(
    "/",
    response_model=ComplianceDocResponse,
    status_code=201,
)
async def create_compliance_doc(
    data: ComplianceDocCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("compliance_docs.create")),
    service: ComplianceDocService = Depends(_get_service),
) -> ComplianceDocResponse:
    """Create a new compliance document."""
    await verify_project_access(data.project_id, user_id, session)
    doc = await service.create_doc(data, user_id=user_id)
    return _to_response(doc)


@router.get(
    "/{doc_id}/",
    response_model=ComplianceDocResponse,
    dependencies=[Depends(RequirePermission("compliance_docs.read"))],
)
async def get_compliance_doc(
    doc_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ComplianceDocService = Depends(_get_service),
) -> ComplianceDocResponse:
    """Read a single compliance document."""
    doc = await service.get_doc(doc_id)
    await verify_project_access(doc.project_id, user_id, session)
    return _to_response(doc)


@router.patch(
    "/{doc_id}/",
    response_model=ComplianceDocResponse,
)
async def update_compliance_doc(
    doc_id: uuid.UUID,
    data: ComplianceDocUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("compliance_docs.update")),
    service: ComplianceDocService = Depends(_get_service),
) -> ComplianceDocResponse:
    """Patch a compliance document. Status is recomputed unless overridden."""
    existing = await service.get_doc(doc_id)
    await verify_project_access(existing.project_id, user_id, session)
    doc = await service.update_doc(doc_id, data, user_id=user_id)
    return _to_response(doc)


@router.delete(
    "/{doc_id}/",
    status_code=204,
)
async def delete_compliance_doc(
    doc_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("compliance_docs.delete")),
    service: ComplianceDocService = Depends(_get_service),
) -> None:
    """Delete a compliance document."""
    existing = await service.get_doc(doc_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_doc(doc_id)


@router.post(
    "/{doc_id}/attachment/",
    response_model=ComplianceDocResponse,
)
async def upload_attachment(
    doc_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("compliance_docs.update")),
    service: ComplianceDocService = Depends(_get_service),
) -> ComplianceDocResponse:
    """Upload an evidence file (PDF / image / Office) for a compliance doc.

    The Content-Type header is attacker-controlled, so we ignore it and
    validate the file's leading bytes against
    :data:`_ALLOWED_ATTACHMENT_TYPES` (PDF, PNG, JPEG, GIF, WebP, Office
    ZIP, OLE, XML). Mismatches return 415. The stored MIME is derived
    from the detected signature - never from the uploader's header - so
    later GETs can't be coerced into serving HTML / SVG / script.
    """
    # Project scoping: we must resolve the doc first so we can route
    # through ``verify_project_access`` before reading any bytes.
    existing = await service.get_doc(doc_id)
    await verify_project_access(existing.project_id, user_id, session)

    try:
        content = await file.read()
    except Exception:
        logger.exception(
            "Unable to read attachment upload for compliance doc %s",
            doc_id,
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded file",
        )

    if not content:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"Uploaded file exceeds the {_MAX_ATTACHMENT_BYTES} byte limit"),
        )

    # Magic-byte gate - reject anything outside the allow-list.
    try:
        detected = require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            _ALLOWED_ATTACHMENT_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=http_status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )
    safe_mime = mime_for_signature(detected)

    # Persist bytes to disk. Filename is derived from the doc id +
    # random suffix to keep collisions impossible across re-uploads;
    # the original filename is logged but not used as a path.
    _ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "evidence.bin").suffix or f".{detected}"
    stored_filename = f"{doc_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = _ATTACHMENTS_DIR / stored_filename
    try:
        filepath.write_bytes(content)
    except Exception:
        logger.exception(
            "Unable to save attachment for compliance doc %s",
            doc_id,
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save file - storage error",
        )

    relative_path = f"compliance_docs/attachments/{stored_filename}"
    doc = await service.attach_file(
        doc_id,
        relative_path=relative_path,
        detected_mime=safe_mime,
        size_bytes=len(content),
        user_id=user_id,
    )
    return _to_response(doc)


__all__ = ["router"]
