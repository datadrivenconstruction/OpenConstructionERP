# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos API, mounted under ``/api/v1/photos/``.

POST   /upload/?project_id=                multi-file upload (+ device JSON, optional target)
GET    /?project_id=&q&tag&album&from&to&source&target_kind&target_id&has_gps&cursor
GET    /timeline/?project_id=              photos grouped by capture day
GET    /map/?project_id=                   GeoJSON of the located photos
GET    /validation/?project_id=            rule set ``photos`` as a traffic light
GET    /by-target/?project_id&kind&id      photos linked to one record
GET|PATCH|DELETE /{id}/                    delete archives an indexed photo
GET    /{id}/file/ | /{id}/thumb/          the image, auth-checked
POST|DELETE /{id}/links/                   link to a BOQ position, activity, punch item, ...
GET|POST /{id}/pins/                       drawing pins (plan room)
POST   /{id}/ai/analyze/?kinds=            queue vision proposals
GET    /{id}/ai/                           proposals of one photo
POST   /ai/{sid}/accept/ | /ai/{sid}/reject/
albums: GET|POST /albums/, PATCH|DELETE /albums/{id}/, POST /albums/{id}/items/, POST /albums/{id}/items/remove/
POST   /compare/, GET /compare/?project_id=, GET /compare/{id}/
POST   /export/ -> job, GET /export/{job}/, GET /export/{job}/file/
POST   /backfill/?project_id=              admin: index every module's photos
"""

from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.i18n import get_locale, t
from app.core.photo_evidence import parse_device_capture
from app.core.rate_limiter import RateLimiter, upload_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.photos.logic import AI_KINDS, SOURCE_MODULES
from app.modules.photos.repository import PhotoFilters
from app.modules.photos.schemas import (
    AcceptIn,
    AlbumIn,
    AlbumItemsIn,
    AlbumListResponse,
    AlbumOut,
    AlbumPatch,
    CompareIn,
    CompareListResponse,
    CompareOut,
    ExportIn,
    ExportStatus,
    JobOut,
    LinkIn,
    PhotoLinkOut,
    PhotoListResponse,
    PhotoOut,
    PhotoPage,
    PhotoPatch,
    PinIn,
    PinListResponse,
    PinOut,
    SuggestionListResponse,
    SuggestionOut,
    TimelineListResponse,
    UploadResult,
)
from app.modules.photos.service import (
    JOB_AI,
    JOB_BACKFILL,
    JOB_EXPORT,
    PhotosService,
    resolve_photo_file,
    resolve_thumb_file,
)

router = APIRouter(tags=["photos"])
logger = logging.getLogger(__name__)

#: Vision calls cost money and time; ten per user per minute is plenty for review work.
ai_limiter = RateLimiter(max_requests=10, window_seconds=60)


def _svc(session: SessionDep) -> PhotosService:
    return PhotosService(session)


def _fail(code: int, key: str, **kwargs: Any) -> HTTPException:
    return HTTPException(status_code=code, detail=t(key, get_locale(), **kwargs))


async def _photo_for(photo_id: uuid.UUID, user_id: str, service: PhotosService) -> Any:
    photo = await service.get_photo(photo_id)
    await verify_project_access(photo.project_id, user_id, service.session)
    return photo


def _filters(
    q: str | None,
    tag: str | None,
    album: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    source: str | None,
    target_kind: str | None,
    target_id: str | None,
    has_gps: bool | None,
    include_archived: bool = False,
    category: str | None = None,
) -> PhotoFilters:
    if source is not None and source not in SOURCE_MODULES:
        raise _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.bad_source")
    return PhotoFilters(
        q=q or None,
        tag=tag or None,
        album_id=album,
        date_from=date_from,
        date_to=date_to,
        source=source,
        category=category or None,
        target_kind=target_kind or None,
        target_id=target_id or None,
        has_gps=has_gps,
        include_archived=include_archived,
    )


# ── Upload ──────────────────────────────────────────────────────────────


@router.post("/upload/", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_photos(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    files: list[UploadFile] = File(...),
    device: str | None = Form(default=None),
    category: str = Form(default="site"),
    caption: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    target_kind: str | None = Form(default=None),
    target_id: str | None = Form(default=None),
    _: None = Depends(RequirePermission("photos.upload")),
) -> dict[str, Any]:
    """Upload photos from the dropzone or the phone camera.

    ``device`` is the browser's capture JSON ``{lat, lon, accuracy_m, altitude_m,
    captured_at, heading_deg}``; it wins over EXIF because it carries a radius.
    """
    await verify_project_access(project_id, user_id, session)
    allowed, _retry = upload_limiter.is_allowed(str(user_id))
    if not allowed:
        raise _fail(status.HTTP_429_TOO_MANY_REQUESTS, "photos.errors.rate_limited")
    capture = None
    if device:
        try:
            raw = json.loads(device)
        except ValueError as exc:
            raise _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.bad_device") from exc
        if not isinstance(raw, dict):
            raise _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.bad_device")
        capture = parse_device_capture(
            lat=raw.get("lat"),
            lon=raw.get("lon"),
            accuracy_m=raw.get("accuracy_m"),
            altitude_m=raw.get("altitude_m"),
            captured_at=raw.get("captured_at"),
            heading_deg=raw.get("heading_deg"),
            pitch_deg=raw.get("pitch_deg"),
            roll_deg=raw.get("roll_deg"),
        )
    if bool(target_kind) != bool(target_id):
        raise _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.target_incomplete")
    parsed_tags = [s.strip() for s in (tags or "").split(",") if s.strip()]
    return await PhotosService(session).ingest_upload(
        project_id,
        files,
        user_id=user_id,
        device=capture,
        category=category,
        caption=caption,
        tags=parsed_tags,
        target_kind=target_kind,
        target_id=target_id,
    )


# ── Lists ───────────────────────────────────────────────────────────────


@router.get("/", response_model=PhotoPage)
async def list_photos(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    q: str | None = Query(None, max_length=200),
    tag: str | None = Query(None, max_length=100),
    album: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    source: str | None = Query(None),
    category: str | None = Query(None, max_length=100),
    target_kind: str | None = Query(None),
    target_id: str | None = Query(None),
    has_gps: bool | None = Query(None),
    include_archived: bool = Query(False),
    cursor: str | None = Query(None, max_length=400),
    limit: int = Query(60, ge=1, le=200),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    f = _filters(q, tag, album, date_from, date_to, source, target_kind, target_id, has_gps, include_archived, category)
    return await PhotosService(session).search(project_id, f, cursor=cursor, limit=limit)


@router.get("/timeline/", response_model=TimelineListResponse)
async def photo_timeline(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    q: str | None = Query(None, max_length=200),
    tag: str | None = Query(None, max_length=100),
    album: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    source: str | None = Query(None),
    category: str | None = Query(None, max_length=100),
    has_gps: bool | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    f = _filters(q, tag, album, date_from, date_to, source, None, None, has_gps, category=category)
    days, total = await PhotosService(session).timeline(project_id, f, offset=offset, limit=limit)
    return {"items": days, "total": total, "offset": offset, "limit": limit}


@router.get("/map/")
async def photo_map(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    q: str | None = Query(None, max_length=200),
    tag: str | None = Query(None, max_length=100),
    album: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    source: str | None = Query(None),
    category: str | None = Query(None, max_length=100),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    """GeoJSON FeatureCollection; ``anchor`` carries the site anchor when the project has one."""
    await verify_project_access(project_id, user_id, session)
    f = _filters(q, tag, album, date_from, date_to, source, None, None, True, category=category)
    return await PhotosService(session).geojson(project_id, f)


@router.get("/validation/")
async def photo_validation(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    photo_id: uuid.UUID | None = Query(None),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    service = PhotosService(session)
    photos = None
    if photo_id is not None:
        photo = await service.get_photo(photo_id)
        if photo.project_id != project_id:
            raise _fail(status.HTTP_404_NOT_FOUND, "photos.errors.not_found")
        photos = [photo]
    return await service.validate(project_id, photos, locale=get_locale())


@router.get("/by-target/", response_model=PhotoListResponse)
async def photos_by_target(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    kind: str = Query(...),
    id: str = Query(..., min_length=1, max_length=64),  # noqa: A002 - public query name
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    items, total = await PhotosService(session).by_target(project_id, kind, id, offset=offset, limit=limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


# ── Albums ──────────────────────────────────────────────────────────────


@router.get("/albums/", response_model=AlbumListResponse)
async def list_albums(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    items, total = await PhotosService(session).list_albums(project_id, offset=offset, limit=limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/albums/", response_model=AlbumOut, status_code=status.HTTP_201_CREATED)
async def create_album(
    body: AlbumIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.edit")),
) -> dict[str, Any]:
    await verify_project_access(body.project_id, user_id, session)
    return await PhotosService(session).create_album(
        body.project_id, body.name, body.description, body.sort_order, user_id
    )


async def _album_for(album_id: uuid.UUID, user_id: str, service: PhotosService) -> Any:
    album = await service.get_album(album_id)
    await verify_project_access(album.project_id, user_id, service.session)
    return album


@router.patch("/albums/{album_id}/", response_model=AlbumOut)
async def update_album(
    album_id: uuid.UUID,
    body: AlbumPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.edit")),
) -> dict[str, Any]:
    service = PhotosService(session)
    album = await _album_for(album_id, user_id, service)
    return await service.update_album(album, body.model_dump(exclude_unset=True))


@router.delete("/albums/{album_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_album(
    album_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.edit")),
) -> None:
    service = PhotosService(session)
    await service.delete_album(await _album_for(album_id, user_id, service))


@router.post("/albums/{album_id}/items/")
async def add_album_items(
    album_id: uuid.UUID,
    body: AlbumItemsIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.edit")),
) -> dict[str, Any]:
    service = PhotosService(session)
    album = await _album_for(album_id, user_id, service)
    return await service.add_album_items(album, list(dict.fromkeys(body.photo_ids)))


@router.post("/albums/{album_id}/items/remove/")
async def remove_album_items(
    album_id: uuid.UUID,
    body: AlbumItemsIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.edit")),
) -> dict[str, Any]:
    service = PhotosService(session)
    album = await _album_for(album_id, user_id, service)
    return await service.remove_album_items(album, list(body.photo_ids))


# ── Compare ─────────────────────────────────────────────────────────────


@router.post("/compare/", response_model=CompareOut, status_code=status.HTTP_201_CREATED)
async def create_compare(
    body: CompareIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.edit")),
) -> dict[str, Any]:
    await verify_project_access(body.project_id, user_id, session)
    service = PhotosService(session)
    row = await service.create_compare(body.project_id, body.before_photo_id, body.after_photo_id, body.title, user_id)
    return await service.compare_out(row)


@router.get("/compare/", response_model=CompareListResponse)
async def list_compares(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    service = PhotosService(session)
    rows, total = await service.repo.list_compares(project_id, offset=offset, limit=limit)
    items = [await service.compare_out(row) for row in rows]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/compare/{compare_id}/", response_model=CompareOut)
async def get_compare(
    compare_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    service = PhotosService(session)
    row = await service.repo.get_compare(compare_id)
    if row is None:
        raise _fail(status.HTTP_404_NOT_FOUND, "photos.errors.compare_not_found")
    await verify_project_access(row.project_id, user_id, session)
    return await service.compare_out(row)


# ── AI review ──────────────────────────────────────────────────────────


@router.post("/ai/{suggestion_id}/accept/", response_model=SuggestionOut)
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: AcceptIn | None = None,
    _: None = Depends(RequirePermission("photos.ai.review")),
) -> Any:
    service = PhotosService(session)
    suggestion, photo = await service.get_suggestion(suggestion_id)
    await verify_project_access(photo.project_id, user_id, session)
    return await service.accept_suggestion(suggestion, photo, user_id, body.payload if body else None)


@router.post("/ai/{suggestion_id}/reject/", response_model=SuggestionOut)
async def reject_suggestion(
    suggestion_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.ai.review")),
) -> Any:
    service = PhotosService(session)
    suggestion, photo = await service.get_suggestion(suggestion_id)
    await verify_project_access(photo.project_id, user_id, session)
    return await service.reject_suggestion(suggestion, user_id)


# ── Export / backfill jobs ─────────────────────────────────────────────


async def _submit(kind: str, payload: dict[str, Any], key: str | None = None) -> dict[str, Any]:
    from app.core.job_runner import submit_job

    run = await submit_job(kind, payload, idempotency_key=key)
    return {"job_id": run.id, "status": run.status, "kind": run.kind}


@router.post("/export/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def start_export(
    body: ExportIn,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.export")),
) -> dict[str, Any]:
    await verify_project_access(body.project_id, user_id, session)
    payload = {
        "project_id": str(body.project_id),
        "photo_ids": [str(p) for p in body.photo_ids] if body.photo_ids else None,
        "album_id": str(body.album_id) if body.album_id else None,
        "requested_by": user_id,
    }
    return await _submit(JOB_EXPORT, payload)


async def _export_run(job_id: uuid.UUID, user_id: str, session: Any) -> Any:
    from app.core.job_run import JobRun

    run = await session.get(JobRun, job_id)
    if run is None or run.kind != JOB_EXPORT:
        raise _fail(status.HTTP_404_NOT_FOUND, "photos.errors.export_not_found")
    project_id = uuid.UUID(str((run.payload_jsonb or {}).get("project_id")))
    await verify_project_access(project_id, user_id, session)
    return run


@router.get("/export/{job_id}/", response_model=ExportStatus)
async def export_status(
    job_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.export")),
) -> dict[str, Any]:
    run = await _export_run(job_id, user_id, session)
    result = run.result_jsonb or {}
    return {
        "job_id": run.id,
        "status": run.status,
        "progress_percent": run.progress_percent or 0,
        "photo_count": result.get("photo_count"),
        "size_bytes": result.get("size_bytes"),
        "ready": run.status == "success" and bool(result.get("export_key")),
    }


@router.get("/export/{job_id}/file/", response_model=None)
async def export_file(
    job_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("photos.export")),
) -> StreamingResponse:
    from app.core.storage import get_storage_backend

    run = await _export_run(job_id, user_id, session)
    key = (run.result_jsonb or {}).get("export_key")
    backend = get_storage_backend()
    if run.status != "success" or not key or not await backend.exists(key):
        raise _fail(status.HTTP_404_NOT_FOUND, "photos.errors.export_not_ready")
    return StreamingResponse(
        backend.open_stream(key),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="photos-{job_id.hex[:8]}.zip"'},
    )


@router.post("/backfill/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def start_backfill(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("photos.admin.backfill")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _submit(JOB_BACKFILL, {"project_id": str(project_id), "requested_by": user_id})


# ── One photo ───────────────────────────────────────────────────────────


@router.get("/{photo_id}/", response_model=PhotoOut)
async def get_photo(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    photo = await _photo_for(photo_id, user_id, service)
    return (await service.with_links([photo]))[0]


@router.patch("/{photo_id}/", response_model=PhotoOut)
async def patch_photo(
    photo_id: uuid.UUID,
    body: PhotoPatch,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.edit")),
) -> dict[str, Any]:
    photo = await _photo_for(photo_id, user_id, service)
    changes = body.model_dump(exclude_unset=True)
    if ("gps_lat" in changes) != ("gps_lon" in changes):
        raise _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.gps_pair")
    await service.patch(photo, changes, user_id)
    return (await service.with_links([photo]))[0]


@router.delete("/{photo_id}/")
async def delete_photo(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.delete")),
) -> dict[str, str]:
    """Delete a gallery photo; a diary, punch or report photo is archived, its file stays with its module."""
    photo = await _photo_for(photo_id, user_id, service)
    return {"result": await service.delete(photo, user_id)}


def _media_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "image/jpeg"


@router.get("/{photo_id}/file/", response_model=None)
async def photo_file(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.read")),
) -> FileResponse:
    photo = await _photo_for(photo_id, user_id, service)
    path = resolve_photo_file(photo)
    if path is None:
        raise _fail(status.HTTP_404_NOT_FOUND, "photos.errors.file_missing")
    return FileResponse(path=str(path), media_type=_media_type(path.name), headers={"Cache-Control": "private"})


@router.get("/{photo_id}/thumb/", response_model=None)
async def photo_thumb(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.read")),
) -> FileResponse:
    photo = await _photo_for(photo_id, user_id, service)
    thumb = resolve_thumb_file(photo)
    if thumb is not None:
        return FileResponse(
            path=str(thumb), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
        )
    path = resolve_photo_file(photo)
    if path is None:
        raise _fail(status.HTTP_404_NOT_FOUND, "photos.errors.file_missing")
    return FileResponse(path=str(path), media_type=_media_type(path.name), headers={"Cache-Control": "private"})


@router.post("/{photo_id}/links/", response_model=PhotoLinkOut, status_code=status.HTTP_201_CREATED)
async def add_link(
    photo_id: uuid.UUID,
    body: LinkIn,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.edit")),
) -> Any:
    photo = await _photo_for(photo_id, user_id, service)
    return await service.add_link(photo, body.target_kind, body.target_id, user_id)


@router.delete("/{photo_id}/links/", status_code=status.HTTP_204_NO_CONTENT)
async def remove_link(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    target_kind: str = Query(...),
    target_id: str = Query(...),
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.edit")),
) -> None:
    photo = await _photo_for(photo_id, user_id, service)
    await service.remove_link(photo, target_kind, target_id)


@router.get("/{photo_id}/pins/", response_model=PinListResponse)
async def list_pins(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    photo = await _photo_for(photo_id, user_id, service)
    pins, total = await service.pins_for(photo, offset=offset, limit=limit)
    items = [
        {
            "id": p.id,
            "document_id": p.document_id,
            "page": p.page,
            "x": p.x,
            "y": p.y,
            "note": p.note,
            "photo_ref": p.photo_ref,
        }
        for p in pins
    ]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/{photo_id}/pins/", response_model=PinOut, status_code=status.HTTP_201_CREATED)
async def create_pin(
    photo_id: uuid.UUID,
    body: PinIn,
    user_id: CurrentUserId,
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.edit")),
) -> Any:
    """Pin the photo on a drawing page; stored by the plan room as ``photo:<id>``."""
    photo = await _photo_for(photo_id, user_id, service)
    pin = await service.create_pin(photo, body.model_dump(), user_id)
    return {
        "id": pin.id,
        "document_id": pin.document_id,
        "page": pin.page,
        "x": pin.x,
        "y": pin.y,
        "note": pin.note,
        "photo_ref": pin.photo_ref,
    }


@router.post("/{photo_id}/ai/analyze/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def analyze_photo(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    kinds: str = Query("caption,tags"),
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.ai.run")),
) -> dict[str, Any]:
    """Queue vision proposals; nothing is applied until someone accepts them."""
    photo = await _photo_for(photo_id, user_id, service)
    wanted = [k for k in dict.fromkeys(s.strip() for s in kinds.split(",")) if k]
    if not wanted or any(k not in AI_KINDS for k in wanted):
        raise _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.bad_ai_kinds")
    allowed, _retry = ai_limiter.is_allowed(str(user_id))
    if not allowed:
        raise _fail(status.HTTP_429_TOO_MANY_REQUESTS, "photos.errors.rate_limited")
    return await _submit(JOB_AI, {"photo_id": str(photo.id), "user_id": user_id, "kinds": wanted})


@router.get("/{photo_id}/ai/", response_model=SuggestionListResponse)
async def list_suggestions(
    photo_id: uuid.UUID,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    service: PhotosService = Depends(_svc),
    _: None = Depends(RequirePermission("photos.read")),
) -> dict[str, Any]:
    photo = await _photo_for(photo_id, user_id, service)
    rows, total = await service.repo.suggestions_page(photo.id, offset=offset, limit=limit)
    return {"items": rows, "total": total, "offset": offset, "limit": limit}
