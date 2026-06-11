# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resumable Uploads API routes.

Mounted at ``/api/v1/resumable-uploads``.

Endpoints:
    POST   /sessions/                       - create a session
    GET    /sessions/{session_id}/          - status (missing chunks)
    PUT    /sessions/{session_id}/chunks/{index}/ - upload one chunk (idempotent)
    POST   /sessions/{session_id}/complete/ - assemble + hand off to documents
    DELETE /sessions/{session_id}/          - abort + cleanup
    POST   /gc/                             - admin-only stale-session sweep

Access control mirrors the single-shot document upload: a user who can
upload into a project (project member with folder write access, or the
owner/admin) can drive a resumable upload for the same project. A missing
or cross-tenant session id collapses to 404 so the surface cannot be used
as an enumeration oracle.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.core.rate_limiter import upload_limiter
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.documents.service import DocumentService
from app.modules.resumable_uploads.models import ResumableUploadSession
from app.modules.resumable_uploads.schemas import (
    ChunkAcceptedResponse,
    CompleteResponse,
    CreateSessionRequest,
    SessionResponse,
)
from app.modules.resumable_uploads.service import ResumableUploadService

router = APIRouter(tags=["Resumable Uploads"])
logger = logging.getLogger(__name__)

# A single chunk is read fully into memory before it is written to disk.
# Cap the request body a little above the largest allowed chunk so an
# oversized body is refused before it is buffered. ``MAX_CHUNK_SIZE`` is
# 64 MiB; allow a small multipart/header slack on top.
_MAX_CHUNK_BODY_BYTES: int = 270 * 1024 * 1024


def _get_service(session: SessionDep) -> ResumableUploadService:
    return ResumableUploadService(session)


def _session_to_response(
    record: ResumableUploadSession,
    *,
    missing: list[int],
) -> SessionResponse:
    """Build a SessionResponse, surfacing the still-missing chunk indices."""
    return SessionResponse(
        id=record.id,
        project_id=record.project_id,
        filename=record.filename,
        category=record.category,
        total_size=record.total_size,
        chunk_size=record.chunk_size,
        total_chunks=record.total_chunks,
        received_chunks=sorted(int(i) for i in (record.received_chunks or [])),
        missing_chunks=missing,
        sha256=record.sha256,
        status=record.status,
        document_id=record.document_id,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


async def _require_project_write(
    project_id: uuid.UUID,
    category: str,
    user_id: str,
    session,  # type: ignore[no-untyped-def]
) -> None:
    """Gate the caller exactly like ``documents.upload_document``.

    Project member with folder write access (or owner / admin) passes; any
    other caller is 404'd so the project's existence is not leaked. Reuses
    the documents folder-permission helpers so resumable uploads honour the
    same per-folder grants as the single-shot path.
    """
    from app.modules.documents.folder_permissions_service import (
        can_write,
        folder_access_for,
        is_project_member,
        kind_and_path_for_document,
    )
    from app.modules.users.repository import UserRepository

    user_repo = UserRepository(session)
    try:
        user = await user_repo.get_by_id(uuid.UUID(str(user_id)))
    except Exception:
        user = None

    is_admin = user is not None and getattr(user, "role", "") == "admin"
    if not is_admin and not await is_project_member(session, project_id, uuid.UUID(str(user_id))):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    kind, path = kind_and_path_for_document(category)
    role = await folder_access_for(
        session,
        project_id=project_id,
        user_id=uuid.UUID(str(user_id)),
        scope_kind=kind,
        scope_path=path,
    )
    if not is_admin and (role is None or not can_write(role)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# ── Create session ───────────────────────────────────────────────────────────


@router.post("/sessions/", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    session: SessionDep,
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("resumable_uploads.create")),
    service: ResumableUploadService = Depends(_get_service),
) -> SessionResponse:
    """Open a resumable upload session and return its id + chunk plan."""
    await _require_project_write(payload.project_id, payload.category, user_id, session)

    allowed, _ = upload_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads. Please wait a moment and try again.",
            headers={"Retry-After": "60"},
        )

    record = await service.create_session(
        project_id=payload.project_id,
        filename=payload.filename,
        total_size=payload.total_size,
        chunk_size=payload.chunk_size,
        category=payload.category,
        sha256=payload.sha256,
        user_id=user_id,
    )
    return _session_to_response(record, missing=service.missing(record))


