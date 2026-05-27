# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub data access layer — one repository per entity."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo_hub.models import (
    GeoAnchor,
    GeoOverlay,
    GeoRasterOverlay,
    GeoViewpoint,
    ImageryLayer,
    TerrainSource,
    TileGenerationJob,
    Tileset,
)


class _BaseRepo:
    """Tiny shared helper — create / update / delete boilerplate."""

    model: type

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, entity_id)

    async def create(self, obj: Any) -> Any:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_fields(self, entity_id: uuid.UUID, **fields: object) -> None:
        if not fields:
            return
        stmt = (
            update(self.model)
            .where(self.model.id == entity_id)  # type: ignore[attr-defined]
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, entity_id: uuid.UUID) -> None:
        obj = await self.get_by_id(entity_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


# ── GeoAnchor ────────────────────────────────────────────────────────────


class GeoAnchorRepository(_BaseRepo):
    model = GeoAnchor

    async def get_by_project(
        self,
        project_id: uuid.UUID,
    ) -> GeoAnchor | None:
        stmt = select(GeoAnchor).where(GeoAnchor.project_id == project_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()


# ── Tileset ──────────────────────────────────────────────────────────────


class TilesetRepository(_BaseRepo):
    model = Tileset

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        development_id: str | None = None,
    ) -> list[Tileset]:
        """List tilesets for ``project_id``, optionally narrowed by status / dev.

        ``development_id`` matches either::

            source_kind == 'development' AND source_id == <dev_id>

        or::

            metadata.development_id == <dev_id>

        The native-source path is matched via a direct column compare;
        the metadata path is matched via JSON-extract so the dev-scoped
        map config doesn't have to load every tileset only to throw most
        away in Python (the pre-v5.2.9 hot path on PropDev customers
        with dozens of tilesets per project).
        """
        from sqlalchemy import and_, or_

        stmt = select(Tileset).where(Tileset.project_id == project_id)
        if status:
            stmt = stmt.where(Tileset.status == status)
        if development_id:
            # ``Tileset.metadata_["development_id"].as_string()`` works on
            # both Postgres (JSONB ->> operator) and SQLite (json_extract)
            # via SQLAlchemy's portable JSON accessor — no Postgres-only
            # SQL leaks into the dev-friendly SQLite path.
            try:
                meta_match = Tileset.metadata_["development_id"].as_string() == development_id
            except Exception:  # noqa: BLE001 — JSON accessor not supported
                meta_match = None
            native_match = and_(
                Tileset.source_kind == "development",
                Tileset.source_id == development_id,
            )
            stmt = stmt.where(
                or_(native_match, meta_match) if meta_match is not None else native_match,
            )
        stmt = stmt.order_by(Tileset.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def find_for_source(
        self,
        source_kind: str,
        source_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
    ) -> Tileset | None:
        """Return the most recent tileset for a polymorphic source.

        ``project_id`` is optional but **must** be supplied by any caller
        that exposes the result back to a tenant — otherwise the
        ``(source_kind, source_id)`` pair can leak across tenants when
        two projects happen to import the same external upload key.
        Internal callers (event-bus subscribers that already know they
        are operating on a trusted payload) may omit it.
        """
        stmt = select(Tileset).where(Tileset.source_kind == source_kind).where(Tileset.source_id == source_id)
        if project_id is not None:
            stmt = stmt.where(Tileset.project_id == project_id)
        stmt = stmt.order_by(Tileset.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().first()


# ── ImageryLayer ─────────────────────────────────────────────────────────


class ImageryLayerRepository(_BaseRepo):
    model = ImageryLayer

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ImageryLayer]:
        stmt = (
            select(ImageryLayer)
            .where(ImageryLayer.project_id == project_id)
            .order_by(
                ImageryLayer.default_for_project.desc(),
                ImageryLayer.created_at.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def clear_default_for_project(self, project_id: uuid.UUID) -> None:
        """Demote every existing default layer for a project."""
        stmt = (
            update(ImageryLayer)
            .where(ImageryLayer.project_id == project_id)
            .where(ImageryLayer.default_for_project.is_(True))
            .values(default_for_project=False)
        )
        await self.session.execute(stmt)
        await self.session.flush()


# ── TerrainSource ────────────────────────────────────────────────────────


class TerrainSourceRepository(_BaseRepo):
    model = TerrainSource

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[TerrainSource]:
        stmt = (
            select(TerrainSource)
            .order_by(
                TerrainSource.is_default.desc(),
                TerrainSource.name.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_default(self) -> TerrainSource | None:
        stmt = select(TerrainSource).where(TerrainSource.is_default.is_(True)).order_by(TerrainSource.created_at.asc())
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def clear_default(self) -> None:
        stmt = update(TerrainSource).where(TerrainSource.is_default.is_(True)).values(is_default=False)
        await self.session.execute(stmt)
        await self.session.flush()


# ── Viewpoint ────────────────────────────────────────────────────────────


class ViewpointRepository(_BaseRepo):
    model = GeoViewpoint

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[GeoViewpoint]:
        stmt = (
            select(GeoViewpoint)
            .where(GeoViewpoint.project_id == project_id)
            .order_by(GeoViewpoint.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


# ── GeoOverlay ───────────────────────────────────────────────────────────


class GeoOverlayRepository(_BaseRepo):
    model = GeoOverlay

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        kind: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[GeoOverlay]:
        stmt = select(GeoOverlay).where(GeoOverlay.project_id == project_id)
        if kind:
            stmt = stmt.where(GeoOverlay.kind == kind)
        stmt = stmt.order_by(GeoOverlay.created_at.asc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def find_by_event(self, event_id: str) -> GeoOverlay | None:
        """Idempotency lookup for cross-module subscribers."""
        stmt = select(GeoOverlay).where(GeoOverlay.source_event_id == event_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()


# ── GeoRasterOverlay ─────────────────────────────────────────────────────


class GeoRasterOverlayRepository(_BaseRepo):
    """Data access for raster overlays — soft-delete aware."""

    model = GeoRasterOverlay

    async def get_active(
        self,
        entity_id: uuid.UUID,
    ) -> GeoRasterOverlay | None:
        """Return the row only when it isn't soft-deleted."""
        obj = await self.get_by_id(entity_id)
        if obj is None or obj.deleted_at is not None:
            return None
        return obj

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_hidden: bool = True,
        offset: int = 0,
        limit: int = 200,
    ) -> list[GeoRasterOverlay]:
        stmt = (
            select(GeoRasterOverlay)
            .where(GeoRasterOverlay.project_id == project_id)
            .where(GeoRasterOverlay.deleted_at.is_(None))
        )
        if not include_hidden:
            stmt = stmt.where(GeoRasterOverlay.visible.is_(True))
        stmt = (
            stmt.order_by(
                GeoRasterOverlay.z_order.asc(),
                GeoRasterOverlay.created_at.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def soft_delete(self, entity_id: uuid.UUID) -> None:
        from datetime import UTC, datetime

        stmt = (
            update(GeoRasterOverlay)
            .where(GeoRasterOverlay.id == entity_id)
            .where(GeoRasterOverlay.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)
        await self.session.flush()


# ── TileGenerationJob ────────────────────────────────────────────────────


class TileJobRepository(_BaseRepo):
    model = TileGenerationJob

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        state: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[TileGenerationJob]:
        stmt = select(TileGenerationJob).where(
            TileGenerationJob.project_id == project_id,
        )
        if state:
            stmt = stmt.where(TileGenerationJob.state == state)
        stmt = stmt.order_by(TileGenerationJob.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def list_active_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[TileGenerationJob]:
        """Queued + running jobs for the map-config bundle."""
        stmt = (
            select(TileGenerationJob)
            .where(TileGenerationJob.project_id == project_id)
            .where(TileGenerationJob.state.in_(("queued", "running")))
            .order_by(TileGenerationJob.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


__all__ = [
    "GeoAnchorRepository",
    "GeoOverlayRepository",
    "GeoRasterOverlayRepository",
    "ImageryLayerRepository",
    "TerrainSourceRepository",
    "TileJobRepository",
    "TilesetRepository",
    "ViewpointRepository",
]
