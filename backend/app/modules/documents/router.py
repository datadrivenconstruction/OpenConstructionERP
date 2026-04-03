"""Document Management API routes.

Endpoints:
    POST   /upload                  — Upload a document
    GET    /?project_id=X           — List for project (with filters)
    GET    /{id}                    — Get document metadata
    GET    /{id}/download           — Download file
    PATCH  /{id}                    — Update metadata
    DELETE /{id}                    — Delete document + file
    GET    /summary?project_id=X    — Aggregated stats
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.documents.schemas import (
    DocumentResponse,
    DocumentSummary,
    DocumentUpdate,
)
from app.modules.documents.service import MAX_FILE_SIZE, UPLOAD_BASE, DocumentService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> DocumentService:
    return DocumentService(session)


def _doc_to_response(doc: object) -> DocumentResponse:
    """Build a DocumentResponse from a Document ORM object."""
    return DocumentResponse(
        id=doc.id,  # type: ignore[attr-defined]
        project_id=doc.project_id,  # type: ignore[attr-defined]
        name=doc.name,  # type: ignore[attr-defined]
        description=doc.description,  # type: ignore[attr-defined]
        category=doc.category,  # type: ignore[attr-defined]
        file_size=doc.file_size,  # type: ignore[attr-defined]
        mime_type=doc.mime_type,  # type: ignore[attr-defined]
        version=doc.version,  # type: ignore[attr-defined]
        uploaded_by=doc.uploaded_by,  # type: ignore[attr-defined]
        tags=getattr(doc, "tags", []),  # type: ignore[attr-defined]
        metadata=getattr(doc, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=doc.created_at,  # type: ignore[attr-defined]
        updated_at=doc.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary", response_model=DocumentSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DocumentService = Depends(_get_service),
) -> DocumentSummary:
    """Aggregated document stats for a project."""
    data = await service.get_summary(project_id)
    return DocumentSummary(**data)


# ── Upload ───────────────────────────────────────────────────────────────────


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    project_id: uuid.UUID = Query(...),
    category: str = Query(default="other"),
    file: UploadFile = File(...),
    content_length: int | None = Header(default=None),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.create")),
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Upload a document to a project."""
    # Early rejection based on Content-Length header (before reading body)
    if content_length is not None and content_length > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB.",
        )
    try:
        doc = await service.upload_document(project_id, file, category, user_id)
        return _doc_to_response(doc)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to upload document")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload document",
        )


# ── List ─────────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    service: DocumentService = Depends(_get_service),
) -> list[DocumentResponse]:
    """List documents for a project."""
    docs, _ = await service.list_documents(
        project_id,
        offset=offset,
        limit=limit,
        category=category,
        search=search,
    )
    return [_doc_to_response(d) for d in docs]


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Get a single document metadata."""
    doc = await service.get_document(document_id)
    return _doc_to_response(doc)


# ── Download ─────────────────────────────────────────────────────────────────


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DocumentService = Depends(_get_service),
) -> FileResponse:
    """Download a document file."""
    doc = await service.get_document(document_id)
    file_path = Path(doc.file_path).resolve()

    # Security: ensure resolved path is within the allowed upload directory
    upload_base = Path(UPLOAD_BASE).resolve()
    if not str(file_path).startswith(str(upload_base)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if not file_path.exists() or file_path.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )

    return FileResponse(
        path=str(file_path),
        filename=doc.name,
        media_type=doc.mime_type or "application/octet-stream",
    )


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: uuid.UUID,
    data: DocumentUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.update")),
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Update document metadata."""
    doc = await service.update_document(document_id, data)
    return _doc_to_response(doc)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: DocumentService = Depends(_get_service),
) -> None:
    """Delete a document and its file."""
    await service.delete_document(document_id)
