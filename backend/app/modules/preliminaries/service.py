# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Preliminaries service - business logic for the general-conditions estimator.

Stateless service layer over the pure engine
(:mod:`app.modules.preliminaries.prelim_math`). Responsibilities:

* Preliminaries item CRUD scoped to a project.
* The per-category and grand-total roll-up returned by the summary endpoint.

The service never commits - it flushes and lets the request-scoped session
commit, matching every peer module. Data access is inline (a single table, no
cross-module joins) so the module stays self-contained.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.preliminaries import prelim_math
from app.modules.preliminaries.models import PrelimItem
from app.modules.preliminaries.schemas import PrelimItemCreate, PrelimItemUpdate

logger = logging.getLogger(__name__)


class PreliminariesService:
    """Business logic for project preliminaries items."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_item(self, data: PrelimItemCreate) -> PrelimItem:
        """Create a preliminaries item on a project."""
        item = PrelimItem(
            project_id=data.project_id,
            label=data.label or "",
            category=prelim_math.normalize_category(data.category),
            item_type=prelim_math.normalize_item_type(data.item_type),
            rate_per_period=data.rate_per_period,
            periods=data.periods,
            fixed_amount=data.fixed_amount,
            sort_order=data.sort_order,
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        logger.info("Preliminaries item created: %s for project %s", item.id, data.project_id)
        return item

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_item(self, item_id: uuid.UUID) -> PrelimItem:
        """Get a preliminaries item by id (404 if missing)."""
        item = await self.session.get(PrelimItem, item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This preliminaries item does not exist or has been removed. Refresh the list and try again.",
            )
        return item

    async def list_items(self, project_id: uuid.UUID) -> list[PrelimItem]:
        """List a project's preliminaries items in display order."""
        stmt = (
            select(PrelimItem)
            .where(PrelimItem.project_id == project_id)
            .order_by(PrelimItem.sort_order, PrelimItem.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_summary(self, project_id: uuid.UUID) -> prelim_math.PrelimRollup:
        """Roll a project's preliminaries up per category and into a grand total."""
        items = await self.list_items(project_id)
        return prelim_math.rollup_by_category([self.to_mapping(item) for item in items])

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_item(self, item_id: uuid.UUID, data: PrelimItemUpdate) -> PrelimItem:
        """Update a preliminaries item's fields."""
        item = await self.get_item(item_id)
        fields = data.model_dump(exclude_unset=True)
        if "category" in fields and fields["category"] is not None:
            fields["category"] = prelim_math.normalize_category(fields["category"])
        if "item_type" in fields and fields["item_type"] is not None:
            fields["item_type"] = prelim_math.normalize_item_type(fields["item_type"])
        for key, value in fields.items():
            if value is not None:
                setattr(item, key, value)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_item(self, item_id: uuid.UUID) -> None:
        """Delete a preliminaries item."""
        item = await self.get_item(item_id)
        await self.session.delete(item)
        await self.session.flush()
        logger.info("Preliminaries item deleted: %s", item_id)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def to_mapping(item: PrelimItem) -> dict[str, Any]:
        """Render an item as a plain dict for the pure engine."""
        return {
            "id": str(item.id),
            "label": item.label or "",
            "category": item.category or prelim_math.DEFAULT_CATEGORY,
            "item_type": item.item_type or prelim_math.TIME_RELATED,
            "rate_per_period": item.rate_per_period,
            "periods": item.periods,
            "fixed_amount": item.fixed_amount,
        }
