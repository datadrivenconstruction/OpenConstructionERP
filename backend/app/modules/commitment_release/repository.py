# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the commitment matrix. Every child row is read by ``(project_id, id)``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commitment_release.models import (
    AbortScenario,
    AbortTerms,
    AuthorityAssignment,
    CommitmentItem,
    CommitmentLink,
    CommitmentMatrix,
    CommitmentPrecondition,
    ReleaseDecision,
)


class CommitmentRepository:
    """Thin queries; the service owns every rule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_matrix(self, project_id: uuid.UUID, *, lock: bool = False) -> CommitmentMatrix | None:
        stmt = select(CommitmentMatrix).where(CommitmentMatrix.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_assignments(self, project_id: uuid.UUID) -> list[AuthorityAssignment]:
        stmt = (
            select(AuthorityAssignment)
            .where(AuthorityAssignment.project_id == project_id)
            .order_by(AuthorityAssignment.project_role, AuthorityAssignment.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_items(self, project_id: uuid.UUID) -> list[CommitmentItem]:
        stmt = select(CommitmentItem).where(CommitmentItem.project_id == project_id).order_by(CommitmentItem.code)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_item(self, project_id: uuid.UUID, item_id: uuid.UUID, *, lock: bool = False) -> CommitmentItem | None:
        stmt = select(CommitmentItem).where(CommitmentItem.project_id == project_id, CommitmentItem.id == item_id)
        if lock:
            # After the wait for the lock the row may have changed: never serve the identity-map copy.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def items_in_group(self, project_id: uuid.UUID, group: str, *, lock: bool = False) -> list[CommitmentItem]:
        """The items of one split group, in id order. ``lock`` row-locks them in that same order, so two
        requests in one group queue up instead of deadlocking, and reads the rows afresh."""
        stmt = (
            select(CommitmentItem)
            .where(CommitmentItem.project_id == project_id, CommitmentItem.split_group == group)
            .order_by(CommitmentItem.id)
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_links(self, project_id: uuid.UUID, item_ids: list[uuid.UUID] | None = None) -> list[CommitmentLink]:
        stmt = select(CommitmentLink).where(CommitmentLink.project_id == project_id)
        if item_ids is not None:
            if not item_ids:
                return []
            stmt = stmt.where(CommitmentLink.item_id.in_(item_ids))
        return list((await self.session.execute(stmt.order_by(CommitmentLink.created_at))).scalars().all())

    async def find_link(self, project_id: uuid.UUID, kind: str, document_id: uuid.UUID) -> CommitmentLink | None:
        stmt = select(CommitmentLink).where(
            CommitmentLink.project_id == project_id,
            CommitmentLink.kind == kind,
            CommitmentLink.target_id == document_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def links_for_documents(self, kind: str, document_ids: list[uuid.UUID]) -> list[CommitmentLink]:
        if not document_ids:
            return []
        stmt = select(CommitmentLink).where(CommitmentLink.kind == kind, CommitmentLink.target_id.in_(document_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_preconditions(
        self, project_id: uuid.UUID, item_ids: list[uuid.UUID] | None = None
    ) -> list[CommitmentPrecondition]:
        stmt = select(CommitmentPrecondition).where(CommitmentPrecondition.project_id == project_id)
        if item_ids is not None:
            if not item_ids:
                return []
            stmt = stmt.where(CommitmentPrecondition.item_id.in_(item_ids))
        return list((await self.session.execute(stmt.order_by(CommitmentPrecondition.created_at))).scalars().all())

    async def get_precondition(
        self, project_id: uuid.UUID, item_id: uuid.UUID, precondition_id: uuid.UUID
    ) -> CommitmentPrecondition | None:
        stmt = select(CommitmentPrecondition).where(
            CommitmentPrecondition.project_id == project_id,
            CommitmentPrecondition.item_id == item_id,
            CommitmentPrecondition.id == precondition_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_releases(
        self, project_id: uuid.UUID, item_ids: list[uuid.UUID] | None = None
    ) -> list[ReleaseDecision]:
        stmt = select(ReleaseDecision).where(ReleaseDecision.project_id == project_id)
        if item_ids is not None:
            if not item_ids:
                return []
            stmt = stmt.where(ReleaseDecision.item_id.in_(item_ids))
        return list((await self.session.execute(stmt.order_by(ReleaseDecision.attempt))).scalars().all())

    async def get_release(self, release_id: uuid.UUID, *, lock: bool = False) -> ReleaseDecision | None:
        stmt = select(ReleaseDecision).where(ReleaseDecision.id == release_id)
        if lock:
            # Same reason as ``get_item``: a withdrawal that committed while this waited must be seen.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_release(self, item_id: uuid.UUID) -> bool:
        """Whether any release was ever requested on the item, whatever became of it."""
        stmt = select(ReleaseDecision.id).where(ReleaseDecision.item_id == item_id).limit(1)
        return (await self.session.execute(stmt)).first() is not None

    async def items_by_risk(
        self, project_id: uuid.UUID, risk_id: uuid.UUID, commitment_type: str
    ) -> list[CommitmentItem]:
        stmt = select(CommitmentItem).where(
            CommitmentItem.project_id == project_id,
            CommitmentItem.risk_id == risk_id,
            CommitmentItem.commitment_type == commitment_type,
        )
        return list((await self.session.execute(stmt.order_by(CommitmentItem.code))).scalars().all())

    async def list_abort_terms(
        self, project_id: uuid.UUID, item_ids: list[uuid.UUID] | None = None
    ) -> list[AbortTerms]:
        stmt = select(AbortTerms).where(AbortTerms.project_id == project_id)
        if item_ids is not None:
            if not item_ids:
                return []
            stmt = stmt.where(AbortTerms.item_id.in_(item_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_abort_terms(self, item_id: uuid.UUID, scope: str) -> AbortTerms | None:
        stmt = select(AbortTerms).where(AbortTerms.item_id == item_id, AbortTerms.scope == scope)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_scenarios(self, project_id: uuid.UUID) -> list[AbortScenario]:
        stmt = (
            select(AbortScenario)
            .where(AbortScenario.project_id == project_id)
            .order_by(AbortScenario.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
