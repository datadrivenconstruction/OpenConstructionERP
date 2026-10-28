# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for project governance.

Every reader takes the project id, so a row id from another project never
resolves: the router asks for ``(project_id, row_id)`` and gets ``None`` for a
row that exists elsewhere, which it answers 404 like a missing one.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, TypeVar

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_governance.models import (
    GovernanceArea,
    GovernanceCatalogue,
    GovernanceCatalogueVersion,
    GovernanceChangeRequest,
    GovernanceCheck,
    GovernanceCondition,
    GovernanceDecision,
    GovernanceDocument,
    GovernanceGate,
    GovernanceModel,
)

T = TypeVar("T")


class GovernanceRepository:
    """Queries scoped to one project at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: T) -> T:
        """Add and flush one row."""
        self.session.add(row)
        await self.session.flush()
        return row

    async def _one(self, model: type[T], project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False) -> T | None:
        stmt = select(model).where(model.id == row_id, model.project_id == project_id)  # type: ignore[attr-defined]
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── model ──
    async def get_model(self, project_id: uuid.UUID, *, lock: bool = False) -> GovernanceModel | None:
        stmt = select(GovernanceModel).where(GovernanceModel.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── areas ──
    async def list_areas(self, project_id: uuid.UUID, *, include_retired: bool = False) -> list[GovernanceArea]:
        stmt = select(GovernanceArea).where(GovernanceArea.project_id == project_id)
        if not include_retired:
            stmt = stmt.where(GovernanceArea.retired.is_(False))
        stmt = stmt.order_by(GovernanceArea.sort_order, GovernanceArea.code)
        return list((await self.session.execute(stmt)).scalars())

    async def get_area(self, project_id: uuid.UUID, area_id: uuid.UUID) -> GovernanceArea | None:
        return await self._one(GovernanceArea, project_id, area_id)

    # ── gates ──
    async def list_gates(self, project_id: uuid.UUID, *, include_historic: bool = False) -> list[GovernanceGate]:
        stmt = select(GovernanceGate).where(GovernanceGate.project_id == project_id)
        if not include_historic:
            stmt = stmt.where(GovernanceGate.historic.is_(False))
        stmt = stmt.order_by(GovernanceGate.historic, GovernanceGate.sort_order)
        return list((await self.session.execute(stmt)).scalars())

    async def get_gate(self, project_id: uuid.UUID, gate_id: uuid.UUID, *, lock: bool = False) -> GovernanceGate | None:
        return await self._one(GovernanceGate, project_id, gate_id, lock=lock)

    async def get_gate_by_id(self, gate_id: uuid.UUID, *, lock: bool = False) -> GovernanceGate | None:
        """Unscoped lookup, for event subscribers that only carry the gate id."""
        stmt = select(GovernanceGate).where(GovernanceGate.id == gate_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── documents ──
    async def list_documents(self, project_id: uuid.UUID) -> list[GovernanceDocument]:
        stmt = (
            select(GovernanceDocument)
            .where(GovernanceDocument.project_id == project_id)
            .order_by(GovernanceDocument.doc_type)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_document(
        self, project_id: uuid.UUID, document_id: uuid.UUID, *, lock: bool = False
    ) -> GovernanceDocument | None:
        return await self._one(GovernanceDocument, project_id, document_id, lock=lock)

    # ── checks ──
    async def list_checks(self, gate_id: uuid.UUID, attempt_no: int) -> list[GovernanceCheck]:
        stmt = select(GovernanceCheck).where(
            GovernanceCheck.gate_id == gate_id, GovernanceCheck.attempt_no == attempt_no
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_open_checks_for_area(self, project_id: uuid.UUID, area_id: uuid.UUID) -> list[GovernanceCheck]:
        """Checks of the current attempt of every undecided gate, for one area."""
        stmt = (
            select(GovernanceCheck)
            .join(GovernanceGate, GovernanceGate.id == GovernanceCheck.gate_id)
            .where(
                GovernanceCheck.project_id == project_id,
                GovernanceCheck.area_id == area_id,
                GovernanceCheck.attempt_no == GovernanceGate.attempt_no,
                GovernanceGate.status.in_(("not_started", "in_preparation", "in_review", "on_hold")),
            )
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_current_checks(self, project_id: uuid.UUID) -> list[GovernanceCheck]:
        """Checks of the current attempt of every live gate of the project, in one query."""
        stmt = (
            select(GovernanceCheck)
            .join(GovernanceGate, GovernanceGate.id == GovernanceCheck.gate_id)
            .where(
                GovernanceCheck.project_id == project_id,
                GovernanceCheck.attempt_no == GovernanceGate.attempt_no,
                GovernanceGate.historic.is_(False),
            )
        )
        return list((await self.session.execute(stmt)).scalars())

    # ── decisions and conditions ──
    async def list_decisions(self, project_id: uuid.UUID, gate_id: uuid.UUID | None = None) -> list[GovernanceDecision]:
        stmt = select(GovernanceDecision).where(GovernanceDecision.project_id == project_id)
        if gate_id is not None:
            stmt = stmt.where(GovernanceDecision.gate_id == gate_id)
        stmt = stmt.order_by(GovernanceDecision.decided_at, GovernanceDecision.attempt_no)
        return list((await self.session.execute(stmt)).scalars())

    async def decision_counts(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        stmt = (
            select(GovernanceDecision.gate_id, func.count())
            .where(GovernanceDecision.project_id == project_id)
            .group_by(GovernanceDecision.gate_id)
        )
        return {gid: int(n) for gid, n in (await self.session.execute(stmt)).all()}

    async def list_conditions(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        today: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[GovernanceCondition], int]:
        """Conditions of a project, optionally of one status.

        With ``today`` the filter is on the effective status: an open condition
        past its due date counts as overdue whether or not the escalation sweep
        has reached it. Without it the filter is on the stored value. Due dates
        are ISO strings, so they order as dates.
        """
        base = select(GovernanceCondition).where(GovernanceCondition.project_id == project_id)
        if status and today is not None and status in ("open", "overdue"):
            late = and_(GovernanceCondition.due_date != "", GovernanceCondition.due_date < today.isoformat())
            if status == "overdue":
                base = base.where(
                    or_(
                        GovernanceCondition.status == "overdue",
                        and_(GovernanceCondition.status == "open", late),
                    )
                )
            else:
                base = base.where(GovernanceCondition.status == "open", ~late)
        elif status:
            base = base.where(GovernanceCondition.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(GovernanceCondition.due_date, GovernanceCondition.created_at).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars()), int(total)

    async def projects_with_late_conditions(self, today: date) -> list[uuid.UUID]:
        """Projects holding an open condition past its due date that no sweep has escalated yet."""
        stmt = (
            select(GovernanceCondition.project_id)
            .where(
                GovernanceCondition.status == "open",
                GovernanceCondition.due_date != "",
                GovernanceCondition.due_date < today.isoformat(),
            )
            .distinct()
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_condition(
        self, project_id: uuid.UUID, condition_id: uuid.UUID, *, lock: bool = False
    ) -> GovernanceCondition | None:
        return await self._one(GovernanceCondition, project_id, condition_id, lock=lock)

    # ── change requests ──
    async def list_change_requests(
        self, project_id: uuid.UUID, document_id: uuid.UUID | None = None
    ) -> list[GovernanceChangeRequest]:
        stmt = select(GovernanceChangeRequest).where(GovernanceChangeRequest.project_id == project_id)
        if document_id is not None:
            stmt = stmt.where(GovernanceChangeRequest.document_id == document_id)
        return list((await self.session.execute(stmt.order_by(GovernanceChangeRequest.created_at))).scalars())

    async def get_change_request(
        self, project_id: uuid.UUID, cr_id: uuid.UUID, *, lock: bool = False
    ) -> GovernanceChangeRequest | None:
        return await self._one(GovernanceChangeRequest, project_id, cr_id, lock=lock)

    async def get_change_request_by_id(self, cr_id: uuid.UUID, *, lock: bool = False) -> GovernanceChangeRequest | None:
        stmt = select(GovernanceChangeRequest).where(GovernanceChangeRequest.id == cr_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── tenant catalogues ──
    async def list_tenant_catalogues(self, tenant_id: str, *, kind: str | None = None) -> list[GovernanceCatalogue]:
        stmt = select(GovernanceCatalogue).where(GovernanceCatalogue.tenant_id == tenant_id)
        if kind is not None:
            stmt = stmt.where(GovernanceCatalogue.kind == kind)
        return list((await self.session.execute(stmt.order_by(GovernanceCatalogue.code))).scalars())

    async def get_tenant_catalogue(
        self, tenant_id: str, catalogue_id: uuid.UUID, *, lock: bool = False
    ) -> GovernanceCatalogue | None:
        stmt = select(GovernanceCatalogue).where(
            GovernanceCatalogue.id == catalogue_id, GovernanceCatalogue.tenant_id == tenant_id
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_catalogue_versions(self, catalogue_id: uuid.UUID) -> list[GovernanceCatalogueVersion]:
        stmt = (
            select(GovernanceCatalogueVersion)
            .where(GovernanceCatalogueVersion.catalogue_id == catalogue_id)
            .order_by(GovernanceCatalogueVersion.version)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_catalogue_version(self, catalogue_id: uuid.UUID, version: int) -> GovernanceCatalogueVersion | None:
        stmt = select(GovernanceCatalogueVersion).where(
            GovernanceCatalogueVersion.catalogue_id == catalogue_id, GovernanceCatalogueVersion.version == version
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()
