"""‌⁠‍Document Management API routes.

Endpoints:
    POST   /upload                  - Upload a document
    GET    /?project_id=X           - List for project (with filters)
    GET    /{id}                    - Get document metadata
    GET    /{id}/download           - Download file
    PATCH  /{id}                    - Update metadata
    DELETE /{id}                    - Delete document + file
    GET    /summary?project_id=X    - Aggregated stats

    POST   /photos/upload           - Upload a photo
    GET    /photos?project_id=X     - List photos with filters
    GET    /photos/gallery          - Gallery data
    GET    /photos/timeline         - Photos grouped by date
    GET    /photos/{id}             - Get photo metadata
    GET    /photos/{id}/file        - Serve photo file
    PATCH  /photos/{id}             - Update photo metadata
    DELETE /photos/{id}             - Delete photo + file
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.core.bulk_ops import BulkDeleteRequest
from app.core.demo_placeholders import materialize_placeholder
from app.core.i18n import get_locale
from app.core.rate_limiter import upload_limiter
from app.core.storage import is_within_safe_root
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.documents.schemas import (
    DocumentActivityResponse,
    DocumentBIMLinkCreate,
    DocumentBIMLinkListResponse,
    DocumentBIMLinkResponse,
    DocumentResponse,
    DocumentSummary,
    DocumentUpdate,
    PhotoResponse,
    PhotoTimelineGroup,
    PhotoUpdate,
    RecentPhotoResponse,
    ShareLinkAccessRequest,
    ShareLinkAccessResponse,
    ShareLinkCreate,
    ShareLinkListItem,
    ShareLinkPublicInfo,
    ShareLinkResponse,
    SheetResponse,
    SheetUpdate,
    SheetVersionHistory,
)
from app.modules.documents.service import (
    PHOTO_BASE,
    PHOTO_THUMB_BASE,
    UPLOAD_BASE,
    DocumentBIMLinkService,
    DocumentService,
    PhotoService,
    SheetService,
    _sanitize_filename,
)

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> DocumentService:
    return DocumentService(session)


# ── Folder-permission integration helpers ───────────────────────────────────
#
# ``verify_project_access`` returns 404 for any non-owner. That keeps
# cross-project IDOR clean for the strict majority of endpoints, but it
# also blocks legitimate project MEMBERS from listing files they
# nominally have access to. The folder-permissions feature (Issue #FP)
# extends the contract: project members can list / read / delete /
# upload files within the scope of any grant they have.
#
# We do NOT change ``verify_project_access`` itself - it's used by
# dozens of unrelated routers and tightening it touches risk we don't
# want here. Instead the document-list / get / delete endpoints use a
# more permissive helper that allows project members through, and then
# the folder-permissions service decides what they actually see.


async def _verify_project_membership_or_404(
    project_id: uuid.UUID,
    user_id: str,
    session,  # type: ignore[no-untyped-def]
) -> None:
    """Raise 404 unless the caller can see ``project_id`` at all.

    Allowed callers:
        * admins (matches ``verify_project_access`` admin bypass)
        * project owner
        * any member of the project's default team

    The 404 surface matches ``verify_project_access`` so attackers
    can't distinguish "wrong project id" from "project exists, you're
    not a member".
    """
    from app.modules.documents.folder_permissions_service import is_project_member
    from app.modules.users.repository import UserRepository

    user_repo = UserRepository(session)
    try:
        user = await user_repo.get_by_id(uuid.UUID(str(user_id)))
    except Exception:
        user = None

    if user is not None and getattr(user, "role", "") == "admin":
        # Make sure the project actually exists for admins too - leaking
        # "yes this id exists" on a non-existent project is undesirable.
        from app.modules.projects.repository import ProjectRepository

        proj_repo = ProjectRepository(session)
        if await proj_repo.get_by_id(project_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.project_not_found", locale=get_locale()),
            )
        return

    if not await is_project_member(session, project_id, uuid.UUID(str(user_id))):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("errors.project_not_found", locale=get_locale()),
        )


def _doc_to_response(doc: object) -> DocumentResponse:
    """‌⁠‍Build a DocumentResponse from a Document ORM object."""
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
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: DocumentService = Depends(_get_service),
) -> DocumentSummary:
    """‌⁠‍Aggregated document stats for a project."""
    await verify_project_access(project_id, user_id, session)
    data = await service.get_summary(project_id)
    return DocumentSummary(**data)


# ── Upload ───────────────────────────────────────────────────────────────────


@router.post("/upload/", response_model=DocumentResponse, status_code=201)
async def upload_document(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    category: str = Query(default="other"),
    file: UploadFile = File(...),
    content_length: int | None = Header(default=None),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.create")),
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Upload a document to a project, honoring folder permissions.

    Members can upload into folders they have an ``editor`` or
    ``owner`` grant on, OR into folders that have no grants at all
    (still open to every project member). Non-members 404.
    """
    await _verify_project_membership_or_404(project_id, user_id, session)

    from app.modules.documents.folder_permissions_service import (
        can_write,
        folder_access_for,
        kind_and_path_for_document,
    )

    kind, path = kind_and_path_for_document(category)
    role = await folder_access_for(
        session,
        project_id=project_id,
        user_id=uuid.UUID(str(user_id)),
        scope_kind=kind,
        scope_path=path,
    )
    # 404 (not 403) keeps enumeration symmetric with list/get/delete.
    if role is None or not can_write(role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )
    allowed, _ = upload_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads. Please wait a moment and try again.",
            headers={"Retry-After": "60"},
        )
    # No upload size cap - per product policy.
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
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str | None = Query(default=None, description="Sort field: name, created_at, category"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: DocumentService = Depends(_get_service),
) -> list[DocumentResponse]:
    """List documents for a project, honoring folder permissions.

    Project owners (and admins) see everything. Project members see:
        * every document whose ``(scope_kind, scope_path)`` has NO
          grant on the project (those folders are "open to all
          members" by default), AND
        * every document whose ``(scope_kind, scope_path)`` has at
          least one grant covering this user.

    Documents the caller cannot see are filtered out server-side. We
    deliberately do not 404 here even when the filtered list is empty
    - knowing the project exists and being told "no files" is the
    expected surface for a member who hasn't been granted a folder
    yet.
    """
    await _verify_project_membership_or_404(project_id, user_id, session)
    docs, _ = await service.list_documents(
        project_id,
        offset=offset,
        limit=limit,
        category=category,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    # Owners and admins bypass folder filtering entirely.
    from app.modules.documents.folder_permissions_service import (
        effective_permissions_for,
        is_project_owner,
        kind_and_path_for_document,
        restricted_scopes_for_project,
    )

    user_uuid = uuid.UUID(str(user_id))
    if await is_project_owner(session, project_id, user_uuid):
        return [_doc_to_response(d) for d in docs]

    # Admin bypass - _verify_project_membership_or_404 already let them
    # through, but we still need to skip filtering for them.
    from app.modules.users.repository import UserRepository

    user = await UserRepository(session).get_by_id(user_uuid)
    if user is not None and getattr(user, "role", "") == "admin":
        return [_doc_to_response(d) for d in docs]

    grants = await effective_permissions_for(
        session,
        project_id=project_id,
        user_id=user_uuid,
    )
    restricted = await restricted_scopes_for_project(session, project_id)

    visible: list = []
    for doc in docs:
        kind, path = kind_and_path_for_document(doc.category)
        # If the folder has any grant, only show docs the user has
        # an explicit grant on (exact scope OR wildcard for the kind).
        is_restricted = (kind, path) in restricted or (kind, None) in restricted
        if not is_restricted:
            visible.append(doc)
            continue
        if (kind, path) in grants or (kind, None) in grants:
            visible.append(doc)

    return [_doc_to_response(d) for d in visible]


@router.get("/file-types-by-project/")
async def file_types_by_project(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, list[str]]:
    """Aggregate map ``{project_id: [file_types]}`` used by the Projects
    page to render "has RVT / IFC / DWG / PDF" chips on each card in a
    single round-trip (instead of N requests, one per card).

    Uses the same owner-OR-member project set as the project list and
    dashboard endpoints (admins see every project) so team-member projects
    keep their file-type chips. Returns extensions lower-cased, without the
    leading dot. Any project the caller cannot read is silently omitted.
    """
    from sqlalchemy import select as _select

    from app.modules.documents.models import Document
    from app.modules.projects.models import Project
    from app.modules.teams.access import member_project_ids_subquery
    from app.modules.users.repository import UserRepository

    if user_id is None:
        return {}
    user_uuid = uuid.UUID(str(user_id))

    # Owner-OR-member set, mirroring ``list_projects`` / ``dashboard_cards``.
    # Admins bypass the ownership check and see every project's chips.
    user = await UserRepository(session).get_by_id(user_uuid)
    is_admin = user is not None and getattr(user, "role", "") == "admin"
    if is_admin:
        proj_stmt = _select(Project.id)
    else:
        proj_stmt = _select(Project.id).where(
            (Project.owner_id == user_uuid) | (Project.id.in_(member_project_ids_subquery(user_uuid)))
        )
    visible_ids = (await session.execute(proj_stmt)).scalars().all()
    if not visible_ids:
        return {}

    rows = (
        await session.execute(
            _select(Document.project_id, Document.file_path, Document.name).where(
                Document.project_id.in_(visible_ids),
            ),
        )
    ).all()

    # Map project → set of extensions. Prefer Document.name (user-visible
    # filename) since file_path may be a storage key without an extension.
    from pathlib import Path as _Path

    out: dict[str, set[str]] = {}
    for project_id, file_path, name in rows:
        ext = (_Path(str(name or "")).suffix or _Path(str(file_path or "")).suffix).lower().lstrip(".")
        if not ext:
            continue
        out.setdefault(str(project_id), set()).add(ext)

    return {k: sorted(v) for k, v in out.items()}


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
        has_thumbnail=bool(getattr(photo, "thumbnail_path", None)),
    )


