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

from app.core.bulk_ops import BulkDeleteRequest
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.documents.schemas import (
    DocumentBIMLinkCreate,
    DocumentBIMLinkListResponse,
    DocumentBIMLinkResponse,
    DocumentResponse,
    DocumentSummary,
    DocumentUpdate,
    PhotoResponse,
    PhotoTimelineGroup,
    PhotoUpdate,
    SheetResponse,
    SheetUpdate,
    SheetVersionHistory,
)
from app.modules.documents.service import (
    MAX_FILE_SIZE,
    PHOTO_BASE,
    UPLOAD_BASE,
    DocumentBIMLinkService,
    DocumentService,
    PhotoService,
    SheetService,
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
        # CDE / revision-chain fields
        cde_state=getattr(doc, "cde_state", None),  # type: ignore[attr-defined]
        suitability_code=getattr(doc, "suitability_code", None),  # type: ignore[attr-defined]
        revision_code=getattr(doc, "revision_code", None),  # type: ignore[attr-defined]
        drawing_number=getattr(doc, "drawing_number", None),  # type: ignore[attr-defined]
        is_current_revision=getattr(doc, "is_current_revision", True),  # type: ignore[attr-defined]
        parent_document_id=getattr(doc, "parent_document_id", None),  # type: ignore[attr-defined]
        security_classification=getattr(doc, "security_classification", None),  # type: ignore[attr-defined]
        discipline=getattr(doc, "discipline", None),  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary/", response_model=DocumentSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DocumentService = Depends(_get_service),
) -> DocumentSummary:
    """Aggregated document stats for a project."""
    data = await service.get_summary(project_id)
    return DocumentSummary(**data)


# ── Upload ───────────────────────────────────────────────────────────────────


@router.post("/upload/", response_model=DocumentResponse, status_code=201)
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


# ══════════════════════════════════════════════════════════════════════════
# Photo Gallery endpoints
# NOTE: These MUST come BEFORE /{document_id} parametric routes to avoid
#       FastAPI matching "/photos" as a document_id (route shadowing).
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


@router.post("/photos/upload/", response_model=PhotoResponse, status_code=201)
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


@router.get("/photos/", response_model=list[PhotoResponse])
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


@router.get("/photos/gallery/", response_model=list[PhotoResponse])
async def get_gallery(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> list[PhotoResponse]:
    """Get all photos for gallery view."""
    photos = await service.get_gallery(project_id)
    return [_photo_to_response(p) for p in photos]


# ── Timeline ────────────────────────────────────────────────────────────


@router.get("/photos/timeline/", response_model=list[PhotoTimelineGroup])
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


@router.get("/photos/{photo_id}/file/")
async def serve_photo_file(
    photo_id: uuid.UUID,
    service: PhotoService = Depends(_get_photo_service),
) -> FileResponse:
    """Serve the actual photo file."""
    photo = await service.get_photo(photo_id)
    file_path = Path(photo.file_path).resolve()
    photo_base = Path(PHOTO_BASE).resolve()

    # Security: Path.resolve().relative_to() handles case-insensitive FS + symlinks
    try:
        file_path.relative_to(photo_base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if file_path.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Symlinks not permitted",
        )

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo file not found on disk",
        )

    # Determine media type from extension
    ext = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
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


# ══════════════════════════════════════════════════════════════════════════
# Sheet Management endpoints
# NOTE: These MUST come BEFORE /{document_id} parametric routes.
# ══════════════════════════════════════════════════════════════════════════


def _get_sheet_service(session: SessionDep) -> SheetService:
    return SheetService(session)


