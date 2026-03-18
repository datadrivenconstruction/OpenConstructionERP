"""BOQ service — business logic for Bill of Quantities management.

Stateless service layer. Handles:
- BOQ CRUD with project scoping
- Position management with auto-calculated totals
- Section (header row) management
- Markup/overhead CRUD and calculation
- Structured BOQ retrieval with sections, subtotals, and markups
- Default markup template application per region
- Grand total computation
- Event publishing for inter-module communication
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.repository import BOQRepository, MarkupRepository, PositionRepository
from app.modules.boq.schemas import (
    BOQCreate,
    BOQUpdate,
    BOQWithPositions,
    BOQWithSections,
    MarkupCalculated,
    MarkupCreate,
    MarkupResponse,
    MarkupUpdate,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
    SectionCreate,
    SectionResponse,
)

logger = logging.getLogger(__name__)


# ── Regional markup templates ────────────────────────────────────────────────

DEFAULT_MARKUP_TEMPLATES: dict[str, list[dict[str, object]]] = {
    "DACH": [
        {
            "name": "Baustellengemeinkosten (BGK)",
            "category": "overhead",
            "percentage": "8.0",
            "sort_order": 0,
        },
        {
            "name": "Allgemeine Geschäftskosten (AGK)",
            "category": "overhead",
            "percentage": "5.0",
            "sort_order": 1,
        },
        {
            "name": "Wagnis und Gewinn (W&G)",
            "category": "profit",
            "percentage": "3.0",
            "sort_order": 2,
        },
    ],
    "UK": [
        {
            "name": "Preliminaries",
            "category": "overhead",
            "percentage": "12.0",
            "sort_order": 0,
        },
        {
            "name": "Overheads & Profit (OH&P)",
            "category": "profit",
            "percentage": "6.0",
            "sort_order": 1,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "sort_order": 2,
        },
    ],
    "US": [
        {
            "name": "General Conditions",
            "category": "overhead",
            "percentage": "10.0",
            "sort_order": 0,
        },
        {
            "name": "Overheads & Profit (OH&P)",
            "category": "profit",
            "percentage": "8.0",
            "sort_order": 1,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "sort_order": 2,
        },
        {
            "name": "Escalation",
            "category": "contingency",
            "percentage": "3.0",
            "sort_order": 3,
        },
    ],
    "RU": [
        {
            "name": "Накладные расходы",
            "category": "overhead",
            "percentage": "15.0",
            "sort_order": 0,
        },
        {
            "name": "Сметная прибыль",
            "category": "profit",
            "percentage": "8.0",
            "sort_order": 1,
        },
        {
            "name": "НДС",
            "category": "tax",
            "percentage": "20.0",
            "sort_order": 2,
        },
    ],
    "GULF": [
        {
            "name": "Overheads & Profit (OH&P)",
            "category": "profit",
            "percentage": "10.0",
            "sort_order": 0,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "sort_order": 1,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "5.0",
            "sort_order": 2,
        },
    ],
    "DEFAULT": [
        {
            "name": "Overhead",
            "category": "overhead",
            "percentage": "10.0",
            "sort_order": 0,
        },
        {
            "name": "Profit",
            "category": "profit",
            "percentage": "5.0",
            "sort_order": 1,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "sort_order": 2,
        },
    ],
}


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


def _is_section(position: Position) -> bool:
    """Determine whether a position is a section header.

    A section is a top-level position (parent_id is None) whose unit is empty
    or the sentinel value ``"section"`` and whose quantity and unit_rate are
    both zero.  This distinguishes section headers from real line items that
    happen to have no parent.
    """
    if position.parent_id is not None:
        return False
    unit = (position.unit or "").strip().lower()
    qty = _str_to_float(position.quantity)
    rate = _str_to_float(position.unit_rate)
    return unit in ("", "section") and qty == 0.0 and rate == 0.0


def _build_position_response(pos: Position) -> PositionResponse:
    """Build a PositionResponse from a Position ORM instance."""
    return PositionResponse(
        id=pos.id,
        boq_id=pos.boq_id,
        parent_id=pos.parent_id,
        ordinal=pos.ordinal,
        description=pos.description,
        unit=pos.unit,
        quantity=_str_to_float(pos.quantity),
        unit_rate=_str_to_float(pos.unit_rate),
        total=_str_to_float(pos.total),
        classification=pos.classification,
        source=pos.source,
        confidence=(
            _str_to_float(pos.confidence) if pos.confidence is not None else None
        ),
        cad_element_ids=pos.cad_element_ids,
        validation_status=pos.validation_status,
        metadata_=pos.metadata_,
        sort_order=pos.sort_order,
        created_at=pos.created_at,
        updated_at=pos.updated_at,
    )


def _build_markup_response(markup: BOQMarkup) -> MarkupResponse:
    """Build a MarkupResponse from a BOQMarkup ORM instance."""
    return MarkupResponse(
        id=markup.id,
        boq_id=markup.boq_id,
        name=markup.name,
        markup_type=markup.markup_type,
        category=markup.category,
        percentage=_str_to_float(markup.percentage),
        fixed_amount=_str_to_float(markup.fixed_amount),
        apply_to=markup.apply_to,
        sort_order=markup.sort_order,
        is_active=markup.is_active,
        metadata_=markup.metadata_,
        created_at=markup.created_at,
        updated_at=markup.updated_at,
    )


def _calculate_markup_amounts(
    direct_cost: Decimal,
    markups: list[BOQMarkup],
) -> list[tuple[BOQMarkup, Decimal]]:
    """Compute the dollar amount for each active markup line.

    Args:
        direct_cost: Sum of all position totals.
        markups: Ordered list of BOQMarkup ORM objects.

    Returns:
        List of (markup, computed_amount) tuples preserving input order.
    """
    results: list[tuple[BOQMarkup, Decimal]] = []
    running_sum = Decimal("0")

    for markup in markups:
        if not markup.is_active:
            results.append((markup, Decimal("0")))
            continue

        # Determine the base for calculation
        apply_to = (markup.apply_to or "direct_cost").lower()
        if apply_to == "cumulative":
            base = direct_cost + running_sum
        else:
            # "direct_cost" and "subtotal" both use direct_cost as base
            base = direct_cost

        # Calculate amount based on type
        markup_type = (markup.markup_type or "percentage").lower()
        if markup_type == "percentage":
            pct = Decimal(str(markup.percentage or "0"))
            amount = base * pct / Decimal("100")
        elif markup_type == "fixed":
            amount = Decimal(str(markup.fixed_amount or "0"))
        else:
            # per_unit and unknown types default to zero
            amount = Decimal("0")

        running_sum += amount
        results.append((markup, amount))

    return results


class BOQService:
    """Business logic for BOQ, Position, and Markup operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.boq_repo = BOQRepository(session)
        self.position_repo = PositionRepository(session)
        self.markup_repo = MarkupRepository(session)

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

    async def create_section(
        self, boq_id: uuid.UUID, data: SectionCreate
    ) -> Position:
        """Create a section header row in a BOQ.

        A section is stored as a Position with unit="section", quantity=0,
        unit_rate=0, and parent_id=None.  This distinguishes it from regular
        items.

        Args:
            boq_id: Target BOQ identifier.
            data: Section creation payload (ordinal, description).

        Returns:
            The newly created section (Position).

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
        """
        await self.get_boq(boq_id)

        max_order = await self.position_repo.get_max_sort_order(boq_id)

        section = Position(
            boq_id=boq_id,
            parent_id=None,
            ordinal=data.ordinal,
            description=data.description,
            unit="section",
            quantity="0",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            confidence=None,
            cad_element_ids=[],
            metadata_=data.metadata,
            sort_order=max_order + 1,
        )
        section = await self.position_repo.create(section)

        await event_bus.publish(
            "boq.section.created",
            {
                "section_id": str(section.id),
                "boq_id": str(boq_id),
                "ordinal": data.ordinal,
            },
            source_module="oe_boq",
        )

        logger.info("Section created: %s in BOQ %s", data.ordinal, boq_id)
        return section

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

    # ── Markup operations ─────────────────────────────────────────────────

    async def add_markup(self, boq_id: uuid.UUID, data: MarkupCreate) -> BOQMarkup:
        """Add a markup/overhead line to a BOQ.

        Args:
            boq_id: Target BOQ identifier.
            data: Markup creation payload.

        Returns:
            The newly created BOQMarkup.

        Raises:
            HTTPException 404 if the target BOQ doesn't exist.
        """
        await self.get_boq(boq_id)

        max_order = await self.markup_repo.get_max_sort_order(boq_id)

        markup = BOQMarkup(
            boq_id=boq_id,
            name=data.name,
            markup_type=data.markup_type,
            category=data.category,
            percentage=str(data.percentage),
            fixed_amount=str(data.fixed_amount),
            apply_to=data.apply_to,
            sort_order=data.sort_order if data.sort_order > 0 else max_order + 1,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        markup = await self.markup_repo.create(markup)

        await event_bus.publish(
            "boq.markup.created",
            {
                "markup_id": str(markup.id),
                "boq_id": str(boq_id),
                "name": data.name,
            },
            source_module="oe_boq",
        )

        logger.info("Markup added: %s to BOQ %s", data.name, boq_id)
        return markup

    async def update_markup(
        self, markup_id: uuid.UUID, data: MarkupUpdate
    ) -> BOQMarkup:
        """Update a markup line.

        Args:
            markup_id: Target markup identifier.
            data: Partial update payload.

        Returns:
            Updated BOQMarkup.

        Raises:
            HTTPException 404 if markup not found.
        """
        markup = await self.markup_repo.get_by_id(markup_id)
        if markup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "percentage" in fields:
            fields["percentage"] = str(fields["percentage"])
        if "fixed_amount" in fields:
            fields["fixed_amount"] = str(fields["fixed_amount"])

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.markup_repo.update_fields(markup_id, **fields)

            await event_bus.publish(
                "boq.markup.updated",
                {
                    "markup_id": str(markup_id),
                    "boq_id": str(markup.boq_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_boq",
            )

        # Re-fetch to return fresh data
        updated = await self.markup_repo.get_by_id(markup_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found after update",
            )
        return updated

    async def delete_markup(self, markup_id: uuid.UUID) -> None:
        """Delete a markup line.

        Raises HTTPException 404 if not found.
        """
        markup = await self.markup_repo.get_by_id(markup_id)
        if markup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Markup not found",
            )

        boq_id = str(markup.boq_id)
        await self.markup_repo.delete(markup_id)

        await event_bus.publish(
            "boq.markup.deleted",
            {"markup_id": str(markup_id), "boq_id": boq_id},
            source_module="oe_boq",
        )

        logger.info("Markup deleted: %s from BOQ %s", markup_id, boq_id)

    async def calculate_markups(
        self, boq_id: uuid.UUID
    ) -> tuple[Decimal, list[tuple[BOQMarkup, Decimal]]]:
        """Compute markup amounts for a BOQ based on its direct cost.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            Tuple of (direct_cost, list of (markup, computed_amount)).
        """
        positions, _ = await self.position_repo.list_for_boq(boq_id)
        markups = await self.markup_repo.list_for_boq(boq_id)

        # Direct cost: sum of totals for non-section items only
        direct_cost = Decimal("0")
        for pos in positions:
            if not _is_section(pos):
                direct_cost += Decimal(str(_str_to_float(pos.total)))

        calculated = _calculate_markup_amounts(direct_cost, markups)
        return direct_cost, calculated

    async def apply_default_markups(
        self, boq_id: uuid.UUID, region: str
    ) -> list[BOQMarkup]:
        """Replace all markups on a BOQ with the default template for a region.

        Deletes existing markups and creates the standard set.

        Args:
            boq_id: Target BOQ identifier.
            region: Region code — "DACH", "UK", "US", "RU", "GULF", or "DEFAULT".

        Returns:
            List of newly created BOQMarkup objects.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        await self.get_boq(boq_id)

        # Look up template; fall back to DEFAULT
        region_key = region.upper()
        template = DEFAULT_MARKUP_TEMPLATES.get(
            region_key, DEFAULT_MARKUP_TEMPLATES["DEFAULT"]
        )

        # Remove existing markups
        await self.markup_repo.delete_all_for_boq(boq_id)

        # Create new markups from template
        new_markups: list[BOQMarkup] = []
        for entry in template:
            markup = BOQMarkup(
                boq_id=boq_id,
                name=str(entry["name"]),
                markup_type="percentage",
                category=str(entry["category"]),
                percentage=str(entry["percentage"]),
                fixed_amount="0",
                apply_to="direct_cost",
                sort_order=int(entry["sort_order"]),  # type: ignore[arg-type]
                is_active=True,
                metadata_={},
            )
            new_markups.append(markup)

        created = await self.markup_repo.bulk_create(new_markups)

        await event_bus.publish(
            "boq.markups.defaults_applied",
            {"boq_id": str(boq_id), "region": region_key, "count": len(created)},
            source_module="oe_boq",
        )

        logger.info(
            "Applied %d default markups (%s) to BOQ %s",
            len(created),
            region_key,
            boq_id,
        )
        return created

    # ── Composite reads ───────────────────────────────────────────────────

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

            position_responses.append(_build_position_response(pos))

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

    async def get_boq_structured(self, boq_id: uuid.UUID) -> BOQWithSections:
        """Get a BOQ with sections, subtotals, markups, and computed totals.

        Positions are grouped into sections based on parent_id.  Positions
        without a parent that are not sections themselves appear in the
        top-level ``positions`` list.

        Args:
            boq_id: Target BOQ identifier.

        Returns:
            BOQWithSections with full hierarchical structure.

        Raises:
            HTTPException 404 if BOQ not found.
        """
        boq = await self.get_boq(boq_id)
        all_positions, _ = await self.position_repo.list_for_boq(boq_id)

        # Separate sections from items
        section_map: dict[uuid.UUID, Position] = {}
        children_map: dict[uuid.UUID, list[Position]] = {}
        ungrouped_items: list[Position] = []

        for pos in all_positions:
            if _is_section(pos):
                section_map[pos.id] = pos
                children_map.setdefault(pos.id, [])
            elif pos.parent_id is not None and pos.parent_id in section_map:
                children_map.setdefault(pos.parent_id, []).append(pos)
            elif pos.parent_id is not None:
                # Parent exists but is not a section — still group under parent
                # if parent is in section_map after full scan, handled below
                ungrouped_items.append(pos)
            else:
                ungrouped_items.append(pos)

        # Second pass: items whose parent_id was scanned later
        remaining_ungrouped: list[Position] = []
        for pos in ungrouped_items:
            if pos.parent_id is not None and pos.parent_id in section_map:
                children_map.setdefault(pos.parent_id, []).append(pos)
            else:
                remaining_ungrouped.append(pos)

        # Build section responses
        sections: list[SectionResponse] = []
        direct_cost = Decimal("0")

        for section_id, section_pos in section_map.items():
            child_responses: list[PositionResponse] = []
            subtotal = Decimal("0")
            for child in children_map.get(section_id, []):
                child_responses.append(_build_position_response(child))
                subtotal += Decimal(str(_str_to_float(child.total)))

            sections.append(
                SectionResponse(
                    id=section_pos.id,
                    ordinal=section_pos.ordinal,
                    description=section_pos.description,
                    positions=child_responses,
                    subtotal=float(subtotal),
                )
            )
            direct_cost += subtotal

        # Ungrouped items
        ungrouped_responses: list[PositionResponse] = []
        for pos in remaining_ungrouped:
            if not _is_section(pos):
                ungrouped_responses.append(_build_position_response(pos))
                direct_cost += Decimal(str(_str_to_float(pos.total)))

        # Calculate markups
        markups_orm = await self.markup_repo.list_for_boq(boq_id)
        markup_results = _calculate_markup_amounts(direct_cost, markups_orm)

        markups_calculated: list[MarkupCalculated] = []
        markup_total = Decimal("0")
        for markup_obj, amount in markup_results:
            markups_calculated.append(
                MarkupCalculated(
                    id=markup_obj.id,
                    boq_id=markup_obj.boq_id,
                    name=markup_obj.name,
                    markup_type=markup_obj.markup_type,
                    category=markup_obj.category,
                    percentage=_str_to_float(markup_obj.percentage),
                    fixed_amount=_str_to_float(markup_obj.fixed_amount),
                    apply_to=markup_obj.apply_to,
                    sort_order=markup_obj.sort_order,
                    is_active=markup_obj.is_active,
                    metadata_=markup_obj.metadata_,
                    created_at=markup_obj.created_at,
                    updated_at=markup_obj.updated_at,
                    amount=float(amount),
                )
            )
            markup_total += amount

        net_total = direct_cost + markup_total

        return BOQWithSections(
            id=boq.id,
            project_id=boq.project_id,
            name=boq.name,
            description=boq.description,
            status=boq.status,
            metadata_=boq.metadata_,
            created_at=boq.created_at,
            updated_at=boq.updated_at,
            sections=sections,
            positions=ungrouped_responses,
            direct_cost=float(direct_cost),
            markups=markups_calculated,
            net_total=float(net_total),
            grand_total=float(net_total),
        )
