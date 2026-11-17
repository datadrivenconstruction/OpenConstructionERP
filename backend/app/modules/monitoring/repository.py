# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for monitoring. Writes only ``oe_monitoring_*`` tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.monitoring.models import (
    MonitoringAlert,
    MonitoringEpoch,
    MonitoringPoint,
    MonitoringProfile,
    MonitoringReading,
    MonitoringSettings,
)


class MonitoringRepository:
    """Queries behind the monitoring service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    # ── Settings and profiles ──────────────────────────────────────────────

    async def settings(self, project_id: uuid.UUID) -> MonitoringSettings | None:
        return (
            await self.session.execute(select(MonitoringSettings).where(MonitoringSettings.project_id == project_id))
        ).scalar_one_or_none()

    async def list_profiles(self, project_id: uuid.UUID) -> list[MonitoringProfile]:
        rows = await self.session.execute(
            select(MonitoringProfile).where(MonitoringProfile.project_id == project_id).order_by(MonitoringProfile.name)
        )
        return list(rows.scalars().all())

    async def get_profile(self, profile_id: uuid.UUID) -> MonitoringProfile | None:
        return await self.session.get(MonitoringProfile, profile_id)

    # ── Points ─────────────────────────────────────────────────────────────

    async def list_points(self, project_id: uuid.UUID) -> list[MonitoringPoint]:
        rows = await self.session.execute(
            select(MonitoringPoint).where(MonitoringPoint.project_id == project_id).order_by(MonitoringPoint.code)
        )
        return list(rows.scalars().all())

    async def get_point(self, point_id: uuid.UUID) -> MonitoringPoint | None:
        return await self.session.get(MonitoringPoint, point_id)

    async def delete_point(self, point: MonitoringPoint) -> None:
        await self.session.execute(delete(MonitoringAlert).where(MonitoringAlert.point_id == point.id))
        await self.session.execute(delete(MonitoringReading).where(MonitoringReading.point_id == point.id))
        await self.session.delete(point)
        await self.session.flush()

    # ── Epochs and readings ────────────────────────────────────────────────

    async def list_epochs(self, project_id: uuid.UUID) -> list[MonitoringEpoch]:
        rows = await self.session.execute(
            select(MonitoringEpoch)
            .where(MonitoringEpoch.project_id == project_id)
            .order_by(MonitoringEpoch.observed_at)
        )
        return list(rows.scalars().all())

    async def epoch_at(self, project_id: uuid.UUID, at: datetime) -> MonitoringEpoch | None:
        return (
            await self.session.execute(
                select(MonitoringEpoch).where(
                    MonitoringEpoch.project_id == project_id, MonitoringEpoch.observed_at == at
                )
            )
        ).scalar_one_or_none()

    async def readings(
        self, project_id: uuid.UUID, point_ids: list[uuid.UUID] | None = None
    ) -> list[tuple[MonitoringReading, datetime]]:
        """Readings with their epoch time, oldest first."""
        stmt = (
            select(MonitoringReading, MonitoringEpoch.observed_at)
            .join(MonitoringEpoch, MonitoringEpoch.id == MonitoringReading.epoch_id)
            .where(MonitoringReading.project_id == project_id)
            .order_by(MonitoringEpoch.observed_at, MonitoringReading.id)
        )
        if point_ids is not None:
            if not point_ids:
                return []
            stmt = stmt.where(MonitoringReading.point_id.in_(point_ids))
        return [(r, at) for r, at in (await self.session.execute(stmt)).all()]

    # ── Alerts ─────────────────────────────────────────────────────────────

    async def alerts(self, project_id: uuid.UUID, point_id: uuid.UUID | None = None) -> list[MonitoringAlert]:
        stmt = select(MonitoringAlert).where(MonitoringAlert.project_id == project_id)
        if point_id is not None:
            stmt = stmt.where(MonitoringAlert.point_id == point_id)
        rows = await self.session.execute(stmt.order_by(MonitoringAlert.observed_at, MonitoringAlert.created_at))
        return list(rows.scalars().all())

    # ── Context ────────────────────────────────────────────────────────────

    async def user_name(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return ""
        from app.modules.users.models import User  # noqa: PLC0415

        row = (await self.session.execute(select(User.full_name, User.email).where(User.id == user_id))).first()
        return "" if row is None else str(row[0] or row[1] or "")

    async def project_owner(self, project_id: uuid.UUID) -> uuid.UUID | None:
        from app.modules.projects.models import Project  # noqa: PLC0415

        return (await self.session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar()

    async def project_name(self, project_id: uuid.UUID) -> str:
        from app.modules.projects.models import Project  # noqa: PLC0415

        return str((await self.session.execute(select(Project.name).where(Project.id == project_id))).scalar() or "")

    async def project_crs_label(self, project_id: uuid.UUID) -> str:
        """``EPSG 32633 · WGS 84 / UTM zone 33N`` from the survey register, or empty."""
        try:
            from app.modules.survey_core.models import SurveyProjectCrs  # noqa: PLC0415
        except ImportError:  # pragma: no cover - survey_core is a declared dependency
            return ""
        row = (
            await self.session.execute(
                select(
                    SurveyProjectCrs.horizontal_epsg, SurveyProjectCrs.horizontal_name, SurveyProjectCrs.is_local_grid
                ).where(SurveyProjectCrs.project_id == project_id)
            )
        ).first()
        if row is None:
            return ""
        if row[2] and not row[0]:
            return "Local grid"
        return f"EPSG {row[0]} · {row[1]}" if row[0] else ""