def _sheet_to_response(sheet: object) -> SheetResponse:
    """Build a SheetResponse from a Sheet ORM object."""
    return SheetResponse(
        id=sheet.id,  # type: ignore[attr-defined]
        project_id=sheet.project_id,  # type: ignore[attr-defined]
        document_id=sheet.document_id,  # type: ignore[attr-defined]
        page_number=sheet.page_number,  # type: ignore[attr-defined]
        sheet_number=sheet.sheet_number,  # type: ignore[attr-defined]
        sheet_title=sheet.sheet_title,  # type: ignore[attr-defined]
        discipline=sheet.discipline,  # type: ignore[attr-defined]
        revision=sheet.revision,  # type: ignore[attr-defined]
        revision_date=sheet.revision_date,  # type: ignore[attr-defined]
        scale=sheet.scale,  # type: ignore[attr-defined]
        is_current=sheet.is_current,  # type: ignore[attr-defined]
        previous_version_id=sheet.previous_version_id,  # type: ignore[attr-defined]
        thumbnail_path=sheet.thumbnail_path,  # type: ignore[attr-defined]
        metadata=getattr(sheet, "metadata_", {}),  # type: ignore[attr-defined]
        created_by=sheet.created_by,  # type: ignore[attr-defined]
        created_at=sheet.created_at,  # type: ignore[attr-defined]
        updated_at=sheet.updated_at,  # type: ignore[attr-defined]
    )


# ── List sheets ────────────────────────────────────────────────────────


@router.get("/sheets/", response_model=list[SheetResponse])
async def list_sheets(
    project_id: uuid.UUID = Query(...),
    discipline: str | None = Query(default=None),
    revision: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    current_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SheetService = Depends(_get_sheet_service),
) -> list[SheetResponse]:
    """List sheets for a project with optional filters."""
    sheets, _ = await service.list_sheets(
        project_id,
        offset=offset,
        limit=limit,
        discipline=discipline,
        revision=revision,
        document_id=document_id,
        current_only=current_only,
    )
    return [_sheet_to_response(s) for s in sheets]


# ── Distinct disciplines ───────────────────────────────────────────────


@router.get("/sheets/disciplines/", response_model=list[str])
async def list_disciplines(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SheetService = Depends(_get_sheet_service),
) -> list[str]:
    """List distinct discipline values for a project."""
    return await service.get_disciplines(project_id)


# ── Split PDF into sheets ──────────────────────────────────────────────


@router.post("/sheets/split-pdf/", response_model=list[SheetResponse], status_code=201)
async def split_pdf(
    project_id: uuid.UUID = Query(...),
    file: UploadFile = File(...),
    content_length: int | None = Header(default=None),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.create")),
    service: SheetService = Depends(_get_sheet_service),
) -> list[SheetResponse]:
    """Upload a multi-page PDF and auto-split into individual sheets.

    Extracts text from each page to detect sheet number, title, scale,
    and revision. Auto-detects discipline from sheet number prefix.
    Generates thumbnails for each page.
    """
    if content_length is not None and content_length > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB.",
        )
    try:
        sheets = await service.split_pdf_to_sheets(project_id, file, user_id)
        return [_sheet_to_response(s) for s in sheets]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to split PDF into sheets")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to split PDF into sheets",
        )


# ── Get single sheet ───────────────────────────────────────────────────


@router.get("/sheets/{sheet_id}", response_model=SheetResponse)
async def get_sheet(
    sheet_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SheetService = Depends(_get_sheet_service),
) -> SheetResponse:
    """Get a single sheet's metadata."""
    sheet = await service.get_sheet(sheet_id)
    return _sheet_to_response(sheet)


# ── Update sheet ───────────────────────────────────────────────────────


@router.patch("/sheets/{sheet_id}", response_model=SheetResponse)
async def update_sheet(
    sheet_id: uuid.UUID,
    data: SheetUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.update")),
    service: SheetService = Depends(_get_sheet_service),
) -> SheetResponse:
    """Update sheet metadata (discipline, title, revision, etc.)."""
    sheet = await service.update_sheet(sheet_id, data)
    return _sheet_to_response(sheet)


# ── Version history ────────────────────────────────────────────────────


