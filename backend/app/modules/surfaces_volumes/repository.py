# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for surfaces and volumes. Writes only ``oe_survey_surface`` / ``oe_survey_volume*``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.surfaces_volumes.models import SurveySurface, SurveyVolume, SurveyVolumeEvent


class VolumesRepository:
    """Queries behind the surfaces and volumes service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    # ── Surfaces ───────────────────────────────────────────────────────────

    async def list_surfaces(self, project_id: uuid.UUID) -> list[SurveySurface]:
        rows = await self.session.execute(
            select(SurveySurface).where(SurveySurface.project_id == project_id).order_by(SurveySurface.code)
        )
        return list(rows.scalars().all())

    async def get_surface(self, surface_id: uuid.UUID) -> SurveySurface | None:
        return await self.session.get(SurveySurface, surface_id)

    async def surface_usage(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """How many calculations use each surface, as base or compare."""
        out: dict[uuid.UUID, int] = {}
        for col in (SurveyVolume.base_surface_id, SurveyVolume.compare_surface_id):
            rows = await self.session.execute(
                select(col, func.count(SurveyVolume.id))
                .where(SurveyVolume.project_id == project_id, col.is_not(None))
                .group_by(col)
            )
            for sid, count in rows.all():
                out[sid] = out.get(sid, 0) + int(count)
        return out

    async def locked_usage(self, surface_id: uuid.UUID) -> int:
        """Confirmed or sent calculations built on a surface."""
        return int(
            (
                await self.session.execute(
                    select(func.count(SurveyVolume.id)).where(
                        or_(SurveyVolume.base_surface_id == surface_id, SurveyVolume.compare_surface_id == surface_id),
                        SurveyVolume.status != "draft",
                    )
                )
            ).scalar_one()
        )

    # ── Volumes ────────────────────────────────────────────────────────────

    async def list_volumes(self, project_id: uuid.UUID) -> list[SurveyVolume]:
        rows = await self.session.execute(
            select(SurveyVolume).where(SurveyVolume.project_id == project_id).order_by(SurveyVolume.code)
        )
        return list(rows.scalars().all())

    async def get_volume(self, volume_id: uuid.UUID) -> SurveyVolume | None:
        return await self.session.get(SurveyVolume, volume_id)

    async def codes(self, model: type[SurveySurface] | type[SurveyVolume], project_id: uuid.UUID) -> list[str]:
        rows = await self.session.execute(select(model.code).where(model.project_id == project_id))
        return [str(c) for (c,) in rows.all()]

    async def events(self, volume_id: uuid.UUID) -> list[SurveyVolumeEvent]:
        rows = await self.session.execute(
            select(SurveyVolumeEvent)
            .where(SurveyVolumeEvent.volume_id == volume_id)
            .order_by(SurveyVolumeEvent.created_at, SurveyVolumeEvent.id)
        )
        return list(rows.scalars().all())

    # ── Other modules, read only ───────────────────────────────────────────

    async def point_rows(self, set_ids: list[uuid.UUID]) -> list[tuple[float, float, float | None]]:
        from app.modules.survey_core.models import SurveyPoint  # noqa: PLC0415

        rows = await self.session.execute(
            select(SurveyPoint.e, SurveyPoint.n, SurveyPoint.z)
            .where(SurveyPoint.point_set_id.in_(set_ids))
            .order_by(SurveyPoint.point_set_id, SurveyPoint.source_line, SurveyPoint.id)
        )
        return [(float(e), float(n), float(z) if z is not None else None) for e, n, z in rows.all()]

    async def user_name(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return ""
        try:
            from app.modules.users.models import User  # noqa: PLC0415
        except ImportError:  # pragma: no cover - users is core
            return ""
        row = (await self.session.execute(select(User.full_name, User.email).where(User.id == user_id))).first()
        if row is None:
            return ""
        return str(row[0] or row[1] or "")

    async def boq_position(self, position_id: uuid.UUID) -> tuple[Any, Any] | None:
        """``(position, boq)`` for a BOQ position id, or None."""
        from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

        row = (
            await self.session.execute(
                select(Position, BOQ).join(BOQ, BOQ.id == Position.boq_id).where(Position.id == position_id)
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def search_positions(self, project_id: uuid.UUID, q: str, unit: str, limit: int = 20) -> list[tuple]:
        from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

        stmt = (
            select(Position, BOQ.name)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id, Position.unit != "")
        )
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Position.description.ilike(like), Position.ordinal.ilike(like)))
        if unit:
            stmt = stmt.where(func.lower(Position.unit).in_([unit.lower(), unit.lower().replace("3", "³")]))
        rows = await self.session.execute(stmt.order_by(BOQ.name, Position.sort_order).limit(limit))
        return list(rows.all())
