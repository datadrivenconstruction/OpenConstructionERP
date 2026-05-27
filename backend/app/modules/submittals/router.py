"""‌⁠‍Submittals API routes.

Endpoints:
    GET    /                          - List submittals for a project
    POST   /                          - Create submittal
    GET    /{submittal_id}            - Get single submittal
    PATCH  /{submittal_id}            - Update submittal
    DELETE /{submittal_id}            - Delete submittal
    POST   /{submittal_id}/submit     - Move to submitted status
    POST   /{submittal_id}/review     - Review (approve/reject/revise) [MANAGER]
    POST   /{submittal_id}/approve    - Final approval [MANAGER]
    GET    /{submittal_id}/attachments/ - List attachment refs
    POST   /{submittal_id}/attachments/upload/ - Direct magic-byte gated upload
    POST   /{submittal_id}/attachments/ - Link existing Document as attachment
    DELETE /{submittal_id}/attachments/{document_id} - Remove attachment ref
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.file_signature import (
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.i18n import get_locale
from app.core.rate_limiter import approval_limiter
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    RequireRole,
    SessionDep,
    verify_project_access,
)
from app.modules.submittals.schemas import (
    SubmittalCreate,
    SubmittalResponse,
    SubmittalReviewRequest,
    SubmittalUpdate,
)
from app.modules.submittals.service import SubmittalService

router = APIRouter()
logger = logging.getLogger(__name__)

# Magic-byte allow-list for direct submittal-attachment uploads.
# Submittals are shop drawings, product data, samples, test reports —
# the realistic format set is PDFs, vector CAD (DWG/DXF/IFC/GLB), Office
# ZIP containers, and site photos. ``xml`` is excluded deliberately: the
# stdlib detector tolerates ``<html>...`` as XML and HTML payloads have
# repeatedly been XSS sinks across audited modules.
_ALLOWED_ATTACHMENT_TYPES = frozenset(
    {
        "pdf",
        "png",
        "jpeg",
        "gif",
        "webp",
        "heic",
        "heif",
        "tiff",
        "zip",
        "ole",
        "dwg",
        "dxf",
        "ifc",
        "glb",
    }
)

# On-disk storage for direct attachment uploads. The path mirrors
# correspondence (``uploads/<module>/<bucket>/``) so the prod backup
# already covers it; created lazily on first upload.
ATTACHMENTS_DIR = Path("uploads/submittals/attachments")

# Per-file upload cap — submittal attachments occasionally include large
# RVT exports / BIM glTF files. 50 MB matches the documents-module cap
# in v4.2.3 and bounds memory at a couple of attachments per request.
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _get_service(session: SessionDep) -> SubmittalService:
    return SubmittalService(session)


def _to_response(item: object) -> SubmittalResponse:
    return SubmittalResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        submittal_number=item.submittal_number,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        spec_section=item.spec_section,  # type: ignore[attr-defined]
        submittal_type=item.submittal_type,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        ball_in_court=str(item.ball_in_court) if item.ball_in_court else None,  # type: ignore[attr-defined]
        current_revision=item.current_revision,  # type: ignore[attr-defined]
        submitted_by_org=item.submitted_by_org,  # type: ignore[attr-defined]
        reviewer_id=str(item.reviewer_id) if item.reviewer_id else None,  # type: ignore[attr-defined]
        approver_id=str(item.approver_id) if item.approver_id else None,  # type: ignore[attr-defined]
        date_submitted=item.date_submitted,  # type: ignore[attr-defined]
        date_required=item.date_required,  # type: ignore[attr-defined]
        date_returned=item.date_returned,  # type: ignore[attr-defined]
        linked_boq_item_ids=item.linked_boq_item_ids or [],  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get(
    "/",
    response_model=list[SubmittalResponse],
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def list_submittals(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    service: SubmittalService = Depends(_get_service),
) -> list[SubmittalResponse]:
    await verify_project_access(project_id, user_id, session)
    submittals, _ = await service.list_submittals(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        submittal_type=type_filter,
    )
    return [_to_response(s) for s in submittals]


@router.post("/", response_model=SubmittalResponse, status_code=201)
async def create_submittal(
    data: SubmittalCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("submittals.create")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    await verify_project_access(data.project_id, user_id, session)
    submittal = await service.create_submittal(data, user_id=user_id)
    return _to_response(submittal)


@router.get(
    "/{submittal_id}",
    response_model=SubmittalResponse,
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def get_submittal(
    submittal_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    submittal = await service.get_submittal(submittal_id)
    await verify_project_access(submittal.project_id, str(user_id), session)
    return _to_response(submittal)


@router.patch("/{submittal_id}", response_model=SubmittalResponse)
async def update_submittal(
    submittal_id: uuid.UUID,
    data: SubmittalUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    existing = await service.get_submittal(submittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    submittal = await service.update_submittal(submittal_id, data)
    return _to_response(submittal)


@router.delete("/{submittal_id}", status_code=204)
async def delete_submittal(
    submittal_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.delete")),
    service: SubmittalService = Depends(_get_service),
) -> None:
    existing = await service.get_submittal(submittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_submittal(submittal_id)


@router.post("/{submittal_id}/submit/", response_model=SubmittalResponse)
async def submit_submittal(
    submittal_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    """‌⁠‍Move a submittal from draft to submitted."""
    existing = await service.get_submittal(submittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    submittal = await service.submit_submittal(submittal_id)
    return _to_response(submittal)


@router.post(
    "/{submittal_id}/review/",
    response_model=SubmittalResponse,
    # Reviewer-role gate: approve / reject / revise-and-resubmit are
    # contract-level decisions that touch payment scheduling downstream.
    # A plain editor with ``submittals.update`` (e.g. an admin assistant
    # entering submittal metadata) must NOT be able to drive the decision.
    dependencies=[Depends(RequireRole("manager"))],
)
async def review_submittal(
    submittal_id: uuid.UUID,
    body: SubmittalReviewRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    """‌⁠‍Review a submittal (approve, reject, revise and resubmit, etc.).

    Requires the ``manager`` role (or higher). The base
    ``submittals.update`` permission alone is not sufficient.
    """
    existing = await service.get_submittal(submittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    submittal = await service.review_submittal(submittal_id, body.status, reviewer_id=user_id)
    return _to_response(submittal)


@router.post(
    "/{submittal_id}/approve/",
    response_model=SubmittalResponse,
    # See note on /review/. Final approval is the most consequential
    # FSM transition and must be MANAGER-or-higher only.
    dependencies=[Depends(RequireRole("manager"))],
)
async def approve_submittal(
    submittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    """Final approval of a submittal.

    Requires the ``manager`` role (or higher).
    """
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded. Try again later.",
        )
    existing = await service.get_submittal(submittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    submittal = await service.approve_submittal(submittal_id, approver_id=user_id)
    return _to_response(submittal)


# ── Attachments ──────────────────────────────────────────────────────────
#
# Two flavours of attachment:
#   * Direct upload (``POST /attachments/upload/``) — raw bytes pass through
#     the magic-byte gate before they are written to disk. New in R4+R5,
#     mirroring correspondence / compliance_docs / punchlist gates.
#   * Document link (``POST /attachments/``) — references an already-
#     uploaded ``Document`` row by id. Retained for backwards compat with
#     existing front-end flows; the magic-byte gate runs in the documents
#     module at the original upload site.


class AttachmentLinkRequest(BaseModel):
    """Request body for linking a document as a submittal attachment."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    document_id: uuid.UUID
    label: str = Field(default="", max_length=255)


