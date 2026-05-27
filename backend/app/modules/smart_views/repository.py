# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Data access for the Smart Views module."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.smart_views.models import SmartView


class SmartViewRepository:
    """‌⁠‍CRUD + scoped queries for :class:`SmartView` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── SmartView CRUD ──────────────────────────────────────────────

    async def get_by_id(self, view_id: uuid.UUID) -> SmartView | None:
        """Single view by primary key, ``None`` if not found."""
        return await self.session.get(SmartView, view_id)

    async def add(self, view: SmartView) -> SmartView:
        """Persist a new view (caller commits)."""
        self.session.add(view)
        await self.session.flush()
        return view

    async def delete(self, view: SmartView) -> None:
        """Hard-delete a view (caller commits)."""
        await self.session.delete(view)

    async def delete_by_id(self, view_id: uuid.UUID) -> int:
        """Bulk-delete by id without loading the row (caller commits).

        Returns the number of deleted rows.
        """
        stmt = delete(SmartView).where(SmartView.id == view_id)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def list_visible_to_user(
        self,
        *,
        user_id: uuid.UUID,
        accessible_project_ids: list[uuid.UUID],
        scope_type: str | None = None,
        scope_id: uuid.UUID | None = None,
    ) -> list[SmartView]:
        """Return every view the caller is allowed to see.

        Visibility rules — kept here so the service layer does not
        need to re-derive them per request:

        * Every ``user``-scoped view authored by ``user_id``.
        * Every ``project``-scoped view whose ``scope_id`` is in
          ``accessible_project_ids``.
        * Every ``federation``-scoped view: at this layer we do NOT
          attempt to resolve federation→project; the service layer
          short-circuits federation visibility via a separate guard
          (caller passes ``scope_type='federation'`` + ``scope_id``
          when it wants exactly that filter).

        Optional ``scope_type`` / ``scope_id`` narrow the result to a
        single page query (the list endpoint's primary use case).
        """
        clauses = [
            and_(
                SmartView.scope_type == "user",
                SmartView.scope_id == user_id,
            ),
        ]
        if accessible_project_ids:
            clauses.append(
                and_(
                    SmartView.scope_type == "project",
                    SmartView.scope_id.in_(accessible_project_ids),
                )
            )
            # Federation visibility: join through BIMFederation.project_id.
            # Without this, federation-scoped views never list (issue #103
            # mirror — they existed in DB but were invisible to owners).
            from app.modules.bim_hub.models import BIMFederation

            fed_subq = (
                select(BIMFederation.id).where(BIMFederation.project_id.in_(accessible_project_ids)).scalar_subquery()
            )
            clauses.append(
                and_(
                    SmartView.scope_type == "federation",
                    SmartView.scope_id.in_(fed_subq),
                )
            )
        visibility = or_(*clauses)

        stmt = select(SmartView).where(visibility)
        if scope_type is not None:
            stmt = stmt.where(SmartView.scope_type == scope_type)
        if scope_id is not None:
            stmt = stmt.where(SmartView.scope_id == scope_id)
        stmt = stmt.order_by(SmartView.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    # ── BIM element feed (for the evaluator) ────────────────────────

    async def elements_for_model(self, model_id: uuid.UUID) -> list[BIMElement]:
        """Return every element of a BIM model — no geometry filter.

        Smart Views drive *visibility*, not geometry, so we must keep
        annotation / schedule rows in the result set (otherwise a view
        could never hide them). The bim_hub bulk import caps a model
        at 50 000 elements (``BIMElementBulkImport``) so loading
        without pagination is bounded.
        """
        stmt = select(BIMElement).where(BIMElement.model_id == model_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_model(self, model_id: uuid.UUID) -> BIMModel | None:
        """Look up a BIM model by id — used by the evaluator endpoint."""
        return await self.session.get(BIMModel, model_id)
