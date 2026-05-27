"""‌⁠‍Punch List API routes.

Endpoints:
    POST   /items                        — Create punch item
    GET    /items?project_id=X           — List with filters
    GET    /items/{id}                   — Get single
    PATCH  /items/{id}                   — Update
    DELETE /items/{id}                   — Delete
    POST   /items/{id}/transition        — Status transition with validation
    GET    /summary?project_id=X         — Aggregated stats
    POST   /items/{id}/photos            — Upload photo
    DELETE /items/{id}/photos/{index}    — Remove photo
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.core.file_signature import (
    ALLOWED_PHOTO_TYPES,
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
    mime_for_signature,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.punchlist.schemas import (
    PinToSheetRequest,
    PunchBulkCloseRequest,
    PunchBulkCloseResponse,
    PunchItemCreate,
    PunchItemResponse,
    PunchItemUpdate,
    PunchListSummary,
    PunchStatusTransition,
)
from app.modules.punchlist.service import PunchListService

router = APIRouter()
logger = logging.getLogger(__name__)

# Directory for storing uploaded punch list photos
PHOTOS_DIR = Path("uploads/punchlist/photos")


def _get_service(session: SessionDep) -> PunchListService:
    return PunchListService(session)


def _item_to_response(item: object) -> PunchItemResponse:
    """‌⁠‍Build a PunchItemResponse from a PunchItem ORM object."""
    return PunchItemResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        document_id=item.document_id,  # type: ignore[attr-defined]
        page=item.page,  # type: ignore[attr-defined]
        location_x=item.location_x,  # type: ignore[attr-defined]
        location_y=item.location_y,  # type: ignore[attr-defined]
        priority=item.priority,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        assigned_to=item.assigned_to,  # type: ignore[attr-defined]
        due_date=item.due_date,  # type: ignore[attr-defined]
        category=item.category,  # type: ignore[attr-defined]
        trade=item.trade,  # type: ignore[attr-defined]
        photos=item.photos or [],  # type: ignore[attr-defined]
        geo_lat=getattr(item, "geo_lat", None),
        geo_lon=getattr(item, "geo_lon", None),
        rework_cost=getattr(item, "rework_cost", None),
        rework_cost_currency=getattr(item, "rework_cost_currency", None) or "USD",
        resolution_notes=item.resolution_notes,  # type: ignore[attr-defined]
        resolved_at=item.resolved_at,  # type: ignore[attr-defined]
        verified_at=item.verified_at,  # type: ignore[attr-defined]
        verified_by=item.verified_by,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        reopen_history=getattr(item, "reopen_history", None) or [],  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary/", response_model=PunchListSummary)
async def get_summary(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PunchListService = Depends(_get_service),
) -> PunchListSummary:
    """‌⁠‍Aggregated punch list stats for a project."""
    await verify_project_access(project_id, user_id, session)
    data = await service.get_summary(project_id)
    return PunchListSummary(**data)


# ── Create ───────────────────────────────────────────────────────────────────


@router.post("/items/", response_model=PunchItemResponse, status_code=201)
async def create_item(
    data: PunchItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("punchlist.create")),
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Create a new punch list item."""
    await verify_project_access(data.project_id, user_id, session)
    try:
        item = await service.create_item(data, user_id=user_id)
        return _item_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create punch item")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create punch item — operation aborted",
        )


# ── List ─────────────────────────────────────────────────────────────────────


@router.get("/items/", response_model=list[PunchItemResponse])
async def list_items(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    category: str | None = Query(default=None),
    trade: str | None = Query(default=None),
    service: PunchListService = Depends(_get_service),
) -> list[PunchItemResponse]:
    """List punch items for a project with optional filters."""
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_items(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        priority_filter=priority,
        assigned_to=assigned_to,
        category_filter=category,
        trade_filter=trade,
    )
    return [_item_to_response(i) for i in items]


# ── Root aliases ─────────────────────────────────────────────────────────────
#
# Sibling modules (changeorders, tasks, meetings, fieldreports, …) expose the
# canonical collection at ``/`` — punchlist historically only exposed it at
# ``/items/`` which trips both REST clients and the QA crawler. We keep the
# old paths working and add ``GET /`` + ``POST /`` aliases so the module
# follows the same shape as everything else.