# ── Upload photo ────────────────────────────────────────────────────────


@router.post("/photos/upload/", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    session: SessionDep,
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
    await verify_project_access(project_id, user_id, session)
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
    session: SessionDep,
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
    await verify_project_access(project_id, user_id, session)
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
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> list[PhotoResponse]:
    """Get all photos for gallery view."""
    await verify_project_access(project_id, user_id, session)
    photos = await service.get_gallery(project_id)
    return [_photo_to_response(p) for p in photos]


# ── Timeline ────────────────────────────────────────────────────────────


@router.get("/photos/timeline/", response_model=list[PhotoTimelineGroup])
async def get_timeline(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PhotoService = Depends(_get_photo_service),
) -> list[PhotoTimelineGroup]:
    """Get photos grouped by date for timeline view."""
    await verify_project_access(project_id, user_id, session)
    groups = await service.get_timeline(project_id)
    return [
        PhotoTimelineGroup(
            date=g["date"],
            photos=[_photo_to_response(p) for p in g["photos"]],
        )
        for g in groups
    ]


# ── Recent photos across the caller's projects ──────────────────────────


@router.get(
    "/photos/recent/",
    response_model=list[RecentPhotoResponse],
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def list_recent_photos(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    limit: int = Query(default=12, ge=1, le=48),
    service: PhotoService = Depends(_get_photo_service),
) -> list[RecentPhotoResponse]:
    """Most recent photos across every project the caller can access.

    Powers the dashboard "Latest site photos" widget. Access control is
    enforced in the service: only projects the user owns or is a member
    of (admins: all) contribute photos, so this never leaks site
    documentation from a project the caller cannot open. Ordered newest
    first by ``taken_at`` with ``created_at`` as the null fallback.

    Each item carries the project name (joined server-side) and a
    relative thumbnail URL matching the existing ``/photos/{id}/thumb/``
    route the gallery already loads through ``AuthImage``.
    """
    rows = await service.recent_across_projects(user_id, limit=limit)
    return [
        RecentPhotoResponse(
            id=photo.id,
            project_id=photo.project_id,
            project_name=project_name,
            caption=photo.caption,
            category=photo.category,
            taken_at=photo.taken_at,
            created_at=photo.created_at,
            file_url=f"/api/v1/documents/photos/{photo.id}/thumb/",
        )
        for photo, project_name in rows
    ]


# ── Get single photo ────────────────────────────────────────────────────


@router.get(
    "/photos/{photo_id}",
    response_model=PhotoResponse,
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def get_photo(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PhotoService = Depends(_get_photo_service),
) -> PhotoResponse:
    """Get a single photo's metadata.

    IDOR-guarded via the parent project (A-DOC-04): a non-member is
    404'd before any photo metadata is disclosed - same contract as
    ``serve_photo_file`` / ``get_sheet``.
    """
    photo = await service.get_photo(photo_id)
    await verify_project_access(photo.project_id, user_id, session)
    return _photo_to_response(photo)


# ── Serve photo file ────────────────────────────────────────────────────


@router.get(
    "/photos/{photo_id}/file/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def serve_photo_file(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PhotoService = Depends(_get_photo_service),
) -> FileResponse:
    """Serve the actual photo file."""
    photo = await service.get_photo(photo_id)
    await verify_project_access(photo.project_id, user_id, session)
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

    safe_dl_name = _sanitize_filename(photo.filename or f"photo{ext}")
    return FileResponse(
        path=str(file_path),
        filename=safe_dl_name,
        media_type=media_type,
        content_disposition_type="attachment",
    )


# ── Serve photo thumbnail ──────────────────────────────────────────────


@router.get(
    "/photos/{photo_id}/thumb/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def serve_photo_thumbnail(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PhotoService = Depends(_get_photo_service),
) -> FileResponse:
    """Serve the generated thumbnail for a photo.

    Falls back to the full-resolution file when no thumbnail was generated
    (legacy photos uploaded before the thumbnail pipeline, or images for
    which Pillow couldn't produce a thumb). The fallback keeps the gallery
    grid functional rather than showing broken-image tiles.
    """
    photo = await service.get_photo(photo_id)
    await verify_project_access(photo.project_id, user_id, session)
    thumb_path_str = getattr(photo, "thumbnail_path", None)

    thumb_base = Path(PHOTO_THUMB_BASE).resolve()
    photo_base = Path(PHOTO_BASE).resolve()

    if thumb_path_str:
        thumb_path = Path(thumb_path_str).resolve()
        try:
            # Only allow paths that sit under the thumb-root - defence against
            # symlink escape + stored-path tampering.
            thumb_path.relative_to(thumb_base)
            if thumb_path.exists() and thumb_path.is_file() and not thumb_path.is_symlink():
                return FileResponse(
                    path=str(thumb_path),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"},
                )
        except ValueError:
            logger.warning(
                "Photo %s has thumbnail_path outside thumb base - ignoring",
                photo_id,
            )

    # Fallback: serve the full file so the gallery never breaks.
    file_path = Path(photo.file_path).resolve()
    try:
        file_path.relative_to(photo_base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    if file_path.is_symlink() or not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo file not found on disk",
        )
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
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Update photo ────────────────────────────────────────────────────────


@router.patch("/photos/{photo_id}", response_model=PhotoResponse)
async def update_photo(
    photo_id: uuid.UUID,
    data: PhotoUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.update")),
    service: PhotoService = Depends(_get_photo_service),
) -> PhotoResponse:
    """Update photo metadata (caption, tags, category).

    R7 audit: the caller must have access to the photo's parent project
    - without this guard any user with the ``documents.update``
    permission could edit a photo belonging to another tenant by
    guessing its UUID. ``verify_project_access`` collapses missing /
    cross-tenant into the same 404 surface so the response cannot be
    used as an enumeration oracle.
    """
    photo = await service.get_photo(photo_id)
    await verify_project_access(photo.project_id, user_id, session)
    photo = await service.update_photo(photo_id, data)
    return _photo_to_response(photo)


# ── Delete photo ────────────────────────────────────────────────────────


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_photo(
    photo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: PhotoService = Depends(_get_photo_service),
) -> None:
    """Delete a photo and its file.

    R7 audit: cross-tenant IDOR guard. Mirrors ``update_photo`` -
    without it, knowledge of a UUID was enough to wipe another tenant's
    site documentation.
    """
    photo = await service.get_photo(photo_id)
    await verify_project_access(photo.project_id, user_id, session)
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
    session: SessionDep,
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
    await verify_project_access(project_id, user_id, session)
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
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SheetService = Depends(_get_sheet_service),
) -> list[str]:
    """List distinct discipline values for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_disciplines(project_id)


# ── Split PDF into sheets ──────────────────────────────────────────────


@router.post("/sheets/split-pdf/", response_model=list[SheetResponse], status_code=201)
async def split_pdf(
    session: SessionDep,
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
    await verify_project_access(project_id, user_id, session)
    # No upload size cap - per product policy.
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


@router.get(
    "/sheets/{sheet_id}",
    response_model=SheetResponse,
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def get_sheet(
    sheet_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SheetService = Depends(_get_sheet_service),
) -> SheetResponse:
    """Get a single sheet's metadata."""
    sheet = await service.get_sheet(sheet_id)
    await verify_project_access(sheet.project_id, user_id, session)
    return _sheet_to_response(sheet)


# ── Update sheet ───────────────────────────────────────────────────────


@router.patch("/sheets/{sheet_id}", response_model=SheetResponse)
async def update_sheet(
    sheet_id: uuid.UUID,
    data: SheetUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.update")),
    service: SheetService = Depends(_get_sheet_service),
) -> SheetResponse:
    """Update sheet metadata (discipline, title, revision, etc.).

    R7 audit: cross-tenant IDOR guard on the parent project. Without
    it, ``documents.update`` was enough to mutate any tenant's sheet
    metadata.
    """
    sheet = await service.get_sheet(sheet_id)
    await verify_project_access(sheet.project_id, user_id, session)
    sheet = await service.update_sheet(sheet_id, data)
    return _sheet_to_response(sheet)


# ── Delete sheet ───────────────────────────────────────────────────────


@router.delete("/sheets/{sheet_id}", status_code=204)
async def delete_sheet(
    sheet_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: SheetService = Depends(_get_sheet_service),
) -> None:
    """Hard-delete a sheet (drawing page extracted from a multi-page PDF).

    IDOR-guarded via the parent project so a 404 is returned for sheets
    the caller cannot reach.
    """
    sheet = await service.get_sheet(sheet_id)
    await verify_project_access(sheet.project_id, user_id, session)
    await service.delete_sheet(sheet_id)


# ── Version history ────────────────────────────────────────────────────


@router.get(
    "/sheets/{sheet_id}/versions/",
    response_model=SheetVersionHistory,
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def get_sheet_versions(
    sheet_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SheetService = Depends(_get_sheet_service),
) -> SheetVersionHistory:
    """Get version history for a sheet."""
    sheet = await service.get_sheet(sheet_id)
    await verify_project_access(sheet.project_id, user_id, session)
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
    session: SessionDep,
    element_id: uuid.UUID | None = Query(default=None),
    document_id: uuid.UUID | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.read")),
    service: DocumentBIMLinkService = Depends(_get_bim_link_service),
) -> DocumentBIMLinkListResponse:
    """List Document ↔ BIM element links.

    Exactly one of ``element_id`` or ``document_id`` must be supplied:
    - ``element_id=X`` - every document linked to BIM element X
    - ``document_id=Y`` - every BIM element linked from document Y

    R7 audit: the caller must have access to the project the lookup
    keys into. Without this guard, ``documents.read`` was enough to
    enumerate every BIM ↔ document link in the database - a sizable
    cross-tenant data leak. 404 keeps the surface symmetric with the
    rest of the documents IDOR contract.
    """
    if (element_id is None) == (document_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Exactly one of 'element_id' or 'document_id' must be provided",
        )

    # Resolve the project the query keys into and 404 on missing /
    # cross-tenant. Inline imports keep the module decoupled at import
    # time while letting the helper participate in the active session.
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.documents.models import Document as _DocModel

    if element_id is not None:
        element = await session.get(BIMElement, element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )
        model = await session.get(BIMModel, element.model_id)
        if model is None or model.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )
        await verify_project_access(model.project_id, user_id, session)
        links = await service.list_links_for_element(element_id)
    else:
        assert document_id is not None  # narrowing for type-checkers
        doc = await session.get(_DocModel, document_id)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        await verify_project_access(doc.project_id, user_id, session)
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
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.create")),
    service: DocumentBIMLinkService = Depends(_get_bim_link_service),
) -> DocumentBIMLinkResponse:
    """Create a new Document ↔ BIM element link.

    R7 audit: enforce project access on BOTH ends of the link before
    creating it. A caller with only ``documents.create`` previously
    could splice arbitrary BIM elements to arbitrary documents (no
    project check) - a clean cross-tenant linkage attack used to
    surface "phantom" drawings in another tenant's viewer.
    """
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.documents.models import Document as _DocModel

    doc = await session.get(_DocModel, payload.document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    await verify_project_access(doc.project_id, user_id, session)

    element = await session.get(BIMElement, payload.bim_element_id)
    if element is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BIM element not found",
        )
    model = await session.get(BIMModel, element.model_id)
    if model is None or model.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BIM element not found",
        )
    await verify_project_access(model.project_id, user_id, session)

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
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: DocumentBIMLinkService = Depends(_get_bim_link_service),
) -> None:
    """Delete a Document ↔ BIM element link.

    R7 audit: the caller must have access to the parent document's
    project before the link is removed. Otherwise the ``documents.delete``
    grant on tenant A let you wipe links inside tenant B.
    """
    from app.modules.documents.models import Document as _DocModel
    from app.modules.documents.models import DocumentBIMLink as _LinkModel

    link = await session.get(_LinkModel, link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DocumentBIMLink not found",
        )
    doc = await session.get(_DocModel, link.document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DocumentBIMLink not found",
        )
    await verify_project_access(doc.project_id, user_id, session)
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
    owned_projects, _ = await proj_repo.list_for_user(owner_id=user_id, offset=0, limit=10000, exclude_archived=False)
    owned_project_ids = {str(p.id) for p in owned_projects}

    rows = (
        await session.execute(_select(Document.id, Document.project_id, Document.name).where(Document.id.in_(body.ids)))
    ).all()
    allowed = [r[0] for r in rows if str(r[1]) in owned_project_ids]
    name_by_id = {r[0]: r[2] for r in rows if str(r[1]) in owned_project_ids}

    # Audit log BEFORE the bulk delete so the rows still reference a
    # live document_id. The FK cascade wipes them along with the parent,
    # so retention is best-effort; the event-bus publish carries the
    # same payload for external audit collectors.
    from app.modules.documents.activity_service import record_activity

    for doc_id in allowed:
        await record_activity(
            session,
            doc_id,
            str(user_id) if user_id else None,
            "deleted",
            {"name": name_by_id.get(doc_id, ""), "batch": True},
        )

    deleted = await bulk_delete(session, Document, allowed)
    logger.info(
        "Bulk delete documents: requested=%d deleted=%d user=%s",
        len(body.ids),
        deleted,
        user_id,
    )
    return {"requested": len(body.ids), "deleted": deleted}


