# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the project catalogue.

Reads the cost database (``oe_costs_item``), the user catalogues that group it
(``oe_costs_catalog``), the resource catalogue (``oe_catalog_resource``) and
the project's bill lines; writes only ``oe_project_catalogue_item``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_catalogue.models import ProjectCatalogueItem

#: Key under a bill line's ``metadata`` naming the project rate that priced it.
LINK_KEY = "project_catalogue_item_id"


class ProjectCatalogueRepository:
    """Queries behind the project catalogue service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_project(self, project_id: uuid.UUID) -> list[ProjectCatalogueItem]:
        rows = await self.session.execute(
            select(ProjectCatalogueItem)
            .where(ProjectCatalogueItem.project_id == project_id)
            .order_by(ProjectCatalogueItem.code, ProjectCatalogueItem.id)
        )
        return list(rows.scalars().all())

    async def get(self, item_id: uuid.UUID) -> ProjectCatalogueItem | None:
        return await self.session.get(ProjectCatalogueItem, item_id)

    async def add(self, item: ProjectCatalogueItem) -> ProjectCatalogueItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def delete(self, item: ProjectCatalogueItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

    async def flush(self, item: ProjectCatalogueItem) -> ProjectCatalogueItem:
        await self.session.flush()
        await self.session.refresh(item)
        return item

    # ── Sources ─────────────────────────────────────────────────────────────

    async def cost_items(self, ids: Iterable[str]) -> dict[str, Any]:
        from app.modules.costs.models import CostItem  # noqa: PLC0415

        keys = _uuids(ids)
        if not keys:
            return {}
        rows = await self.session.execute(select(CostItem).where(CostItem.id.in_(keys)))
        return {str(r.id): r for r in rows.scalars().all()}

    async def catalog_names(self, ids: Iterable[uuid.UUID | None]) -> dict[str, str]:
        from app.modules.costs.models import CostCatalog  # noqa: PLC0415

        keys = {i for i in ids if i is not None}
        if not keys:
            return {}
        rows = await self.session.execute(select(CostCatalog.id, CostCatalog.name).where(CostCatalog.id.in_(keys)))
        return {str(i): n for i, n in rows.all()}

    async def catalog_resources(self, ids: Iterable[str]) -> dict[str, Any]:
        try:
            from app.modules.catalog.models import CatalogResource  # noqa: PLC0415
        except ImportError:  # pragma: no cover - optional module absent
            return {}
        keys = _uuids(ids)
        if not keys:
            return {}
        rows = await self.session.execute(select(CatalogResource).where(CatalogResource.id.in_(keys)))
        return {str(r.id): r for r in rows.scalars().all()}

    async def search_cost_items(self, q: str, region: str, offset: int, limit: int) -> tuple[list[Any], int]:
        from app.modules.costs.models import CostItem  # noqa: PLC0415

        cond = [CostItem.is_active.is_(True)]
        if q:
            like = f"%{q}%"
            cond.append(or_(CostItem.code.ilike(like), CostItem.description.ilike(like)))
        if region:
            cond.append(CostItem.region == region)
        total = (await self.session.execute(select(func.count()).select_from(CostItem).where(*cond))).scalar_one()
        rows = await self.session.execute(
            select(CostItem).where(*cond).order_by(CostItem.code, CostItem.id).offset(offset).limit(limit)
        )
        return list(rows.scalars().all()), int(total)

    async def search_catalog_resources(self, q: str, region: str, offset: int, limit: int) -> tuple[list[Any], int]:
        try:
            from app.modules.catalog.models import CatalogResource  # noqa: PLC0415
        except ImportError:  # pragma: no cover - optional module absent
            return [], 0
        cond = [CatalogResource.is_active.is_(True)]
        if q:
            like = f"%{q}%"
            cond.append(or_(CatalogResource.resource_code.ilike(like), CatalogResource.name.ilike(like)))
        if region:
            cond.append(CatalogResource.region == region)
        total = (
            await self.session.execute(select(func.count()).select_from(CatalogResource).where(*cond))
        ).scalar_one()
        rows = await self.session.execute(
            select(CatalogResource)
            .where(*cond)
            .order_by(CatalogResource.resource_code, CatalogResource.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows.scalars().all()), int(total)

    # ── Bill lines ──────────────────────────────────────────────────────────

    async def project_positions(self, project_id: uuid.UUID) -> list[tuple[Any, str]]:
        """Every bill line of the project with its bill's name, in bill and sort order."""
        from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

        rows = await self.session.execute(
            select(Position, BOQ.name)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id)
            .order_by(BOQ.name, Position.sort_order, Position.ordinal)
        )
        return [(p, n) for p, n in rows.all()]

    async def position_project(self, position_id: uuid.UUID) -> tuple[Any, uuid.UUID] | None:
        """A bill line and the project its bill belongs to."""
        from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

        row = (
            await self.session.execute(
                select(Position, BOQ.project_id).join(BOQ, BOQ.id == Position.boq_id).where(Position.id == position_id)
            )
        ).first()
        return None if row is None else (row[0], row[1])

    async def project_currency(self, project_id: uuid.UUID) -> str:
        from app.modules.projects.models import Project  # noqa: PLC0415

        value = (await self.session.execute(select(Project.currency).where(Project.id == project_id))).scalar()
        return str(value or "")


def _uuids(ids: Iterable[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for raw in ids:
        try:
            out.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return out


def link_of(metadata: Any) -> str | None:
    """The project rate id a bill line's metadata names, if any."""
    if isinstance(metadata, dict):
        value = metadata.get(LINK_KEY)
        return str(value) if value else None
    return None
