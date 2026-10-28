# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the permits module. Every child row is read by ``(project_id, id)``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permits.models import (
    ClockEvent,
    ConditionDischarge,
    ConditionEvidence,
    Permit,
    PermitApplication,
    PermitCondition,
    PermitDecision,
    PermitRequirement,
    PermitRoadmap,
    RequirementDependency,
)


class PermitRepository:
    """Thin queries; the service owns every rule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def _one(self, model: Any, project_id: uuid.UUID, row_id: uuid.UUID, lock: bool) -> Any:
        stmt = select(model).where(model.project_id == project_id, model.id == row_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _all(self, model: Any, project_id: uuid.UUID, *order: Any) -> list[Any]:
        stmt = select(model).where(model.project_id == project_id).order_by(*order, model.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_roadmap(self, project_id: uuid.UUID, *, lock: bool = False) -> PermitRoadmap | None:
        stmt = select(PermitRoadmap).where(PermitRoadmap.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_requirements(self, project_id: uuid.UUID) -> list[PermitRequirement]:
        return await self._all(PermitRequirement, project_id, PermitRequirement.sort_order)

    async def get_requirement(
        self, project_id: uuid.UUID, rid: uuid.UUID, *, lock: bool = False
    ) -> PermitRequirement | None:
        return await self._one(PermitRequirement, project_id, rid, lock)

    async def list_dependencies(self, project_id: uuid.UUID) -> list[RequirementDependency]:
        return await self._all(RequirementDependency, project_id)

    async def list_applications(self, project_id: uuid.UUID) -> list[PermitApplication]:
        return await self._all(PermitApplication, project_id, PermitApplication.attempt)

    async def get_application(
        self, project_id: uuid.UUID, aid: uuid.UUID, *, lock: bool = False
    ) -> PermitApplication | None:
        return await self._one(PermitApplication, project_id, aid, lock)

    async def list_clock_events(self, project_id: uuid.UUID, aid: uuid.UUID | None = None) -> list[ClockEvent]:
        stmt = select(ClockEvent).where(ClockEvent.project_id == project_id)
        if aid is not None:
            stmt = stmt.where(ClockEvent.application_id == aid)
        stmt = stmt.order_by(ClockEvent.event_date, ClockEvent.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_decisions(self, project_id: uuid.UUID) -> list[PermitDecision]:
        return await self._all(PermitDecision, project_id, PermitDecision.revision)

    async def get_decision(self, project_id: uuid.UUID, did: uuid.UUID, *, lock: bool = False) -> PermitDecision | None:
        return await self._one(PermitDecision, project_id, did, lock)

    async def list_permits(self, project_id: uuid.UUID) -> list[Permit]:
        return await self._all(Permit, project_id)

    async def get_permit(self, project_id: uuid.UUID, pid: uuid.UUID, *, lock: bool = False) -> Permit | None:
        return await self._one(Permit, project_id, pid, lock)

    async def list_conditions(self, project_id: uuid.UUID) -> list[PermitCondition]:
        return await self._all(PermitCondition, project_id, PermitCondition.permit_id, PermitCondition.number)

    async def get_condition(
        self, project_id: uuid.UUID, cid: uuid.UUID, *, lock: bool = False
    ) -> PermitCondition | None:
        return await self._one(PermitCondition, project_id, cid, lock)

    async def conditions_of_permit(self, project_id: uuid.UUID, permit_id: uuid.UUID) -> list[PermitCondition]:
        stmt = (
            select(PermitCondition)
            .where(PermitCondition.project_id == project_id, PermitCondition.permit_id == permit_id)
            .order_by(PermitCondition.number)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_evidence(self, project_id: uuid.UUID, cid: uuid.UUID | None = None) -> list[ConditionEvidence]:
        stmt = select(ConditionEvidence).where(ConditionEvidence.project_id == project_id)
        if cid is not None:
            stmt = stmt.where(ConditionEvidence.condition_id == cid)
        return list((await self.session.execute(stmt.order_by(ConditionEvidence.created_at))).scalars().all())

    async def get_evidence(self, project_id: uuid.UUID, eid: uuid.UUID) -> ConditionEvidence | None:
        return await self._one(ConditionEvidence, project_id, eid, False)

    async def list_discharges(self, project_id: uuid.UUID, cid: uuid.UUID | None = None) -> list[ConditionDischarge]:
        stmt = select(ConditionDischarge).where(ConditionDischarge.project_id == project_id)
        if cid is not None:
            stmt = stmt.where(ConditionDischarge.condition_id == cid)
        return list((await self.session.execute(stmt.order_by(ConditionDischarge.created_at))).scalars().all())
