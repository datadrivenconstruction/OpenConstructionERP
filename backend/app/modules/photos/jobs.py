# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photo background jobs, one photo or one project per job.

* ``photos.thumbnail``  - thumbnail of one photo; the pixel cap runs before any decode.
* ``photos.ai_analyze`` - vision proposals for one photo, stored as pending.
* ``photos.export_zip`` - originals, JSON sidecars and a manifest, written file by file.
* ``photos.backfill``   - index the photos every module of a project already holds.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from app.core.job_runner import register_handler, update_progress
from app.database import async_session_factory
from app.modules.photos.service import (
    JOB_AI,
    JOB_BACKFILL,
    JOB_EXPORT,
    JOB_THUMBNAIL,
    PhotosService,
    resolve_photo_file,
)

if TYPE_CHECKING:
    from app.core.job_run import JobRun

logger = logging.getLogger(__name__)


def _coerce_uuid(value: object) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def export_key(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"photos/exports/{project_id}/{job_id}.zip"


async def make_thumbnail(session: Any, photo_id: uuid.UUID) -> str:
    """Build the thumbnail of one photo and record the outcome on the row. Returns the new status."""
    from app.modules.documents.service import (
        PHOTO_THUMB_BASE,
        ensure_photo_within_pixel_cap,
        generate_photo_thumbnail,
    )

    service = PhotosService(session)
    photo = await service.repo.get_photo(photo_id)
    if photo is None:
        return "missing"
    path = resolve_photo_file(photo)
    if path is None:
        photo.thumb_status = "skipped" if (photo.file_path or "").startswith(("http", "/api/")) else "failed"
        await session.flush()
        return photo.thumb_status
    content = await asyncio.to_thread(path.read_bytes)
    try:
        await asyncio.to_thread(ensure_photo_within_pixel_cap, content)
    except HTTPException:
        photo.thumb_status = "failed"
        await session.flush()
        return "failed"
    dest = Path(PHOTO_THUMB_BASE) / str(photo.project_id) / f"{photo.id.hex[:12]}_thumb.jpg"
    ok = await asyncio.to_thread(generate_photo_thumbnail, content, dest)
    if ok:
        photo.thumbnail_path = str(dest)
        if photo.width is None:
            from app.modules.photos.service import image_size

            photo.width, photo.height = await asyncio.to_thread(image_size, content)
        if not photo.sha256:
            from app.core.photo_evidence import sha256_hex

            photo.sha256 = sha256_hex(content)
    photo.thumb_status = "ready" if ok else "failed"
    await session.flush()
    return photo.thumb_status


async def thumbnail_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    photo_id = _coerce_uuid(payload.get("photo_id"))
    if photo_id is None:
        return {"error": "missing photo_id"}
    async with async_session_factory() as session:
        result = await make_thumbnail(session, photo_id)
        await session.commit()
    return {"photo_id": str(photo_id), "thumb_status": result}


async def ai_analyze_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    photo_id = _coerce_uuid(payload.get("photo_id"))
    user_id = str(payload.get("user_id") or "")
    kinds = [str(k) for k in payload.get("kinds") or []]
    if photo_id is None or not user_id:
        return {"error": "missing photo_id or user_id"}
    await update_progress(job_run.id, percent=20, message="Reading photo")
    async with async_session_factory() as session:
        service = PhotosService(session)
        photo = await service.repo.get_photo(photo_id)
        if photo is None:
            return {"error": "photo not found"}
        try:
            stored = await service.analyze(photo, kinds, user_id)
        except ValueError as exc:
            return {"error": str(exc)}
        await session.commit()
    await update_progress(job_run.id, percent=100, message="Suggestions ready")
    return {"photo_id": str(photo_id), "suggestions": len(stored)}


async def export_zip_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    from app.core.storage import get_storage_backend

    project_id = _coerce_uuid(payload.get("project_id"))
    if project_id is None:
        return {"error": "missing project_id"}
    ids = [u for u in (_coerce_uuid(x) for x in payload.get("photo_ids") or []) if u is not None] or None
    album_id = _coerce_uuid(payload.get("album_id"))
    await update_progress(job_run.id, percent=10, message="Collecting photos")
    async with async_session_factory() as session:
        service = PhotosService(session)
        photos = await service.export_photos(project_id, ids, album_id)
        with tempfile.TemporaryDirectory(prefix="oe-photos-export-") as tmp:
            dest = Path(tmp) / "photos.zip"
            summary = await service.build_export_zip(project_id, photos, dest)
            key = export_key(project_id, job_run.id)
            await update_progress(job_run.id, percent=90, message="Writing archive")
            await get_storage_backend().put_stream(key, dest)
    await update_progress(job_run.id, percent=100, message="Archive ready")
    return {"export_key": key, "project_id": str(project_id), **summary}


async def backfill_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = _coerce_uuid(payload.get("project_id"))
    if project_id is None:
        return {"error": "missing project_id"}
    await update_progress(job_run.id, percent=10, message="Indexing photos")
    async with async_session_factory() as session:
        counts = await PhotosService(session).backfill_project(project_id)
        await session.commit()
    await update_progress(job_run.id, percent=60, message="Building thumbnails")
    thumbs = await build_pending_thumbnails(project_id)
    await update_progress(job_run.id, percent=100, message="Backfill done")
    return {"project_id": str(project_id), "indexed": counts, "thumbnails": thumbs}


async def build_pending_thumbnails(project_id: uuid.UUID) -> int:
    """Thumbnails for every pending photo of a project, one at a time, committed one by one."""
    from sqlalchemy import select

    from app.modules.documents.models import ProjectPhoto

    async with async_session_factory() as session:
        stmt = select(ProjectPhoto.id).where(
            ProjectPhoto.project_id == project_id, ProjectPhoto.thumb_status == "pending"
        )
        ids = [r for (r,) in (await session.execute(stmt)).all()]
    done = 0
    for photo_id in ids:
        async with async_session_factory() as session:
            if await make_thumbnail(session, photo_id) == "ready":
                done += 1
            await session.commit()
    return done


def register_photos_job_handlers() -> None:
    register_handler(JOB_THUMBNAIL, thumbnail_handler)
    register_handler(JOB_AI, ai_analyze_handler)
    register_handler(JOB_EXPORT, export_zip_handler)
    register_handler(JOB_BACKFILL, backfill_handler)