class AttachmentResponse(BaseModel):
    """Attachment reference returned from the API."""

    document_id: uuid.UUID
    label: str = ""
    added_by: str = ""
    added_at: str = ""


@router.get(
    "/{submittal_id}/attachments/",
    response_model=list[AttachmentResponse],
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def list_submittal_attachments(
    submittal_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SubmittalService = Depends(_get_service),
) -> list[AttachmentResponse]:
    """List attachments linked to a submittal."""
    submittal = await service.get_submittal(submittal_id)
    await verify_project_access(submittal.project_id, str(user_id), session)
    meta = dict(getattr(submittal, "metadata_", {}) or {})
    attachments_raw = meta.get("attachments", [])
    if not isinstance(attachments_raw, list):
        return []
    out: list[AttachmentResponse] = []
    for a in attachments_raw:
        if not isinstance(a, dict):
            continue
        try:
            out.append(
                AttachmentResponse(
                    document_id=uuid.UUID(str(a.get("document_id", ""))),
                    label=str(a.get("label", "")),
                    added_by=str(a.get("added_by", "")),
                    added_at=str(a.get("added_at", "")),
                )
            )
        except (ValueError, TypeError):
            continue
    return out


@router.post(
    "/{submittal_id}/attachments/upload/",
    response_model=AttachmentResponse,
    status_code=201,
)
async def upload_submittal_attachment(
    submittal_id: uuid.UUID,
    session: SessionDep,
    file: UploadFile = File(...),
    label: str = "",
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> AttachmentResponse:
    """Directly upload an attachment (magic-byte validated).

    Unlike :func:`add_submittal_attachment` which links a pre-uploaded
    Document by ID, this endpoint accepts the raw bytes and inspects the
    magic bytes via :func:`require_signature`. ``Content-Type`` and
    extension are attacker-controlled, so only the detector decides what
    we keep on disk. Mirrors the v4.2.1 punchlist gate and v4.2.3 photo
    upload gate. The stored filename is server-derived to prevent path
    poisoning, and the body is bounded by :data:`_MAX_UPLOAD_BYTES` to
    cap memory.
    """
    from datetime import UTC, datetime

    # IDOR gate must run BEFORE we read any bytes — a caller without
    # project access never causes us to touch the disk or learn whether
    # the submittal exists.
    submittal = await service.get_submittal(submittal_id)
    await verify_project_access(submittal.project_id, str(user_id), session)

    # Reject closed submittals — they're terminal and should not accept
    # late attachments. ``draft`` and the active FSM states are fine.
    if submittal.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot attach files to a closed submittal",
        )

    # Snapshot row attributes BEFORE update_fields — that helper expires
    # the ORM row so a later lazy-attribute access (project_id, status)
    # would trigger MissingGreenlet under async context.
    project_id_s = str(submittal.project_id)

    try:
        content = await file.read()
    except Exception as exc:
        logger.exception(
            "Unable to read attachment upload for submittal %s",
            submittal_id,
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
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload cap",
        )

    try:
        detected = require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            _ALLOWED_ATTACHMENT_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    # Server-derived filename. Extension is from client's name purely as
    # a hint for OS file managers; the magic-byte gate above decided.
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "attachment.bin").suffix or ".bin"
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"{submittal_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = ATTACHMENTS_DIR / safe_name

    try:
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception(
            "Unable to save attachment for submittal %s",
            submittal_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save attachment — storage error",
        ) from exc

    relative_path = f"submittals/attachments/{safe_name}"
    now = datetime.now(UTC).isoformat()
    entry = {
        "document_id": str(uuid.uuid4()),
        "path": relative_path,
        "label": (label or file.filename or "")[:255],
        "added_by": str(user_id) if user_id else "",
        "added_at": now,
        "detected_type": detected,
        "size_bytes": len(content),
    }
    meta = dict(getattr(submittal, "metadata_", {}) or {})
    attachments: list[dict] = list(meta.get("attachments", []) or [])
    attachments.append(entry)
    meta["attachments"] = attachments
    await service.repo.update_fields(submittal_id, metadata_=meta)

    logger.info(
        "submittal.attachment_uploaded %s",
        {
            "event": "submittal.attachment_uploaded",
            "submittal_id": str(submittal_id),
            "project_id": project_id_s,
            "actor_id": str(user_id) if user_id else None,
            "detected_type": detected,
            "size_bytes": len(content),
            "path": relative_path,
        },
    )

    return AttachmentResponse(
        document_id=uuid.UUID(entry["document_id"]),
        label=entry["label"],
        added_by=entry["added_by"],
        added_at=entry["added_at"],
    )


