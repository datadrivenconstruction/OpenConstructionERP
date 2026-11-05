# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos service: one archive over the documents gallery and every module's photos.

The gallery's ``ProjectPhoto`` stays the only photo row. Uploads go through the
documents upload path (validation, size and pixel caps, GPS privacy, thumbnail);
photos other modules already hold get an index row that points at their file,
which never moves. AI proposals are stored as pending and change nothing until a
person accepts them; accepting a progress reading only links the photo and
emits an event, it never moves BOQ or schedule progress.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.core.i18n import t
from app.core.photo_evidence import (
    DeviceCapture,
    build_evidence_record,
    read_exif_evidence,
    sha256_hex,
)
from app.modules.documents.models import ProjectPhoto
from app.modules.photos.logic import (
    AI_KINDS,
    AI_MAX_SIDE_PX,
    SOURCE_LINK_KIND,
    ai_prompt,
    archive_name,
    as_utc,
    evidence_grade_for,
    external_photo_entries,
    group_timeline,
    parse_ai_suggestions,
    sidecar,
    to_geojson,
    valid_lat_lon,
)
from app.modules.photos.models import PhotoAISuggestion, PhotoAlbum, PhotoCompare, PhotoLink
from app.modules.photos.repository import PhotoFilters, PhotosRepository
from app.modules.photos.validators import evaluate

logger = logging.getLogger(__name__)

SOURCE = "oe_photos"
JOB_THUMBNAIL = "photos.thumbnail"
JOB_AI = "photos.ai_analyze"
JOB_EXPORT = "photos.export_zip"
JOB_BACKFILL = "photos.backfill"
BACKFILL_BATCH = 200
MAX_FILES_PER_UPLOAD = 50

#: A diary photo that points at a gallery photo is that gallery photo, not a second one.
_GALLERY_URL = re.compile(r"/api/v1/documents/photos/([0-9a-fA-F-]{36})/file/?$")

#: Model caller: ``(session, user_id, prompt, image_b64) -> (raw_text, provider, model)``.
AICaller = Callable[[AsyncSession, str, str, str], Awaitable[tuple[str, str | None, str | None]]]


def _err(code: int, key: str, **kwargs: Any) -> HTTPException:
    return HTTPException(status_code=code, detail=t(key, None, **kwargs))


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def image_size(content: bytes) -> tuple[int | None, int | None]:
    """Pixel size from the image header (no full decode)."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as img:
            return int(img.width), int(img.height)
    except Exception:  # noqa: BLE001 - not an image Pillow can read: size stays unknown
        return None, None


def downscale_for_ai(content: bytes, max_side: int = AI_MAX_SIDE_PX) -> bytes:
    """A JPEG no larger than ``max_side`` on its long edge, orientation applied."""
    from PIL import Image, ImageOps

    from app.modules.documents.service import MAX_PHOTO_PIXELS

    Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS
    with Image.open(io.BytesIO(content)) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def resolve_photo_file(photo: ProjectPhoto) -> Path | None:
    """The readable file behind a photo row, or ``None``.

    Gallery uploads store an absolute path that is re-homed across data dirs;
    indexed photos store the relative path their module wrote, resolved inside
    the upload roots only. URLs are never fetched.
    """
    raw = (photo.file_path or "").strip()
    if not raw or raw.startswith(("http://", "https://", "/api/")):
        return None
    if Path(raw).is_absolute():
        from app.modules.documents.router import _resolve_photo_blob
        from app.modules.documents.service import PHOTO_BASE

        return _resolve_photo_blob(raw, Path(PHOTO_BASE), ("photos",))
    from app.core.storage import find_existing_upload

    return find_existing_upload(raw)


def resolve_thumb_file(photo: ProjectPhoto) -> Path | None:
    if not photo.thumbnail_path:
        return None
    from app.modules.documents.router import _resolve_photo_blob
    from app.modules.documents.service import PHOTO_THUMB_BASE

    return _resolve_photo_blob(photo.thumbnail_path, Path(PHOTO_THUMB_BASE), ("photos", "thumbs"))


def is_remote(photo: ProjectPhoto) -> bool:
    return (photo.file_path or "").strip().startswith(("http://", "https://", "/api/"))


def photo_dict(photo: ProjectPhoto) -> dict[str, Any]:
    """Plain snapshot of a photo row for logic, rules and events."""
    return {
        "id": str(photo.id),
        "project_id": str(photo.project_id),
        "filename": photo.filename,
        "caption": photo.caption,
        "category": photo.category,
        "tags": list(photo.tags or []),
        "taken_at": as_utc(photo.taken_at),
        "created_at": as_utc(photo.created_at),
        "gps_lat": photo.gps_lat,
        "gps_lon": photo.gps_lon,
        "gps_accuracy_m": photo.gps_accuracy_m,
        "width": photo.width,
        "height": photo.height,
        "sha256": photo.sha256,
        "source_module": photo.source_module,
        "source_id": photo.source_id,
        "zone": photo.zone,
        "metadata": dict(photo.metadata_ or {}),
    }


def photo_out(photo: ProjectPhoto, links: list[PhotoLink] | None = None) -> dict[str, Any]:
    """API shape of a photo. Never exposes the server path."""
    meta = dict(photo.metadata_ or {})
    return {
        "id": photo.id,
        "project_id": photo.project_id,
        "filename": photo.filename,
        "caption": photo.caption,
        "category": photo.category,
        "tags": list(photo.tags or []),
        "taken_at": photo.taken_at,
        "created_at": photo.created_at,
        "created_by": photo.created_by or "",
        "gps_lat": photo.gps_lat,
        "gps_lon": photo.gps_lon,
        "gps_accuracy_m": photo.gps_accuracy_m,
        "width": photo.width,
        "height": photo.height,
        "sha256": photo.sha256,
        "source_module": photo.source_module or "documents",
        "source_id": photo.source_id,
        "category_suggestion": meta["category_suggestion"]
        if isinstance(meta.get("category_suggestion"), dict)
        else None,
        "thumb_status": photo.thumb_status or "pending",
        "location_id": photo.location_id,
        "zone": photo.zone,
        "is_archived": bool(photo.is_archived),
        "evidence_grade": evidence_grade_for(meta.get("evidence")),
        "taken_at_source": meta.get("taken_at_source"),
        "file_url": f"/api/v1/photos/{photo.id}/file/",
        "thumb_url": f"/api/v1/photos/{photo.id}/thumb/",
        "links": [
            {
                "id": link.id,
                "photo_id": link.photo_id,
                "target_kind": link.target_kind,
                "target_id": link.target_id,
                "created_by": link.created_by,
                "created_at": link.created_at,
            }
            for link in links or []
        ],
    }


async def _default_ai_caller(
    session: AsyncSession, user_id: str, prompt: str, image_b64: str
) -> tuple[str, str | None, str | None]:
    """Call the user's configured vision provider. Raises ``ValueError`` when none is set up."""
    from app.modules.ai.ai_client import call_ai, resolve_provider_key_model
    from app.modules.ai.repository import AISettingsRepository

    settings = await AISettingsRepository(session).get_by_user_id(uuid.UUID(user_id))
    provider, api_key, model = resolve_provider_key_model(settings)
    if not provider:
        raise ValueError("no AI provider configured")
    raw, _tokens = await call_ai(
        provider=provider,
        api_key=api_key,
        system="You describe construction-site photos precisely. Output JSON only.",
        prompt=prompt,
        image_base64=image_b64,
        image_media_type="image/jpeg",
        model=model,
        max_tokens=700,
    )
    return raw, provider, model