# ══════════════════════════════════════════════════════════════════════════
# Public share-link endpoints
# NOTE: These MUST come BEFORE /{document_id} parametric routes to avoid
#       FastAPI matching "share-links" as a document_id (route shadowing).
#       Endpoints are intentionally public - they DO NOT require auth.
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/share-links/{token}/",
    response_model=ShareLinkPublicInfo,
)
async def get_share_link_info(
    token: str,
    session: SessionDep,
) -> ShareLinkPublicInfo:
    """Public probe - what the recipient sees BEFORE entering a password.

    Returns the filename so the share page can display a meaningful
    title, plus two flags so the frontend knows whether to prompt for a
    password or render an "expired" notice. Revoked links 404 so a
    third party can't tell whether a token is wrong, revoked, or expired.
    """
    from app.modules.documents.share_service import (
        _is_expired,
        get_share_link_public,
    )

    link, doc = await get_share_link_public(session, token)
    return ShareLinkPublicInfo(
        filename=doc.name,
        requires_password=bool(link.password_hash),
        expired=_is_expired(link),
    )


@router.post(
    "/share-links/{token}/access/",
    response_model=ShareLinkAccessResponse,
)
async def access_share_link_endpoint(
    token: str,
    body: ShareLinkAccessRequest,
    session: SessionDep,
) -> ShareLinkAccessResponse:
    """Public unlock - verify password, bump count, return download URL.

    Returns 401 when a password is required and missing/wrong;
    404 when the link is unknown, revoked, or expired.
    """
    from app.modules.documents.share_service import access_share_link

    link, doc = await access_share_link(
        session,
        token=token,
        password=body.password,
    )
    return ShareLinkAccessResponse(
        download_url=f"/api/v1/documents/share-links/{link.token}/file/",
        filename=doc.name,
    )


