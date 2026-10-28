# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the stakeholders module. Every child row is read by ``(project_id, id)``."""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stakeholders.models import (
    CommunicationPlanItem,
    EngagementEvent,
    GovernanceBody,
    GovernanceBodyMember,
    Mandate,
    ProjectRole,
    Stakeholder,
    StakeholderAssessment,
    StakeholderCommitment,
    StakeholderSettings,
)

T = TypeVar("T")


class StakeholderRepository:
    """Thin queries; the service owns every rule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: T) -> T:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def get_in_project(
        self, model: type[T], project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False
    ) -> T | None:
        stmt = select(model).where(model.project_id == project_id, model.id == row_id)  # type: ignore[attr-defined]
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_in_project(self, model: type[T], project_id: uuid.UUID, *order: Any) -> list[T]:
        stmt = select(model).where(model.project_id == project_id)  # type: ignore[attr-defined]
        if order:
            stmt = stmt.order_by(*order)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_settings(self, project_id: uuid.UUID, *, lock: bool = False) -> StakeholderSettings | None:
        stmt = select(StakeholderSettings).where(StakeholderSettings.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def stakeholders(self, project_id: uuid.UUID) -> list[Stakeholder]:
        return await self.list_in_project(Stakeholder, project_id, Stakeholder.code)

    async def stakeholder_by_code(self, project_id: uuid.UUID, code: str) -> Stakeholder | None:
        stmt = select(Stakeholder).where(Stakeholder.project_id == project_id, Stakeholder.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def assessments(
        self, project_id: uuid.UUID, stakeholder_id: uuid.UUID | None = None
    ) -> list[StakeholderAssessment]:
        stmt = select(StakeholderAssessment).where(StakeholderAssessment.project_id == project_id)
        if stakeholder_id is not None:
            stmt = stmt.where(StakeholderAssessment.stakeholder_id == stakeholder_id)
        stmt = stmt.order_by(StakeholderAssessment.assessed_at.desc(), StakeholderAssessment.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def plan_items(self, project_id: uuid.UUID) -> list[CommunicationPlanItem]:
        return await self.list_in_project(CommunicationPlanItem, project_id, CommunicationPlanItem.created_at)

    async def events(self, project_id: uuid.UUID, *, include_deleted: bool = False) -> list[EngagementEvent]:
        stmt = select(EngagementEvent).where(EngagementEvent.project_id == project_id)
        if not include_deleted:
            stmt = stmt.where(EngagementEvent.deleted_at.is_(None))
        stmt = stmt.order_by(EngagementEvent.held_on.desc().nulls_last(), EngagementEvent.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def plan_events(self, plan_item_id: uuid.UUID) -> list[EngagementEvent]:
        stmt = select(EngagementEvent).where(
            EngagementEvent.plan_item_id == plan_item_id, EngagementEvent.deleted_at.is_(None)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def commitments(self, project_id: uuid.UUID) -> list[StakeholderCommitment]:
        return await self.list_in_project(StakeholderCommitment, project_id, StakeholderCommitment.code)

    async def commitment_by_instance(self, instance_id: uuid.UUID) -> StakeholderCommitment | None:
        stmt = (
            select(StakeholderCommitment)
            .where(StakeholderCommitment.approval_instance_id == instance_id)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def roles(self, project_id: uuid.UUID) -> list[ProjectRole]:
        return await self.list_in_project(ProjectRole, project_id, ProjectRole.role_code, ProjectRole.created_at)

    async def bodies(self, project_id: uuid.UUID) -> list[GovernanceBody]:
        return await self.list_in_project(
            GovernanceBody, project_id, GovernanceBody.decision_level, GovernanceBody.code
        )

    async def body_members(self, project_id: uuid.UUID) -> list[GovernanceBodyMember]:
        return await self.list_in_project(GovernanceBodyMember, project_id, GovernanceBodyMember.created_at)

    async def mandates(self, project_id: uuid.UUID, *, lock: bool = False) -> list[Mandate]:
        stmt = (
            select(Mandate)
            .where(Mandate.project_id == project_id)
            .order_by(Mandate.decision_type, Mandate.scope, Mandate.letter)
        )
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars().all())

    async def next_code(self, model: Any, project_id: uuid.UUID, prefix: str) -> str:
        rows = (await self.session.execute(select(model.code).where(model.project_id == project_id))).scalars().all()
        n = 0
        for code in rows:
            if code.startswith(prefix) and code[len(prefix) :].isdigit():
                n = max(n, int(code[len(prefix) :]))
        return f"{prefix}{n + 1:03d}"