@router.get("/sheets/{sheet_id}/versions/", response_model=SheetVersionHistory)
async def get_sheet_versions(
    sheet_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SheetService = Depends(_get_sheet_service),
) -> SheetVersionHistory:
    """Get version history for a sheet."""
    result = await service.get_version_history(sheet_id)
    return SheetVersionHistory(
        current=_sheet_to_response(result["current"]),
        history=[_sheet_to_response(s) for s in result["history"]],
    )


# ══════════════════════════════════════════════════════════════════════════
# Document ↔ BIM element links
# NOTE: These MUST come BEFORE /{document_id} parametric routes to avoid
#       FastAPI matching "/bim-links" as a document_id (route shadowing).
# ══════════════════════════════════════════════════════════════════════════


def _get_bim_link_service(session: SessionDep) -> DocumentBIMLinkService:
    return DocumentBIMLinkService(session)


def _bim_link_to_response(link: object) -> DocumentBIMLinkResponse:
    """Build a DocumentBIMLinkResponse from a DocumentBIMLink ORM object."""
    return DocumentBIMLinkResponse.model_validate(link)


@router.get("/bim-links/", response_model=DocumentBIMLinkListResponse)
async def list_bim_links(
    element_id: uuid.UUID | None = Query(default=None),
    document_id: uuid.UUID | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.read")),
    service: DocumentBIMLinkService = Depends(_get_bim_link_service),
) -> DocumentBIMLinkListResponse:
    """List Document ↔ BIM element links.

    Exactly one of ``element_id`` or ``document_id`` must be supplied:
    - ``element_id=X`` — every document linked to BIM element X
    - ``document_id=Y`` — every BIM element linked from document Y
    """
    if (element_id is None) == (document_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Exactly one of 'element_id' or 'document_id' must be provided",
        )

    if element_id is not None:
        links = await service.list_links_for_element(element_id)
    else:
        assert document_id is not None  # narrowing for type-checkers
        links = await service.list_links_for_document(document_id)

    items = [_bim_link_to_response(link) for link in links]
    return DocumentBIMLinkListResponse(items=items, total=len(items))


@router.post(
    "/bim-links/",
    response_model=DocumentBIMLinkResponse,
    status_code=201,
)
async def create_bim_link(
    payload: DocumentBIMLinkCreate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.create")),
    service: DocumentBIMLinkService = Depends(_get_bim_link_service),
) -> DocumentBIMLinkResponse:
    """Create a new Document ↔ BIM element link."""
    parsed_user_id: uuid.UUID | None = None
    if user_id:
        try:
            parsed_user_id = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            parsed_user_id = None

    link = await service.create_link(payload, user_id=parsed_user_id)
    return _bim_link_to_response(link)


@router.delete("/bim-links/{link_id}", status_code=204)
async def delete_bim_link(
    link_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: DocumentBIMLinkService = Depends(_get_bim_link_service),
) -> None:
    """Delete a Document ↔ BIM element link."""
    await service.delete_link(link_id)


# ══════════════════════════════════════════════════════════════════════════
# Bulk operations (must come BEFORE parametric /{document_id})
# ══════════════════════════════════════════════════════════════════════════


