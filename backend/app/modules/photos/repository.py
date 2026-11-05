# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos data access. Every read is scoped by project id."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import ProjectPhoto
from app.modules.photos.models import (
    PhotoAISuggestion,
    PhotoAlbum,
    PhotoCompare,
    PhotoLink,
    photo_album_item,
)

#: SQL resolving a link target to its project id. Plain SQL so a module that is not installed
#: (its table absent) reads as "target not found" instead of an import error.
TARGET_PROJECT_SQL: dict[str, str] = {
    "boq_position": (
        "SELECT b.project_id FROM oe_boq_position p JOIN oe_boq_boq b ON b.id = p.boq_id WHERE p.id = :id"
    ),
    "schedule_activity": (
        "SELECT s.project_id FROM oe_schedule_activity a JOIN oe_schedule_schedule s ON s.id = a.schedule_id "
        "WHERE a.id = :id"
    ),
    "location": (
        "SELECT m.project_id FROM oe_schedule_advanced_takt_location l "
        "JOIN oe_schedule_advanced_takt_schedule ts ON ts.id = l.takt_schedule_id "
        "JOIN oe_schedule_advanced_master_schedule m ON m.id = ts.master_schedule_id WHERE l.id = :id"
    ),
    "punch_item": "SELECT project_id FROM oe_punchlist_item WHERE id = :id",
    "inspection": "SELECT project_id FROM oe_inspections_inspection WHERE id = :id",
    "diary": "SELECT project_id FROM oe_daily_diary_diary WHERE id = :id",
    "field_report": "SELECT project_id FROM oe_fieldreports_report WHERE id = :id",
    "safety_obs": "SELECT project_id FROM oe_safety_observation WHERE id = :id",
}


@dataclass
class PhotoFilters:
    """Search filters for the archive; all optional, combined with AND."""

    q: str | None = None
    tag: str | None = None
    album_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    source: str | None = None
    category: str | None = None
    target_kind: str | None = None
    target_id: str | None = None
    has_gps: bool | None = None
    include_archived: bool = False
    photo_ids: list[uuid.UUID] | None = None


def _sort_at() -> Any:
    return func.coalesce(ProjectPhoto.taken_at, ProjectPhoto.created_at)


class PhotosRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Photos ──────────────────────────────────────────────────────────

    async def get_photo(self, photo_id: uuid.UUID) -> ProjectPhoto | None:
        return await self.session.get(ProjectPhoto, photo_id)

    def _filtered(self, project_id: uuid.UUID, f: PhotoFilters) -> Any:
        stmt = select(ProjectPhoto).where(ProjectPhoto.project_id == project_id)
        if not f.include_archived:
            stmt = stmt.where(ProjectPhoto.is_archived.is_(False))
        if f.photo_ids is not None:
            stmt = stmt.where(ProjectPhoto.id.in_(f.photo_ids))
        if f.q:
            like = f"%{f.q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(ProjectPhoto.filename).like(like),
                    func.lower(func.coalesce(ProjectPhoto.caption, "")).like(like),
                    func.lower(func.coalesce(ProjectPhoto.zone, "")).like(like),
                )
            )
        if f.source:
            stmt = stmt.where(ProjectPhoto.source_module == f.source)
        if f.category:
            stmt = stmt.where(ProjectPhoto.category == f.category)
        if f.date_from is not None:
            stmt = stmt.where(_sort_at() >= f.date_from)
        if f.date_to is not None:
            stmt = stmt.where(_sort_at() <= f.date_to)
        if f.has_gps is True:
            stmt = stmt.where(ProjectPhoto.gps_lat.is_not(None), ProjectPhoto.gps_lon.is_not(None))
        elif f.has_gps is False:
            stmt = stmt.where(or_(ProjectPhoto.gps_lat.is_(None), ProjectPhoto.gps_lon.is_(None)))
        if f.album_id is not None:
            stmt = stmt.where(
                ProjectPhoto.id.in_(
                    select(photo_album_item.c.photo_id).where(photo_album_item.c.album_id == f.album_id)
                )
            )
        if f.target_kind and f.target_id:
            stmt = stmt.where(
                ProjectPhoto.id.in_(
                    select(PhotoLink.photo_id).where(
                        PhotoLink.target_kind == f.target_kind, PhotoLink.target_id == f.target_id
                    )
                )
            )
        return stmt

    async def search(
        self,
        project_id: uuid.UUID,
        f: PhotoFilters,
        *,
        after: tuple[datetime, str] | None = None,
        limit: int = 60,
    ) -> tuple[list[ProjectPhoto], int]:
        """Keyset page ordered newest capture first; the tag filter runs in Python (JSON list column)."""
        base = self._filtered(project_id, f)
        stmt = base
        if after is not None:
            moment, pid = after
            stmt = stmt.where(or_(_sort_at() < moment, and_(_sort_at() == moment, ProjectPhoto.id < uuid.UUID(pid))))
        stmt = stmt.order_by(_sort_at().desc(), ProjectPhoto.id.desc())
        if f.tag:
            rows = list((await self.session.execute(stmt)).scalars().all())
            wanted = f.tag.strip().lower()
            rows = [r for r in rows if wanted in {str(t).lower() for t in (r.tags or [])}]
            total_rows = list((await self.session.execute(base)).scalars().all())
            total = sum(1 for r in total_rows if wanted in {str(t).lower() for t in (r.tags or [])})
            return rows[:limit], total
        rows = list((await self.session.execute(stmt.limit(limit))).scalars().all())
        total = int((await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0)
        return rows, total

    async def photos_page(
        self, project_id: uuid.UUID, f: PhotoFilters, *, offset: int = 0, limit: int = 200
    ) -> tuple[list[ProjectPhoto], int]:
        """SQL page for filters that need no Python post-filter (no tag)."""
        base = self._filtered(project_id, f)
        stmt = base.order_by(_sort_at().desc(), ProjectPhoto.id.desc()).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = int((await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0)
        return rows, total

    async def all_photos(self, project_id: uuid.UUID, f: PhotoFilters | None = None) -> list[ProjectPhoto]:
        stmt = self._filtered(project_id, f or PhotoFilters()).order_by(_sort_at().desc(), ProjectPhoto.id.desc())
        rows = list((await self.session.execute(stmt)).scalars().all())
        if f is not None and f.tag:
            wanted = f.tag.strip().lower()
            rows = [r for r in rows if wanted in {str(t).lower() for t in (r.tags or [])}]
        return rows

    async def find_indexed(
        self, project_id: uuid.UUID, source_module: str, source_id: str, file_path: str
    ) -> ProjectPhoto | None:
        stmt = select(ProjectPhoto).where(
            ProjectPhoto.project_id == project_id,
            ProjectPhoto.source_module == source_module,
            ProjectPhoto.source_id == source_id,
            ProjectPhoto.file_path == file_path,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def indexed_for_source(self, project_id: uuid.UUID, source_module: str, source_id: str) -> list[ProjectPhoto]:
        stmt = select(ProjectPhoto).where(
            ProjectPhoto.project_id == project_id,
            ProjectPhoto.source_module == source_module,
            ProjectPhoto.source_id == source_id,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ── Links ───────────────────────────────────────────────────────────

    async def links_for(self, photo_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PhotoLink]]:
        out: dict[uuid.UUID, list[PhotoLink]] = {pid: [] for pid in photo_ids}
        if not photo_ids:
            return out
        stmt = select(PhotoLink).where(PhotoLink.photo_id.in_(photo_ids)).order_by(PhotoLink.created_at)
        for link in (await self.session.execute(stmt)).scalars().all():
            out.setdefault(link.photo_id, []).append(link)
        return out

    async def get_link(self, photo_id: uuid.UUID, kind: str, target_id: str) -> PhotoLink | None:
        stmt = select(PhotoLink).where(
            PhotoLink.photo_id == photo_id, PhotoLink.target_kind == kind, PhotoLink.target_id == target_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def target_project(self, kind: str, target_id: str) -> str | None:
        """Project id owning a link target, or ``None`` when it does not exist (or its module is absent)."""
        sql = TARGET_PROJECT_SQL.get(kind)
        if sql is None:
            return None
        try:
            async with self.session.begin_nested():
                value = (await self.session.execute(text(sql), {"id": str(target_id)})).scalar()
        except Exception:  # noqa: BLE001 - table of an uninstalled module: the target cannot exist
            return None
        return str(value) if value is not None else None

    # ── Albums ──────────────────────────────────────────────────────────

    async def count_albums(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(PhotoAlbum).where(PhotoAlbum.project_id == project_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_albums(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> list[tuple[PhotoAlbum, int]]:
        counts = (
            select(photo_album_item.c.album_id, func.count().label("n"))
            .group_by(photo_album_item.c.album_id)
            .subquery()
        )
        stmt = (
            select(PhotoAlbum, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.album_id == PhotoAlbum.id)
            .where(PhotoAlbum.project_id == project_id)
            .order_by(PhotoAlbum.sort_order, PhotoAlbum.name, PhotoAlbum.id)
            .offset(offset)
            .limit(limit)
        )
        return [(a, int(n)) for a, n in (await self.session.execute(stmt)).all()]

    async def get_album(self, album_id: uuid.UUID) -> PhotoAlbum | None:
        return await self.session.get(PhotoAlbum, album_id)

    async def album_by_name(self, project_id: uuid.UUID, name: str) -> PhotoAlbum | None:
        stmt = select(PhotoAlbum).where(PhotoAlbum.project_id == project_id, PhotoAlbum.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def album_count(self, album_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(photo_album_item).where(photo_album_item.c.album_id == album_id)
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def album_photo_ids(self, album_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = (
            select(photo_album_item.c.photo_id)
            .where(photo_album_item.c.album_id == album_id)
            .order_by(photo_album_item.c.position)
        )
        return [r for (r,) in (await self.session.execute(stmt)).all()]

    async def add_album_items(self, album_id: uuid.UUID, photo_ids: list[uuid.UUID]) -> int:
        existing = set(await self.album_photo_ids(album_id))
        position = len(existing)
        added = 0
        for pid in photo_ids:
            if pid in existing:
                continue
            await self.session.execute(
                insert(photo_album_item).values(album_id=album_id, photo_id=pid, position=position)
            )
            existing.add(pid)
            position += 1
            added += 1
        return added

    async def remove_album_items(self, album_id: uuid.UUID, photo_ids: list[uuid.UUID]) -> int:
        result = await self.session.execute(
            delete(photo_album_item).where(
                photo_album_item.c.album_id == album_id, photo_album_item.c.photo_id.in_(photo_ids)
            )
        )
        return int(result.rowcount or 0)

    # ── AI suggestions ──────────────────────────────────────────────────

    async def suggestions_for(self, photo_id: uuid.UUID) -> list[PhotoAISuggestion]:
        stmt = (
            select(PhotoAISuggestion)
            .where(PhotoAISuggestion.photo_id == photo_id)
            .order_by(PhotoAISuggestion.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def suggestions_page(
        self, photo_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[PhotoAISuggestion], int]:
        stmt = (
            select(PhotoAISuggestion)
            .where(PhotoAISuggestion.photo_id == photo_id)
            .order_by(PhotoAISuggestion.created_at.desc(), PhotoAISuggestion.id)
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        count = select(func.count()).select_from(PhotoAISuggestion).where(PhotoAISuggestion.photo_id == photo_id)
        return rows, int((await self.session.execute(count)).scalar() or 0)

    async def suggestions_for_project(self, project_id: uuid.UUID) -> list[PhotoAISuggestion]:
        stmt = (
            select(PhotoAISuggestion)
            .join(ProjectPhoto, ProjectPhoto.id == PhotoAISuggestion.photo_id)
            .where(ProjectPhoto.project_id == project_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_suggestion(self, suggestion_id: uuid.UUID) -> PhotoAISuggestion | None:
        return await self.session.get(PhotoAISuggestion, suggestion_id)

    # ── Compare ─────────────────────────────────────────────────────────

    async def get_compare(self, compare_id: uuid.UUID) -> PhotoCompare | None:
        return await self.session.get(PhotoCompare, compare_id)

    async def list_compares(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[PhotoCompare], int]:
        where = PhotoCompare.project_id == project_id
        stmt = (
            select(PhotoCompare)
            .where(where)
            .order_by(PhotoCompare.created_at.desc(), PhotoCompare.id)
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = (await self.session.execute(select(func.count()).select_from(PhotoCompare).where(where))).scalar()
        return rows, int(total or 0)