# ── Status ───────────────────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/", response_model=SessionResponse)
async def get_session_status(
    session: SessionDep,
    session_id: uuid.UUID = Path(...),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("resumable_uploads.read")),
    service: ResumableUploadService = Depends(_get_service),
) -> SessionResponse:
    """Report session status and the chunk indices still missing.

    The caller must have access to the session's project; a cross-tenant
    or missing session is 404.
    """
    record = await service.get_session(session_id)
    await verify_project_access(record.project_id, user_id, session)
    return _session_to_response(record, missing=service.missing(record))


# ── Upload a chunk (idempotent) ──────────────────────────────────────────────


@router.put("/sessions/{session_id}/chunks/{chunk_index}/", response_model=ChunkAcceptedResponse)
async def upload_chunk(
    request: Request,
    session: SessionDep,
    session_id: uuid.UUID = Path(...),
    chunk_index: int = Path(..., ge=0),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("resumable_uploads.create")),
    service: ResumableUploadService = Depends(_get_service),
) -> ChunkAcceptedResponse:
    """Store one chunk by index. Re-uploading a stored chunk is a no-op.

    The chunk bytes are the raw request body. Validation rejects an
    out-of-range index or a chunk whose size does not match the session
    contract for that index, and refuses an oversized body before it is
    buffered.
    """
    record = await service.get_session(session_id)
    await verify_project_access(record.project_id, user_id, session)
    await _require_project_write(record.project_id, record.category, user_id, session)

    # Refuse an oversized body before reading it into memory. Trust the
    # Content-Length header for the cheap pre-check; the exact-size match
    # in the service is the authoritative gate.
    content_length_header = request.headers.get("content-length")
    if content_length_header is not None:
        try:
            declared = int(content_length_header)
        except ValueError:
            declared = None
        if declared is not None and declared > _MAX_CHUNK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Chunk body too large",
            )

    # Stream the body in, capping the buffered size as a hard stop in case
    # the Content-Length header lied or was absent.
    buffered: list[bytes] = []
    total = 0
    async for piece in request.stream():
        if not piece:
            continue
        total += len(piece)
        if total > _MAX_CHUNK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Chunk body too large",
            )
        buffered.append(piece)
    data = b"".join(buffered)

    record, duplicate = await service.accept_chunk(record, chunk_index, data)
    return ChunkAcceptedResponse(
        session_id=record.id,
        chunk_index=chunk_index,
        received=len(record.received_chunks or []),
        total_chunks=record.total_chunks,
        duplicate=duplicate,
        status=record.status,
    )


# ── Complete ─────────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/complete/", response_model=CompleteResponse)
async def complete_session(
    session: SessionDep,
    session_id: uuid.UUID = Path(...),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("resumable_uploads.create")),
    service: ResumableUploadService = Depends(_get_service),
) -> CompleteResponse:
    """Assemble the chunks and hand the file to the document store.

    Returns 409 with the missing chunk list when the upload is incomplete,
    400 when the assembled size or SHA-256 does not match what was
    declared. On success the assembled file is stored and converted exactly
    as a single-shot document upload would be.
    """
    record = await service.get_session(session_id)
    await verify_project_access(record.project_id, user_id, session)
    await _require_project_write(record.project_id, record.category, user_id, session)

    document_service = DocumentService(session)
    record = await service.complete_session(
        record,
        document_service=document_service,
        user_id=user_id,
    )
    if record.document_id is None:
        # Defensive: a successful complete always sets document_id.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload completed without a document reference",
        )
    return CompleteResponse(
        session_id=record.id,
        document_id=record.document_id,
        filename=record.filename,
        file_size=record.total_size,
        status=record.status,
    )


# ── Abort ────────────────────────────────────────────────────────────────────


@router.delete("/sessions/{session_id}/", status_code=204)
async def abort_session(
    session: SessionDep,
    session_id: uuid.UUID = Path(...),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("resumable_uploads.delete")),
    service: ResumableUploadService = Depends(_get_service),
) -> None:
    """Abort a session and remove its scratch chunks."""
    record = await service.get_session(session_id)
    await verify_project_access(record.project_id, user_id, session)
    await _require_project_write(record.project_id, record.category, user_id, session)
    await service.abort_session(record)


# ── GC sweep (admin) ─────────────────────────────────────────────────────────


@router.post("/gc/")
async def gc_sweep(
    session: SessionDep,
    _admin: None = Depends(RequirePermission("system.settings.write")),
    service: ResumableUploadService = Depends(_get_service),
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, int]:
    """Reap stale in-flight sessions and prune old terminal rows.

    Admin-only maintenance endpoint. In-flight sessions past their TTL are
    expired and their chunks removed; terminal rows older than ``days`` are
    deleted.
    """
    from datetime import timedelta

    expired = await service.gc_expired(terminal_retention=timedelta(days=days))
    return {"expired": expired}