class PhotosService:
    """Business logic of the photo archive. Callers verify project access first."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PhotosRepository(session)

    # ── Reads ───────────────────────────────────────────────────────────

    async def get_photo(self, photo_id: uuid.UUID) -> ProjectPhoto:
        photo = await self.repo.get_photo(photo_id)
        if photo is None:
            raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.not_found")
        return photo

    async def with_links(self, photos: list[ProjectPhoto]) -> list[dict[str, Any]]:
        links = await self.repo.links_for([p.id for p in photos])
        return [photo_out(p, links.get(p.id, [])) for p in photos]

    async def search(
        self, project_id: uuid.UUID, filters: PhotoFilters, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        from app.modules.photos.logic import decode_cursor, encode_cursor

        rows, total = await self.repo.search(project_id, filters, after=decode_cursor(cursor), limit=limit + 1)
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(as_utc(last.taken_at or last.created_at), str(last.id))  # type: ignore[arg-type]
        return {"items": await self.with_links(rows), "next_cursor": next_cursor, "total": total}

    async def timeline(
        self, project_id: uuid.UUID, filters: PhotoFilters, *, offset: int = 0, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of day groups, newest first, plus the number of days that matched."""
        rows = await self.repo.all_photos(project_id, filters)
        days = group_timeline([photo_dict(p) for p in rows])
        page = days[offset : offset + limit]
        wanted = {p["id"] for d in page for p in d["photos"]}
        outs = {str(o["id"]): o for o in await self.with_links([r for r in rows if str(r.id) in wanted])}
        return [
            {
                "date": d["date"],
                "count": d["count"],
                "undated": d["undated"],
                "photos": [outs[p["id"]] for p in d["photos"]],
            }
            for d in page
        ], len(days)

    async def geojson(self, project_id: uuid.UUID, filters: PhotoFilters) -> dict[str, Any]:
        rows = await self.repo.all_photos(project_id, filters)
        collection = to_geojson([photo_dict(p) for p in rows])
        anchor = await self._anchor(project_id)
        if anchor is not None:
            collection["anchor"] = anchor
        return collection

    # ── Upload ──────────────────────────────────────────────────────────

    async def ingest_upload(
        self,
        project_id: uuid.UUID,
        files: list[UploadFile],
        *,
        user_id: str,
        device: DeviceCapture | None,
        category: str = "site",
        caption: str | None = None,
        tags: list[str] | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload one or more photos through the gallery path and complete their archive fields.

        One bad file does not fail the batch; its error comes back next to the
        photos that were stored. A target, when given, is checked before any
        file is written so a foreign record can never collect photos.
        """
        if not files:
            raise _err(status.HTTP_400_BAD_REQUEST, "photos.errors.no_files")
        if len(files) > MAX_FILES_PER_UPLOAD:
            raise _err(status.HTTP_400_BAD_REQUEST, "photos.errors.too_many_files", max=MAX_FILES_PER_UPLOAD)
        if target_kind and target_id:
            await self._check_target(project_id, target_kind, target_id)

        from app.modules.documents.service import PhotoService

        gallery = PhotoService(self.session)
        stored: list[ProjectPhoto] = []
        errors: list[dict[str, str]] = []
        for upload in files:
            try:
                async with self.session.begin_nested():
                    photo = await gallery.upload_photo(
                        project_id=project_id,
                        file=upload,
                        category=category,
                        user_id=user_id,
                        caption=caption,
                        tags=list(tags or []),
                    )
                    await self._complete_upload(photo, device=device, user_id=user_id)
            except HTTPException as exc:
                errors.append({"filename": upload.filename or "", "detail": str(exc.detail)})
                continue
            stored.append(photo)
            if target_kind and target_id:
                await self._link(photo, target_kind, target_id, user_id)
            publish_after_commit(
                self.session,
                "photos.photo.created",
                {
                    "photo_id": str(photo.id),
                    "project_id": str(project_id),
                    "source_module": "documents",
                    "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
                },
                source_module=SOURCE,
            )
        return {"items": await self.with_links(stored), "errors": errors}

    async def _complete_upload(self, photo: ProjectPhoto, *, device: DeviceCapture | None, user_id: str) -> None:
        """Hash, size, evidence record, device-over-EXIF position and thumbnail state of a fresh upload."""
        from app.modules.photos.logic import resolve_capture

        path = resolve_photo_file(photo)
        content = await asyncio.to_thread(path.read_bytes) if path is not None else b""
        meta = dict(photo.metadata_ or {})
        exif = await asyncio.to_thread(read_exif_evidence, content) if content else {}
        # The stored copy may have had its GPS block stripped; the coordinates read from the original are on the row.
        if meta.get("gps_source") == "exif" and valid_lat_lon(photo.gps_lat, photo.gps_lon):
            exif.setdefault("lat", photo.gps_lat)
            exif.setdefault("lon", photo.gps_lon)
        if meta.get("taken_at_source") == "exif" and photo.taken_at is not None:
            exif.setdefault("taken_at", as_utc(photo.taken_at).isoformat())  # type: ignore[union-attr]
        device_dict = None
        if device is not None:
            device_dict = {
                "lat": device.lat,
                "lon": device.lon,
                "accuracy_m": device.accuracy_m,
                "captured_at": device.captured_at.isoformat() if device.captured_at else None,
            }
        capture = resolve_capture(device=device_dict, exif=exif)
        if capture["location_source"] == "device":
            photo.gps_lat, photo.gps_lon = capture["lat"], capture["lon"]
            photo.gps_accuracy_m = capture["accuracy_m"]
        if capture["taken_at"] is not None:
            photo.taken_at = capture["taken_at"]
        if content:
            photo.sha256 = sha256_hex(content)
            photo.width, photo.height = await asyncio.to_thread(image_size, content)
            meta["evidence"] = build_evidence_record(
                content, path=f"photo:{photo.id}", device=device, exif=exif, uploaded_by=user_id
            )
        if capture["taken_at_source"]:
            meta["taken_at_source"] = capture["taken_at_source"]
        photo.metadata_ = meta
        photo.source_module = "documents"
        photo.thumb_status = "ready" if photo.thumbnail_path else "failed"
        await self.session.flush()

    # ── External photos (index rows) ───────────────────────────────────

    async def register_external_photo(
        self, project_id: uuid.UUID, source_module: str, draft: dict[str, Any], *, link_target: str | None = None
    ) -> tuple[ProjectPhoto | None, bool]:
        """Idempotently index one photo another module holds. Returns ``(photo, created)``.

        The file is never copied or moved. A diary photo that is itself a
        gallery photo links that photo instead of indexing it twice. A path that
        escapes the upload roots is refused.
        """
        file_path = str(draft.get("file_path") or "").strip()
        source_id = str(draft.get("source_id") or "").strip()
        if not file_path or not source_id:
            return None, False
        link_kind = SOURCE_LINK_KIND.get(source_module)

        gallery = _GALLERY_URL.search(file_path)
        if gallery:
            photo = await self.repo.get_photo(uuid.UUID(gallery.group(1)))
            if photo is None or photo.project_id != project_id:
                return None, False
            if link_kind and link_target:
                await self._link(photo, link_kind, link_target, None)
            return photo, False

        if not file_path.startswith(("http://", "https://", "/api/")):
            from app.core.storage import contained_upload_candidates

            if Path(file_path).is_absolute() or not contained_upload_candidates(file_path):
                logger.warning("photos: refused to index %s path outside the upload roots", source_module)
                return None, False

        existing = await self.repo.find_indexed(project_id, source_module, source_id, file_path)
        if existing is not None:
            if existing.is_archived:
                existing.is_archived = False
            if link_kind and link_target:
                await self._link(existing, link_kind, link_target, None)
            return existing, False

        lat, lon = _float(draft.get("gps_lat")), _float(draft.get("gps_lon"))
        if not valid_lat_lon(lat, lon):
            lat = lon = None
        meta: dict[str, Any] = {"indexed_from": source_module}
        if isinstance(draft.get("evidence"), dict):
            meta["evidence"] = draft["evidence"]
        photo = ProjectPhoto(
            project_id=project_id,
            filename=Path(file_path.split("?", 1)[0]).name[:255] or "photo.jpg",
            file_path=file_path[:500],
            caption=(draft.get("caption") or None),
            gps_lat=lat,
            gps_lon=lon,
            gps_accuracy_m=_float(draft.get("gps_accuracy_m")),
            tags=list(draft.get("tags") or []),
            taken_at=as_utc(draft.get("taken_at")),
            category="site",
            metadata_=meta,
            created_by="",
            source_module=source_module,
            source_id=source_id[:64],
            sha256=draft.get("sha256"),
            zone=(draft.get("zone") or None),
            thumb_status="skipped" if file_path.startswith(("http://", "https://", "/api/")) else "pending",
        )
        try:
            async with self.session.begin_nested():
                self.session.add(photo)
                await self.session.flush()
        except IntegrityError:
            return await self.repo.find_indexed(project_id, source_module, source_id, file_path), False
        if link_kind and link_target:
            await self._link(photo, link_kind, link_target, None)
        publish_after_commit(
            self.session,
            "photos.photo.created",
            {"photo_id": str(photo.id), "project_id": str(project_id), "source_module": source_module},
            source_module=SOURCE,
        )
        return photo, True

    async def archive_source(self, project_id: uuid.UUID, source_module: str, source_id: str) -> int:
        """Archive the index rows of a deleted source record; their files belong to that module."""
        rows = await self.repo.indexed_for_source(project_id, source_module, source_id)
        for row in rows:
            if not row.is_archived:
                row.is_archived = True
                publish_after_commit(
                    self.session,
                    "photos.photo.archived",
                    {"photo_id": str(row.id), "project_id": str(project_id), "reason": "source_deleted"},
                    source_module=SOURCE,
                )
        await self.session.flush()
        return len(rows)

    async def index_source_record(self, project_id: uuid.UUID, source_module: str, row: dict[str, Any]) -> int:
        """Index every photo of one source record and archive rows whose file left the record."""
        drafts = external_photo_entries(source_module, row)
        link_target = str(row.get("diary_id") or "") if source_module == "daily_diary" else str(row.get("id"))
        kept: set[str] = set()
        created = 0
        for draft in drafts:
            photo, is_new = await self.register_external_photo(
                project_id, source_module, draft, link_target=link_target or None
            )
            created += 1 if is_new else 0
            if photo is not None:
                kept.add(photo.file_path)
        if source_module != "daily_diary":
            for existing in await self.repo.indexed_for_source(project_id, source_module, str(row.get("id"))):
                if existing.file_path not in kept and not existing.is_archived:
                    existing.is_archived = True
        await self.session.flush()
        return created

    async def backfill_project(self, project_id: uuid.UUID, *, batch: int = BACKFILL_BATCH) -> dict[str, int]:
        """Index every photo the project's modules hold. Safe to rerun: existing rows are kept."""
        counts: dict[str, int] = {}
        for source_module, model_path in (
            ("daily_diary", "app.modules.daily_diary.models:DiaryPhoto"),
            ("punchlist", "app.modules.punchlist.models:PunchItem"),
            ("fieldreports", "app.modules.fieldreports.models:FieldReport"),
            ("progress", "app.modules.progress.models:ProgressEntry"),
        ):
            module_name, cls_name = model_path.split(":")
            try:
                module = __import__(module_name, fromlist=[cls_name])
                model = getattr(module, cls_name)
            except Exception:  # noqa: BLE001 - module not installed: nothing to index
                continue
            created = 0
            offset = 0
            while True:
                stmt = (
                    select(model).where(model.project_id == project_id).order_by(model.id).offset(offset).limit(batch)
                )
                rows = list((await self.session.execute(stmt)).scalars().all())
                if not rows:
                    break
                for row in rows:
                    created += await self.index_source_record(project_id, source_module, _row_dict(row))
                offset += batch
                await self.session.flush()
            counts[source_module] = created
        return counts

    # ── Edit / delete ──────────────────────────────────────────────────

    async def patch(self, photo: ProjectPhoto, changes: dict[str, Any], user_id: str) -> ProjectPhoto:
        if "tags" in changes and changes["tags"] is not None:
            changes["tags"] = [s for s in dict.fromkeys(str(x).strip() for x in changes["tags"]) if s][:50]
        if "taken_at" in changes and changes["taken_at"] is not None:
            meta = dict(photo.metadata_ or {})
            meta["taken_at_source"] = "manual"
            photo.metadata_ = meta
        if "gps_lat" in changes or "gps_lon" in changes:
            photo.gps_accuracy_m = None
        for key, value in changes.items():
            setattr(photo, key, value)
        await self.session.flush()
        publish_after_commit(
            self.session,
            "photos.photo.updated",
            {"photo_id": str(photo.id), "project_id": str(photo.project_id), "fields": sorted(changes)},
            source_module=SOURCE,
        )
        return photo

    async def delete(self, photo: ProjectPhoto, user_id: str) -> str:
        """Delete a gallery photo; archive an indexed one (its file belongs to the source module)."""
        if (photo.source_module or "documents") != "documents":
            photo.is_archived = True
            await self.session.flush()
            publish_after_commit(
                self.session,
                "photos.photo.archived",
                {"photo_id": str(photo.id), "project_id": str(photo.project_id), "reason": "user"},
                source_module=SOURCE,
            )
            return "archived"
        from app.modules.documents.service import PhotoService

        project_id = photo.project_id
        await PhotoService(self.session).delete_photo(photo.id)
        publish_after_commit(
            self.session,
            "photos.photo.archived",
            {"photo_id": str(photo.id), "project_id": str(project_id), "reason": "deleted"},
            source_module=SOURCE,
        )
        return "deleted"

    # ── Links ───────────────────────────────────────────────────────────

    async def _check_target(self, project_id: uuid.UUID, kind: str, target_id: str) -> None:
        owner = await self.repo.target_project(kind, target_id)
        # Same 404 for "missing" and "other project", so ids of foreign records do not leak.
        if owner is None or owner != str(project_id):
            raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.target_not_found")

    async def _link(self, photo: ProjectPhoto, kind: str, target_id: str, user_id: str | None) -> PhotoLink:
        existing = await self.repo.get_link(photo.id, kind, target_id)
        if existing is not None:
            return existing
        link = PhotoLink(photo_id=photo.id, target_kind=kind, target_id=str(target_id), created_by=user_id)
        try:
            async with self.session.begin_nested():
                self.session.add(link)
                await self.session.flush()
        except IntegrityError:
            found = await self.repo.get_link(photo.id, kind, target_id)
            if found is None:
                raise
            return found
        publish_after_commit(
            self.session,
            "photos.link.added",
            {
                "photo_id": str(photo.id),
                "project_id": str(photo.project_id),
                "target_kind": kind,
                "target_id": str(target_id),
            },
            source_module=SOURCE,
        )
        return link

    async def add_link(self, photo: ProjectPhoto, kind: str, target_id: str, user_id: str) -> PhotoLink:
        await self._check_target(photo.project_id, kind, target_id)
        return await self._link(photo, kind, target_id, user_id)

    async def remove_link(self, photo: ProjectPhoto, kind: str, target_id: str) -> None:
        link = await self.repo.get_link(photo.id, kind, target_id)
        if link is None:
            raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.link_not_found")
        await self.session.delete(link)
        await self.session.flush()

    async def by_target(
        self, project_id: uuid.UUID, kind: str, target_id: str, *, offset: int = 0, limit: int = 200
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.photos_page(
            project_id, PhotoFilters(target_kind=kind, target_id=target_id), offset=offset, limit=limit
        )
        return await self.with_links(rows), total

    # ── Albums ──────────────────────────────────────────────────────────

    async def list_albums(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 200
    ) -> tuple[list[dict[str, Any]], int]:
        rows = await self.repo.list_albums(project_id, offset=offset, limit=limit)
        return [_album_out(a, n) for a, n in rows], await self.repo.count_albums(project_id)

    async def get_album(self, album_id: uuid.UUID) -> PhotoAlbum:
        album = await self.repo.get_album(album_id)
        if album is None:
            raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.album_not_found")
        return album

    async def create_album(
        self, project_id: uuid.UUID, name: str, description: str | None, sort_order: int, user_id: str
    ) -> dict[str, Any]:
        clean = name.strip()
        if not clean:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.album_name_required")
        if await self.repo.album_by_name(project_id, clean) is not None:
            raise _err(status.HTTP_409_CONFLICT, "photos.errors.album_exists", name=clean)
        album = PhotoAlbum(
            project_id=project_id, name=clean, description=description, sort_order=sort_order, created_by=user_id
        )
        self.session.add(album)
        await self.session.flush()
        return _album_out(album, 0)

    async def update_album(self, album: PhotoAlbum, changes: dict[str, Any]) -> dict[str, Any]:
        if "name" in changes and changes["name"] is not None:
            clean = changes["name"].strip()
            other = await self.repo.album_by_name(album.project_id, clean)
            if other is not None and other.id != album.id:
                raise _err(status.HTTP_409_CONFLICT, "photos.errors.album_exists", name=clean)
            changes["name"] = clean
        if changes.get("cover_photo_id") is not None:
            cover = await self.repo.get_photo(changes["cover_photo_id"])
            if cover is None or cover.project_id != album.project_id:
                raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.not_found")
        for key, value in changes.items():
            setattr(album, key, value)
        await self.session.flush()
        return _album_out(album, await self.repo.album_count(album.id))

    async def delete_album(self, album: PhotoAlbum) -> None:
        await self.session.delete(album)
        await self.session.flush()

    async def add_album_items(self, album: PhotoAlbum, photo_ids: list[uuid.UUID]) -> dict[str, Any]:
        await self._same_project(album.project_id, photo_ids)
        added = await self.repo.add_album_items(album.id, photo_ids)
        if album.cover_photo_id is None and photo_ids:
            album.cover_photo_id = photo_ids[0]
        await self.session.flush()
        return {"added": added, "photo_count": await self.repo.album_count(album.id)}

    async def remove_album_items(self, album: PhotoAlbum, photo_ids: list[uuid.UUID]) -> dict[str, Any]:
        removed = await self.repo.remove_album_items(album.id, photo_ids)
        if album.cover_photo_id in photo_ids:
            remaining = await self.repo.album_photo_ids(album.id)
            album.cover_photo_id = remaining[0] if remaining else None
        await self.session.flush()
        return {"removed": removed, "photo_count": await self.repo.album_count(album.id)}

    async def _same_project(self, project_id: uuid.UUID, photo_ids: list[uuid.UUID]) -> list[ProjectPhoto]:
        photos: list[ProjectPhoto] = []
        for pid in photo_ids:
            photo = await self.repo.get_photo(pid)
            if photo is None or photo.project_id != project_id:
                raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.not_found")
            photos.append(photo)
        return photos

    # ── Drawing pins (plan room) ───────────────────────────────────────

    async def create_pin(self, photo: ProjectPhoto, data: dict[str, Any], user_id: str) -> Any:
        try:
            from app.modules.plan_room.schemas import PlanPinCreate
            from app.modules.plan_room.service import PlanRoomService
        except Exception as exc:  # noqa: BLE001 - plan room not installed
            raise _err(status.HTTP_409_CONFLICT, "photos.errors.plan_room_unavailable") from exc
        service = PlanRoomService(self.session)
        document = await service.resolve_document(data["document_id"])
        if document is None or getattr(document, "project_id", None) != photo.project_id:
            raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.document_not_found")
        return await service.create_pin(
            project_id=photo.project_id,
            document_id=str(document.id),
            page=data["page"],
            data=PlanPinCreate(
                page=data["page"], x=data["x"], y=data["y"], note=data.get("note"), photo_ref=f"photo:{photo.id}"
            ),
            user_id=user_id,
        )

    async def pins_for(self, photo: ProjectPhoto, *, offset: int = 0, limit: int = 200) -> tuple[list[Any], int]:
        try:
            from app.modules.plan_room.models import PlanPin
        except Exception:  # noqa: BLE001 - plan room not installed
            return [], 0
        where = (PlanPin.project_id == photo.project_id, PlanPin.photo_ref == f"photo:{photo.id}")
        stmt = select(PlanPin).where(*where).order_by(PlanPin.id).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = (await self.session.execute(select(func.count()).select_from(PlanPin).where(*where))).scalar()
        return rows, int(total or 0)

    # ── Compare ─────────────────────────────────────────────────────────

    async def create_compare(
        self, project_id: uuid.UUID, before_id: uuid.UUID, after_id: uuid.UUID, title: str, user_id: str
    ) -> PhotoCompare:
        if before_id == after_id:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.compare_same_photo")
        await self._same_project(project_id, [before_id, after_id])
        row = PhotoCompare(
            project_id=project_id,
            before_photo_id=before_id,
            after_photo_id=after_id,
            title=title.strip(),
            created_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def compare_out(self, row: PhotoCompare) -> dict[str, Any]:
        before = await self.get_photo(row.before_photo_id)
        after = await self.get_photo(row.after_photo_id)
        outs = await self.with_links([before, after])
        return {
            "id": row.id,
            "project_id": row.project_id,
            "title": row.title,
            "before": outs[0],
            "after": outs[1],
            "created_at": row.created_at,
        }

    # ── AI ──────────────────────────────────────────────────────────────

    async def analyze(
        self, photo: ProjectPhoto, kinds: list[str], user_id: str, *, caller: AICaller | None = None
    ) -> list[PhotoAISuggestion]:
        """Ask the vision model about one photo and store what it proposes as pending.

        Malformed answers are dropped row by row; nothing on the photo changes.
        Raises ``ValueError`` when no provider is configured or the file is gone.
        """
        wanted = [k for k in dict.fromkeys(kinds) if k in AI_KINDS]
        if not wanted:
            return []
        path = resolve_photo_file(photo)
        if path is None:
            raise ValueError("photo file not reachable")
        content = await asyncio.to_thread(path.read_bytes)
        from app.modules.documents.service import ensure_photo_within_pixel_cap

        try:
            await asyncio.to_thread(ensure_photo_within_pixel_cap, content)
        except HTTPException as exc:
            raise ValueError("photo exceeds the pixel cap") from exc
        small = await asyncio.to_thread(downscale_for_ai, content)
        links = (await self.repo.links_for([photo.id])).get(photo.id, [])
        linked: dict[str, list[str]] = {}
        for link in links:
            if link.target_kind in ("boq_position", "schedule_activity"):
                linked.setdefault(link.target_kind, []).append(link.target_id)
        prompt = ai_prompt(wanted, linked)
        raw, provider, model = await (caller or _default_ai_caller)(
            self.session, user_id, prompt, base64.b64encode(small).decode("ascii")
        )
        from app.modules.ai.ai_client import extract_json

        try:
            parsed = extract_json(raw)
        except (ValueError, json.JSONDecodeError):
            parsed = None
        rows = parse_ai_suggestions(parsed, wanted, allowed_targets={k: set(v) for k, v in linked.items()})
        stored: list[PhotoAISuggestion] = []
        for row in rows:
            suggestion = PhotoAISuggestion(
                photo_id=photo.id,
                kind=row["kind"],
                payload=row["payload"],
                confidence=row["confidence"],
                provider=provider,
                model=model,
                status="pending",
            )
            self.session.add(suggestion)
            stored.append(suggestion)
        await self.session.flush()
        if stored:
            publish_after_commit(
                self.session,
                "photos.ai.suggested",
                {
                    "photo_id": str(photo.id),
                    "project_id": str(photo.project_id),
                    "kinds": sorted({s.kind for s in stored}),
                    "count": len(stored),
                },
                source_module=SOURCE,
            )
        return stored

    async def get_suggestion(self, suggestion_id: uuid.UUID) -> tuple[PhotoAISuggestion, ProjectPhoto]:
        suggestion = await self.repo.get_suggestion(suggestion_id)
        if suggestion is None:
            raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.suggestion_not_found")
        return suggestion, await self.get_photo(suggestion.photo_id)

    async def accept_suggestion(
        self, suggestion: PhotoAISuggestion, photo: ProjectPhoto, user_id: str, edited: dict[str, Any] | None
    ) -> PhotoAISuggestion:
        """Apply a reviewed proposal. Caption and tags are written; progress only links and emits."""
        if suggestion.status != "pending":
            raise _err(status.HTTP_409_CONFLICT, "photos.errors.suggestion_reviewed")
        payload = dict(suggestion.payload or {})
        if edited is not None:
            cleaned = parse_ai_suggestions(
                _edited_shape(suggestion.kind, edited, suggestion.confidence),
                [suggestion.kind],
                allowed_targets={payload.get("target_kind", ""): {str(payload.get("target_id", ""))}},
            )
            if not cleaned:
                raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "photos.errors.suggestion_invalid")
            payload = cleaned[0]["payload"]
        if suggestion.kind == "caption":
            photo.caption = payload["text"]
        elif suggestion.kind == "tags":
            await self._apply_tags(photo, payload["tags"], user_id)
        elif suggestion.kind == "progress":
            await self.add_link(photo, payload["target_kind"], payload["target_id"], user_id)
        suggestion.payload = payload
        suggestion.status = "edited" if edited is not None else "accepted"
        suggestion.reviewed_by = user_id
        suggestion.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        publish_after_commit(
            self.session,
            "photos.ai.accepted",
            {
                "suggestion_id": str(suggestion.id),
                "photo_id": str(photo.id),
                "project_id": str(photo.project_id),
                "kind": suggestion.kind,
                "payload": payload,
                "confidence": suggestion.confidence,
                "accepted_by": user_id,
            },
            source_module=SOURCE,
        )
        return suggestion

    async def reject_suggestion(self, suggestion: PhotoAISuggestion, user_id: str) -> PhotoAISuggestion:
        if suggestion.status != "pending":
            raise _err(status.HTTP_409_CONFLICT, "photos.errors.suggestion_reviewed")
        suggestion.status = "rejected"
        suggestion.reviewed_by = user_id
        suggestion.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        return suggestion

    async def _apply_tags(self, photo: ProjectPhoto, tags: list[str], user_id: str) -> None:
        """Write tags to the photo and to the shared file tags, so every file view shows them."""
        from app.modules.file_tags.models import FileTag
        from app.modules.file_tags.schemas import slugify
        from app.modules.file_tags.service import assign_tag

        uid = _uuid(user_id)
        for display in tags:
            slug = slugify(display)
            if not slug:
                continue
            stmt = select(FileTag).where(FileTag.project_id == photo.project_id, FileTag.name == slug)
            tag = (await self.session.execute(stmt)).scalar_one_or_none()
            if tag is None:
                tag = FileTag(project_id=photo.project_id, name=slug, display_name=display[:100], created_by_id=uid)
                self.session.add(tag)
                await self.session.flush()
            await assign_tag(self.session, photo.project_id, tag.id, "photo", [str(photo.id)], uid)
        photo.tags = list(dict.fromkeys([*(photo.tags or []), *tags]))

    # ── Validation ─────────────────────────────────────────────────────

    async def snapshot(self, project_id: uuid.UUID, photos: list[ProjectPhoto] | None = None) -> dict[str, Any]:
        rows = photos if photos is not None else await self.repo.all_photos(project_id)
        links = await self.repo.links_for([p.id for p in rows])
        target_cache: dict[tuple[str, str], bool] = {}
        out_photos: list[dict[str, Any]] = []
        for p in rows:
            entry = photo_dict(p)
            entry["evidence"] = entry.pop("metadata").get("evidence")
            entry["taken_at"] = entry["taken_at"].isoformat() if entry["taken_at"] else None
            entry.pop("created_at")
            if not is_remote(p):
                entry["file_reachable"] = await asyncio.to_thread(resolve_photo_file, p) is not None
            entry_links = []
            for link in links.get(p.id, []):
                key = (link.target_kind, link.target_id)
                if key not in target_cache:
                    target_cache[key] = await self.repo.target_project(*key) == str(project_id)
                entry_links.append(
                    {"target_kind": link.target_kind, "target_id": link.target_id, "target_exists": target_cache[key]}
                )
            entry["links"] = entry_links
            out_photos.append(entry)
        ids = {p.id for p in rows}
        suggestions = [
            {
                "id": str(s.id),
                "photo_id": str(s.photo_id),
                "kind": s.kind,
                "status": s.status,
                "payload": s.payload,
                "created_at": as_utc(s.created_at).isoformat() if s.created_at else None,  # type: ignore[union-attr]
            }
            for s in await self.repo.suggestions_for_project(project_id)
            if s.photo_id in ids
        ]
        return {
            "now": datetime.now(UTC).isoformat(),
            "project_start": await self._project_start(project_id),
            "anchor": await self._anchor(project_id),
            "photos": out_photos,
            "suggestions": suggestions,
        }

    async def validate(
        self, project_id: uuid.UUID, photos: list[ProjectPhoto] | None = None, locale: str | None = None
    ) -> dict[str, Any]:
        return await evaluate(await self.snapshot(project_id, photos), target_id=str(project_id), locale=locale)

    async def _project_start(self, project_id: uuid.UUID) -> str | None:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            return None
        return getattr(project, "actual_start_date", None) or getattr(project, "planned_start_date", None)

    async def _anchor(self, project_id: uuid.UUID) -> dict[str, float] | None:
        try:
            from app.modules.geo_hub.models import GeoAnchor
        except Exception:  # noqa: BLE001 - geo hub not installed
            return None
        try:
            async with self.session.begin_nested():
                stmt = select(GeoAnchor).where(GeoAnchor.project_id == project_id)
                anchor = (await self.session.execute(stmt)).scalar_one_or_none()
        except Exception:  # noqa: BLE001 - table absent
            return None
        if anchor is None:
            return None
        return {"lat": float(anchor.lat), "lon": float(anchor.lon)}

    # ── Export ──────────────────────────────────────────────────────────

    async def export_photos(
        self, project_id: uuid.UUID, photo_ids: list[uuid.UUID] | None, album_id: uuid.UUID | None
    ) -> list[ProjectPhoto]:
        if album_id is not None:
            album = await self.get_album(album_id)
            if album.project_id != project_id:
                raise _err(status.HTTP_404_NOT_FOUND, "photos.errors.album_not_found")
            photo_ids = await self.repo.album_photo_ids(album_id)
        rows = await self.repo.all_photos(project_id, PhotoFilters(photo_ids=photo_ids))
        return rows

    async def build_export_zip(self, project_id: uuid.UUID, photos: list[ProjectPhoto], dest: Path) -> dict[str, Any]:
        """Write originals, ``photo-<id>.json`` sidecars and ``manifest.json`` to ``dest``, file by file."""
        import zipfile

        from app.modules.file_tags.service import tags_by_files

        links = await self.repo.links_for([p.id for p in photos])
        shared_tags: dict[str, list[str]] = {}
        try:
            by_file = await tags_by_files(self.session, project_id, "photo", [str(p.id) for p in photos])
            shared_tags = {k: [t.display_name for t in v] for k, v in by_file.items()}
        except Exception:  # noqa: BLE001 - file tags optional for the export
            logger.debug("photos export: file tags unavailable", exc_info=True)
        entries: list[dict[str, Any]] = []
        missing: list[str] = []
        snapshots = []
        for p in photos:
            snap = photo_dict(p)
            tags = [*snap["tags"], *shared_tags.get(str(p.id), [])]
            link_dicts = [{"target_kind": x.target_kind, "target_id": x.target_id} for x in links.get(p.id, [])]
            snapshots.append((p, sidecar(snap, link_dicts, tags), resolve_photo_file(p)))

        def _write() -> int:
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                for photo, record, path in snapshots:
                    name = archive_name(str(photo.id), photo.filename)
                    if path is not None:
                        # Originals are already compressed; stored in chunks, never read whole into memory.
                        with path.open("rb") as src, zf.open(zipfile.ZipInfo(name), "w", force_zip64=True) as out:
                            while chunk := src.read(1024 * 1024):
                                out.write(chunk)
                        record["file"] = name
                    else:
                        record["file"] = None
                        missing.append(str(photo.id))
                    zf.writestr(f"photo-{photo.id}.json", json.dumps(record, ensure_ascii=False, indent=2))
                    entries.append({"id": str(photo.id), "file": record["file"], "sidecar": f"photo-{photo.id}.json"})
                manifest = {
                    "format": "openconstructionerp.photos/1",
                    "project_id": str(project_id),
                    "exported_at": datetime.now(UTC).isoformat(),
                    "photo_count": len(entries),
                    "missing_files": missing,
                    "photos": entries,
                }
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            return len(entries)

        count = await asyncio.to_thread(_write)
        return {"photo_count": count, "missing_files": len(missing), "size_bytes": dest.stat().st_size}


def _album_out(album: PhotoAlbum, count: int) -> dict[str, Any]:
    return {
        "id": album.id,
        "project_id": album.project_id,
        "name": album.name,
        "description": album.description,
        "cover_photo_id": album.cover_photo_id,
        "sort_order": album.sort_order,
        "photo_count": count,
        "created_at": album.created_at,
    }


def _edited_shape(kind: str, edited: dict[str, Any], confidence: float) -> dict[str, Any]:
    """Wrap an edited payload in the model's answer shape so it passes the same cleaning."""
    if kind == "caption":
        return {"caption": {"text": edited.get("text"), "confidence": confidence}}
    if kind == "tags":
        return {"tags": {"tags": edited.get("tags"), "confidence": confidence}}
    if kind == "progress":
        return {"progress": [{**edited, "confidence": confidence}]}
    return {"hazards": [{**edited, "confidence": confidence}]}


def _row_dict(row: Any) -> dict[str, Any]:
    """Plain dict of a source ORM row (columns only)."""
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        key = "metadata" if column.key == "metadata" else column.key
        attr = "metadata_" if column.key == "metadata" and hasattr(row, "metadata_") else column.key
        out[key] = getattr(row, attr, None)
    return out