@router.get(
    "/share-links/{token}/file/",
)
async def serve_share_link_file(
    token: str,
    session: SessionDep,
    password: str | None = Query(default=None),
) -> FileResponse:
    """Stream the actual file bytes for a share link.

    This is the URL we return from :func:`access_share_link_endpoint`.
    Because share-link recipients are unauthenticated, we re-verify
    the token + password here on every download rather than trusting
    a short-lived signed URL.

    Security: re-uses the same containment / symlink rules as the
    authenticated ``/{document_id}/download/`` route.
    """
    from app.modules.documents.share_service import access_share_link

    link, doc = await access_share_link(session, token=token, password=password)

    upload_base = Path(UPLOAD_BASE).resolve()
    raw = Path(doc.file_path) if doc.file_path else None
    if raw is None:
        # Share links cannot be issued for documents without a stored
        # path - fall through to 404 rather than re-materialise demo
        # placeholders (which is auth-side behaviour).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )
    file_path = (raw if raw.is_absolute() else upload_base / raw).resolve()

    try:
        file_path.relative_to(upload_base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
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


def _link_to_response(link: object, public_url: str) -> ShareLinkResponse:
    """Build a ShareLinkResponse from a DocumentShareLink ORM row."""
    return ShareLinkResponse(
        id=link.id,  # type: ignore[attr-defined]
        token=link.token,  # type: ignore[attr-defined]
        url=public_url,
        document_id=link.document_id,  # type: ignore[attr-defined]
        requires_password=bool(link.password_hash),  # type: ignore[attr-defined]
        expires_at=link.expires_at,  # type: ignore[attr-defined]
        created_at=link.created_at,  # type: ignore[attr-defined]
        download_count=link.download_count or 0,  # type: ignore[attr-defined]
        revoked=link.revoked,  # type: ignore[attr-defined]
    )


# ══════════════════════════════════════════════════════════════════════════
# Document CRUD by ID (parametric routes - MUST be after /photos/* and /sheets/* routes)
# ══════════════════════════════════════════════════════════════════════════


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Get a single document, honoring folder permissions.

    Non-owner project members are 404'd when the document lives in a
    restricted folder they have no grant on. The 404 (not 403) keeps
    enumeration symmetric with ``verify_project_access``.
    """
    doc = await service.get_document(document_id)
    await _verify_project_membership_or_404(doc.project_id, user_id, session)

    from app.modules.documents.folder_permissions_service import (
        folder_access_for,
        kind_and_path_for_document,
        require_read,
    )

    kind, path = kind_and_path_for_document(doc.category)
    role = await folder_access_for(
        session,
        project_id=doc.project_id,
        user_id=uuid.UUID(str(user_id)),
        scope_kind=kind,
        scope_path=path,
    )
    require_read(role)
    return _doc_to_response(doc)


# ── Download ─────────────────────────────────────────────────────────────────


@router.get(
    "/{document_id}/download/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def download_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DocumentService = Depends(_get_service),
) -> FileResponse:
    """Download a document file.

    Security: uses ``Path.resolve().relative_to()`` for containment check so
    case-insensitive filesystems and symlinks cannot escape ``UPLOAD_BASE``.
    """
    doc = await service.get_document(document_id)
    await verify_project_access(doc.project_id, user_id, session)
    upload_base = Path(UPLOAD_BASE).resolve()
    meta = getattr(doc, "metadata_", None) or {}
    is_demo = bool(meta.get("is_demo"))
    # A document is "placeholder-eligible" when its real blob may legitimately
    # be absent on this box: curated demo rows, and /files mirror documents
    # that point back at another module's upload (dwg-takeoff, takeoff) whose
    # blob can be pruned independently. For those we materialize a typed stub
    # on demand rather than 404, so every /files row downloads something valid.
    is_mirror = bool(meta.get("source_module"))
    placeholder_eligible = is_demo or is_mirror

    # file_path stored in DB may be relative (demo seed records) or absolute
    # (real uploads). Normalize relatives against UPLOAD_BASE before resolving
    # so they don't escape the base via CWD.
    raw = Path(doc.file_path) if doc.file_path else None
    if raw is None:
        file_path = (upload_base / "demo" / f"{doc.id}{_placeholder_suffix(doc)}").resolve()
    else:
        file_path = (raw if raw.is_absolute() else upload_base / raw).resolve()

    # Security: path must resolve inside a directory the platform owns. The
    # blob may legitimately live under a sibling root (a /files mirror document
    # points at the dwg-takeoff or takeoff upload dir, not UPLOAD_BASE), so we
    # accept UPLOAD_BASE plus the platform-wide safe data roots. ``relative_to``
    # (not ``str.startswith``) defeats Windows case-fold and symlink escapes.
    contained = is_within_safe_root(file_path, extra_roots=[upload_base])

    if not contained:
        # The stored absolute path resolves outside every directory the
        # platform writes to (e.g. a demo seeded with another machine's paths,
        # or an upload dir moved between releases). The doc IS accessible to
        # this user (project_access already verified); only the stored path is
        # stale. For placeholder-eligible docs we re-anchor to a deterministic
        # safe location and materialize a stub there. For real uploads we
        # degrade to 404 ("file is missing"), the truthful error.
        if placeholder_eligible:
            file_path = (upload_base / "demo" / f"{doc.id}{_placeholder_suffix(doc)}").resolve()
            logger.info(
                "Re-anchored demo/mirror doc %s to %s (stored path outside safe roots)",
                doc.id,
                file_path,
            )
        else:
            logger.warning(
                "Document %s file_path %s resolves outside the platform data roots",
                doc.id,
                doc.file_path,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found on disk",
            )

    if file_path.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Symlinks not permitted",
        )

    if not file_path.exists() or not file_path.is_file():
        # Demo/mirror records may reference a blob that was never shipped in
        # the wheel or has been pruned. Materialize a minimal, type-correct
        # placeholder on first download so /files deeplinks land on a real
        # file (PDF for PDFs, a tiny valid DWG/IFC stub for CAD, a text note
        # otherwise) instead of a raw 404.
        if placeholder_eligible:
            try:
                _materialize_demo_placeholder(file_path, doc.name, meta.get("demo_id"))
            except Exception:  # pragma: no cover - degrade to 404 on unexpected failure
                logger.warning("Failed to materialize demo placeholder for %s", doc.id, exc_info=True)
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


def _placeholder_suffix(doc: object) -> str:
    """Return the file extension to give a re-anchored placeholder for ``doc``.

    Prefer the document's own name extension (so a .dwg row stays .dwg, a .ifc
    row stays .ifc); fall back to .pdf for PDFs or anything without a usable
    extension. This keeps the materialized stub type-correct for the viewer
    the /files row links to.
    """
    name = getattr(doc, "name", "") or ""
    suffix = Path(name).suffix.lower()
    if suffix and len(suffix) <= 6:
        return suffix
    mime = (getattr(doc, "mime_type", "") or "").lower()
    if "pdf" in mime:
        return ".pdf"
    return ".pdf"


def _materialize_demo_placeholder(target: Path, name: str, demo_id: str | None) -> None:
    """Write a minimal, type-correct placeholder file to ``target``.

    Why: demo and showcase projects ship without bundled binaries, so seeded
    ``Document`` rows (and /files mirror rows pointing at another module's
    pruned upload) reference paths that may not exist on disk. Generating a
    placeholder of the right type on first download keeps ``/files`` deeplinks
    honest (PDF takeoff opens, the CAD/IFC viewer gets a real file) without
    bloating the wheel. Dispatch by extension lives in
    :mod:`app.core.demo_placeholders`.
    """
    note = f"Project: {demo_id}" if demo_id else None
    materialize_placeholder(target, name, note)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: uuid.UUID,
    data: DocumentUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("documents.update")),
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Update document metadata.

    The caller's app role (from the JWT payload) is passed through so the
    service can enforce the ISO 19650 CDE role gates on a state transition
    (Gate A / B / C). A non-state PATCH (rename, retag, …) is unaffected.
    """
    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    doc = await service.update_document(
        document_id,
        data,
        user_id=str(user_id) if user_id else None,
        user_role=payload.get("role"),
    )
    return _doc_to_response(doc)


