"""Requirements & Quality Gates data access layer.

All database queries for requirement sets, requirements, and gate results
live here. No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.requirements.models import GateResult, Requirement, RequirementSet


class RequirementSetRepository:
    """Data access for RequirementSet models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, set_id: uuid.UUID) -> RequirementSet | None:
        """Get requirement set by ID (with eagerly loaded relationships)."""
        return await self.session.get(RequirementSet, set_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[RequirementSet], int]:
        """List requirement sets for a project with pagination."""
        base = select(RequirementSet).where(RequirementSet.project_id == project_id)
        if status is not None:
            base = base.where(RequirementSet.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.order_by(RequirementSet.created_at.desc()).offset(offset).limit(limit)
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: RequirementSet) -> RequirementSet:
        """Insert a new requirement set."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, set_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a requirement set."""
        stmt = (
            update(RequirementSet)
            .where(RequirementSet.id == set_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, set_id: uuid.UUID) -> None:
        """Hard delete a requirement set and all related data (cascade)."""
        item = await self.get_by_id(set_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """Count requirement sets for a project."""
        stmt = select(func.count()).select_from(
            select(RequirementSet)
            .where(RequirementSet.project_id == project_id)
            .subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()


class RequirementRepository:
    """Data access for Requirement (EAC triplet) models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, req_id: uuid.UUID) -> Requirement | None:
        """Get requirement by ID."""
        return await self.session.get(Requirement, req_id)

    async def list_for_set(
        self,
        set_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Requirement], int]:
        """List requirements for a set with pagination."""
        base = select(Requirement).where(Requirement.requirement_set_id == set_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Requirement.created_at).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def all_for_set(self, set_id: uuid.UUID) -> list[Requirement]:
        """Return all requirements for a set (used for gate validation)."""
        stmt = (
            select(Requirement)
            .where(Requirement.requirement_set_id == set_id)
            .order_by(Requirement.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def all_for_project(self, project_id: uuid.UUID) -> list[Requirement]:
        """Return all requirements across all sets for a project."""
        stmt = (
            select(Requirement)
            .join(RequirementSet)
            .where(RequirementSet.project_id == project_id)
            .order_by(Requirement.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, item: Requirement) -> Requirement:
        """Insert a new requirement."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def bulk_create(self, items: list[Requirement]) -> list[Requirement]:
        """Insert multiple requirements."""
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def update_fields(self, req_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a requirement."""
        stmt = (
            update(Requirement)
            .where(Requirement.id == req_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, req_id: uuid.UUID) -> None:
        """Hard delete a requirement."""
        item = await self.get_by_id(req_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def search(
        self,
        query: str,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Requirement], int]:
        """Text search in entity/attribute/constraint_value fields."""
        pattern = f"%{query}%"
        base = (
            select(Requirement)
            .join(RequirementSet)
            .where(RequirementSet.project_id == project_id)
            .where(
                or_(
                    Requirement.entity.ilike(pattern),
                    Requirement.attribute.ilike(pattern),
                    Requirement.constraint_value.ilike(pattern),
                )
            )
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Requirement.created_at).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """Count all requirements across all sets for a project."""
        stmt = select(func.count()).select_from(
            select(Requirement)
            .join(RequirementSet)
            .where(RequirementSet.project_id == project_id)
            .subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()


class GateResultRepository:
    """Data access for GateResult models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, result_id: uuid.UUID) -> GateResult | None:
        """Get gate result by ID."""
        return await self.session.get(GateResult, result_id)

    async def list_for_set(self, set_id: uuid.UUID) -> list[GateResult]:
        """List all gate results for a requirement set."""
        stmt = (
            select(GateResult)
            .where(GateResult.requirement_set_id == set_id)
            .order_by(GateResult.gate_number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_gate(
        self,
        set_id: uuid.UUID,
        gate_number: int,
    ) -> GateResult | None:
        """Get the most recent result for a specific gate."""
        stmt = (
            select(GateResult)
            .where(
                GateResult.requirement_set_id == set_id,
                GateResult.gate_number == gate_number,
            )
            .order_by(GateResult.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, item: GateResult) -> GateResult:
        """Insert a new gate result."""
        self.session.add(item)
        await self.session.flush()
        return item
