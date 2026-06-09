"""Demo seed data for the documents photo gallery.

Loaded on demand via ``await seed_photos(session, project_ids)``.

Seeds real construction site photos so a fresh install arrives with a
populated Photos gallery (and a non-empty "Latest site photos" dashboard
widget) instead of an empty grid. The bundled JPEGs live under the
committed asset directory ``scripts/flagship_assets/site_photos`` together
with a ``captions.json`` that carries the caption, category, capture date
and tags for each image. The flagship project receives the full twelve
photo construction timeline; every other project receives a rotating
subset of the more generic build-stage photos (excavation, slab, rebar,
crane) so no project gallery is blank.

Each row is stored exactly like a real upload: the file id is generated up
front, the JPEG is copied into ``PHOTO_BASE / "demo" / {project_id}`` and a
JPEG thumbnail is written under ``PHOTO_THUMB_BASE`` using the same helper
the upload endpoint uses, so the gallery serves the seeded photos from
``GET /v1/documents/photos/{id}/file/`` and ``/thumb/`` without any special
casing.

The seed is idempotent: it short-circuits and returns an empty dict when a
photo already exists for the flagship (or first) project. It never touches
a lazy relationship after a flush, and every non-nullable column receives a
typed value. Projects without a resolvable owner are skipped.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import ProjectPhoto
from app.modules.documents.service import (
    PHOTO_BASE,
    PHOTO_THUMB_BASE,
    _generate_photo_thumbnail,
)
from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)

_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# Committed asset directory holding the downsized JPEGs plus a captions.json
# carrying caption / category / taken_at / tags per file. Read metadata from
# here (inside the repo) rather than any external temp directory.
_ASSET_DIR = Path(__file__).resolve().parents[2] / "scripts" / "flagship_assets" / "site_photos"
_CAPTIONS_FILE = _ASSET_DIR / "captions.json"

# Generic build-stage photos shared with non-flagship projects (0-based
# indices into the captions list): deep excavation, mat slab pour, concrete
# core and crane, rebar placement, superstructure, crane lift. Skyline and
# facade shots are intentionally excluded so secondary galleries stay on the
# neutral construction stages.
_GENERIC_POOL = [1, 2, 3, 5, 6, 8]
_SUBSET_SIZE = 4


def _load_captions() -> list[dict]:
    """Load the per-photo metadata committed alongside the JPEG assets."""
    if not _CAPTIONS_FILE.exists():
        return []
    try:
        data = json.loads(_CAPTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("photos seed: could not read %s", _CAPTIONS_FILE)
        return []
    return data if isinstance(data, list) else []


def _parse_taken_at(value: str | None) -> datetime | None:
    """Parse a naive ISO timestamp from captions.json into UTC-aware form."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _resolve_owner_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve a valid owner user id for the seeded photos.

    Prefers the owner of the target project; falls back to any existing user.
    Returns None when no user is available, in which case the caller skips
    the project.
    """
    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner_id is not None:
        return owner_id
    return (await session.execute(select(User.id).limit(1))).scalar_one_or_none()


def _store_photo_files(project_id: uuid.UUID, source: Path) -> tuple[str, str, str | None]:
    """Copy ``source`` into the project photo store and build a thumbnail.

    Returns ``(filename, file_path, thumbnail_path)``. The on-disk names are
    UUID-prefixed exactly like the upload path so the stored row matches the
    file. The thumbnail is best-effort; ``thumbnail_path`` is None when Pillow
    is unavailable, in which case the serve endpoint falls back to the full
    image.
    """
    file_uuid = uuid.uuid4().hex[:12]
    storage_name = f"{file_uuid}_{source.name}"

    upload_dir = PHOTO_BASE / "demo" / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / storage_name
    shutil.copyfile(source, dest_path)

    thumb_dir = PHOTO_THUMB_BASE / "demo" / str(project_id)
    thumb_path = thumb_dir / f"{file_uuid}_thumb.jpg"
    thumb_ok = _generate_photo_thumbnail(dest_path.read_bytes(), thumb_path)

    return storage_name, str(dest_path), (str(thumb_path) if thumb_ok else None)


def _photo_indexes_for(project_id: uuid.UUID, slot: int, total: int) -> list[int]:
    """Return the caption indexes a project should receive.

    The flagship gets the full timeline; every other project gets a rotating
    window of ``_SUBSET_SIZE`` generic build-stage photos so galleries differ
    but none is empty.
    """
    if project_id == _FLAGSHIP_ID:
        return list(range(total))
    pool = _GENERIC_POOL
    start = (slot * _SUBSET_SIZE) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(_SUBSET_SIZE)]


async def seed_photos(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed demo site photos for the demo projects.

    Args:
        session: Open async DB session.
        project_ids: Candidate projects. The flagship project is always
            preferred for the idempotency guard and receives the full photo
            timeline; the rest receive a rotating generic subset.

    Returns:
        A dict of row counts (``{"photos": N}``), or an empty dict when
        nothing was seeded (already present, no project, no owner, or the
        bundled assets are missing).
    """
    if not project_ids:
        return {}

    captions = _load_captions()
    if not captions:
        logger.info("photos seed skipped: no committed photo assets at %s", _ASSET_DIR)
        return {}

    # Prefer the flagship project for the idempotency guard so the check lands
    # where users browse first.
    guard_id = _FLAGSHIP_ID if _FLAGSHIP_ID in project_ids else project_ids[0]
    existing = (
        await session.execute(select(ProjectPhoto.id).where(ProjectPhoto.project_id == guard_id).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return {}

    total = len(captions)
    counts = {"photos": 0}

    for slot, project_id in enumerate(project_ids):
        owner_id = await _resolve_owner_id(session, project_id)
        if owner_id is None:
            logger.info("photos seed: skipping %s (no owner user)", project_id)
            continue
        owner_ref = str(owner_id)

        for index in _photo_indexes_for(project_id, slot, total):
            entry = captions[index]
            source = _ASSET_DIR / str(entry.get("file", ""))
            if not source.exists():
                logger.warning("photos seed: asset missing %s", source)
                continue

            photo_id = uuid.uuid4()
            filename, file_path, thumbnail_path = _store_photo_files(project_id, source)

            tags = entry.get("tags") or []
            if not isinstance(tags, list):
                tags = [str(tags)]

            photo = ProjectPhoto(
                id=photo_id,
                project_id=project_id,
                filename=filename,
                file_path=file_path,
                thumbnail_path=thumbnail_path,
                caption=entry.get("caption"),
                gps_lat=None,
                gps_lon=None,
                tags=tags,
                taken_at=_parse_taken_at(entry.get("taken_at")),
                category=str(entry.get("category") or "site"),
                metadata_={"seed": True, "demo": True},
                created_by=owner_ref,
            )
            session.add(photo)
            counts["photos"] += 1

    await session.flush()
    logger.info("photos demo seed inserted: %s", counts)
    return counts