# ── Revisions (Epic C - Document Versioning Unification) ────────────────


@router.post("/{document_id}/revisions/", response_model=DocumentResponse, status_code=201)
async def upload_document_revision(
    document_id: uuid.UUID,
    session: SessionDep,
    file: UploadFile = File(...),
    notes: str | None = Form(default=None),
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("documents.update")),
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    """Upload a new revision against an existing document.

    Epic C unification:
        * The chain key stays anchored to the existing document's name
          so version_number monotonically increments.
        * Stored bytes are written to disk; the Document row's
          ``file_path`` / ``file_size`` / ``mime_type`` are bumped to
          point at the new revision.
        * A new ``FileVersion`` row is inserted with ``is_current=True``
          and the prior current is superseded inside one transaction.

    Returns the (now updated) Document. The chain is queryable at
    ``GET /api/v1/file-versions/?file_id={id}&kind=document``.
    """
    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)

    allowed, _ = upload_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads. Please wait a moment and try again.",
            headers={"Retry-After": "60"},
        )

    try:
        doc = await service.upload_document_revision(document_id, file, str(user_id) if user_id else "", notes=notes)
        return _doc_to_response(doc)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to upload document revision")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload document revision",
        )


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("documents.delete")),
    service: DocumentService = Depends(_get_service),
) -> None:
    """Delete a document, honoring folder permissions.

    Non-owner members are 404'd when:
        * the folder is restricted and they have no grant, OR
        * they only have a ``viewer`` grant (no write capability).

    Editors can only delete their OWN uploads - a defence in depth so
    a single member can't accidentally nuke another member's work
    just because they share an "editor" grant.
    """
    existing = await service.get_document(document_id)
    await _verify_project_membership_or_404(existing.project_id, user_id, session)

    from app.modules.documents.folder_permissions_service import (
        can_write,
        folder_access_for,
        kind_and_path_for_document,
        require_read,
    )

    kind, path = kind_and_path_for_document(existing.category)
    role = await folder_access_for(
        session,
        project_id=existing.project_id,
        user_id=uuid.UUID(str(user_id)),
        scope_kind=kind,
        scope_path=path,
    )
    require_read(role)

    # Owner of the project bypasses write checks (folder_access_for
    # returns "owner" for them).
    if role != "owner" and not can_write(role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    # Editors can only delete their own uploads. Folder "owner" role
    # and project owner role bypass this rule.
    if role == "editor":
        uploaded_by = str(getattr(existing, "uploaded_by", "") or "")
        if uploaded_by and uploaded_by != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )

    await service.delete_document(document_id, user_id=str(user_id) if user_id else None)


