# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data-access layer for the site-prep module.

Thin async repositories for the two site-prep tables: the per-project
mobilisation plan and the readiness items. Every query is project-scoped so a
foreign project id can never slip through, mirroring the IDOR defence already
present in the service layer.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_prep.models import SitePrepItem, SitePrepPlan


class SitePrepPlanRepository:
    """Data access for :class:`SitePrepPlan` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project(self, project_id: uuid.UUID) -> SitePrepPlan | None:
        """Return the plan for a project, or ``None`` if none exists yet.

        Args:
            project_id: The owning project id.

        Returns:
            The plan row or ``None``.
        """
        stmt = select(SitePrepPlan).where(SitePrepPlan.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, plan: SitePrepPlan) -> SitePrepPlan:
        """Persist a new plan and flush to obtain its generated id.

        Args:
            plan: A transient ``SitePrepPlan`` instance.

        Returns:
            The same instance after flush (id populated).
        """
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def plan_exists_for_project(self, project_id: uuid.UUID, plan_id: uuid.UUID) -> bool:
        """Check whether ``plan_id`` belongs to ``project_id``.

        Used by the service layer to prevent an item from being attached to
        another project's plan (the IDOR guard).

        Args:
            project_id: The project the caller is authorised on.
            plan_id: The plan id provided on create / update.

        Returns:
            ``True`` when the plan exists and belongs to the project.
        """
        stmt = select(SitePrepPlan.id).where(
            SitePrepPlan.id == plan_id,
            SitePrepPlan.project_id == project_id,
        )
        return (await self.session.execute(stmt)).first() is not None


class SitePrepItemRepository:
    """Data access for :class:`SitePrepItem` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        status: str | None = None,
    ) -> list[SitePrepItem]:
        """List items for a project with optional category / status filters.

        Args:
            project_id: The owning project id.
            category: If provided, restrict to this mobilisation category.
            status: If provided, restrict to this item status.

        Returns:
            Items ordered by ``sort_order`` then ``created_at``.
        """
        stmt = select(SitePrepItem).where(SitePrepItem.project_id == project_id)
        if category is not None:
            stmt = stmt.where(SitePrepItem.category == category)
        if status is not None:
            stmt = stmt.where(SitePrepItem.status == status)
        stmt = stmt.order_by(SitePrepItem.sort_order.asc(), SitePrepItem.created_at.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_id_and_project(
        self,
        item_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> SitePrepItem | None:
        """Load one item scoped to its project (``None`` if absent or foreign).

        Args:
            item_id: The item primary key.
            project_id: The owning project id.

        Returns:
            The item row or ``None``.
        """
        stmt = select(SitePrepItem).where(
            SitePrepItem.id == item_id,
            SitePrepItem.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, item: SitePrepItem) -> SitePrepItem:
        """Persist a new item and flush to obtain its generated id.

        Args:
            item: A transient ``SitePrepItem`` instance.

        Returns:
            The same instance after flush (id populated).
        """
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete(self, item: SitePrepItem) -> None:
        """Delete an item from the session.

        Args:
            item: The persistent item to remove.
        """
        await self.session.delete(item)
        await self.session.flush()
