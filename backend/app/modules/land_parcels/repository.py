# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for land and parcels. Writes only ``oe_land_*`` tables."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.land_parcels.models import (
    LandParcel,
    LandParcelPoint,
    LandParcelSettings,
    LandParty,
    LandRight,
    LandWorkZone,
)


class ParcelRepository:
    """Queries behind the parcel service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    # ── Parcels ────────────────────────────────────────────────────────────

    async def list_parcels(self, project_id: uuid.UUID) -> list[LandParcel]:
        rows = await self.session.execute(
            select(LandParcel).where(LandParcel.project_id == project_id).order_by(LandParcel.parcel_ref, LandParcel.id)
        )
        return list(rows.scalars().all())

    async def get_parcel(self, parcel_id: uuid.UUID) -> LandParcel | None:
        return await self.session.get(LandParcel, parcel_id)

    async def points_by_parcel(self, parcel_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[LandParcelPoint]]:
        out: dict[uuid.UUID, list[LandParcelPoint]] = {pid: [] for pid in parcel_ids}
        if not parcel_ids:
            return out
        rows = await self.session.execute(
            select(LandParcelPoint)
            .where(LandParcelPoint.parcel_id.in_(parcel_ids))
            .order_by(LandParcelPoint.parcel_id, LandParcelPoint.seq)
        )
        for p in rows.scalars().all():
            out.setdefault(p.parcel_id, []).append(p)
        return out

    async def replace_points(self, parcel_id: uuid.UUID, points: list[LandParcelPoint]) -> None:
        await self.session.execute(delete(LandParcelPoint).where(LandParcelPoint.parcel_id == parcel_id))
        self.session.add_all(points)
        await self.session.flush()

    # ── Parties and rights ─────────────────────────────────────────────────

    async def list_parties(self, project_id: uuid.UUID) -> list[LandParty]:
        rows = await self.session.execute(
            select(LandParty).where(LandParty.project_id == project_id).order_by(LandParty.name, LandParty.id)
        )
        return list(rows.scalars().all())

    async def get_party(self, party_id: uuid.UUID) -> LandParty | None:
        return await self.session.get(LandParty, party_id)

    async def list_rights(self, project_id: uuid.UUID, parcel_id: uuid.UUID | None = None) -> list[LandRight]:
        stmt = select(LandRight).where(LandRight.project_id == project_id)
        if parcel_id is not None:
            stmt = stmt.where(LandRight.parcel_id == parcel_id)
        rows = await self.session.execute(stmt.order_by(LandRight.created_at, LandRight.id))
        return list(rows.scalars().all())

    async def get_right(self, right_id: uuid.UUID) -> LandRight | None:
        return await self.session.get(LandRight, right_id)

    # ── Work zones and settings ────────────────────────────────────────────

    async def list_zones(self, project_id: uuid.UUID) -> list[LandWorkZone]:
        rows = await self.session.execute(
            select(LandWorkZone).where(LandWorkZone.project_id == project_id).order_by(LandWorkZone.created_at)
        )
        return list(rows.scalars().all())

    async def get_zone(self, zone_id: uuid.UUID) -> LandWorkZone | None:
        return await self.session.get(LandWorkZone, zone_id)

    async def get_settings(self, project_id: uuid.UUID) -> LandParcelSettings | None:
        rows = await self.session.execute(select(LandParcelSettings).where(LandParcelSettings.project_id == project_id))
        return rows.scalar_one_or_none()

    # ── Other modules (read only) ──────────────────────────────────────────

    async def project_epsg(self, project_id: uuid.UUID) -> tuple[int | None, bool]:
        """The project CRS from the survey register: ``(EPSG, is local grid)``."""
        from app.modules.survey_core.models import SurveyProjectCrs  # noqa: PLC0415

        row = (
            await self.session.execute(
                select(SurveyProjectCrs.horizontal_epsg, SurveyProjectCrs.is_local_grid).where(
                    SurveyProjectCrs.project_id == project_id
                )
            )
        ).first()
        return (row[0], bool(row[1])) if row else (None, False)

    async def project_info(self, project_id: uuid.UUID) -> dict[str, Any]:
        from app.modules.projects.models import Project  # noqa: PLC0415

        row = await self.session.get(Project, project_id)
        if row is None:
            return {}
        return {
            "name": row.name,
            "currency": getattr(row, "currency", "") or "",
            "country": getattr(row, "country_code", None) or "",
        }
