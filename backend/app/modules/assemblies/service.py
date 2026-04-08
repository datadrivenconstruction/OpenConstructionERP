"""Assembly service — business logic for Assemblies & Calculations management.

Stateless service layer. Handles:
- Assembly CRUD with search and filtering
- Component management with auto-calculated totals
- Assembly total rate computation (sum of components * bid_factor)
- Cloning assemblies across projects
- Applying an assembly to a BOQ as a new position
- Event publishing for inter-module communication
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.assemblies.models import Assembly, Component
from app.modules.assemblies.repository import AssemblyRepository, ComponentRepository
from app.modules.assemblies.schemas import (
    ApplyToBOQRequest,
    AssemblyCreate,
    AssemblyUpdate,
    AssemblyWithComponents,
    CloneAssemblyRequest,
    ComponentCreate,
    ComponentResponse,
    ComponentUpdate,
)

logger = logging.getLogger(__name__)


def _compute_component_total(factor: float, quantity: float, unit_cost: float) -> str:
    """Compute component total as string: factor * quantity * unit_cost.

    Uses Decimal for precision, returns string for SQLite-safe storage.
    """
    try:
        f = Decimal(str(factor))
        q = Decimal(str(quantity))
        c = Decimal(str(unit_cost))
        return str(f * q * c)
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


def _sum_component_totals(components: list[Component]) -> Decimal:
    """Sum all component totals as Decimal."""
    total = Decimal("0")
    for comp in components:
        try:
            total += Decimal(str(comp.total))
        except (InvalidOperation, ValueError):
            pass
    return total


def _compute_assembly_total(components: list[Component], bid_factor: str) -> str:
    """Compute assembly total_rate = sum(component totals) * bid_factor."""
    try:
        subtotal = _sum_component_totals(components)
        bf = Decimal(str(bid_factor))
        return str(subtotal * bf)
    except (InvalidOperation, ValueError):
        return "0"


class AssemblyService:
    """Business logic for Assembly and Component operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assembly_repo = AssemblyRepository(session)
        self.component_repo = ComponentRepository(session)

    # ── Assembly operations ────────────────────────────────────────────────

    async def create_assembly(self, data: AssemblyCreate, owner_id: str | None = None) -> Assembly:
        """Create a new assembly.

        Args:
            data: Assembly creation payload.
            owner_id: ID of the user creating the assembly.

        Returns:
            The newly created Assembly.

        Raises:
            HTTPException 409 if code already exists.
        """
        existing = await self.assembly_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Assembly with code '{data.code}' already exists",
            )

        assembly = Assembly(
            code=data.code,
            name=data.name,
            description=data.description,
            unit=data.unit,
            category=data.category,
            classification=data.classification,
            total_rate="0",
            currency=data.currency,
            bid_factor=str(data.bid_factor),
            regional_factors=data.regional_factors,
            is_template=data.is_template,
            project_id=data.project_id,
            owner_id=uuid.UUID(owner_id) if owner_id else None,
            metadata_=data.metadata,
        )
        assembly = await self.assembly_repo.create(assembly)

        await _safe_publish(
            "assemblies.assembly.created",
            {"assembly_id": str(assembly.id), "code": data.code},
            source_module="oe_assemblies",
        )

        logger.info("Assembly created: %s (%s)", data.code, data.name)
        return assembly

    async def get_assembly(self, assembly_id: uuid.UUID) -> Assembly:
        """Get assembly by ID. Raises 404 if not found."""
        assembly = await self.assembly_repo.get_by_id(assembly_id)
        if assembly is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assembly not found",
            )
        return assembly

    async def search_assemblies(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        unit: str | None = None,
        project_id: uuid.UUID | None = None,
        is_template: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Assembly], int]:
        """Search assemblies with filters and pagination."""
        return await self.assembly_repo.list_all(
            q=q,
            category=category,
            unit=unit,
            project_id=project_id,
            is_template=is_template,
            offset=offset,
            limit=limit,
        )

    async def update_assembly(self, assembly_id: uuid.UUID, data: AssemblyUpdate) -> Assembly:
        """Update assembly metadata fields.

        Args:
            assembly_id: Target assembly identifier.
            data: Partial update payload.

        Returns:
            Updated Assembly.

        Raises:
            HTTPException 404 if assembly not found.
            HTTPException 409 if new code conflicts with an existing assembly.
        """
        assembly = await self.get_assembly(assembly_id)

        fields = data.model_dump(exclude_unset=True)

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Convert bid_factor float to string for storage
        if "bid_factor" in fields:
            fields["bid_factor"] = str(fields["bid_factor"])

        # Check code uniqueness if code is being changed
        if "code" in fields and fields["code"] != assembly.code:
            existing = await self.assembly_repo.get_by_code(fields["code"])
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Assembly with code '{fields['code']}' already exists",
                )

        if fields:
            await self.assembly_repo.update_fields(assembly_id, **fields)

            # Recalculate total if bid_factor changed
            if "bid_factor" in fields:
                await self._recalculate_total(assembly_id)

            await _safe_publish(
                "assemblies.assembly.updated",
                {"assembly_id": str(assembly_id), "fields": list(fields.keys())},
                source_module="oe_assemblies",
            )

        return await self.get_assembly(assembly_id)

    async def delete_assembly(self, assembly_id: uuid.UUID) -> None:
        """Delete an assembly and all its components.

        Raises HTTPException 404 if not found.
        """
        assembly = await self.get_assembly(assembly_id)

        await self.assembly_repo.delete(assembly_id)

        await _safe_publish(
            "assemblies.assembly.deleted",
            {"assembly_id": str(assembly_id), "code": assembly.code},
            source_module="oe_assemblies",
        )

        logger.info("Assembly deleted: %s (%s)", assembly.code, assembly_id)

    # ── Component operations ───────────────────────────────────────────────

    async def add_component(self, assembly_id: uuid.UUID, data: ComponentCreate) -> Component:
        """Add a new component to an assembly.

        Auto-computes total = factor * quantity * unit_cost, then recalculates
        the assembly total_rate.

        Args:
            assembly_id: Parent assembly identifier.
            data: Component creation payload.

        Returns:
            The newly created Component.

        Raises:
            HTTPException 404 if assembly not found.
        """
        await self.get_assembly(assembly_id)

        total = _compute_component_total(data.factor, data.quantity, data.unit_cost)
        max_order = await self.component_repo.get_max_sort_order(assembly_id)

        component = Component(
            assembly_id=assembly_id,
            cost_item_id=data.cost_item_id,
            description=data.description,
            factor=str(data.factor),
            quantity=str(data.quantity),
            unit=data.unit,
            unit_cost=str(data.unit_cost),
            total=total,
            sort_order=max_order + 1,
        )
        component = await self.component_repo.create(component)

        # Recalculate assembly total
        await self._recalculate_total(assembly_id)

        # Re-fetch component to avoid MissingGreenlet after expire_all
        refreshed = await self.component_repo.get_by_id(component.id)
        if refreshed is not None:
            component = refreshed

        await _safe_publish(
            "assemblies.component.created",
            {
                "component_id": str(component.id),
                "assembly_id": str(assembly_id),
            },
            source_module="oe_assemblies",
        )

        logger.info("Component added to assembly %s: %s", assembly_id, data.description[:40])
        return component

    async def update_component(
        self, assembly_id: uuid.UUID, component_id: uuid.UUID, data: ComponentUpdate
    ) -> Component:
        """Update a component and recalculate totals.

        Args:
            assembly_id: Parent assembly identifier (for validation).
            component_id: Target component identifier.
            data: Partial update payload.

        Returns:
            Updated Component.

        Raises:
            HTTPException 404 if component not found or does not belong to assembly.
        """
        component = await self.component_repo.get_by_id(component_id)
        if component is None or component.assembly_id != assembly_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not found in this assembly",
            )

        fields = data.model_dump(exclude_unset=True)

        # Convert float values to strings for storage
        if "factor" in fields:
            fields["factor"] = str(fields["factor"])
        if "quantity" in fields:
            fields["quantity"] = str(fields["quantity"])
        if "unit_cost" in fields:
            fields["unit_cost"] = str(fields["unit_cost"])

        # Map 'metadata' key to the model's 'metadata_' column
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recalculate component total if any numeric field changed
        new_factor = fields.get("factor", component.factor)
        new_quantity = fields.get("quantity", component.quantity)
        new_unit_cost = fields.get("unit_cost", component.unit_cost)
        fields["total"] = _compute_component_total(
            _str_to_float(new_factor),
            _str_to_float(new_quantity),
            _str_to_float(new_unit_cost),
        )

        if fields:
            await self.component_repo.update_fields(component_id, **fields)

            await _safe_publish(
                "assemblies.component.updated",
                {
                    "component_id": str(component_id),
                    "assembly_id": str(assembly_id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_assemblies",
            )

        # Recalculate assembly total
        await self._recalculate_total(assembly_id)

        updated = await self.component_repo.get_by_id(component_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not found after update",
            )
        return updated

    async def delete_component(self, assembly_id: uuid.UUID, component_id: uuid.UUID) -> None:
        """Delete a component and recalculate assembly total.

        Raises HTTPException 404 if not found or does not belong to assembly.
        """
        component = await self.component_repo.get_by_id(component_id)
        if component is None or component.assembly_id != assembly_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not found in this assembly",
            )

        await self.component_repo.delete(component_id)

        # Recalculate assembly total after removal
        await self._recalculate_total(assembly_id)

        await _safe_publish(
            "assemblies.component.deleted",
            {
                "component_id": str(component_id),
                "assembly_id": str(assembly_id),
            },
            source_module="oe_assemblies",
        )

        logger.info("Component deleted: %s from assembly %s", component_id, assembly_id)

    # ── Composite operations ───────────────────────────────────────────────

    async def get_assembly_with_components(self, assembly_id: uuid.UUID) -> AssemblyWithComponents:
        """Get an assembly with all its components and computed total.

        Args:
            assembly_id: Target assembly identifier.

        Returns:
            AssemblyWithComponents including components list and computed_total.

        Raises:
            HTTPException 404 if assembly not found.
        """
        assembly = await self.get_assembly(assembly_id)
        components = await self.component_repo.list_for_assembly(assembly_id)

        component_responses = []
        for comp in components:
            component_responses.append(
                ComponentResponse(
                    id=comp.id,
                    assembly_id=comp.assembly_id,
                    cost_item_id=comp.cost_item_id,
                    description=comp.description,
                    factor=_str_to_float(comp.factor),
                    quantity=_str_to_float(comp.quantity),
                    unit=comp.unit,
                    unit_cost=_str_to_float(comp.unit_cost),
                    total=_str_to_float(comp.total),
                    sort_order=comp.sort_order,
                    metadata_=comp.metadata_,
                    created_at=comp.created_at,
                    updated_at=comp.updated_at,
                )
            )

        computed_total = _str_to_float(assembly.total_rate)

        return AssemblyWithComponents(
            id=assembly.id,
            code=assembly.code,
            name=assembly.name,
            description=assembly.description,
            unit=assembly.unit,
            category=assembly.category,
            classification=assembly.classification,
            total_rate=_str_to_float(assembly.total_rate),
            currency=assembly.currency,
            bid_factor=_str_to_float(assembly.bid_factor),
            regional_factors=assembly.regional_factors,
            is_template=assembly.is_template,
            project_id=assembly.project_id,
            owner_id=assembly.owner_id,
            is_active=assembly.is_active,
            metadata_=assembly.metadata_,
            created_at=assembly.created_at,
            updated_at=assembly.updated_at,
            components=component_responses,
            computed_total=computed_total,
        )

    async def _recalculate_total(self, assembly_id: uuid.UUID) -> None:
        """Recalculate assembly total_rate from all component totals * bid_factor.

        Fetches the assembly and all its components, sums component totals,
        multiplies by bid_factor, and persists the result.
        """
        assembly = await self.assembly_repo.get_by_id(assembly_id)
        if assembly is None:
            return

        components = await self.component_repo.list_for_assembly(assembly_id)
        new_total = _compute_assembly_total(components, assembly.bid_factor)

        await self.assembly_repo.update_fields(assembly_id, total_rate=new_total)

    async def apply_to_boq(self, assembly_id: uuid.UUID, data: ApplyToBOQRequest) -> object:
        """Apply an assembly to a BOQ by creating a new position.

        The position's unit_rate is set to the assembly total_rate (optionally
        adjusted by a regional factor), and the source is marked as "assembly".

        Args:
            assembly_id: Source assembly identifier.
            data: Request with boq_id, quantity, optional ordinal and region.

        Returns:
            The newly created BOQ Position.

        Raises:
            HTTPException 404 if assembly or BOQ not found.
        """
        from app.modules.boq.schemas import PositionCreate
        from app.modules.boq.service import BOQService

        assembly = await self.get_assembly(assembly_id)

        # Determine effective rate (apply regional factor if provided)
        try:
            base_rate = Decimal(str(assembly.total_rate))
        except (InvalidOperation, ValueError):
            base_rate = Decimal("0")

        if data.region and data.region in assembly.regional_factors:
            try:
                factor = Decimal(str(assembly.regional_factors[data.region]))
                effective_rate = base_rate * factor
            except (InvalidOperation, ValueError):
                effective_rate = base_rate
        else:
            effective_rate = base_rate

        ordinal = data.ordinal if data.ordinal else f"ASM-{assembly.code}"

        # Build resource list from assembly components
        resources = []
        for comp in assembly.components:
            res_type = "material"  # default
            desc_lower = (comp.description or "").lower()
            if any(w in desc_lower for w in ("labor", "worker", "crew", "работ", "труд")):
                res_type = "labor"
            elif any(w in desc_lower for w in ("equip", "machine", "crane", "техник", "механ")):
                res_type = "equipment"
            elif any(w in desc_lower for w in ("operator", "оператор", "машинист")):
                res_type = "operator"

            resources.append(
                {
                    "name": comp.description or "",
                    "code": "",
                    "type": res_type,
                    "unit": comp.unit or "",
                    "quantity": _str_to_float(comp.quantity),
                    "unit_rate": _str_to_float(comp.unit_cost),
                    "total": _str_to_float(comp.total),
                }
            )

        position_data = PositionCreate(
            boq_id=data.boq_id,
            ordinal=ordinal,
            description=f"{assembly.name} [{assembly.code}]",
            unit=assembly.unit,
            quantity=data.quantity,
            unit_rate=float(effective_rate),
            classification=assembly.classification,
            source="assembly",
            metadata={
                "assembly_id": str(assembly_id),
                "assembly_code": assembly.code,
                "bid_factor": assembly.bid_factor,
                "region": data.region,
                "currency": assembly.currency,
                "resources": resources,
            },
        )

        boq_service = BOQService(self.session)
        position = await boq_service.add_position(position_data)

        await _safe_publish(
            "assemblies.applied_to_boq",
            {
                "assembly_id": str(assembly_id),
                "boq_id": str(data.boq_id),
                "position_id": str(position.id),
            },
            source_module="oe_assemblies",
        )

        logger.info(
            "Assembly %s applied to BOQ %s as position %s",
            assembly.code,
            data.boq_id,
            position.id,
        )
        return position

    async def clone_assembly(
        self,
        assembly_id: uuid.UUID,
        data: CloneAssemblyRequest,
        owner_id: str | None = None,
    ) -> Assembly:
        """Clone an assembly, optionally assigning it to a different project.

        Args:
            assembly_id: Source assembly to clone.
            data: Clone options (new_code, project_id).
            owner_id: ID of the user performing the clone.

        Returns:
            The newly created (cloned) Assembly with all components.

        Raises:
            HTTPException 404 if source assembly not found.
            HTTPException 409 if new_code conflicts with an existing assembly.
        """
        source = await self.get_assembly(assembly_id)
        components = await self.component_repo.list_for_assembly(assembly_id)

        new_code = data.new_code or f"{source.code}-copy"

        # Check code uniqueness
        existing = await self.assembly_repo.get_by_code(new_code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Assembly with code '{new_code}' already exists",
            )

        cloned = Assembly(
            code=new_code,
            name=source.name,
            description=source.description,
            unit=source.unit,
            category=source.category,
            classification=dict(source.classification) if source.classification else {},
            total_rate=source.total_rate,
            currency=source.currency,
            bid_factor=source.bid_factor,
            regional_factors=(dict(source.regional_factors) if source.regional_factors else {}),
            is_template=source.is_template,
            project_id=data.project_id if data.project_id else source.project_id,
            owner_id=uuid.UUID(owner_id) if owner_id else source.owner_id,
            metadata_=dict(source.metadata_) if source.metadata_ else {},
        )
        cloned = await self.assembly_repo.create(cloned)

        # Clone all components
        cloned_components = []
        for comp in components:
            cloned_comp = Component(
                assembly_id=cloned.id,
                cost_item_id=comp.cost_item_id,
                description=comp.description,
                factor=comp.factor,
                quantity=comp.quantity,
                unit=comp.unit,
                unit_cost=comp.unit_cost,
                total=comp.total,
                sort_order=comp.sort_order,
                metadata_=dict(comp.metadata_) if comp.metadata_ else {},
            )
            cloned_components.append(cloned_comp)

        if cloned_components:
            await self.component_repo.bulk_create(cloned_components)

        await _safe_publish(
            "assemblies.assembly.cloned",
            {
                "source_id": str(assembly_id),
                "clone_id": str(cloned.id),
                "code": new_code,
            },
            source_module="oe_assemblies",
        )

        logger.info("Assembly cloned: %s → %s", source.code, new_code)
        return cloned

    # ── Stats ─────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, object]:
        """Return aggregated assembly statistics.

        Returns total count, category breakdown, and most-used assemblies
        (determined by the number of BOQ positions referencing each assembly).
        """
        from sqlalchemy import func as sqlfunc

        # All active assemblies with components loaded
        assemblies, total = await self.assembly_repo.list_all(offset=0, limit=10000)

        by_category: dict[str, int] = {}
        for asm in assemblies:
            cat = asm.category or "uncategorized"
            by_category[cat] = by_category.get(cat, 0) + 1

        # Try to get usage counts from BOQ positions that reference assemblies
        most_used: list[dict[str, object]] = []
        try:
            from sqlalchemy import select as sa_select

            from app.modules.boq.models import BOQPosition

            stmt = (
                sa_select(Assembly.name, sqlfunc.count(BOQPosition.id).label("cnt"))
                .join(BOQPosition, BOQPosition.assembly_id == Assembly.id)
                .where(Assembly.is_active.is_(True))
                .group_by(Assembly.id, Assembly.name)
                .order_by(sqlfunc.count(BOQPosition.id).desc())
                .limit(5)
            )
            rows = (await self.session.execute(stmt)).all()
            most_used = [{"name": row[0], "usage_count": row[1]} for row in rows]
        except Exception:
            # BOQ module may not exist or table not yet created
            logger.debug("Could not compute assembly usage stats from BOQ positions")

        return {
            "total": total,
            "most_used": most_used,
            "by_category": by_category,
        }