@router.get("/", response_model=list[PunchItemResponse])
async def list_items_root_alias(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    category: str | None = Query(default=None),
    trade: str | None = Query(default=None),
    service: PunchListService = Depends(_get_service),
) -> list[PunchItemResponse]:
    """Alias for ``GET /items/`` — see that handler for full semantics."""
    return await list_items(
        session=session,
        project_id=project_id,
        user_id=user_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        priority=priority,
        assigned_to=assigned_to,
        category=category,
        trade=trade,
        service=service,
    )


@router.post("/", response_model=PunchItemResponse, status_code=201)
async def create_item_root_alias(
    data: PunchItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("punchlist.create")),
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Alias for ``POST /items/`` — see that handler for full semantics."""
    await verify_project_access(data.project_id, user_id, session)
    try:
        item = await service.create_item(data, user_id=user_id)
        return _item_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to create punch item")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create punch item — operation aborted",
        )


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/items/{item_id}", response_model=PunchItemResponse)
async def get_item(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Get a single punch item."""
    item = await service.get_item(item_id)
    await verify_project_access(item.project_id, str(user_id), session)
    return _item_to_response(item)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/items/{item_id}", response_model=PunchItemResponse)
async def update_item(
    item_id: uuid.UUID,
    data: PunchItemUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("punchlist.update")),
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Update a punch item."""
    existing = await service.get_item(item_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    item = await service.update_item(item_id, data)
    return _item_to_response(item)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("punchlist.delete")),
    service: PunchListService = Depends(_get_service),
) -> None:
    """Delete a punch item."""
    existing = await service.get_item(item_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_item(item_id)


# ── Status transition ────────────────────────────────────────────────────────


@router.post("/items/{item_id}/transition/", response_model=PunchItemResponse)
async def transition_status(
    item_id: uuid.UUID,
    data: PunchStatusTransition,
    user_id: CurrentUserId,
    session: SessionDep,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("punchlist.update")),
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Transition a punch item status with validation.

    Special rules:
    - resolved -> verified requires punchlist.verify permission and a different user
    - verified -> closed requires punchlist.verify permission
    """
    existing = await service.get_item(item_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    # For verify and close transitions, require the punchlist.verify permission
    # in addition to punchlist.update which is already checked by the decorator.
    if data.new_status in ("verified", "closed"):
        await RequirePermission("punchlist.verify")(payload)

    item = await service.transition_status(item_id, data, user_id)
    return _item_to_response(item)


# ── Pin to sheet ─────────────────────────────────────────────────────────────


@router.post("/items/{item_id}/pin-to-sheet/", response_model=PunchItemResponse)
async def pin_to_sheet(
    item_id: uuid.UUID,
    data: PinToSheetRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("punchlist.update")),
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Pin a punch item to a specific location on a document sheet.

    Updates the punch item's document_id, page, location_x, and location_y
    fields so the item is visually anchored on a drawing sheet.
    """
    existing = await service.get_item(item_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    if data.sheet_id is None and data.document_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either sheet_id or document_id must be provided",
        )

    item = await service.pin_to_sheet(
        item_id,
        sheet_id=data.sheet_id,
        document_id=data.document_id,
        page=data.page,
        location_x=data.location_x,
        location_y=data.location_y,
    )
    return _item_to_response(item)


# ── Photos ───────────────────────────────────────────────────────────────────


@router.post("/items/{item_id}/photos/", response_model=PunchItemResponse)
async def upload_photo(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("punchlist.update")),
    service: PunchListService = Depends(_get_service),
) -> PunchItemResponse:
    """Upload a photo for a punch item.

    Content-type headers are attacker-controlled, so we validate the raw
    magic bytes against :data:`ALLOWED_PHOTO_TYPES` (jpeg, png, gif, webp,
    heic, heif, tiff). SVG and any other format are rejected with 415.
    """
    try:
        content = await file.read()
    except Exception:
        logger.exception("Unable to read photo upload for punch item %s", item_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded photo",
        )

    # Magic-byte gate: read enough bytes to identify the signature and
    # reject anything outside the photo allow-list. Storing an attacker-
    # controlled MIME on the cross-linked Document would let later
    # consumers serve it as HTML/SVG/etc., so we derive the stored MIME
    # from the detected signature instead of trusting ``file.content_type``.
    try:
        detected = require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_PHOTO_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )
    safe_mime = mime_for_signature(detected)

    # Now that we've accepted the body, prepare the destination.
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "photo.jpg").suffix or ".jpg"
    filename = f"{item_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = PHOTOS_DIR / filename

    try:
        filepath.write_bytes(content)
    except Exception:
        logger.exception("Unable to save photo for punch item %s", item_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save photo — storage error",
        )

    # Store relative path in the database
    photo_path = f"punchlist/photos/{filename}"
    item = await service.add_photo(item_id, photo_path)

    # Cross-link: create Document record so punch photos appear in
    # Documents hub.  Uses the ORM model directly (NOT raw SQL) so
    # timestamps + defaults are filled by SQLAlchemy / Base mixin and
    # the row stays in sync with the rest of the documents module if
    # its schema evolves.  Best-effort: a failure here MUST NOT break
    # the upload — the photo itself is already persisted.
    try:
        from app.modules.documents.models import Document

        punch_project_id = item.project_id  # type: ignore[attr-defined]
        doc = Document(
            project_id=punch_project_id,
            name=filename,
            description=f"Punch list photo for item {item_id}",
            category="photo",
            file_size=len(content),
            mime_type=safe_mime,
            file_path=str(filepath),
            version=1,
            uploaded_by=user_id or "",
            tags=["punchlist", "photo"],
        )
        service.session.add(doc)
        await service.session.flush()
        logger.info("Cross-linked punch photo -> document %s", doc.id)
    except Exception:
        logger.exception("Failed to cross-link punch photo to Documents hub")

    return _item_to_response(item)


@router.delete("/items/{item_id}/photos/{index}", status_code=204)
async def remove_photo(
    item_id: uuid.UUID,
    index: int,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("punchlist.update")),
    service: PunchListService = Depends(_get_service),
) -> None:
    """Remove a photo by index from a punch item."""
    existing = await service.get_item(item_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.remove_photo(item_id, index)


# ── Bulk close ───────────────────────────────────────────────────────────────


@router.post("/bulk-close/", response_model=PunchBulkCloseResponse)
async def bulk_close(
    data: PunchBulkCloseRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("punchlist.update")),
    service: PunchListService = Depends(_get_service),
) -> PunchBulkCloseResponse:
    """‌⁠‍Close many punch items at once.

    Per-id outcomes are summarised: ``closed`` (now closed), ``skipped``
    (already closed) and ``errors`` (not found, project mismatch, critical
    items still blocked by open peers, etc.). Successful closes emit the
    standard ``punchlist.item.status_changed`` event.
    """
    await verify_project_access(data.project_id, user_id, session)
    summary = await service.bulk_close(
        data.project_id,
        list(data.ids),
        user_id=str(user_id) if user_id else "",
        comment=data.comment,
    )
    return PunchBulkCloseResponse(**summary)


# ── PDF Export ───────────────────────────────────────────────────────────────


@router.get("/export/pdf/")
async def export_pdf(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PunchListService = Depends(_get_service),
) -> Response:
    """Export punch list as a PDF report."""
    await verify_project_access(project_id, user_id, session)
    pdf_bytes = await service.export_pdf(project_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=punchlist_{project_id}.pdf"},
    )


@router.get("/export/excel/")
async def export_excel(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: PunchListService = Depends(_get_service),
) -> Response:
    """Export punch list as an Excel spreadsheet."""
    await verify_project_access(project_id, user_id, session)
    excel_bytes = await service.export_excel(project_id)
    # Determine media type: openpyxl produces xlsx, fallback produces CSV
    is_xlsx = excel_bytes[:4] == b"PK\x03\x04"
    if is_xlsx:
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    else:
        media_type = "text/csv"
        ext = "csv"
    return Response(
        content=excel_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=punchlist_{project_id}.{ext}"},
    )
