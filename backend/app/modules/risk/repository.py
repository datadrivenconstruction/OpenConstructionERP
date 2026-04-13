"""Risk Register data access layer.

All database queries for risk items live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.risk.models import RiskItem


class RiskRepository:
    """Data access for RiskItem models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, risk_id: uuid.UUID) -> RiskItem | None:
        """Get risk item by ID."""
        return await self.session.get(RiskItem, risk_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[RiskItem], int]:
        """List risk items for a project with pagination and filters."""
        base = select(RiskItem).where(RiskItem.project_id == project_id)
        if status is not None:
            base = base.where(RiskItem.status == status)
        if category is not None:
            base = base.where(RiskItem.category == category)
        if severity is not None:
            base = base.where(RiskItem.impact_severity == severity)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Sorting
        order_clause = None
        if sort_by:
            col = getattr(RiskItem, sort_by, None)
            if col is not None:
                order_clause = col.desc() if sort_order == "desc" else col.asc()
        if order_clause is None:
            order_clause = RiskItem.created_at.desc()

        stmt = base.order_by(order_clause).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: RiskItem) -> RiskItem:
        """Insert a new risk item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, risk_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a risk item."""
        stmt = update(RiskItem).where(RiskItem.id == risk_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, risk_id: uuid.UUID) -> None:
        """Hard delete a risk item."""
        item = await self.get_by_id(risk_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """Count risk items for a project (used for code generation)."""
        stmt = select(func.count()).select_from(select(RiskItem).where(RiskItem.project_id == project_id).subquery())
        return (await self.session.execute(stmt)).scalar_one()

    async def all_for_project(self, project_id: uuid.UUID) -> list[RiskItem]:
        """Return all risk items for a project (used for summary/matrix)."""
        stmt = select(RiskItem).where(RiskItem.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
