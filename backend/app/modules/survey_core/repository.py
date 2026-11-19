# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the survey register. Writes only ``oe_survey_*`` tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core.models import (
    SurveyGeodesy,
    SurveyPoint,
    SurveyPointSet,
    SurveyProfile,
    SurveyProjectCrs,
    SurveyTraverse,
)


class SurveyRepository:
    """Queries behind the survey register service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── CRS ────────────────────────────────────────────────────────────────

    async def get_crs(self, project_id: uuid.UUID) -> SurveyProjectCrs | None:
        rows = await self.session.execute(select(SurveyProjectCrs).where(SurveyProjectCrs.project_id == project_id))
        return rows.scalar_one_or_none()

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    async def anchor_latlon(self, project_id: uuid.UUID) -> tuple[float, float] | None:
        """The project's map pin from Geo Hub, when that module is installed and a pin is set."""
        try:
            from app.modules.geo_hub.models import GeoAnchor  # noqa: PLC0415
        except ImportError:  # pragma: no cover - geo_hub is optional
            return None
        row = (
            await self.session.execute(select(GeoAnchor.lat, GeoAnchor.lon).where(GeoAnchor.project_id == project_id))
        ).first()
        if row is None or row[0] is None or row[1] is None:
            return None
        return float(row[0]), float(row[1])

    # ── Point sets ─────────────────────────────────────────────────────────

    async def list_sets(self, project_id: uuid.UUID) -> list[SurveyPointSet]:
        rows = await self.session.execute(
            select(SurveyPointSet)
            .where(SurveyPointSet.project_id == project_id)
            .order_by(SurveyPointSet.created_at.desc(), SurveyPointSet.id)
        )
        return list(rows.scalars().all())

    async def get_set(self, set_id: uuid.UUID) -> SurveyPointSet | None:
        return await self.session.get(SurveyPointSet, set_id)

    async def delete_set(self, point_set: SurveyPointSet) -> None:
        await self.session.execute(delete(SurveyPoint).where(SurveyPoint.point_set_id == point_set.id))
        await self.session.delete(point_set)
        await self.session.flush()

    async def last_import(self, project_id: uuid.UUID) -> datetime | None:
        return (
            await self.session.execute(
                select(func.max(SurveyPointSet.created_at)).where(SurveyPointSet.project_id == project_id)
            )
        ).scalar()

    # ── Points ─────────────────────────────────────────────────────────────

    def _filtered(
        self, stmt: Select, project_id: uuid.UUID, kind: str, set_id: uuid.UUID | None, code: str, q: str
    ) -> Select:
        stmt = stmt.where(SurveyPoint.project_id == project_id)
        if kind:
            stmt = stmt.where(SurveyPoint.kind == kind)
        if set_id:
            stmt = stmt.where(SurveyPoint.point_set_id == set_id)
        if code:
            stmt = stmt.where(SurveyPoint.code == code)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            stmt = stmt.where(
                or_(
                    SurveyPoint.point_id.ilike(like, escape="\\"),
                    SurveyPoint.description.ilike(like, escape="\\"),
                )
            )
        return stmt

    async def list_points(
        self,
        project_id: uuid.UUID,
        *,
        kind: str = "",
        set_id: uuid.UUID | None = None,
        code: str = "",
        q: str = "",
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[SurveyPoint], int]:
        total = (
            await self.session.execute(
                self._filtered(select(func.count(SurveyPoint.id)), project_id, kind, set_id, code, q)
            )
        ).scalar_one()
        rows = await self.session.execute(
            self._filtered(select(SurveyPoint), project_id, kind, set_id, code, q)
            .order_by(SurveyPoint.point_id, SurveyPoint.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows.scalars().all()), int(total)

    async def point_positions(self, project_id: uuid.UUID) -> list[tuple[str, float, float, float | None, str]]:
        """``(point_id, e, n, z, set_id)`` of every point; enough for duplicate checks."""
        rows = await self.session.execute(
            select(SurveyPoint.point_id, SurveyPoint.e, SurveyPoint.n, SurveyPoint.z, SurveyPoint.point_set_id).where(
                SurveyPoint.project_id == project_id
            )
        )
        return [
            (pid, float(e), float(n), float(z) if z is not None else None, str(sid)) for pid, e, n, z, sid in rows.all()
        ]

    async def counts(self, project_id: uuid.UUID) -> tuple[int, int]:
        """Points and control points of the project."""
        total = (
            await self.session.execute(select(func.count(SurveyPoint.id)).where(SurveyPoint.project_id == project_id))
        ).scalar_one()
        control = (
            await self.session.execute(
                select(func.count(SurveyPoint.id)).where(
                    SurveyPoint.project_id == project_id, SurveyPoint.kind == "control"
                )
            )
        ).scalar_one()
        return int(total), int(control)

    async def centroid(self, project_id: uuid.UUID) -> tuple[float, float, float | None, int] | None:
        """Mean E, N and Z of the project's points and how many there are; ``None`` without points."""
        row = (
            await self.session.execute(
                select(
                    func.avg(SurveyPoint.e),
                    func.avg(SurveyPoint.n),
                    func.avg(SurveyPoint.z),
                    func.count(SurveyPoint.id),
                ).where(SurveyPoint.project_id == project_id)
            )
        ).first()
        if row is None or not row[3]:
            return None
        return float(row[0]), float(row[1]), float(row[2]) if row[2] is not None else None, int(row[3])

    async def get_geodesy(self, project_id: uuid.UUID) -> SurveyGeodesy | None:
        rows = await self.session.execute(select(SurveyGeodesy).where(SurveyGeodesy.project_id == project_id))
        return rows.scalar_one_or_none()

    async def export_points(
        self, project_id: uuid.UUID, *, kind: str = "", set_id: uuid.UUID | None = None, limit: int = 100_000
    ) -> list[tuple[str, float, float, float | None, str, str]]:
        """``(point_id, e, n, z, code, description)`` for an export, in point id order (rows, not objects)."""
        q = select(
            SurveyPoint.point_id, SurveyPoint.e, SurveyPoint.n, SurveyPoint.z, SurveyPoint.code, SurveyPoint.description
        ).where(SurveyPoint.project_id == project_id)
        if kind:
            q = q.where(SurveyPoint.kind == kind)
        if set_id is not None:
            q = q.where(SurveyPoint.point_set_id == set_id)
        rows = await self.session.execute(q.order_by(SurveyPoint.point_id, SurveyPoint.id).limit(limit))
        return [
            (pid, float(e), float(n), float(z) if z is not None else None, code or "", desc or "")
            for pid, e, n, z, code, desc in rows.all()
        ]

    async def add_points(self, points: list[SurveyPoint]) -> None:
        self.session.add_all(points)
        await self.session.flush()

    # ── Traverses and profiles ─────────────────────────────────────────────

    async def list_traverses(self, project_id: uuid.UUID) -> list[SurveyTraverse]:
        rows = await self.session.execute(
            select(SurveyTraverse)
            .where(SurveyTraverse.project_id == project_id)
            .order_by(SurveyTraverse.created_at.desc(), SurveyTraverse.id)
        )
        return list(rows.scalars().all())

    async def get_traverse(self, traverse_id: uuid.UUID) -> SurveyTraverse | None:
        return await self.session.get(SurveyTraverse, traverse_id)

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    async def get_profile(self, project_id: uuid.UUID | None) -> SurveyProfile | None:
        """The project's own profile row, or the workspace default when ``project_id`` is None."""
        cond = SurveyProfile.project_id.is_(None) if project_id is None else SurveyProfile.project_id == project_id
        rows = await self.session.execute(select(SurveyProfile).where(cond).order_by(SurveyProfile.created_at))
        return rows.scalars().first()
