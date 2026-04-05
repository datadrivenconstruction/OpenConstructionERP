"""Document Management API routes.

Endpoints:
    POST   /upload                  — Upload a document
    GET    /?project_id=X           — List for project (with filters)
    GET    /{id}                    — Get document metadata
    GET    /{id}/download           — Download file
    PATCH  /{id}                    — Update metadata
    DELETE /{id}                    — Delete document + file
    GET    /summary?project_id=X    — Aggregated stats

    POST   /photos/upload           — Upload a photo
    GET    /photos?project_id=X     — List photos with filters
    GET    /photos/gallery          — Gallery data
    GET    /photos/timeline         — Photos grouped by date
    GET    /photos/{id}             — Get photo metadata
    GET    /photos/{id}/file        — Serve photo file
    PATCH  /photos/{id}             — Update photo metadata
    DELETE /photos/{id}             — Delete photo + file
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.documents.schemas import (
    DocumentResponse,
    DocumentSummary,
    DocumentUpdate,
    PhotoResponse,
    PhotoTimelineGroup,
    PhotoUpdate,
)
from app.modules.documents.service import (
    MAX_FILE_SIZE,
    PHOTO_BASE,
    UPLOAD_BASE,
    DocumentService,
    PhotoService,
)

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


# ══════════════════════════════════════════════════════════════════════════
# Photo Gallery endpoints
# ══════════════════════════════════════════════════════════════════════════


def _get_photo_service(session: SessionDep) -> PhotoService:
    return PhotoService(session)


def _photo_to_response(photo: object) -> PhotoResponse:
    """Build a PhotoResponse from a ProjectPhoto ORM object."""
    return PhotoResponse(
        id=photo.id,  # type: ignore[attr-defined]
        project_id=photo.project_id,  # type: ignore[attr-defined]
        document_id=photo.document_id,  # type: ignore[attr-defined]
        filename=photo.filename,  # type: ignore[attr-defined]
        file_path="",  # Never expose full server path
        caption=photo.caption,  # type: ignore[attr-defined]
        gps_lat=photo.gps_lat,  # type: ignore[attr-defined]
        gps_lon=photo.gps_lon,  # type: ignore[attr-defined]
        tags=getattr(photo, "tags", []),  # type: ignore[attr-defined]
        taken_at=photo.taken_at,  # type: ignore[attr-defined]
        category=photo.category,  # type: ignore[attr-defined]
        metadata=getattr(photo, "metadata_", {}),  # type: ignore[attr-defined]
        created_by=photo.created_by,  # type: ignore[attr-defined]
        created_at=photo.created_at,  # type: ignore[attr-defined]
        updated_at=photo.updated_at,  # type: ignore[attr-defined]
    )


# ── Upload photo ────────────────────────────────────────────────────────


@router.post("/photos/upload", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    project_id: uuid.UUID = Query(...),
    category: str = Form(default="site"),
    caption: str | None = Form(default=None),
    gps_lat: float | None = Form(default=None),
    gps_lon: float | None = Form(default=None),
    tags: str | None = Form(default=None),
    taken_at: str | None = Form(default=None),
    file: UploadFile = File(...),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.create")),
    service: PhotoService = Depends(_get_photo_service),
) -> PhotoResponse:
    """Upload a photo with metadata to a project."""
    # Parse tags from comma-separated string
    parsed_tags: list[str] = []
    if tags:
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    # Parse taken_at datetime
    parsed_taken_at: datetime | None = None
    if taken_at:
        try:
            parsed_taken_at = datetime.fromisoformat(taken_at)
        except ValueError:
            pass

    photo = await service.upload_photo(
        project_id=project_id,
        file=file,
        category=category,
        user_id=user_id,
        caption=caption,
        gps_lat=gps_lat,
        gps_lon=gps_lon,
        tags=parsed_tags,
        taken_at=parsed_taken_at,
    )
    return _photo_to_response(photo)


# ── List photos ─────────────────────────────────────────────────────────


@router.get("/photos", response_model=list[PhotoResponse])
async def list_photos(
    project_id: uuid.UUID = Query(...),
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> list[PhotoResponse]:
    """List photos for a project with optional filters."""
    parsed_date_from: datetime | None = None
    parsed_date_to: datetime | None = None
    if date_from:
        try:
            parsed_date_from = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            parsed_date_to = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    photos, _ = await service.list_photos(
        project_id,
        offset=offset,
        limit=limit,
        category=category,
        tag=tag,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        search=search,
    )
    return [_photo_to_response(p) for p in photos]


# ── Gallery ─────────────────────────────────────────────────────────────


@router.get("/photos/gallery", response_model=list[PhotoResponse])
async def get_gallery(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> list[PhotoResponse]:
    """Get all photos for gallery view."""
    photos = await service.get_gallery(project_id)
    return [_photo_to_response(p) for p in photos]


# ── Timeline ────────────────────────────────────────────────────────────


@router.get("/photos/timeline", response_model=list[PhotoTimelineGroup])
async def get_timeline(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> list[PhotoTimelineGroup]:
    """Get photos grouped by date for timeline view."""
    groups = await service.get_timeline(project_id)
    return [
        PhotoTimelineGroup(
            date=g["date"],
            photos=[_photo_to_response(p) for p in g["photos"]],
        )
        for g in groups
    ]


# ── Get single photo ────────────────────────────────────────────────────


@router.get("/photos/{photo_id}", response_model=PhotoResponse)
async def get_photo(
    photo_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> PhotoResponse:
    """Get a single photo's metadata."""
    photo = await service.get_photo(photo_id)
    return _photo_to_response(photo)


# ── Serve photo file ────────────────────────────────────────────────────


@router.get("/photos/{photo_id}/file")
async def serve_photo_file(
    photo_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> FileResponse:
    """Serve the actual photo file."""
    photo = await service.get_photo(photo_id)
    file_path = Path(photo.file_path).resolve()

    # Security: ensure resolved path is within allowed photo directory
    photo_base = Path(PHOTO_BASE).resolve()
    if not str(file_path).startswith(str(photo_base)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if not file_path.exists() or file_path.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo file not found on disk",
        )

    # Determine media type from extension
    ext = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".heic": "image/heic", ".heif": "image/heif",
        ".tiff": "image/tiff", ".tif": "image/tiff",
    }
    media_type = media_types.get(ext, "image/jpeg")

    return FileResponse(
        path=str(file_path),
        filename=photo.filename,
        media_type=media_type,
    )


# ── Update photo ────────────────────────────────────────────────────────


@router.patch("/photos/{photo_id}", response_model=PhotoResponse)
async def update_photo(
    photo_id: uuid.UUID,
    data: PhotoUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.update")),
    service: PhotoService = Depends(_get_photo_service),
) -> PhotoResponse:
    """Update photo metadata (caption, tags, category)."""
    photo = await service.update_photo(photo_id, data)
    return _photo_to_response(photo)


# ── Delete photo ────────────────────────────────────────────────────────


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_photo(
    photo_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: PhotoService = Depends(_get_photo_service),
) -> None:
    """Delete a photo and its file."""
    await service.delete_photo(photo_id)
