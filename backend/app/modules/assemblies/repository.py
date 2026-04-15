"""Assembly data access layer.

All database queries for assemblies and components live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import String, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.modules.assemblies.models import Assembly, Component


class AssemblyRepository:
    """Data access for Assembly model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, assembly_id: uuid.UUID) -> Assembly | None:
        """Get assembly by ID without loading components (avoids MissingGreenlet)."""
        stmt = select(Assembly).where(Assembly.id == assembly_id).options(noload(Assembly.components))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_components(self, assembly_id: uuid.UUID) -> Assembly | None:
        """Get assembly by ID with components eagerly loaded."""
        stmt = select(Assembly).where(Assembly.id == assembly_id).options(selectinload(Assembly.components))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Assembly | None:
        """Get assembly by unique code."""
        stmt = select(Assembly).where(Assembly.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        q: str | None = None,
        category: str | None = None,
        unit: str | None = None,
        tag: str | None = None,
        project_id: uuid.UUID | None = None,
        is_template: bool | None = None,
    ) -> tuple[list[Assembly], int]:
        """List assemblies with pagination and optional filters.

        Args:
            offset: Number of items to skip.
            limit: Maximum number of items to return.
            q: Optional text search on code, name, and description.
            category: Filter by category (exact match).
            unit: Filter by unit (exact match).
            tag: Filter by tag (stored in metadata.tags JSON array).
            project_id: Filter by project_id (null = global templates).
            is_template: Filter by template flag.

        Returns:
            Tuple of (assemblies, total_count).
        """
        base = select(Assembly).where(Assembly.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            base = base.where(
                Assembly.code.ilike(pattern) | Assembly.name.ilike(pattern) | Assembly.description.ilike(pattern)
            )

        if category:
            base = base.where(Assembly.category == category)

        if unit:
            base = base.where(Assembly.unit == unit)

        if tag:
            # Filter by tag in metadata JSON — uses LIKE on the JSON string
            # which works for both SQLite and PostgreSQL
            tag_pattern = f"%{tag.strip().lower()}%"
            base = base.where(
                Assembly.metadata_.cast(String).ilike(tag_pattern)
            )

        if project_id is not None:
            base = base.where(Assembly.project_id == project_id)

        if is_template is not None:
            base = base.where(Assembly.is_template.is_(is_template))

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch — skip eager loading of components for list queries
        stmt = (
            base.options(noload(Assembly.components))
            .order_by(Assembly.code)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        assemblies = list(result.scalars().all())

        return assemblies, total

    async def create(self, assembly: Assembly) -> Assembly:
        """Insert a new assembly."""
        self.session.add(assembly)
        await self.session.flush()
        await self.session.refresh(assembly)
        return assembly

    async def update_fields(self, assembly_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an assembly."""
        stmt = update(Assembly).where(Assembly.id == assembly_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete(self, assembly_id: uuid.UUID) -> None:
        """Delete an assembly and all its components (via CASCADE)."""
        stmt = delete(Assembly).where(Assembly.id == assembly_id)
        await self.session.execute(stmt)

    async def count(self) -> int:
        """Total number of active assemblies."""
        stmt = select(func.count()).select_from(select(Assembly).where(Assembly.is_active.is_(True)).subquery())
        return (await self.session.execute(stmt)).scalar_one()


class ComponentRepository:
    """Data access for Component model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, component_id: uuid.UUID) -> Component | None:
        """Get component by ID."""
        stmt = select(Component).where(Component.id == component_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_assembly(
        self,
        assembly_id: uuid.UUID,
    ) -> list[Component]:
        """List components for an assembly ordered by sort_order.

        Args:
            assembly_id: Parent assembly identifier.

        Returns:
            List of components ordered by sort_order.
        """
        stmt = select(Component).where(Component.assembly_id == assembly_id).order_by(Component.sort_order)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, component: Component) -> Component:
        """Insert a new component."""
        self.session.add(component)
        await self.session.flush()
        await self.session.refresh(component)
        return component

    async def bulk_create(self, components: list[Component]) -> list[Component]:
        """Insert multiple components at once."""
        self.session.add_all(components)
        await self.session.flush()
        return components

    async def update_fields(self, component_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a component."""
        stmt = update(Component).where(Component.id == component_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, component_id: uuid.UUID) -> None:
        """Delete a single component."""
        stmt = delete(Component).where(Component.id == component_id)
        await self.session.execute(stmt)

    async def get_max_sort_order(self, assembly_id: uuid.UUID) -> int:
        """Get the highest sort_order for components in an assembly."""
        stmt = select(func.coalesce(func.max(Component.sort_order), -1)).where(Component.assembly_id == assembly_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)
