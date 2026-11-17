# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for setting-out. Writes only ``oe_setting_out_*`` tables."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.setting_out.models import (
    SettingOutPoint,
    SettingOutRecord,
    SettingOutRequest,
    SettingOutToleranceProfile,
)


class SettingOutRepository:
    """Queries behind the setting-out service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, obj: Any) -> None:
        self.session.add(obj)
        await self.session.flush()

    # ── Profiles ───────────────────────────────────────────────────────────

    async def list_profiles(self, project_id: uuid.UUID) -> list[SettingOutToleranceProfile]:
        rows = await self.session.execute(
            select(SettingOutToleranceProfile)
            .where(SettingOutToleranceProfile.project_id == project_id)
            .order_by(SettingOutToleranceProfile.name)
        )
        return list(rows.scalars().all())

    async def get_profile(self, profile_id: uuid.UUID) -> SettingOutToleranceProfile | None:
        return await self.session.get(SettingOutToleranceProfile, profile_id)

    # ── Requests ───────────────────────────────────────────────────────────

    async def list_requests(self, project_id: uuid.UUID) -> list[SettingOutRequest]:
        rows = await self.session.execute(
            select(SettingOutRequest)
            .where(SettingOutRequest.project_id == project_id)
            .order_by(SettingOutRequest.code, SettingOutRequest.id)
        )
        return list(rows.scalars().all())

    async def get_request(self, request_id: uuid.UUID) -> SettingOutRequest | None:
        return await self.session.get(SettingOutRequest, request_id)

    async def next_code(self, project_id: uuid.UUID) -> str:
        count = (
            await self.session.execute(
                select(func.count(SettingOutRequest.id)).where(SettingOutRequest.project_id == project_id)
            )
        ).scalar_one()
        existing = {r.code for r in await self.list_requests(project_id)}
        n = int(count) + 1
        while f"SO-{n:03d}" in existing:
            n += 1
        return f"SO-{n:03d}"

    async def delete_request(self, request: SettingOutRequest) -> None:
        await self.session.execute(delete(SettingOutRecord).where(SettingOutRecord.request_id == request.id))
        await self.session.execute(delete(SettingOutPoint).where(SettingOutPoint.request_id == request.id))
        await self.session.delete(request)
        await self.session.flush()

    # ── Stakes ─────────────────────────────────────────────────────────────

    async def stakes(self, request_ids: list[uuid.UUID]) -> list[SettingOutPoint]:
        if not request_ids:
            return []
        rows = await self.session.execute(
            select(SettingOutPoint)
            .where(SettingOutPoint.request_id.in_(request_ids))
            .order_by(SettingOutPoint.sort_order, SettingOutPoint.point_id)
        )
        return list(rows.scalars().all())

    async def get_stake(self, stake_id: uuid.UUID) -> SettingOutPoint | None:
        return await self.session.get(SettingOutPoint, stake_id)

    async def delete_unmeasured_stakes(self, request_id: uuid.UUID) -> None:
        measured = select(SettingOutRecord.point_id).where(SettingOutRecord.request_id == request_id)
        await self.session.execute(
            delete(SettingOutPoint).where(SettingOutPoint.request_id == request_id, SettingOutPoint.id.not_in(measured))
        )
        await self.session.flush()

    # ── Records ────────────────────────────────────────────────────────────

    async def records(self, request_ids: list[uuid.UUID]) -> list[SettingOutRecord]:
        """Every record of the requests, oldest first."""
        if not request_ids:
            return []
        rows = await self.session.execute(
            select(SettingOutRecord)
            .where(SettingOutRecord.request_id.in_(request_ids))
            .order_by(SettingOutRecord.measured_at, SettingOutRecord.created_at, SettingOutRecord.id)
        )
        return list(rows.scalars().all())

    async def point_records(self, stake_id: uuid.UUID) -> list[SettingOutRecord]:
        rows = await self.session.execute(
            select(SettingOutRecord)
            .where(SettingOutRecord.point_id == stake_id)
            .order_by(SettingOutRecord.measured_at.desc(), SettingOutRecord.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_record(self, record_id: uuid.UUID) -> SettingOutRecord | None:
        return await self.session.get(SettingOutRecord, record_id)

    async def user_name(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return ""
        from app.modules.users.models import User  # noqa: PLC0415

        row = (await self.session.execute(select(User.full_name, User.email).where(User.id == user_id))).first()
        if row is None:
            return ""
        return str(row[0] or row[1] or "")

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
