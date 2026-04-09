"""BIM Hub data access layer.

All database queries for BIM models, elements, BOQ links, quantity maps,
and model diffs live here. No business logic — pure data access.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.modules.bim_hub.models import (
    BIMElement,
    BIMModel,
    BIMModelDiff,
    BIMQuantityMap,
    BOQElementLink,
)


class BIMModelRepository:
    """Data access for BIMModel."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, model_id: uuid.UUID) -> BIMModel | None:
        """Get BIM model by ID."""
        return await self.session.get(BIMModel, model_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BIMModel], int]:
        """List BIM models for a project with pagination.

        Elements are NOT loaded in list queries — use get() for a single model
        with elements when needed.
        """
        base = select(BIMModel).where(BIMModel.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(noload(BIMModel.elements))
            .order_by(BIMModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        models = list(result.scalars().all())
        return models, total

    async def create(self, model: BIMModel) -> BIMModel:
        """Insert a new BIM model."""
        self.session.add(model)
        await self.session.flush()
        return model

    async def update_fields(self, model_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a BIM model."""
        stmt = update(BIMModel).where(BIMModel.id == model_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, model_id: uuid.UUID) -> None:
        """Delete a BIM model and all its elements (via CASCADE)."""
        stmt = delete(BIMModel).where(BIMModel.id == model_id)
        await self.session.execute(stmt)

    async def cleanup_stale_processing(
        self,
        project_id: uuid.UUID,
        max_age_hours: int = 1,
    ) -> int:
        """Delete models stuck in 'processing' with 0 elements for longer than max_age_hours.

        Returns the number of models deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        # Find stale models
        find_stmt = select(BIMModel.id).where(
            BIMModel.project_id == project_id,
            BIMModel.status == "processing",
            BIMModel.element_count == 0,
            BIMModel.created_at < cutoff,
        )
        result = await self.session.execute(find_stmt)
        stale_ids = [row[0] for row in result.all()]
        if not stale_ids:
            return 0
        # Delete them
        del_stmt = delete(BIMModel).where(BIMModel.id.in_(stale_ids))
        await self.session.execute(del_stmt)
        return len(stale_ids)


class BIMElementRepository:
    """Data access for BIMElement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, element_id: uuid.UUID) -> BIMElement | None:
        """Get BIM element by ID."""
        return await self.session.get(BIMElement, element_id)

    async def list_for_model(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BIMElement], int]:
        """List elements for a model with optional filters and pagination.

        BOQ links are NOT loaded in list queries to avoid N+1.
        """
        base = select(BIMElement).where(BIMElement.model_id == model_id)

        if element_type is not None:
            base = base.where(BIMElement.element_type == element_type)
        if storey is not None:
            base = base.where(BIMElement.storey == storey)
        if discipline is not None:
            base = base.where(BIMElement.discipline == discipline)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(noload(BIMElement.boq_links))
            .order_by(BIMElement.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        elements = list(result.scalars().all())
        return elements, total

    async def list_by_stable_ids(
        self,
        model_id: uuid.UUID,
        stable_ids: list[str],
    ) -> list[BIMElement]:
        """Get elements by their stable IDs within a model."""
        if not stable_ids:
            return []
        stmt = (
            select(BIMElement)
            .where(BIMElement.model_id == model_id, BIMElement.stable_id.in_(stable_ids))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, element: BIMElement) -> BIMElement:
        """Insert a new BIM element."""
        self.session.add(element)
        await self.session.flush()
        return element

    async def bulk_create(self, elements: list[BIMElement]) -> list[BIMElement]:
        """Insert multiple elements at once."""
        self.session.add_all(elements)
        await self.session.flush()
        return elements

    async def delete_all_for_model(self, model_id: uuid.UUID) -> int:
        """Delete all elements for a model. Returns count deleted."""
        count_stmt = select(func.count()).where(BIMElement.model_id == model_id)
        count = (await self.session.execute(count_stmt)).scalar_one()
        stmt = delete(BIMElement).where(BIMElement.model_id == model_id)
        await self.session.execute(stmt)
        return count


class BOQElementLinkRepository:
    """Data access for BOQElementLink."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, link_id: uuid.UUID) -> BOQElementLink | None:
        """Get a link by ID."""
        return await self.session.get(BOQElementLink, link_id)

    async def list_by_boq_position(
        self,
        boq_position_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all links for a BOQ position."""
        stmt = (
            select(BOQElementLink)
            .where(BOQElementLink.boq_position_id == boq_position_id)
            .order_by(BOQElementLink.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_bim_element(
        self,
        bim_element_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all links for a BIM element."""
        stmt = (
            select(BOQElementLink)
            .where(BOQElementLink.bim_element_id == bim_element_id)
            .order_by(BOQElementLink.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, link: BOQElementLink) -> BOQElementLink:
        """Insert a new BOQ-BIM link."""
        self.session.add(link)
        await self.session.flush()
        return link

    async def delete(self, link_id: uuid.UUID) -> None:
        """Delete a single link."""
        stmt = delete(BOQElementLink).where(BOQElementLink.id == link_id)
        await self.session.execute(stmt)


class BIMQuantityMapRepository:
    """Data access for BIMQuantityMap."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, map_id: uuid.UUID) -> BIMQuantityMap | None:
        """Get a quantity map rule by ID."""
        return await self.session.get(BIMQuantityMap, map_id)

    async def list_active(
        self,
        *,
        project_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
    ) -> list[BIMQuantityMap]:
        """List active quantity map rules, optionally filtered by project/org."""
        base = select(BIMQuantityMap).where(BIMQuantityMap.is_active.is_(True))

        if project_id is not None:
            base = base.where(
                (BIMQuantityMap.project_id == project_id)
                | (BIMQuantityMap.project_id.is_(None))
            )
        if org_id is not None:
            base = base.where(
                (BIMQuantityMap.org_id == org_id)
                | (BIMQuantityMap.org_id.is_(None))
            )

        stmt = base.order_by(BIMQuantityMap.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[BIMQuantityMap], int]:
        """List all quantity map rules with pagination."""
        base = select(BIMQuantityMap)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BIMQuantityMap.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        maps = list(result.scalars().all())
        return maps, total

    async def create(self, qmap: BIMQuantityMap) -> BIMQuantityMap:
        """Insert a new quantity map rule."""
        self.session.add(qmap)
        await self.session.flush()
        return qmap

    async def update_fields(self, map_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a quantity map rule."""
        stmt = update(BIMQuantityMap).where(BIMQuantityMap.id == map_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, map_id: uuid.UUID) -> None:
        """Delete a quantity map rule."""
        stmt = delete(BIMQuantityMap).where(BIMQuantityMap.id == map_id)
        await self.session.execute(stmt)


class BIMModelDiffRepository:
    """Data access for BIMModelDiff."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, diff_id: uuid.UUID) -> BIMModelDiff | None:
        """Get a model diff by ID."""
        return await self.session.get(BIMModelDiff, diff_id)

    async def get_by_pair(
        self,
        old_model_id: uuid.UUID,
        new_model_id: uuid.UUID,
    ) -> BIMModelDiff | None:
        """Get diff by model pair."""
        stmt = select(BIMModelDiff).where(
            BIMModelDiff.old_model_id == old_model_id,
            BIMModelDiff.new_model_id == new_model_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, diff: BIMModelDiff) -> BIMModelDiff:
        """Insert a new model diff."""
        self.session.add(diff)
        await self.session.flush()
        return diff

    async def delete(self, diff_id: uuid.UUID) -> None:
        """Delete a model diff."""
        stmt = delete(BIMModelDiff).where(BIMModelDiff.id == diff_id)
        await self.session.execute(stmt)