@router.post(
    "/{submittal_id}/attachments/",
    response_model=AttachmentResponse,
    status_code=201,
)
async def add_submittal_attachment(
    submittal_id: uuid.UUID,
    data: AttachmentLinkRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> AttachmentResponse:
    """Link an existing Document to a submittal.

    The Document must already exist (upload via ``POST /api/documents/``);
    this endpoint creates the association and stores it inside the
    submittal's metadata — no new table required.
    """
    from datetime import UTC, datetime

    from app.modules.documents.repository import DocumentRepository

    # Verify the document exists and is accessible.
    doc_repo = DocumentRepository(session)
    document = await doc_repo.get_by_id(data.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=translate("errors.document_not_found", locale=get_locale()))

    submittal = await service.get_submittal(submittal_id)
    await verify_project_access(submittal.project_id, str(user_id), session)
    meta = dict(getattr(submittal, "metadata_", {}) or {})
    attachments: list[dict] = list(meta.get("attachments", []) or [])

    # Reject duplicates — idempotency for retry-safe clients.
    if any(str(a.get("document_id")) == str(data.document_id) for a in attachments if isinstance(a, dict)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document already attached to this submittal",
        )

    now = datetime.now(UTC).isoformat()
    entry = {
        "document_id": str(data.document_id),
        "label": data.label or getattr(document, "name", ""),
        "added_by": str(user_id) if user_id else "",
        "added_at": now,
    }
    attachments.append(entry)
    meta["attachments"] = attachments

    # Persist through the repository so expire_all / refresh behaviour stays
    # consistent with the rest of the module (same pattern as BUG-122/123).
    await service.repo.update_fields(submittal_id, metadata_=meta)

    return AttachmentResponse(**entry)


@router.delete(
    "/{submittal_id}/attachments/{document_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("submittals.update"))],
)
async def remove_submittal_attachment(
    submittal_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SubmittalService = Depends(_get_service),
) -> None:
    """Remove a document attachment reference from a submittal.

    Does not delete the underlying Document — use
    ``DELETE /api/documents/{id}`` for that.
    """
    submittal = await service.get_submittal(submittal_id)
    await verify_project_access(submittal.project_id, str(user_id), session)
    meta = dict(getattr(submittal, "metadata_", {}) or {})
    attachments: list[dict] = list(meta.get("attachments", []) or [])

    new_list = [a for a in attachments if isinstance(a, dict) and str(a.get("document_id")) != str(document_id)]
    if len(new_list) == len(attachments):
        raise HTTPException(status_code=404, detail="Attachment not found")

    meta["attachments"] = new_list
    await service.repo.update_fields(submittal_id, metadata_=meta)