@router.post(
    "/batch/delete/",
    status_code=200,
    dependencies=[Depends(RequirePermission("documents.delete"))],
)
async def batch_delete_documents(
    body: BulkDeleteRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Delete multiple documents in one request."""
    from sqlalchemy import select as _select

    from app.core.bulk_ops import bulk_delete
    from app.modules.documents.models import Document
    from app.modules.projects.repository import ProjectRepository

    proj_repo = ProjectRepository(session)
    owned_projects, _ = await proj_repo.list_for_user(
        owner_id=user_id, offset=0, limit=10000, exclude_archived=False
    )
    owned_project_ids = {str(p.id) for p in owned_projects}

    rows = (await session.execute(
        _select(Document.id, Document.project_id).where(Document.id.in_(body.ids))
    )).all()
    allowed = [r[0] for r in rows if str(r[1]) in owned_project_ids]

    deleted = await bulk_delete(session, Document, allowed)
    logger.info(
        "Bulk delete documents: requested=%d deleted=%d user=%s",
        len(body.ids), deleted, user_id,
    )
    return {"requested": len(body.ids), "deleted": deleted}


# ══════════════════════════════════════════════════════════════════════════
# Document CRUD by ID (parametric routes — MUST be after /photos/* and /sheets/* routes)
# ══════════════════════════════════════════════════════════════════════════


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


@router.get(
    "/{document_id}/download/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def download_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    service: DocumentService = Depends(_get_service),
) -> FileResponse:
    """Download a document file.

    Security: uses ``Path.resolve().relative_to()`` for containment check so
    case-insensitive filesystems and symlinks cannot escape ``UPLOAD_BASE``.
    """
    doc = await service.get_document(document_id)
    file_path = Path(doc.file_path).resolve()
    upload_base = Path(UPLOAD_BASE).resolve()

    # Security: path must be STRICTLY inside upload_base after full resolution.
    # ``str.startswith`` can be fooled on Windows case-insensitive FS and by
    # symlinks; ``relative_to`` rejects both cases explicitly.
    try:
        file_path.relative_to(upload_base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if file_path.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Symlinks not permitted",
        )

    if not file_path.exists() or not file_path.is_file():
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


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# These three routes plug the Documents module into the cross-module
# semantic memory layer (see ``app/core/vector_index.py``).  They are
# intentionally uniform across every module that participates — only the
# adapter and the row loader differ.


@router.get(
    "/vector/status/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def documents_vector_status() -> dict:
    """Return health + row count for the ``oe_documents`` collection.

    Used by the admin panel and the global search status widget so the
    user can tell at a glance whether semantic search over documents is
    ready, partially indexed or empty.
    """
    from app.core.vector_index import COLLECTION_DOCUMENTS, collection_status

    return collection_status(COLLECTION_DOCUMENTS)


@router.post(
    "/vector/reindex/",
    dependencies=[Depends(RequirePermission("documents.update"))],
)
async def documents_vector_reindex(
    session: SessionDep,
    _user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    purge_first: bool = Query(default=False),
) -> dict:
    """Backfill the documents vector collection.

    Optional ``project_id`` filter narrows the scope so users can reindex
    one project at a time without re-embedding the entire tenant.  Set
    ``purge_first=true`` to wipe the matching subset before re-encoding —
    useful when the embedding model has changed.
    """
    from sqlalchemy import select

    from app.core.vector_index import reindex_collection
    from app.modules.documents.models import Document
    from app.modules.documents.vector_adapter import document_vector_adapter

    stmt = select(Document)
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)

    rows = list((await session.execute(stmt)).scalars().all())
    return await reindex_collection(
        document_vector_adapter,
        rows,
        purge_first=purge_first,
    )


@router.get(
    "/{document_id}/similar/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def documents_similar(
    document_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=True),
) -> dict:
    """Return documents semantically similar to the given one.

    By default the search is **cross-project** — that's the highest-value
    use case: engineers want to find how a similar drawing or spec was
    handled on past projects so they can reuse context.  Pass
    ``cross_project=false`` to limit the search to the same project.

    Returns a list of :class:`VectorHit` dicts plus the original row id
    so the frontend can highlight the source.
    """
    from sqlalchemy import select

    from app.core.vector_index import find_similar
    from app.modules.documents.models import Document
    from app.modules.documents.vector_adapter import document_vector_adapter

    stmt = select(Document).where(Document.id == document_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    project_id = str(row.project_id) if row.project_id is not None else None
    hits = await find_similar(
        document_vector_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
    )
    return {
        "source_id": str(document_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }
