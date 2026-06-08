"""‌⁠‍Assembly service - business logic for Assemblies & Calculations management.

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
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.assemblies.models import Assembly, Component
from app.modules.assemblies.repository import AssemblyRepository, ComponentRepository
from app.modules.assemblies.schemas import (
    ApplyToBOQRequest,
    AssemblyCreate,
    AssemblyExport,
    AssemblyUpdate,
    AssemblyWithComponents,
    CloneAssemblyRequest,
    ComponentCreate,
    ComponentResponse,
    ComponentUpdate,
)

_logger_ev = logging.getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


logger = logging.getLogger(__name__)


# ── Recursion / cycle guard (R7 deep-improve) ──────────────────────────────
# Assemblies can reference other assemblies as components ("composite
# recipes"). A self-reference or a long A→B→C→…→A loop would otherwise
# explode the recursion stack and the response size. We cap depth and
# raise a 400 with a translatable message when the cap is hit or a cycle
# is detected.
MAX_ASSEMBLY_DEPTH: int = 8


class AssemblyCycleError(HTTPException):
    """Raised when assembly nesting cycles or exceeds MAX_ASSEMBLY_DEPTH."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=400, detail=detail)


def _check_assembly_depth(
    assembly_id: uuid.UUID,
    visited: frozenset[uuid.UUID] | None = None,
    depth: int = 0,
) -> frozenset[uuid.UUID]:
    """Guard against cyclic / over-deep assembly composition.

    Raises ``AssemblyCycleError`` (HTTP 400) if ``assembly_id`` is already
    in ``visited`` (cycle), or if ``depth >= MAX_ASSEMBLY_DEPTH`` (nesting
    too deep). Returns the new ``visited`` set on success.
    """
    if visited is None:
        visited = frozenset()
    if assembly_id in visited:
        raise AssemblyCycleError(
            f"Assembly cycle detected involving {assembly_id}",
        )
    if depth >= MAX_ASSEMBLY_DEPTH:
        raise AssemblyCycleError(
            f"Assembly nesting depth exceeds {MAX_ASSEMBLY_DEPTH} levels",
        )
    return visited | {assembly_id}


def _compute_component_total(factor: float, quantity: float, unit_cost: float) -> str:
    """‌⁠‍Compute component total as string: factor * quantity * unit_cost.

    Uses Decimal for precision, returns string for SQLite-safe storage.
    """
    try:
        f = Decimal(str(factor))
        q = Decimal(str(quantity))
        c = Decimal(str(unit_cost))
        return str(f * q * c)
    except (InvalidOperation, ValueError):
        return "0"


def _compute_typed_total(
    *,
    resource_type: str | None,
    factor: float,
    quantity: float,
    unit_cost: float,
    metadata: dict | None,
) -> str:
    """Compute a component total using a type-aware formula.

    The default (unknown / overhead / subcontractor / cost-item rows)
    stays the simple ``factor * quantity * unit_cost`` triple - the
    behaviour every existing assembly already relies on.

    Resource-typed rows take the same triple as a base, then layer the
    industry-standard adjustments on top so a professional estimator
    can express things mainstream estimating and 5D suites let them express:

    * **material**  base × (1 + waste_pct/100)
    * **labor**     ``crew_size`` is a quantity multiplier (already
                    captured in ``quantity``); ``hours`` overrides the
                    quantity if given (kept here for clarity but the FE
                    is encouraged to put hours in ``quantity``); the
                    final cost gets a burden uplift via
                    base × (1 + burden_pct/100).
    * **equipment** base + (rental_days * fuel_cost_per_day) - fuel is
                    additive because it's a separate line on most
                    rental contracts; if both ``rental_days`` and a
                    per-day ``fuel_cost`` are set we add their product.

    Returns a string for SQLite-safe storage. Negative or zero results
    fall through to the unmodified triple - never punish the user with
    a smaller total than the raw inputs imply.
    """
    base_str = _compute_component_total(factor, quantity, unit_cost)
    if not resource_type or not metadata:
        return base_str
    try:
        base = Decimal(base_str)
    except (InvalidOperation, ValueError):
        return base_str

    rt = (resource_type or "").lower()
    try:
        if rt == "material":
            waste = _safe_meta_multiplier(metadata.get("waste_pct"))
            if waste is not None and waste > 0:
                result = base * (Decimal("1") + waste / Decimal("100"))
                if result.is_finite():
                    return str(result)
        elif rt == "labor":
            burden = _safe_meta_multiplier(metadata.get("burden_pct"))
            if burden is not None and burden > 0:
                result = base * (Decimal("1") + burden / Decimal("100"))
                if result.is_finite():
                    return str(result)
        elif rt == "equipment":
            days = _safe_meta_multiplier(metadata.get("rental_days"))
            fuel = _safe_meta_multiplier(metadata.get("fuel_cost"))
            if days is not None and fuel is not None and days > 0 and fuel > 0:
                result = base + days * fuel
                if result.is_finite():
                    return str(result)
    except (InvalidOperation, ValueError):
        return base_str

    return base_str


