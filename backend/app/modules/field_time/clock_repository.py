# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Time clock data access layer​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Queries for geofences, clock settings, consent and clock events. Pure data
access; the rules about what a clock means live in ``clock_service``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time.models import (
    FieldClockConsent,
    FieldClockEvent,
    FieldClockSettings,
    FieldSiteGeofence,
)


class ClockRepository:
    """Data access for the geofenced time clock."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Geofences ────────────────────────────────────────────────────────────

    async def list_geofences(self, project_id: uuid.UUID, *, active_only: bool = False) -> list[FieldSiteGeofence]:
        """Fences of a project, oldest first."""
        stmt = select(FieldSiteGeofence).where(FieldSiteGeofence.project_id == project_id)
        if active_only:
            stmt = stmt.where(FieldSiteGeofence.active.is_(True))
        stmt = stmt.order_by(FieldSiteGeofence.created_at, FieldSiteGeofence.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_geofence(self, geofence_id: uuid.UUID) -> FieldSiteGeofence | None:
        """One fence by id."""
        return await self.session.get(FieldSiteGeofence, geofence_id)

    async def add(self, row: object) -> None:
        """Stage and flush a new row."""
        self.session.add(row)
        await self.session.flush()

    async def delete(self, row: object) -> None:
        """Delete a row and flush."""
        await self.session.delete(row)
        await self.session.flush()

    # ── Settings + consent ───────────────────────────────────────────────────

    async def get_settings(self, project_id: uuid.UUID) -> FieldClockSettings | None:
        """The project's clock settings row, if any."""
        stmt = select(FieldClockSettings).where(FieldClockSettings.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_consent(self, project_id: uuid.UUID, resource_id: uuid.UUID) -> FieldClockConsent | None:
        """A worker's consent row on a project, if any."""
        stmt = select(FieldClockConsent).where(
            FieldClockConsent.project_id == project_id,
            FieldClockConsent.resource_id == resource_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── Events ───────────────────────────────────────────────────────────────

    async def get_event(self, event_id: uuid.UUID) -> FieldClockEvent | None:
        """One clock event by id."""
        return await self.session.get(FieldClockEvent, event_id)

    async def get_by_client_op(self, project_id: uuid.UUID, client_op_id: str) -> FieldClockEvent | None:
        """The event an offline replay already created, if it did."""
        stmt = select(FieldClockEvent).where(
            FieldClockEvent.project_id == project_id,
            FieldClockEvent.client_op_id == client_op_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def last_event_for(
        self, project_id: uuid.UUID, resource_id: uuid.UUID, before: datetime | None = None
    ) -> FieldClockEvent | None:
        """The worker's latest clock event on the project (optionally before an instant)."""
        stmt = select(FieldClockEvent).where(
            FieldClockEvent.project_id == project_id,
            FieldClockEvent.resource_id == resource_id,
        )
        if before is not None:
            stmt = stmt.where(FieldClockEvent.occurred_at <= before)
        stmt = stmt.order_by(FieldClockEvent.occurred_at.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_events(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        resource_id: uuid.UUID | None = None,
        approval_status: str | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[FieldClockEvent], int]:
        """Events of a project in a window, newest first, with the total count."""
        conds = [FieldClockEvent.project_id == project_id]
        if since is not None:
            conds.append(FieldClockEvent.occurred_at >= since)
        if until is not None:
            conds.append(FieldClockEvent.occurred_at < until)
        if resource_id is not None:
            conds.append(FieldClockEvent.resource_id == resource_id)
        if approval_status:
            conds.append(FieldClockEvent.approval_status == approval_status)
        total = (await self.session.execute(select(func.count()).select_from(FieldClockEvent).where(*conds))).scalar()
        stmt = (
            select(FieldClockEvent)
            .where(*conds)
            .order_by(FieldClockEvent.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), int(total or 0)

    async def count_pending(self, project_id: uuid.UUID) -> int:
        """Flagged clocks still waiting for a supervisor."""
        stmt = (
            select(func.count())
            .select_from(FieldClockEvent)
            .where(FieldClockEvent.project_id == project_id, FieldClockEvent.approval_status == "pending")
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def purge_positions(self, project_id: uuid.UUID, before: datetime, now: datetime) -> int:
        """Erase stored positions captured before ``before``; returns rows erased."""
        stmt = (
            update(FieldClockEvent)
            .where(
                FieldClockEvent.project_id == project_id,
                FieldClockEvent.occurred_at < before,
                FieldClockEvent.position_purged_at.is_(None),
            )
            .values(latitude=None, longitude=None, accuracy_m=None, position_purged_at=now)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def resource_names(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        """``{resource_id: name}`` from the resources module (best-effort)."""
        if not ids:
            return {}
        from app.modules.resources.models import Resource

        rows = (await self.session.execute(select(Resource.id, Resource.name).where(Resource.id.in_(ids)))).all()
        return {rid: name or "" for rid, name in rows}
