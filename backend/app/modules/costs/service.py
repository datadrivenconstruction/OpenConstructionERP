"""Cost item service — business logic for cost database management.

Stateless service layer. Handles:
- Cost item CRUD
- Search with filters
- Bulk import
- Event publishing for cost changes
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.costs.models import CostItem
from app.modules.costs.repository import CostItemRepository
from app.modules.costs.schemas import CostItemCreate, CostItemUpdate, CostSearchQuery

logger = logging.getLogger(__name__)


class CostItemService:
    """Business logic for cost item operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CostItemRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_cost_item(self, data: CostItemCreate) -> CostItem:
        """Create a new cost item.

        Raises HTTPException 409 if code already exists.
        """
        existing = await self.repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cost item with code '{data.code}' already exists",
            )

        item = CostItem(
            code=data.code,
            description=data.description,
            descriptions=data.descriptions,
            unit=data.unit,
            rate=str(data.rate),
            currency=data.currency,
            source=data.source,
            classification=data.classification,
            components=data.components,
            tags=data.tags,
            region=data.region,
            metadata_=data.metadata,
        )
        item = await self.repo.create(item)

        await event_bus.publish(
            "costs.item.created",
            {"item_id": str(item.id), "code": item.code},
            source_module="oe_costs",
        )

        logger.info("Cost item created: %s (%s)", item.code, item.unit)
        return item

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_cost_item(self, item_id: uuid.UUID) -> CostItem:
        """Get cost item by ID. Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )
        return item

    async def search_costs(
        self, query: CostSearchQuery
    ) -> tuple[list[CostItem], int]:
        """Search cost items with filters and pagination."""
        return await self.repo.search(
            q=query.q,
            unit=query.unit,
            source=query.source,
            min_rate=query.min_rate,
            max_rate=query.max_rate,
            offset=query.offset,
            limit=query.limit,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_cost_item(
        self, item_id: uuid.UUID, data: CostItemUpdate
    ) -> CostItem:
        """Update a cost item. Raises 404 if not found, 409 on code conflict."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert rate float → string for storage
        if "rate" in fields and fields["rate"] is not None:
            fields["rate"] = str(fields["rate"])

        # Rename metadata → metadata_ for the ORM column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Check code uniqueness if code is being changed
        if "code" in fields and fields["code"] != item.code:
            existing = await self.repo.get_by_code(fields["code"])
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cost item with code '{fields['code']}' already exists",
                )

        if fields:
            await self.repo.update_fields(item_id, **fields)

        updated = await self.repo.get_by_id(item_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        await event_bus.publish(
            "costs.item.updated",
            {"item_id": str(item_id), "code": updated.code, "fields": list(fields.keys())},
            source_module="oe_costs",
        )

        logger.info("Cost item updated: %s", updated.code)
        return updated

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_cost_item(self, item_id: uuid.UUID) -> None:
        """Soft-delete a cost item (set is_active=False). Raises 404 if not found."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost item not found",
            )

        await self.repo.update_fields(item_id, is_active=False)

        await event_bus.publish(
            "costs.item.deleted",
            {"item_id": str(item_id), "code": item.code},
            source_module="oe_costs",
        )

        logger.info("Cost item deleted (soft): %s", item.code)

    # ── Bulk import ───────────────────────────────────────────────────────

    async def bulk_import(self, items_data: list[CostItemCreate]) -> list[CostItem]:
        """Bulk import cost items. Skips items with duplicate codes.

        Returns the list of successfully created items.
        """
        created: list[CostItem] = []
        skipped_codes: list[str] = []

        for data in items_data:
            existing = await self.repo.get_by_code(data.code)
            if existing is not None:
                skipped_codes.append(data.code)
                continue

            item = CostItem(
                code=data.code,
                description=data.description,
                descriptions=data.descriptions,
                unit=data.unit,
                rate=str(data.rate),
                currency=data.currency,
                source=data.source,
                classification=data.classification,
                components=data.components,
                tags=data.tags,
                region=data.region,
                metadata_=data.metadata,
            )
            created.append(item)

        if created:
            created = await self.repo.bulk_create(created)

        await event_bus.publish(
            "costs.items.bulk_imported",
            {
                "created_count": len(created),
                "skipped_count": len(skipped_codes),
                "skipped_codes": skipped_codes[:20],  # Limit for event payload size
            },
            source_module="oe_costs",
        )

        logger.info(
            "Bulk import: %d created, %d skipped (duplicate codes)",
            len(created),
            len(skipped_codes),
        )
        return created