def _str_to_float(value: str | None) -> float:
    """‌⁠‍Convert a string-stored numeric value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# Upper bound for a metadata multiplier (waste_pct / burden_pct /
# rental_days / fuel_cost). Mirrors ``schemas._NUM_MAX`` - far beyond
# any real estimating value, yet keeps the typed-total product finite.
_META_NUM_MAX = Decimal("1e12")


def _safe_meta_multiplier(raw: object) -> Decimal | None:
    """Coerce a FE-supplied metadata multiplier to a sane Decimal.

    The typed-total formula (``_compute_typed_total``) reads free-form
    ``metadata`` keys (waste_pct / burden_pct / rental_days /
    fuel_cost). Those are NOT covered by the Pydantic ``ge/le/
    allow_inf_nan`` bounds on factor/quantity/unit_cost, so a payload
    like ``{"waste_pct": "Infinity"}`` or ``{"burden_pct": -50}`` would
    otherwise flow straight into ``base * (1 + x/100)`` and persist a
    non-finite / negative total (NEW-ASM-102).

    Returns ``None`` for anything that is not a finite, non-negative,
    in-range number - the caller then treats the multiplier as absent
    (no-op), matching the existing "never punish the user with a
    smaller total than the raw inputs imply" fall-through contract
    rather than raising. Garbage never reaches the stored total.
    """
    if raw is None or isinstance(raw, (bool, dict, list)):
        return None
    try:
        dec = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not dec.is_finite() or dec < 0 or dec > _META_NUM_MAX:
        return None
    return dec


# Upper bound for an imported component numeric - mirrors
# ``schemas._NUM_MAX``. Kept local (no cross-module import) so the
# import path is self-contained; both are 1e12.
_IMPORT_NUM_MAX = Decimal("1e12")


def _parse_import_decimal(raw: object, field: str, idx: int) -> Decimal:
    """Parse one imported component numeric into a finite, non-negative Decimal.

    The export/import round-trip is a core "no vendor lock-in" guarantee,
    so this is intentionally liberal about *shape* (accepts native int /
    float, ASCII-decimal string ``'1.5'``, integer string ``'2'``, and
    the EU locale comma ``'1,5'``) but strict about *validity*: garbage
    (``'abc'``, a nested dict / list), non-finite (NaN / Infinity, or a
    value large enough to overflow), and negatives are rejected with a
    clean HTTP 422 - never an unhandled ``ValueError`` 500.

    Args:
        raw: The raw value pulled from the export payload.
        field: Field name (factor / quantity / unit_cost) for the error.
        idx: Zero-based component index for the error message.

    Returns:
        A finite ``Decimal`` >= 0 and <= ``_IMPORT_NUM_MAX``.

    Raises:
        HTTPException 422 if the value cannot be parsed to a sane number.
    """
    if isinstance(raw, (bool, dict, list)):
        # bool is an int subclass - an explicit True/False is almost
        # certainly a malformed export, not "1".
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"components[{idx}].{field}: expected a number, got {type(raw).__name__}",
        )
    try:
        if isinstance(raw, (int, float)):
            dec = Decimal(str(raw))
        else:
            text = str(raw).strip()
            if not text:
                raise InvalidOperation
            # EU locale: "1.234,56" → "1234.56"; bare "1,5" → "1.5".
            if "," in text and "." in text:
                text = text.replace(".", "").replace(",", ".")
            elif "," in text:
                text = text.replace(",", ".")
            dec = Decimal(text)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"components[{idx}].{field}: '{raw}' is not a valid number",
        ) from exc

    if not dec.is_finite():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"components[{idx}].{field}: non-finite values are not allowed",
        )
    if dec < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"components[{idx}].{field}: must be >= 0",
        )
    if dec > _IMPORT_NUM_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"components[{idx}].{field}: exceeds the maximum of {_IMPORT_NUM_MAX:e}",
        )
    return dec


def _sum_component_totals(components: list[Component]) -> Decimal:
    """Sum all component totals as Decimal.

    ``Decimal("Infinity")`` / ``Decimal("NaN")`` parse WITHOUT raising,
    so a single component carrying a non-finite stored ``total`` (e.g.
    written by a legacy snapshot or an older code path) would otherwise
    poison the whole subtotal and ultimately persist ``Infinity`` /
    ``NaN`` into ``Assembly.total_rate`` (NEW-ASM-104). Skip any
    non-finite component total instead of letting it propagate.
    """
    total = Decimal("0")
    for comp in components:
        try:
            val = Decimal(str(comp.total))
        except (InvalidOperation, ValueError):
            continue
        if not val.is_finite():
            continue
        total += val
    return total


def _compute_assembly_total(components: list[Component], bid_factor: str) -> str:
    """Compute assembly total_rate = sum(component totals) * bid_factor.

    Hardened (NEW-ASM-104): a non-finite ``bid_factor`` string (or a
    product that overflows to ``Infinity``) is rejected to "0" rather
    than persisted, so ``Assembly.total_rate`` is always a finite
    number the API can serialise.
    """
    try:
        subtotal = _sum_component_totals(components)
        bf = Decimal(str(bid_factor))
        if not bf.is_finite():
            return "0"
        result = subtotal * bf
        if not result.is_finite():
            return "0"
        return str(result)
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
        tag: str | None = None,
        project_id: uuid.UUID | None = None,
        is_template: bool | None = None,
        offset: int = 0,
        limit: int = 50,
        owner_id: uuid.UUID | None = None,
    ) -> tuple[list[Assembly], int]:
        """Search assemblies with filters and pagination.

        ``owner_id`` scopes the result to a single tenant; pass ``None``
        for an admin / unscoped listing. The list and stats endpoints
        thread the caller's id through so a VIEWER cannot enumerate other
        tenants' assemblies (the per-item endpoints already 404 on a
        non-owner - this closes the matching leak in the collection).
        """
        return await self.assembly_repo.list_all(
            q=q,
            category=category,
            unit=unit,
            tag=tag,
            project_id=project_id,
            is_template=is_template,
            offset=offset,
            limit=limit,
            owner_id=owner_id,
        )

    async def update_assembly(
        self,
        assembly_id: uuid.UUID,
        data: AssemblyUpdate,
        *,
        caller_user_id: str | None = None,
        caller_is_admin: bool = False,
    ) -> Assembly:
        """Update assembly metadata fields.

        Args:
            assembly_id: Target assembly identifier.
            data: Partial update payload.
            caller_user_id: ID of the calling user (for project re-parent
                ownership check - NEW-ASM-106).
            caller_is_admin: When True, skip the cross-tenant project
                ownership check (admins manage global templates).

        Returns:
            Updated Assembly.

        Raises:
            HTTPException 404 if assembly not found.
            HTTPException 404 if a new ``project_id`` refers to a project
                the caller does not own (returned as 404 not 403 to keep
                the existence-oracle closed - matches the rest of this
                module).
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

        # NEW-ASM-106 - verify the caller owns the *new* project before
        # re-parenting. Without this, an authenticated owner of assembly
        # X could PATCH ``{"project_id": "<other-tenant's-project-id>"}``
        # and pollute the other tenant's per-project assembly listing
        # (``GET /assemblies/?project_id=...``). The owner_id of the
        # assembly is unchanged - but the project filter is keyed off
        # ``project_id``, so the assembly would show up under another
        # tenant's project. 404 (not 403) - see docstring.
        if (
            "project_id" in fields
            and fields["project_id"] is not None
            and not caller_is_admin
            and caller_user_id is not None
        ):
            new_pid = fields["project_id"]
            current_pid = assembly.project_id
            if str(new_pid) != str(current_pid or ""):
                from app.modules.projects.repository import ProjectRepository

                project_repo = ProjectRepository(self.session)
                target_project = await project_repo.get_by_id(new_pid)
                if target_project is None or str(getattr(target_project, "owner_id", "")) != str(caller_user_id):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=translate("errors.project_not_found", locale=get_locale()),
                    )

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

        # Resolve aliased fields: name→description, unit_rate→unit_cost
        description = data.get_description()
        unit_cost = data.get_unit_cost()

        # Merge any FE-supplied metadata (waste_pct / burden_pct / crew /
        # rental_days / fuel_cost / vendor / productivity) before total
        # computation - the typed formula reads these fields to apply
        # type-specific adjustments (waste uplift on material, burden on
        # labor, fuel add-on on equipment).
        comp_metadata: dict = dict(data.metadata or {})
        # Mirror the column into metadata too so the legacy reader path
        # (BOQ apply, AI generate previews, exports) keeps working
        # without conditionals.
        if data.resource_type:
            comp_metadata.setdefault("resource_type", data.resource_type)

        total = _compute_typed_total(
            resource_type=data.resource_type,
            factor=data.factor,
            quantity=data.quantity,
            unit_cost=unit_cost,
            metadata=comp_metadata,
        )
        max_order = await self.component_repo.get_max_sort_order(assembly_id)

        component = Component(
            assembly_id=assembly_id,
            cost_item_id=data.cost_item_id,
            catalog_resource_id=data.catalog_resource_id,
            description=description,
            resource_type=data.resource_type,
            factor=str(data.factor),
            quantity=str(data.quantity),
            unit=data.unit,
            unit_cost=str(unit_cost),
            total=total,
            sort_order=max_order + 1,
            metadata_=comp_metadata,
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

        # Recalculate component total using the typed formula so that
        # changes to waste_pct / burden_pct / fuel_cost / resource_type
        # immediately reflect in the rolled-up assembly total without a
        # separate save round-trip.
        new_factor = fields.get("factor", component.factor)
        new_quantity = fields.get("quantity", component.quantity)
        new_unit_cost = fields.get("unit_cost", component.unit_cost)
        new_resource_type = fields.get("resource_type", component.resource_type)
        new_metadata = fields.get("metadata_", component.metadata_) or {}
        fields["total"] = _compute_typed_total(
            resource_type=new_resource_type,
            factor=_str_to_float(new_factor),
            quantity=_str_to_float(new_quantity),
            unit_cost=_str_to_float(new_unit_cost),
            metadata=new_metadata if isinstance(new_metadata, dict) else {},
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
                    catalog_resource_id=comp.catalog_resource_id,
                    description=comp.description,
                    resource_type=comp.resource_type,
                    factor=_str_to_float(comp.factor),
                    quantity=_str_to_float(comp.quantity),
                    unit=comp.unit,
                    # v3 §10 - money as Decimal; Pydantic coerces str→Decimal
                    unit_cost=Decimal(str(comp.unit_cost or "0")),
                    total=Decimal(str(comp.total or "0")),
                    sort_order=comp.sort_order,
                    metadata=comp.metadata_ or {},
                    created_at=comp.created_at,
                    updated_at=comp.updated_at,
                )
            )

        computed_total = _str_to_float(assembly.total_rate)
        metadata = assembly.metadata_ or {}
        tags: list[str] = metadata.get("tags", []) if isinstance(metadata, dict) else []

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
            tags=tags,
            metadata=metadata,
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
        from app.modules.boq.repository import BOQRepository
        from app.modules.boq.schemas import PositionCreate
        from app.modules.boq.service import BOQService
        from app.modules.projects.repository import ProjectRepository

        assembly = await self.get_assembly(assembly_id)

        # ── Cross-currency handling (ASM-006, Issue #128) ───────────────
        # An assembly priced in a currency other than the target
        # project's base used to be hard-refused with a 409 - which made
        # every foreign-currency assembly impossible to place, even when
        # the project HAD an FX rate configured for that currency. We now
        # mirror how foreign-currency *resources* already behave: convert
        # via the project's ``fx_rates`` when a rate exists; otherwise let
        # it through with a visible, non-blocking ``currency_mismatch``
        # flag - never silent corruption, never a dead end for the user.
        from app.modules.boq.service import _project_fx_map

        currency_warning: dict | None = None
        currency_converted: dict | None = None
        fx_multiplier = Decimal("1")
        asm_currency = (assembly.currency or "").strip().upper()
        project = None
        project_currency = ""
        try:
            boq_repo = BOQRepository(self.session)
            target_boq = await boq_repo.get_by_id(data.boq_id)
            if target_boq is not None:
                project_repo = ProjectRepository(self.session)
                project = await project_repo.get_by_id(target_boq.project_id)
                if project is not None:
                    project_currency = (project.currency or "").strip().upper()
        except Exception:
            # Never let the currency lookup itself break apply-to-boq;
            # absence of currency data simply skips conversion.
            project = None
            project_currency = ""

        if asm_currency and project_currency and asm_currency != project_currency:
            # Project ``fx_rates`` projected to {CODE: "<base units per 1
            # unit of foreign currency>"} - same convention the BOQ
            # resource rollup uses, so foreign→base is multiplication.
            fx_map = _project_fx_map(project)
            raw_rate = fx_map.get(asm_currency)
            conv_rate: Decimal | None = None
            if raw_rate is not None:
                try:
                    candidate = Decimal(str(raw_rate))
                    if candidate.is_finite() and candidate > 0:
                        conv_rate = candidate
                except (InvalidOperation, ValueError):
                    conv_rate = None

            if conv_rate is not None:
                # Convert the whole assembly into the project's currency.
                fx_multiplier = conv_rate
                currency_converted = {
                    "type": "currency_converted",
                    "from": asm_currency,
                    "to": project_currency,
                    "rate": str(conv_rate),
                    "message": (
                        f"Assembly priced in {asm_currency} was converted "
                        f"to {project_currency} at {conv_rate} "
                        f"({asm_currency}->{project_currency})."
                    ),
                }
            else:
                # No FX rate configured for this currency - proceed
                # anyway. The legacy hard 409 trapped the user with no
                # UI escape hatch (Issue #128). Flag it loudly so the
                # un-converted foreign value is visible, not silent.
                currency_warning = {
                    "type": "currency_mismatch",
                    "assembly_currency": asm_currency,
                    "project_currency": project_currency,
                    "message": (
                        f"Unit rate is in {asm_currency} but the project "
                        f"is {project_currency}, and no FX rate is "
                        f"configured for {asm_currency}; the value was "
                        f"kept in {asm_currency} (no conversion). Add an "
                        f"FX rate in Project Settings to convert it."
                    ),
                }

        # Determine effective rate (apply regional factor if provided).
        # NEW-ASM-105 / ASM-007 - ``Decimal("Infinity")`` and
        # ``Decimal("NaN")`` parse WITHOUT raising, so a poisoned
        # ``regional_factors`` value (or a legacy assembly whose stored
        # ``total_rate`` is non-finite) would otherwise propagate through
        # the float() cast below into ``PositionCreate.unit_rate`` -
        # whose schema only enforces ``ge=0.0`` and happily accepts
        # ``inf``. The result is a BOQ position with a non-finite
        # ``unit_rate`` that serialises as ``null`` and corrupts every
        # downstream rollup. Reject any non-finite intermediate to 0.
        try:
            base_rate = Decimal(str(assembly.total_rate))
        except (InvalidOperation, ValueError):
            base_rate = Decimal("0")
        if not base_rate.is_finite() or base_rate < 0:
            base_rate = Decimal("0")

        if data.region and data.region in assembly.regional_factors:
            try:
                factor = Decimal(str(assembly.regional_factors[data.region]))
            except (InvalidOperation, ValueError):
                factor = Decimal("1")
            if not factor.is_finite() or factor < 0:
                # Garbage stored factor - silently skip (matches the
                # existing fall-through contract for an absent region).
                effective_rate = base_rate
            else:
                effective_rate = base_rate * factor
                if not effective_rate.is_finite():
                    effective_rate = base_rate
        else:
            effective_rate = base_rate

        # Issue #128 - when the assembly is priced in a foreign currency
        # for which the project has an FX rate, fold the conversion into
        # the rate (and the component money fields below) so the BOQ
        # position lands in the project's base currency. ``fx_multiplier``
        # is Decimal("1") when no conversion applies, so this is a no-op
        # for same-currency / unconfigured-rate paths.
        effective_rate = effective_rate * fx_multiplier
        if not effective_rate.is_finite() or effective_rate < 0:
            # Final guard - the product can also overflow when both
            # ``base_rate`` and ``fx_multiplier`` sit near the upper
            # bound. Land at 0 rather than poison the BOQ.
            effective_rate = Decimal("0")

        ordinal = data.ordinal if data.ordinal else f"ASM-{assembly.code}"

        # Fetch components separately to avoid MissingGreenlet (noload on get_assembly)
        components = await self.component_repo.list_for_assembly(assembly_id)

        # Build resource list from assembly components.
        # Trust the new ``resource_type`` column; only fall back to
        # description heuristics for legacy rows that the v2940
        # back-fill couldn't classify.
        def _infer_legacy(desc: str) -> str:
            d = (desc or "").lower()
            if any(w in d for w in ("labor", "worker", "crew", "работ", "труд")):
                return "labor"
            if any(w in d for w in ("equip", "machine", "crane", "техник", "механ")):
                return "equipment"
            if any(w in d for w in ("operator", "оператор", "машинист")):
                return "operator"
            return "material"

        resources = []
        # Roll the component totals up by type so the BOQ position can
        # carry a structured M/L/E split (and a UI on /boq can render
        # "60% Mat · 30% Lab · 10% Eq" without re-walking the components).
        breakdown_totals: dict[str, Decimal] = {}
        # Issue #128 - scale each component's money fields by the same FX
        # multiplier as the rate so the resource breakdown stays
        # consistent with the converted unit_rate.
        fx_mult_f = float(fx_multiplier)
        for comp in components:
            res_type = comp.resource_type or _infer_legacy(comp.description or "")
            comp_total = _str_to_float(comp.total) * fx_mult_f
            try:
                breakdown_totals[res_type] = breakdown_totals.get(res_type, Decimal("0")) + Decimal(str(comp_total))
            except (InvalidOperation, ValueError):
                pass

            resources.append(
                {
                    "name": comp.description or "",
                    "code": "",
                    "type": res_type,
                    "unit": comp.unit or "",
                    "quantity": _str_to_float(comp.quantity),
                    "unit_rate": _str_to_float(comp.unit_cost) * fx_mult_f,
                    "total": comp_total,
                    # Pass through useful metadata (vendor, waste_pct,
                    # crew_size, …) so downstream consumers can inspect
                    # the cost driver detail without joining back to
                    # the source assembly.
                    "metadata": dict(comp.metadata_) if comp.metadata_ else {},
                }
            )

        # Compute the breakdown payload - totals per type plus
        # percentages of the rolled subtotal.
        subtotal = sum(breakdown_totals.values(), Decimal("0"))
        resource_breakdown: dict[str, dict[str, float]] = {}
        if subtotal > 0:
            for rtype, ttl in breakdown_totals.items():
                resource_breakdown[rtype] = {
                    "total": float(ttl),
                    "pct": float((ttl / subtotal) * Decimal("100")),
                }

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
                # When converted, the position now holds project-currency
                # values, so its currency IS the project currency. When
                # not converted it stays in the assembly's own currency.
                "currency": (project_currency if currency_converted else assembly.currency),
                "resources": resources,
                # Standard key the BOQ UI reads to render the M/L/E
                # mini-badge - see ``backend/app/modules/boq/models.py``
                # docstring for the metadata vocabulary.
                "resource_breakdown": resource_breakdown,
                # Audit trail: exactly one of these is present when the
                # assembly currency differed from the project's - a
                # ``currency_converted`` record (FX applied) or a
                # non-blocking ``currency_mismatch`` flag (Issue #128).
                **({"currency_converted": currency_converted} if currency_converted else {}),
                **({"currency_mismatch": currency_warning} if currency_warning else {}),
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
                catalog_resource_id=comp.catalog_resource_id,
                description=comp.description,
                resource_type=comp.resource_type,
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
        # Re-fetch WITH components eagerly loaded. ``cloned`` came from
        # ``create()`` (only ``refresh()``-ed its column attrs) so its
        # ``components`` selectin relationship is unloaded; the router's
        # ``_assembly_to_response`` reads ``assembly.components`` which
        # would trigger a sync lazy-load outside the async greenlet
        # (MissingGreenlet → HTTP 500 / component_count=0). The
        # with-components query the GET endpoint uses materialises the
        # collection inside the greenlet so the response carries the
        # real component_count (NEW-ASM-103 / ASM-001).
        reloaded = await self.assembly_repo.get_by_id_with_components(cloned.id)
        return reloaded if reloaded is not None else cloned

    # ── Stats ─────────────────────────────────────────────────────────────

    async def get_stats(self, *, owner_id: uuid.UUID | None = None) -> dict[str, object]:
        """Return aggregated assembly statistics.

        Returns total count, category breakdown, and most-used assemblies
        (determined by the number of BOQ positions referencing each assembly).

        ``owner_id`` scopes the totals/breakdown to a single tenant so the
        stats banner does not leak the platform-wide count to a VIEWER;
        pass ``None`` for an admin / unscoped roll-up.
        """
        # All active assemblies for this tenant
        assemblies, total = await self.assembly_repo.list_all(offset=0, limit=10000, owner_id=owner_id)

        by_category: dict[str, int] = {}
        for asm in assemblies:
            cat = asm.category or "uncategorized"
            by_category[cat] = by_category.get(cat, 0) + 1

        # Most-used: count BOQ positions that reference each assembly via
        # their metadata (positions carry no ``assembly_id`` column - the
        # reference lives in ``metadata_['assembly_id']``), restricted to
        # the tenant's own assemblies so the banner never exposes another
        # owner's recipe names.
        most_used: list[dict[str, object]] = []
        try:
            scoped_ids = {str(asm.id): asm.name for asm in assemblies}
            if scoped_ids:
                usage = await self.get_usage_counts(
                    [asm.id for asm in assemblies],
                    owner_id=owner_id,
                )
                ranked = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)
                most_used = [
                    {"name": scoped_ids.get(aid, ""), "usage_count": cnt} for aid, cnt in ranked[:5] if cnt > 0
                ]
        except Exception:
            # BOQ module may not exist or table not yet created
            logger.debug("Could not compute assembly usage stats from BOQ positions")

        return {
            "total": total,
            "most_used": most_used,
            "by_category": by_category,
        }

    # ── Reorder ──────────────────────────────────────────────────────────

    async def reorder_components(
        self,
        assembly_id: uuid.UUID,
        component_ids: list[uuid.UUID],
    ) -> None:
        """Reorder components within an assembly.

        Updates the sort_order of each component to match its position in
        the provided list of component IDs.

        Args:
            assembly_id: Parent assembly identifier.
            component_ids: Ordered list of component IDs.

        Raises:
            HTTPException 404 if assembly not found.
            HTTPException 400 if component IDs don't match assembly.
        """
        await self.get_assembly(assembly_id)
        components = await self.component_repo.list_for_assembly(assembly_id)
        existing_ids = {str(c.id) for c in components}
        request_ids = {str(cid) for cid in component_ids}

        if existing_ids != request_ids:
            raise HTTPException(
                status_code=400,
                detail="Component IDs do not match the assembly's components",
            )

        for idx, cid in enumerate(component_ids):
            await self.component_repo.update_fields(cid, sort_order=idx)

        logger.info(
            "Reordered %d components in assembly %s",
            len(component_ids),
            assembly_id,
        )

    # ── Export / Import ──────────────────────────────────────────────────

    async def export_assembly(self, assembly_id: uuid.UUID) -> dict:
        """Export an assembly with all components as a shareable JSON dict.

        Args:
            assembly_id: Target assembly identifier.

        Returns:
            dict matching the AssemblyExport schema.

        Raises:
            HTTPException 404 if assembly not found.
        """
        assembly = await self.get_assembly(assembly_id)
        components = await self.component_repo.list_for_assembly(assembly_id)

        metadata = assembly.metadata_ or {}
        tags: list[str] = metadata.get("tags", []) if isinstance(metadata, dict) else []

        export_components = []
        for comp in components:
            export_components.append(
                {
                    "description": comp.description,
                    "resource_type": comp.resource_type,
                    "factor": _str_to_float(comp.factor),
                    "quantity": _str_to_float(comp.quantity),
                    "unit": comp.unit,
                    "unit_cost": _str_to_float(comp.unit_cost),
                    "sort_order": comp.sort_order,
                    "metadata": dict(comp.metadata_) if comp.metadata_ else {},
                }
            )

        return {
            "code": assembly.code,
            "name": assembly.name,
            "description": assembly.description,
            "unit": assembly.unit,
            "category": assembly.category,
            "classification": assembly.classification or {},
            "currency": assembly.currency,
            "bid_factor": _str_to_float(assembly.bid_factor),
            "regional_factors": assembly.regional_factors or {},
            "tags": tags,
            "components": export_components,
        }

    async def import_assembly(
        self,
        data: AssemblyExport,
        owner_id: str | None = None,
    ) -> Assembly:
        """Import an assembly from an exported JSON payload.

        Creates a new assembly with all components. If the code already
        exists, appends a numeric suffix to make it unique.

        Args:
            data: Assembly export payload with components.
            owner_id: ID of the user importing the assembly.

        Returns:
            The newly created Assembly.
        """
        # ── Validate & parse every component BEFORE creating the
        # assembly row. A bad numeric yields a clean 422 instead of an
        # unhandled ValueError 500, AND we don't leave an orphan
        # assembly behind when one component is malformed - the
        # export/import round-trip is a core "no vendor lock-in"
        # guarantee, so a partial import is worse than a clean refusal.
        parsed_components: list[dict] = []
        for idx, comp_data in enumerate(data.components):
            if not isinstance(comp_data, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"components[{idx}]: expected an object",
                )
            factor_dec = _parse_import_decimal(comp_data.get("factor", 1.0), "factor", idx)
            quantity_dec = _parse_import_decimal(comp_data.get("quantity", 1.0), "quantity", idx)
            unit_cost_dec = _parse_import_decimal(comp_data.get("unit_cost", 0.0), "unit_cost", idx)
            res_type_raw = comp_data.get("resource_type")
            res_type = str(res_type_raw).lower() if isinstance(res_type_raw, str) and res_type_raw else None
            comp_meta = comp_data.get("metadata") if isinstance(comp_data.get("metadata"), dict) else {}
            sort_raw = comp_data.get("sort_order", idx)
            parsed_components.append(
                {
                    "description": str(comp_data.get("description", "") or ""),
                    "resource_type": res_type,
                    "factor": factor_dec,
                    "quantity": quantity_dec,
                    "unit_cost": unit_cost_dec,
                    "unit": str(comp_data.get("unit", data.unit) or data.unit),
                    "metadata": comp_meta,
                    "sort_order": sort_raw if isinstance(sort_raw, int) else idx,
                }
            )

        # Ensure unique code
        code = data.code
        existing = await self.assembly_repo.get_by_code(code)
        suffix = 1
        while existing is not None:
            code = f"{data.code}-{suffix}"
            existing = await self.assembly_repo.get_by_code(code)
            suffix += 1

        metadata: dict = {}
        if data.tags:
            metadata["tags"] = data.tags
        metadata["imported"] = True

        assembly = Assembly(
            code=code,
            name=data.name,
            description=data.description,
            unit=data.unit,
            category=data.category,
            classification=data.classification,
            total_rate="0",
            currency=data.currency,
            bid_factor=str(data.bid_factor),
            regional_factors=data.regional_factors,
            is_template=True,
            owner_id=uuid.UUID(owner_id) if owner_id else None,
            metadata_=metadata,
        )
        assembly = await self.assembly_repo.create(assembly)

        components_to_create = []
        for pc in parsed_components:
            total = _compute_typed_total(
                resource_type=pc["resource_type"],
                factor=float(pc["factor"]),
                quantity=float(pc["quantity"]),
                unit_cost=float(pc["unit_cost"]),
                metadata=pc["metadata"],
            )
            components_to_create.append(
                Component(
                    assembly_id=assembly.id,
                    description=pc["description"],
                    resource_type=pc["resource_type"],
                    factor=str(pc["factor"]),
                    quantity=str(pc["quantity"]),
                    unit=pc["unit"],
                    unit_cost=str(pc["unit_cost"]),
                    total=total,
                    sort_order=pc["sort_order"],
                    metadata_=pc["metadata"],
                )
            )

        if components_to_create:
            await self.component_repo.bulk_create(components_to_create)

        # Recalculate total
        await self._recalculate_total(assembly.id)

        await _safe_publish(
            "assemblies.assembly.imported",
            {"assembly_id": str(assembly.id), "code": code},
            source_module="oe_assemblies",
        )

        logger.info("Assembly imported: %s (%s)", code, data.name)
        # Re-fetch WITH components + the freshly recalculated total_rate.
        # ``assembly`` is the object returned by ``create()`` (its
        # ``components`` selectin relationship is unloaded and its
        # ``total_rate`` still reads the pre-recalc "0"). The router's
        # ``_assembly_to_response`` touches ``assembly.components``,
        # which would otherwise trigger a sync lazy-load outside the
        # async greenlet → MissingGreenlet → HTTP 500 for EVERY valid
        # import payload (ASM-001). Reloading via the with-components
        # query (same one the GET endpoint uses) materialises the
        # collection inside the greenlet and surfaces the correct
        # total_rate + component_count (NEW-ASM-103).
        reloaded = await self.assembly_repo.get_by_id_with_components(assembly.id)
        return reloaded if reloaded is not None else assembly

    # ── Tags ─────────────────────────────────────────────────────────────

    async def update_tags(
        self,
        assembly_id: uuid.UUID,
        tags: list[str],
    ) -> Assembly:
        """Update tags on an assembly.

        Tags are stored in the metadata_ JSON field under the 'tags' key.

        Args:
            assembly_id: Target assembly identifier.
            tags: List of tag strings.

        Returns:
            Updated Assembly.

        Raises:
            HTTPException 404 if assembly not found.
        """
        assembly = await self.get_assembly(assembly_id)
        metadata = dict(assembly.metadata_) if assembly.metadata_ else {}
        # Deduplicate and clean tags
        clean_tags = list(dict.fromkeys(t.strip().lower() for t in tags if t.strip()))
        metadata["tags"] = clean_tags
        await self.assembly_repo.update_fields(assembly_id, metadata_=metadata)

        await _safe_publish(
            "assemblies.assembly.tags_updated",
            {"assembly_id": str(assembly_id), "tags": clean_tags},
            source_module="oe_assemblies",
        )

        return await self.get_assembly(assembly_id)

    # ── Usage counts ─────────────────────────────────────────────────────

    async def get_usage_counts(
        self,
        assembly_ids: list[uuid.UUID],
        *,
        owner_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Get BOQ position usage counts for a list of assemblies.

        Positions carry no ``assembly_id`` column - the reference lives in
        ``Position.metadata_['assembly_id']`` (set by ``apply_to_boq``).
        We therefore can't ``GROUP BY`` on a column, but we DON'T need to
        load every assembly-sourced position into Python either: a
        ``LIKE`` over the serialised JSON metadata pre-filters in SQL to
        only the rows that mention one of the requested assembly ids, and
        we select just the ``metadata`` column instead of whole ORM rows.

        Args:
            assembly_ids: List of assembly UUIDs to check.
            owner_id: When provided, only count positions in BOQs that
                belong to the caller's own projects, so the usage figure
                never reflects (and the scan never reads) another tenant's
                BOQ positions.

        Returns:
            Dict mapping assembly_id (str) to usage count.
        """
        if not assembly_ids:
            return {}

        usage: dict[str, int] = {str(aid): 0 for aid in assembly_ids}

        try:
            from sqlalchemy import String, or_
            from sqlalchemy import select as sa_select

            from app.modules.boq.models import BOQ
            from app.modules.boq.models import Position as BOQPosition

            # Pre-filter in SQL: only assembly-sourced positions whose
            # serialised metadata mentions at least one of the requested
            # assembly ids. ``metadata_`` is a JSON column; casting to
            # text + LIKE is portable across SQLite and PostgreSQL and
            # avoids pulling the full table into Python.
            meta_text = BOQPosition.metadata_.cast(String)
            id_clauses = [meta_text.ilike(f'%"assembly_id": "{aid}"%') for aid in assembly_ids]

            stmt = sa_select(BOQPosition.metadata_).where(
                BOQPosition.source == "assembly",
                or_(*id_clauses),
            )

            # Tenant scope: restrict to the caller's own projects via the
            # BOQ → project owner link so the count (and the scan) never
            # crosses tenants.
            if owner_id is not None:
                from app.modules.projects.models import Project

                stmt = (
                    stmt.join(BOQ, BOQ.id == BOQPosition.boq_id)
                    .join(Project, Project.id == BOQ.project_id)
                    .where(Project.owner_id == owner_id)
                )

            result = await self.session.execute(stmt)
            for (meta,) in result.all():
                ref_id = (meta or {}).get("assembly_id", "")
                if ref_id in usage:
                    usage[ref_id] += 1
        except Exception:
            logger.debug("Could not compute usage counts from BOQ positions")

        return usage