# ── Activity log ─────────────────────────────────────────────────────────────


@router.get(
    "/{document_id}/activity/",
    response_model=list[DocumentActivityResponse],
)
async def list_document_activity(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    service: DocumentService = Depends(_get_service),
) -> list[DocumentActivityResponse]:
    """Return the newest-first audit timeline for a document.

    Used by the file-preview pane to render "X uploaded this on T;
    renamed by Y on T+1; …". Returns 404 when the document is missing
    or the caller has no access to its project (mirrors the cross-module
    secret-by-id convention from :func:`verify_project_access`).
    """
    from app.modules.documents.activity_service import list_activity

    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    rows = await list_activity(session, document_id, limit=limit)
    return [DocumentActivityResponse.model_validate(r) for r in rows]


# ── Share-link management (owner-only) ──────────────────────────────────


@router.post(
    "/{document_id}/share-links/",
    response_model=ShareLinkResponse,
    status_code=201,
)
async def create_document_share_link(
    document_id: uuid.UUID,
    body: ShareLinkCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("documents.update")),
    service: DocumentService = Depends(_get_service),
) -> ShareLinkResponse:
    """Mint a password-protected share link for a document.

    Owner-only: enforced via :func:`verify_project_access` against the
    document's parent project. Returns the new token + public URL.
    """
    from app.modules.documents.share_service import (
        _build_public_url,
        create_share_link,
    )

    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)

    try:
        created_by_uuid = uuid.UUID(str(user_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user id in token",
        ) from exc

    link = await create_share_link(
        session,
        document_id=document_id,
        created_by=created_by_uuid,
        password=body.password,
        expires_in_days=body.expires_in_days,
    )
    return _link_to_response(link, _build_public_url(link.token))


@router.get(
    "/{document_id}/share-links/",
    response_model=list[ShareLinkListItem],
)
async def list_document_share_links(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("documents.read")),
    service: DocumentService = Depends(_get_service),
) -> list[ShareLinkListItem]:
    """List active (non-revoked) share links for a document.

    Owner-only. Returned newest-first. Revoked links are filtered server-
    side so the UI list stays focused on the actionable surface.
    """
    from app.modules.documents.share_service import (
        _build_public_url,
        list_share_links_for_document,
    )

    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    links = await list_share_links_for_document(session, document_id)
    return [
        ShareLinkListItem(
            id=link.id,
            token=link.token,
            url=_build_public_url(link.token),
            requires_password=bool(link.password_hash),
            expires_at=link.expires_at,
            created_at=link.created_at,
            download_count=link.download_count or 0,
            revoked=link.revoked,
        )
        for link in links
    ]


