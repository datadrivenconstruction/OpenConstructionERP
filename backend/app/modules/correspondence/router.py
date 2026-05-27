"""‌⁠‍Correspondence API routes.

Endpoints:
    GET    /                                            - List correspondence for a project
    POST   /                                            - Create correspondence
    GET    /{correspondence_id}                         - Get single correspondence
    PATCH  /{correspondence_id}                         - Update correspondence
    DELETE /{correspondence_id}                         - Delete correspondence
    POST   /{correspondence_id}/attachments/            - Upload attachment (magic-byte gated)
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.core.file_signature import (
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
)
from app.core.file_signature import (
    require as require_signature,
)

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
    CorrespondenceResponse,
    CorrespondenceUpdate,
)
from app.modules.correspondence.service import CorrespondenceService

router = APIRouter()
logger = logging.getLogger(__name__)

# On-disk storage for correspondence attachments. Path layout mirrors
# punchlist (``uploads/<module>/<bucket>/``) so the prod backup script
# already picks it up. The directory is created lazily on first upload —
# fresh installs that never use the feature don't need to ship the dir.
ATTACHMENTS_DIR = Path("uploads/correspondence/attachments")


def _get_service(session: SessionDep) -> CorrespondenceService:
    return CorrespondenceService(session)


def _to_response(item: object) -> CorrespondenceResponse:
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
        notes=item.notes,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        attachments=getattr(item, "attachments", None) or [],
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[CorrespondenceResponse])
async def list_correspondences(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    direction: str | None = Query(default=None),
    type_filter: str | None = Query(default=None, alias="type"),
    service: CorrespondenceService = Depends(_get_service),
) -> list[CorrespondenceResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_correspondences(
        project_id,
        offset=offset,
        limit=limit,
        direction=direction,
        correspondence_type=type_filter,
    )
    return [_to_response(c) for c in items]


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
    """‌⁠‍Upload an attachment for a correspondence record.

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
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "attachment.bin").suffix or ".bin"
    # Strip any path separators that survived in the suffix (defence in
    # depth — Path.suffix already returns at most one segment).
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"{correspondence_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = ATTACHMENTS_DIR / safe_name

    try:
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception(
            "Unable to save attachment for correspondence %s",
            correspondence_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save attachment — storage error",
        ) from exc

    relative_path = f"correspondence/attachments/{safe_name}"
    updated = await service.add_attachment(correspondence_id, relative_path)
    return _to_response(updated)
