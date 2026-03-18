"""BOQ service — business logic for Bill of Quantities management.

Stateless service layer. Handles:
- BOQ CRUD with project scoping
- Position management with auto-calculated totals
- Grand total computation
- Event publishing for inter-module communication
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.boq.models import BOQ, Position
from app.modules.boq.repository import BOQRepository, PositionRepository
from app.modules.boq.schemas import (
    BOQCreate,
    BOQUpdate,
    BOQWithPositions,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
)

logger = logging.getLogger(__name__)


def _compute_total(quantity: float, unit_rate: float) -> str:
    """Compute total as string from quantity and unit_rate.

    Uses Decimal for precision, returns string for SQLite-safe storage.
    """
    try:
        q = Decimal(str(quantity))
        r = Decimal(str(unit_rate))
        return str(q * r)
    except (InvalidOperation, ValueError):
        return "0"


def _str_to_float(value: str | None) -> float:
    """Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


class BOQService:
    """Business logic for BOQ and Position operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.boq_repo = BOQRepository(session)
        self.position_repo = PositionRepository(session)

    # ── BOQ operations ────────────────────────────────────────────────────

    async def create_boq(self, data: BOQCreate) -> BOQ:
        """Create a new Bill of Quantities.

        Args:
            data: BOQ creation payload with project_id, name, description.

        Returns:
            The newly created BOQ.
        """
        boq = BOQ(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            status="draft",
        )
        boq = await self.boq_repo.create(boq)

        await event_bus.publish(
            "boq.boq.created",
            {"boq_id": str(boq.id), "project_id": str(data.project_id)},
            source_module="oe_boq",
        )

        logger.info("BOQ created: %s (project=%s)", boq.name, data.project_id)
        return boq

    async def get_boq(self, boq_id: uuid.UUID) -> BOQ:
        """Get BOQ by ID. Raises 404 if not found."""
        boq = await self.boq_repo.get_by_id(boq_id)
        if boq is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ not found",
            )
        return boq

    async def list_boqs_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQ], int]:
        """List BOQs for a given project with pagination."""
        return await self.boq_repo.list_for_project(
            project_id, offset=offset, limit=limit
        )

    async def update_boq(self, boq_id: uuid.UUID, data: BOQUpdate) -> BOQ:
        """Update BOQ metadata fields.

        Args:
            boq_id: Target BOQ identifier.
            data: Partial update payload.

        Returns:
            Updated BOQ.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)

        fields = data.model_dump(exclude_unset=True)
        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.boq_repo.update_fields(boq_id, **fields)

            await event_bus.publish(
                "boq.boq.updated",
                {"boq_id": str(boq_id), "fields": list(fields.keys())},
                source_module="oe_boq",
            )

        # Re-fetch to return fresh data
        return await self.get_boq(boq_id)

    async def delete_boq(self, boq_id: uuid.UUID) -> None:
        """Delete a BOQ and all its positions.

        Raises HTTPException 404 if not found.
        """
        boq = await self.get_boq(boq_id)
        project_id = str(boq.project_id)

        await self.boq_repo.delete(boq_id)

        await event_bus.publish(
            "boq.boq.deleted",
            {"boq_id": str(boq_id), "project_id": project_id},
            source_module="oe_boq",
        )

        logger.info("BOQ deleted: %s", boq_id)

    # ── Position operations ───────────────────────────────────────────────

    async def add_position(self, data: PositionCreate) -> Position:
        """Add a new position to a BOQ.

        Auto-calculates total = quantity * unit_rate.
        Assigns sort_order to place the position at the end.

        Args:
            data: Position creation payload.

        Returns:
            The newly created position.

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
        """
        # Verify BOQ exists
        await self.get_boq(data.boq_id)

        total = _compute_total(data.quantity, data.unit_rate)
        max_order = await self.position_repo.get_max_sort_order(data.boq_id)

        position = Position(
            boq_id=data.boq_id,
            parent_id=data.parent_id,
            ordinal=data.ordinal,
            description=data.description,
            unit=data.unit,
            quantity=str(data.quantity),
            unit_rate=str(data.unit_rate),
            total=total,
            classification=data.classification,
            source=data.source,
            confidence=str(data.confidence) if data.confidence is not None else None,
            cad_element_ids=data.cad_element_ids,
            metadata_=data.metadata,
            sort_order=max_order + 1,
        )
        position = await self.position_repo.create(position)

        await event_bus.publish(
            "boq.position.created",
            {
                "position_id": str(position.id),
                "boq_id": str(data.boq_id),
                "ordinal": data.ordinal,
            },
            source_module="oe_boq",
        )

        logger.info("Position added: %s to BOQ %s", data.ordinal, data.boq_id)
        return position

    async def update_position(
        self, position_id: uuid.UUID, data: PositionUpdate
    ) -> Position:
        """Update a position and recalculate total if quantity or unit_rate changed.

        Args:
            position_id: Target position identifier.
            data: Partial update payload.

        Returns:
            Updated position.

        Raises:
            HTTPException 404 if position not found.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "quantity" in fields:
            fields["quantity"] = str(fields["quantity"])
        if "unit_rate" in fields:
            fields["unit_rate"] = str(fields["unit_rate"])
        if "confidence" in fields:
            val = fields["confidence"]
            fields["confidence"] = str(val) if val is not None else None

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recalculate total if quantity or unit_rate changed
        new_quantity = fields.get("quantity", position.quantity)
        new_unit_rate = fields.get("unit_rate", position.unit_rate)
        fields["total"] = _compute_total(
            _str_to_float(new_quantity), _str_to_float(new_unit_rate)
        )

        if fields:
            await self.position_repo.update_fields(position_id, **fields)

            await event_bus.publish(
                "boq.position.updated",
                {
                    "position_id": str(position_id),
                    "boq_id": str(position.boq_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_boq",
            )

        # Re-fetch to return fresh data
        updated = await self.position_repo.get_by_id(position_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found after update",
            )
        return updated

    async def delete_position(self, position_id: uuid.UUID) -> None:
        """Delete a position.

        Raises HTTPException 404 if not found.
        """
        position = await self.position_repo.get_by_id(position_id)
        if position is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )

        boq_id = str(position.boq_id)
        await self.position_repo.delete(position_id)

        await event_bus.publish(
            "boq.position.deleted",
            {"position_id": str(position_id), "boq_id": boq_id},
            source_module="oe_boq",
        )

        logger.info("Position deleted: %s from BOQ %s", position_id, boq_id)

    async def get_boq_with_positions(self, boq_id: uuid.UUID) -> BOQWithPositions:
        """Get a BOQ with all its positions and computed grand total.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            BOQWithPositions including positions list and grand_total.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        positions, _ = await self.position_repo.list_for_boq(boq_id)

        # Build position responses with float conversions
        position_responses = []
        grand_total = Decimal("0")

        for pos in positions:
            total_val = _str_to_float(pos.total)
            grand_total += Decimal(str(total_val))

            position_responses.append(
                PositionResponse(
                    id=pos.id,
                    boq_id=pos.boq_id,
                    parent_id=pos.parent_id,
                    ordinal=pos.ordinal,
                    description=pos.description,
                    unit=pos.unit,
                    quantity=_str_to_float(pos.quantity),
                    unit_rate=_str_to_float(pos.unit_rate),
                    total=total_val,
                    classification=pos.classification,
                    source=pos.source,
                    confidence=(
                        _str_to_float(pos.confidence)
                        if pos.confidence is not None
                        else None
                    ),
                    cad_element_ids=pos.cad_element_ids,
                    validation_status=pos.validation_status,
                    metadata_=pos.metadata_,
                    sort_order=pos.sort_order,
                    created_at=pos.created_at,
                    updated_at=pos.updated_at,
                )
            )

        return BOQWithPositions(
            id=boq.id,
            project_id=boq.project_id,
            name=boq.name,
            description=boq.description,
            status=boq.status,
            metadata_=boq.metadata_,
            created_at=boq.created_at,
            updated_at=boq.updated_at,
            positions=position_responses,
            grand_total=float(grand_total),
        )
