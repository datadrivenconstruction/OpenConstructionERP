# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Risk Register data access layer.

All database queries for risk items live here.
No business logic - pure data access.
"""

import re
import uuid

from sqlalchemy import Float, case, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.risk.models import RiskItem

# Numeric values are kept as strings in these columns, so they are cast for
# ordering; "" on legacy rows sorts as 0 instead of failing the cast.
_NUMERIC_SORT = ("risk_score", "probability", "impact_cost", "response_cost")
_PLAIN_SORT = (
    "created_at",
    "updated_at",
    "code",
    "title",
    "status",
    "category",
    "impact_severity",
    "impact_schedule_days",
    "probability_score",
    "risk_tier",
)


def _order_clause(sort_by: str | None, sort_order: str) -> ClauseElement:
    """ORDER BY for the register list; unknown fields fall back to newest first."""
    desc = sort_order == "desc"
    if sort_by in _NUMERIC_SORT:
        col = getattr(RiskItem, sort_by)
        key = case((col == "", 0), else_=cast(col, Float))
    elif sort_by in _PLAIN_SORT:
        key = getattr(RiskItem, sort_by)
    else:
        return RiskItem.created_at.desc()
    return key.desc() if desc else key.asc()


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

        order_clause = _order_clause(sort_by, sort_order)

        stmt = base.order_by(order_clause).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: RiskItem) -> RiskItem:
        """Insert a new risk item.

        ``refresh()`` after ``flush()`` so server-side defaults
        (``id``, ``created_at``, ``updated_at``, ``metadata``) are
        populated before the row is serialized - otherwise the create
        response path triggers an implicit lazy-load. Mirrors the
        repository convention used across the codebase.
        """
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update_fields(self, risk_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a risk item."""
        stmt = update(RiskItem).where(RiskItem.id == risk_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(RiskItem, risk_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, risk_id: uuid.UUID) -> None:
        """Hard delete a risk item."""
        item = await self.get_by_id(risk_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def next_code(self, project_id: uuid.UUID) -> str:
        """Next ``R-NNN`` code: one past the highest used, so deletes never cause a repeat."""
        codes = (await self.session.execute(select(RiskItem.code).where(RiskItem.project_id == project_id))).scalars()
        highest = 0
        for code in codes:
            match = re.fullmatch(r"R-(\d+)", code or "")
            if match:
                highest = max(highest, int(match.group(1)))
        return f"R-{highest + 1:03d}"

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """Count risk items for a project (used for code generation)."""
        stmt = select(func.count()).select_from(select(RiskItem).where(RiskItem.project_id == project_id).subquery())
        return (await self.session.execute(stmt)).scalar_one()

    async def all_for_project(self, project_id: uuid.UUID) -> list[RiskItem]:
        """Return all risk items for a project (used for summary/matrix)."""
        stmt = select(RiskItem).where(RiskItem.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
