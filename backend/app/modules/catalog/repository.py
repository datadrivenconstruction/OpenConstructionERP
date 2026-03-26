"""Catalog resource data access layer.

All database queries for catalog resources live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import Float, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import CatalogResource


class CatalogResourceRepository:
    """Data access for CatalogResource model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, resource_id: uuid.UUID) -> CatalogResource | None:
        """Get catalog resource by ID."""
        return await self.session.get(CatalogResource, resource_id)

    async def get_by_code(self, resource_code: str) -> CatalogResource | None:
        """Get catalog resource by unique code."""
        stmt = select(CatalogResource).where(CatalogResource.resource_code == resource_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        q: str | None = None,
        resource_type: str | None = None,
        category: str | None = None,
        region: str | None = None,
        unit: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CatalogResource], int]:
        """Search catalog resources with multiple filters.

        Args:
            q: Text search on resource_code and name.
            resource_type: Filter by type (exact match).
            category: Filter by category (exact match).
            region: Filter by region (exact match).
            unit: Filter by unit (exact match).
            min_price: Minimum base_price (inclusive).
            max_price: Maximum base_price (inclusive).
            offset: Number of items to skip.
            limit: Maximum number of items to return.

        Returns:
            Tuple of (items, total_count).
        """
        base = select(CatalogResource).where(CatalogResource.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            base = base.where(
                CatalogResource.resource_code.ilike(pattern)
                | CatalogResource.name.ilike(pattern)
            )

        if resource_type:
            base = base.where(CatalogResource.resource_type == resource_type)

        if category:
            base = base.where(CatalogResource.category == category)

        if region:
            base = base.where(CatalogResource.region == region)

        if unit:
            base = base.where(CatalogResource.unit == unit)

        if min_price is not None:
            base = base.where(cast(CatalogResource.base_price, Float) >= min_price)

        if max_price is not None:
            base = base.where(cast(CatalogResource.base_price, Float) <= max_price)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch (ordered by usage_count desc for relevance)
        stmt = base.order_by(CatalogResource.usage_count.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, resource: CatalogResource) -> CatalogResource:
        """Insert a new catalog resource."""
        self.session.add(resource)
        await self.session.flush()
        return resource

    async def bulk_create(self, resources: list[CatalogResource]) -> list[CatalogResource]:
        """Insert multiple catalog resources at once."""
        self.session.add_all(resources)
        await self.session.flush()
        return resources

    async def update_fields(self, resource_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a catalog resource."""
        stmt = (
            update(CatalogResource)
            .where(CatalogResource.id == resource_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def count(self) -> int:
        """Total number of active catalog resources."""
        stmt = select(func.count()).select_from(
            select(CatalogResource).where(CatalogResource.is_active.is_(True)).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def stats_by_type(self) -> list[tuple[str, int]]:
        """Count of active resources grouped by resource_type."""
        stmt = (
            select(CatalogResource.resource_type, func.count())
            .where(CatalogResource.is_active.is_(True))
            .group_by(CatalogResource.resource_type)
            .order_by(func.count().desc())
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def stats_by_category(self) -> list[tuple[str, int]]:
        """Count of active resources grouped by category."""
        stmt = (
            select(CatalogResource.category, func.count())
            .where(CatalogResource.is_active.is_(True))
            .group_by(CatalogResource.category)
            .order_by(func.count().desc())
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def stats_by_region(self) -> list[dict[str, object]]:
        """Count of active resources grouped by region (non-null only)."""
        stmt = (
            select(CatalogResource.region, func.count())
            .where(
                CatalogResource.is_active.is_(True),
                CatalogResource.region.isnot(None),
            )
            .group_by(CatalogResource.region)
            .order_by(func.count().desc())
        )
        result = await self.session.execute(stmt)
        return [{"region": region, "count": count} for region, count in result.all()]

    async def delete_by_region(self, region: str) -> int:
        """Hard-delete all resources for a given region. Returns count deleted."""
        from sqlalchemy import delete as sa_delete

        count_stmt = (
            select(func.count())
            .select_from(CatalogResource)
            .where(CatalogResource.region == region)
        )
        count = (await self.session.execute(count_stmt)).scalar_one()

        if count > 0:
            del_stmt = sa_delete(CatalogResource).where(CatalogResource.region == region)
            await self.session.execute(del_stmt)

        return count

    async def delete_by_source(self, source: str) -> int:
        """Delete all resources from a given source. Returns count deleted."""
        stmt = (
            select(func.count())
            .select_from(CatalogResource)
            .where(CatalogResource.source == source)
        )
        count = (await self.session.execute(stmt)).scalar_one()

        if count > 0:
            del_stmt = (
                update(CatalogResource)
                .where(CatalogResource.source == source)
                .values(is_active=False)
            )
            await self.session.execute(del_stmt)

        return count