@router.delete(
    "/{document_id}/share-links/{link_id}/",
    status_code=204,
)
async def revoke_document_share_link(
    document_id: uuid.UUID,
    link_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("documents.update")),
    service: DocumentService = Depends(_get_service),
) -> None:
    """Soft-revoke a share link by id.

    Owner-only. After revocation the token returns 404 (same as unknown
    / expired) so attackers cannot distinguish the three states.
    """
    from app.modules.documents.share_service import revoke_share_link

    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    await revoke_share_link(session, link_id=link_id, document_id=document_id)


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` and ``/vector/reindex/`` are wired via the shared
# factory in ``app.core.vector_routes`` (see bottom of file for the
# ``include_router`` call).  The ``/{id}/similar/`` endpoint remains
# module-specific and is defined below.


@router.get(
    "/{document_id}/similar/",
    dependencies=[Depends(RequirePermission("documents.read"))],
)
async def documents_similar(
    document_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=False),
) -> dict:
    """Return documents semantically similar to the given one.

    By default the search is **scoped to the same project**.  Pass
    ``cross_project=true`` to expand the search across all projects the
    caller has access to (useful for finding how similar drawings/specs
    were handled on past projects).

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("errors.document_not_found", locale=get_locale())
        )

    # Cross-tenant IDOR gate - mirror ``get_document`` so a caller with no
    # access to the document's project gets a 404 (not a 200 leaking a
    # populated vector index). Was previously missing here while every
    # sibling /{id}/* endpoint enforces it.
    if row.project_id is not None:
        await _verify_project_membership_or_404(row.project_id, _user_id, session)

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


# ── Mount vector status + reindex via the shared factory ────────────────
from app.core.vector_index import COLLECTION_DOCUMENTS  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.documents.models import Document as _DocumentModel  # noqa: E402
from app.modules.documents.vector_adapter import (  # noqa: E402
    document_vector_adapter as _document_vector_adapter,
)

router.include_router(
    create_vector_routes(
        collection=COLLECTION_DOCUMENTS,
        adapter=_document_vector_adapter,
        model=_DocumentModel,
        read_permission="documents.read",
        write_permission="documents.update",
        project_id_attr="project_id",
    )
)
