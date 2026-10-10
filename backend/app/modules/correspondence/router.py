# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Correspondence API routes.

Endpoints:
    GET    /                                            - List correspondence for a project
    POST   /                                            - Create correspondence
    GET    /{correspondence_id}                         - Get single correspondence
    PATCH  /{correspondence_id}                         - Update correspondence
    DELETE /{correspondence_id}                         - Delete correspondence
    POST   /{correspondence_id}/attachments/            - Upload attachment (magic-byte gated)
    GET    /{correspondence_id}/attachments/{index}     - Download a stored attachment
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.core.file_signature import (
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.storage import contained_upload_candidates, module_uploads_dir

# Allow-list of magic-byte tokens we accept for correspondence attachments.
# Deliberately tighter than the module-level ``ALLOWED_DOCUMENT_TYPES``:
# ``xml`` is excluded because the stdlib detector accepts ``<html>...`` as
# an XML signature, and HTML payloads served back out (even with a benign
# Content-Type) have repeatedly been XSS sinks in audited modules. Real
# correspondence attachments are PDFs, images, and Office docs (ZIP/OLE).
ALLOWED_ATTACHMENT_TYPES = frozenset({"pdf", "png", "jpeg", "gif", "webp", "zip", "ole"})
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.correspondence.schemas import (
    CorrespondenceCreate,
    CorrespondenceListResponse,
    CorrespondenceResponse,
    CorrespondenceUpdate,
)
from app.modules.correspondence.service import CorrespondenceService

router = APIRouter(tags=["correspondence"])

# Register and record exports (workbook and PDF). Included first, so the
# static "export" paths are matched before the "/{id}" routes below.
from app.modules.correspondence.export_routes import export_router  # noqa: E402

router.include_router(export_router)
logger = logging.getLogger(__name__)

# On-disk storage for correspondence attachments. Path layout mirrors
# punchlist (``uploads/<module>/<bucket>/``) so the prod backup script
# already picks it up. The directory is created lazily on first upload -
# fresh installs that never use the feature don't need to ship the dir.
#
# Anchored on the platform data dir, not the process working directory: a
# bare relative literal points wherever the app was started, which differs
# per deployment and on a per-machine Windows install is a Program Files
# folder an unelevated user cannot create anything in.
ATTACHMENTS_DIR = module_uploads_dir("correspondence", "attachments")


def _get_service(session: SessionDep) -> CorrespondenceService:
    return CorrespondenceService(session)


def _compute_correspondence_fields(item: object) -> tuple[bool, int | None]:
    """Compute ``is_overdue`` and ``days_until_due`` from the response deadline.

    A record is overdue when it still awaits a reply (``status`` is ``open`` or
    ``awaiting_response``) and its ``response_required_by`` date has passed.
    ``days_until_due`` is signed - negative once the deadline is behind us - and
    is ``None`` when no deadline was set. Date-only arithmetic keeps "due today"
    from reading as overdue just because the clock has moved past midnight UTC.
    """
    due_raw = getattr(item, "response_required_by", None)
    if not due_raw:
        return False, None
    try:
        due = datetime.fromisoformat(str(due_raw))
    except (ValueError, TypeError):
        return False, None
    today = datetime.now(UTC).date()
    days_until_due = (due.date() - today).days
    status_val = getattr(item, "status", "open")
    is_overdue = status_val in ("open", "awaiting_response") and today > due.date()
    return is_overdue, days_until_due


def _to_response(item: object) -> CorrespondenceResponse:
    is_overdue, days_until_due = _compute_correspondence_fields(item)
    return CorrespondenceResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        reference_number=item.reference_number,  # type: ignore[attr-defined]
        direction=item.direction,  # type: ignore[attr-defined]
        subject=item.subject,  # type: ignore[attr-defined]
        from_contact_id=item.from_contact_id,  # type: ignore[attr-defined]
        to_contact_ids=item.to_contact_ids or [],  # type: ignore[attr-defined]
        date_sent=item.date_sent,  # type: ignore[attr-defined]
        date_received=item.date_received,  # type: ignore[attr-defined]
        correspondence_type=item.correspondence_type,  # type: ignore[attr-defined]
        linked_document_ids=item.linked_document_ids or [],  # type: ignore[attr-defined]
        linked_transmittal_id=item.linked_transmittal_id,  # type: ignore[attr-defined]
        linked_rfi_id=item.linked_rfi_id,  # type: ignore[attr-defined]
        status=getattr(item, "status", "open") or "open",
        response_required_by=getattr(item, "response_required_by", None),
        contract_clause_ref=getattr(item, "contract_clause_ref", None),
        is_overdue=is_overdue,
        days_until_due=days_until_due,
        notes=item.notes,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        attachments=getattr(item, "attachments", None) or [],
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=CorrespondenceListResponse)
async def list_correspondences(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    direction: str | None = Query(default=None),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(open|awaiting_response|responded|closed)$",
    ),
    _perm: None = Depends(RequirePermission("correspondence.read")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceListResponse:
    """List correspondence for a project, one page plus the matching total.

    The service already counts the whole filtered set to build the page; this
    returns that count instead of discarding it, so a caller can tell a
    complete log from a truncated one.
    """
    await verify_project_access(project_id, user_id, session)
    items, total = await service.list_correspondences(
        project_id,
        offset=offset,
        limit=limit,
        direction=direction,
        correspondence_type=type_filter,
        status=status_filter,
    )
    return CorrespondenceListResponse(
        items=[_to_response(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=CorrespondenceResponse, status_code=201)
async def create_correspondence(
    data: CorrespondenceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("correspondence.create")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    await verify_project_access(data.project_id, user_id, session)
    correspondence = await service.create_correspondence(data, user_id=user_id)
    return _to_response(correspondence)


@router.get("/{correspondence_id}", response_model=CorrespondenceResponse)
async def get_correspondence(
    correspondence_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.read")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    correspondence = await service.get_correspondence(correspondence_id)
    await verify_project_access(correspondence.project_id, str(user_id), session)
    return _to_response(correspondence)


@router.patch("/{correspondence_id}", response_model=CorrespondenceResponse)
async def update_correspondence(
    correspondence_id: uuid.UUID,
    data: CorrespondenceUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.update")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    existing = await service.get_correspondence(correspondence_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    correspondence = await service.update_correspondence(correspondence_id, data)
    return _to_response(correspondence)


@router.delete("/{correspondence_id}", status_code=204)
async def delete_correspondence(
    correspondence_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.delete")),
    service: CorrespondenceService = Depends(_get_service),
) -> None:
    existing = await service.get_correspondence(correspondence_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_correspondence(correspondence_id)


# ── Attachments ──────────────────────────────────────────────────────────────


@router.post(
    "/{correspondence_id}/attachments/",
    response_model=CorrespondenceResponse,
)
async def upload_attachment(
    correspondence_id: uuid.UUID,
    session: SessionDep,
    file: UploadFile = File(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.update")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    """Upload an attachment for a correspondence record.

    The ``Content-Type`` header is fully attacker-controlled, so we
    inspect the raw magic bytes via :func:`require_signature` and reject
    anything outside :data:`ALLOWED_DOCUMENT_TYPES` (PDF, common images,
    Office ZIP containers, XML, legacy OLE). This mirrors the v4.2.1
    punchlist fix and the v4.2.3 AI photo-upload gate: extension /
    declared MIME never decide what we keep on disk.

    The stored filename is server-derived (``{correspondence_id}_{hex}{ext}``)
    so an attacker cannot poison the path or break out of
    ``ATTACHMENTS_DIR``.
    """
    # IDOR gate: project-scope check must run BEFORE the upload work so a
    # caller without access to the project never causes us to read the
    # body, hit the disk, or learn whether the correspondence exists.
    existing = await service.get_correspondence(correspondence_id)
    await verify_project_access(existing.project_id, str(user_id), session)

    try:
        content = await file.read()
    except Exception as exc:
        logger.exception(
            "Unable to read attachment upload for correspondence %s",
            correspondence_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded attachment",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_ATTACHMENT_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    # Server-derived filename. Extension is taken from the client-provided
    # name purely as a hint for OS file managers; the magic-byte gate
    # above is the only thing that decides whether we actually store it.
    ext = Path(file.filename or "attachment.bin").suffix or ".bin"
    # Strip any path separators that survived in the suffix (defence in
    # depth - Path.suffix already returns at most one segment).
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"{correspondence_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = ATTACHMENTS_DIR / safe_name

    # mkdir belongs inside the try: it, not the write, is what fails when the
    # storage root is not writable, and outside the try that failure bypassed
    # this handler and surfaced as a bare 500.
    try:
        ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception(
            "Unable to save attachment for correspondence %s",
            correspondence_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save attachment - storage error",
        ) from exc

    relative_path = f"correspondence/attachments/{safe_name}"
    updated = await service.add_attachment(correspondence_id, relative_path)
    return _to_response(updated)


# Base directory under which every correspondence attachment lives. The
# stored attachment paths are relative to this (``correspondence/attachments/
# <name>``), so the download handler resolves against it and refuses anything
# that escapes the tree.
#
# Reads additionally fall back to the working-directory-relative tree earlier
# releases wrote to, so attachments stored before upload roots were anchored on
# the data dir stay downloadable. No file is ever moved.
_UPLOADS_BASE = module_uploads_dir()

# Media types we are willing to hand back, keyed by stored extension. Anything
# not in this map is served as ``application/octet-stream`` so the browser
# downloads rather than renders it - defence in depth against an HTML/SVG
# payload that slipped past the upload magic-byte gate.
_DOWNLOAD_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".zip": "application/zip",
}


@router.get("/{correspondence_id}/attachments/{index}")
async def download_attachment(
    correspondence_id: uuid.UUID,
    index: int,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.read")),
    service: CorrespondenceService = Depends(_get_service),
) -> FileResponse:
    """Serve a stored correspondence attachment by its list index.

    The attachment list holds server-derived relative paths only; the index
    addresses an entry rather than letting the client name a path. We still
    resolve the path and confirm it stays inside ``uploads/`` (and is not a
    symlink) before streaming, mirroring the Documents photo-serve gate.
    """
    existing = await service.get_correspondence(correspondence_id)
    await verify_project_access(existing.project_id, str(user_id), session)

    attachments = list(getattr(existing, "attachments", None) or [])
    if index < 0 or index >= len(attachments):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    relative_path = attachments[index]

    # Path-traversal guard - the stored path is trusted (we derived it), but
    # resolve-then-relative_to is cheap insurance against a poisoned row or a
    # future code path that stores a client-influenced value. No candidate
    # means the path escapes every root it could resolve against.
    candidates = contained_upload_candidates(relative_path, _UPLOADS_BASE)
    if not candidates:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Active root first, then the legacy working-directory-relative tree.
    file_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])

    if file_path.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Symlinks not permitted",
        )

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment file missing on disk",
        )

    ext = file_path.suffix.lower()
    media_type = _DOWNLOAD_MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_type,
        content_disposition_type="attachment",
    )
