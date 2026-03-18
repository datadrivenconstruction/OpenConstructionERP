"""Cost item data access layer.

All database queries for cost items live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.models import CostItem


class CostItemRepository:
    """Data access for CostItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> CostItem | None:
        """Get cost item by ID."""
        return await self.session.get(CostItem, item_id)

    async def get_by_code(self, code: str) -> CostItem | None:
        """Get cost item by unique code."""
        stmt = select(CostItem).where(CostItem.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        q: str | None = None,
    ) -> tuple[list[CostItem], int]:
        """List cost items with pagination and optional text search.

        Args:
            offset: Number of items to skip.
            limit: Maximum number of items to return.
            q: Optional text search query (LIKE on code and description).

        Returns:
            Tuple of (items, total_count).
        """
        base = select(CostItem).where(CostItem.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            base = base.where(
                CostItem.code.ilike(pattern) | CostItem.description.ilike(pattern)
            )

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(CostItem.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: CostItem) -> CostItem:
        """Insert a new cost item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a cost item."""
        stmt = update(CostItem).where(CostItem.id == item_id).values(**fields)
        await self.session.execute(stmt)

    async def bulk_create(self, items: list[CostItem]) -> list[CostItem]:
        """Insert multiple cost items at once."""
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def count(self) -> int:
        """Total number of active cost items."""
        stmt = select(func.count()).select_from(
            select(CostItem).where(CostItem.is_active.is_(True)).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def search(
        self,
        *,
        q: str | None = None,
        unit: str | None = None,
        source: str | None = None,
        min_rate: float | None = None,
        max_rate: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CostItem], int]:
        """Advanced search with multiple filters.

        Args:
            q: Text search on code and description.
            unit: Filter by unit (exact match).
            source: Filter by source (exact match).
            min_rate: Minimum rate (inclusive). Compares as float via CAST.
            max_rate: Maximum rate (inclusive). Compares as float via CAST.
            offset: Number of items to skip.
            limit: Maximum number of items to return.

        Returns:
            Tuple of (items, total_count).
        """
        from sqlalchemy import Float

        base = select(CostItem).where(CostItem.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            base = base.where(
                CostItem.code.ilike(pattern) | CostItem.description.ilike(pattern)
            )

        if unit:
            base = base.where(CostItem.unit == unit)

        if source:
            base = base.where(CostItem.source == source)

        if min_rate is not None:
            base = base.where(cast(CostItem.rate, Float) >= min_rate)

        if max_rate is not None:
            base = base.where(cast(CostItem.rate, Float) <= max_rate)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(CostItem.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total
