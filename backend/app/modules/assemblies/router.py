"""Assembly API routes.

Endpoints:
    POST   /                          — Create a new assembly
    GET    /                          — Search assemblies (q, category, unit, project_id, is_template)
    POST   /ai-generate               — AI-generate an assembly from natural language
    GET    /{assembly_id}             — Get assembly with all components
    PATCH  /{assembly_id}             — Update assembly
    DELETE /{assembly_id}             — Delete assembly and all components
    POST   /{assembly_id}/components            — Add a component
    PATCH  /{assembly_id}/components/{cid}      — Update a component
    DELETE /{assembly_id}/components/{cid}      — Delete a component
    POST   /{assembly_id}/apply-to-boq          — Apply assembly to a BOQ
    POST   /{assembly_id}/clone                 — Clone assembly
"""

import logging
import time
import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.assemblies.schemas import (
    ApplyToBOQRequest,
    AssemblyCreate,
    AssemblyImportRequest,
    AssemblyResponse,
    AssemblySearchResponse,
    AssemblyUpdate,
    AssemblyWithComponents,
    CloneAssemblyRequest,
    ComponentCreate,
    ComponentResponse,
    ComponentUpdate,
    ReorderComponentsRequest,
)
from app.modules.assemblies.service import AssemblyService, _str_to_float

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_service(session: SessionDep) -> AssemblyService:
    return AssemblyService(session)


async def _verify_assembly_owner(
    session: SessionDep,
    assembly_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> None:
    """Load an assembly and verify ownership.

    Admins bypass the check via the role claim on the JWT payload.

    Returns 404 (not 403) on ownership mismatch so attackers cannot
    enumerate valid assembly UUIDs by probing for 403 responses.
    """
    if payload and payload.get("role") == "admin":
        return

    from app.modules.assemblies.repository import AssemblyRepository

    repo = AssemblyRepository(session)
    assembly = await repo.get_by_id(assembly_id)
    if assembly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assembly not found",
        )
    # Legacy/global templates with no owner are readable only by admins (handled
    # above). Treat as not-found for regular users to avoid leaking their ids.
    if assembly.owner_id is None or str(assembly.owner_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assembly not found",
        )


async def _verify_target_boq_owner(
    session: SessionDep,
    boq_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> None:
    """Verify the user owns the project that contains the given BOQ.

    Used by `apply_to_boq` to prevent cross-tenant injection of assembly
    positions into someone else's BOQ. Mirrors ``boq.router._verify_boq_owner``
    but lives here to avoid a circular import at module load time.
    """
    if payload and payload.get("role") == "admin":
        return

    from app.modules.boq.repository import BOQRepository
    from app.modules.projects.repository import ProjectRepository

    boq_repo = BOQRepository(session)
    boq = await boq_repo.get_by_id(boq_id)
    if boq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(boq.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if str(project.owner_id) != str(user_id):
        # 404 here too — don't let callers probe for valid BOQ ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")


def _assembly_to_response(
    assembly: object, usage_count: int = 0,
) -> AssemblyResponse:
    """Convert an Assembly ORM model to an AssemblyResponse schema."""
    components = getattr(assembly, "components", None) or []
    metadata = getattr(assembly, "metadata_", {}) or {}
    tags: list[str] = metadata.get("tags", []) if isinstance(metadata, dict) else []
    return AssemblyResponse(
        id=assembly.id,  # type: ignore[attr-defined]
        code=assembly.code,  # type: ignore[attr-defined]
        name=assembly.name,  # type: ignore[attr-defined]
        description=assembly.description,  # type: ignore[attr-defined]
        unit=assembly.unit,  # type: ignore[attr-defined]
        category=assembly.category,  # type: ignore[attr-defined]
        classification=assembly.classification,  # type: ignore[attr-defined]
        total_rate=_str_to_float(assembly.total_rate),  # type: ignore[attr-defined]
        currency=assembly.currency,  # type: ignore[attr-defined]
        bid_factor=_str_to_float(assembly.bid_factor),  # type: ignore[attr-defined]
        regional_factors=assembly.regional_factors,  # type: ignore[attr-defined]
        is_template=assembly.is_template,  # type: ignore[attr-defined]
        project_id=assembly.project_id,  # type: ignore[attr-defined]
        owner_id=assembly.owner_id,  # type: ignore[attr-defined]
        is_active=assembly.is_active,  # type: ignore[attr-defined]
        component_count=len(components),
        usage_count=usage_count,
        tags=tags,
        metadata_=metadata,
        created_at=assembly.created_at,  # type: ignore[attr-defined]
        updated_at=assembly.updated_at,  # type: ignore[attr-defined]
    )


def _component_to_response(comp: object) -> ComponentResponse:
    """Convert a Component ORM model to a ComponentResponse schema."""
    return ComponentResponse(
        id=comp.id,  # type: ignore[attr-defined]
        assembly_id=comp.assembly_id,  # type: ignore[attr-defined]
        cost_item_id=comp.cost_item_id,  # type: ignore[attr-defined]
        catalog_resource_id=getattr(comp, "catalog_resource_id", None),  # type: ignore[attr-defined]
        description=comp.description,  # type: ignore[attr-defined]
        factor=_str_to_float(comp.factor),  # type: ignore[attr-defined]
        quantity=_str_to_float(comp.quantity),  # type: ignore[attr-defined]
        unit=comp.unit,  # type: ignore[attr-defined]
        unit_cost=_str_to_float(comp.unit_cost),  # type: ignore[attr-defined]
        total=_str_to_float(comp.total),  # type: ignore[attr-defined]
        sort_order=comp.sort_order,  # type: ignore[attr-defined]
        metadata_=comp.metadata_,  # type: ignore[attr-defined]
        created_at=comp.created_at,  # type: ignore[attr-defined]
        updated_at=comp.updated_at,  # type: ignore[attr-defined]
    )


# ── Assembly CRUD ────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=AssemblyResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.create"))],
)
async def create_assembly(
    data: AssemblyCreate,
    user_id: CurrentUserId,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Create a new assembly (composite cost item)."""
    assembly = await service.create_assembly(data, owner_id=user_id)
    return _assembly_to_response(assembly)


@router.get(
    "/",
    response_model=AssemblySearchResponse,
    dependencies=[Depends(RequirePermission("assemblies.read"))],
)
async def search_assemblies(
    q: str | None = Query(default=None, description="Text search on code, name, description"),
    category: str | None = Query(default=None, description="Filter by category"),
    unit: str | None = Query(default=None, description="Filter by unit"),
    tag: str | None = Query(default=None, description="Filter by tag"),
    project_id: uuid.UUID | None = Query(default=None, description="Filter by project"),
    is_template: bool | None = Query(default=None, description="Filter by template flag"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    service: AssemblyService = Depends(_get_service),
) -> AssemblySearchResponse:
    """Search assemblies with optional filters and pagination."""
    assemblies, total = await service.search_assemblies(
        q=q,
        category=category,
        unit=unit,
        tag=tag,
        project_id=project_id,
        is_template=is_template,
        offset=offset,
        limit=limit,
    )

    # Compute usage counts for each assembly from BOQ metadata
    usage_map: dict[str, int] = {}
    try:
        usage_map = await service.get_usage_counts(
            [a.id for a in assemblies],
        )
    except Exception:
        logger.debug("Could not compute assembly usage counts")

    return AssemblySearchResponse(
        items=[
            _assembly_to_response(a, usage_count=usage_map.get(str(a.id), 0))
            for a in assemblies
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── AI Assembly Generation ──────────────────────────────────────────────────


class AIGenerateRequest(BaseModel):
    """Request body for AI assembly generation."""

    description: str = Field(..., min_length=3, max_length=500)
    region: str = Field(default="", max_length=50)
    unit: str = Field(default="m2", max_length=20)


def _guess_component_type(item: object) -> str:
    """Infer component type (material, labor, equipment) from a cost item."""
    desc = (getattr(item, "description", "") or "").lower()
    tags = getattr(item, "tags", []) or []
    tags_lower = [str(t).lower() for t in tags]
    meta = getattr(item, "metadata_", {}) or {}
    item_type = str(meta.get("type", "")).lower()

    labor_keywords = (
        "labor",
        "labour",
        "worker",
        "crew",
        "mason",
        "carpenter",
        "plumber",
        "electrician",
        "fitter",
        "welder",
        "helper",
        "operator",
        "plasterer",
        "roofer",
        "driver",
        "arbeit",
        "lohn",
        "monteur",
        "arbeiter",
    )
    equipment_keywords = (
        "equip",
        "machine",
        "crane",
        "excavator",
        "pump",
        "mixer",
        "truck",
        "scaffold",
        "vibrator",
        "compressor",
        "generator",
        "maschine",
        "bagger",
        "kran",
        "gerät",
    )

    if item_type in ("labor", "labour"):
        return "labor"
    if item_type in ("equipment", "plant"):
        return "equipment"
    if any(kw in desc for kw in labor_keywords) or "labor" in tags_lower:
        return "labor"
    if any(kw in desc for kw in equipment_keywords) or "equipment" in tags_lower:
        return "equipment"
    return "material"


@router.post(
    "/ai-generate/",
    dependencies=[Depends(RequirePermission("assemblies.create"))],
)
async def ai_generate_assembly(
    data: AIGenerateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict:
    """Generate an assembly from a natural language description.

    Searches the cost database for matching components and builds a
    preview assembly. The result is NOT saved — the user reviews and
    confirms before creating.

    Args:
        data: Description, optional region and unit.
        session: Database session.
        user_id: Authenticated user ID.

    Returns:
        dict with generated assembly preview including components and
        total rate.
    """
    from app.modules.costs.models import CostItem

    description = data.description.strip()

    # Build search terms: split description into meaningful keywords
    search_terms = [w for w in description.split() if len(w) >= 3]

    found_items: list[object] = []

    # Strategy 1: Try ILIKE search with full description
    pattern = f"%{description}%"
    stmt = select(CostItem).where(CostItem.is_active.is_(True), CostItem.description.ilike(pattern)).limit(15)
    result = await session.execute(stmt)
    found_items = list(result.scalars().all())

    # Strategy 2: If too few results, search by individual keywords
    if len(found_items) < 3 and search_terms:
        for term in search_terms[:5]:
            kw_pattern = f"%{term}%"
            kw_stmt = (
                select(CostItem).where(CostItem.is_active.is_(True), CostItem.description.ilike(kw_pattern)).limit(8)
            )
            kw_result = await session.execute(kw_stmt)
            for item in kw_result.scalars().all():
                if item.id not in {getattr(i, "id", None) for i in found_items}:
                    found_items.append(item)
            if len(found_items) >= 15:
                break

    # Optionally filter by region
    if data.region and found_items:
        region_items = [
            i for i in found_items if getattr(i, "region", None) is None or getattr(i, "region", "") == data.region
        ]
        if region_items:
            found_items = region_items

    # Build components from found items (cap at 15)
    found_items = found_items[:15]
    components = []
    total_rate = 0.0

    for idx, item in enumerate(found_items):
        rate = 0.0
        try:
            rate = float(getattr(item, "rate", 0))
        except (ValueError, TypeError):
            pass

        comp_type = _guess_component_type(item)
        item_desc = str(getattr(item, "description", ""))[:200]
        item_code = str(getattr(item, "code", ""))
        item_unit = str(getattr(item, "unit", data.unit))

        comp_total = rate * 1.0  # quantity=1.0 by default
        total_rate += comp_total

        components.append(
            {
                "name": item_desc,
                "code": item_code,
                "unit": item_unit,
                "quantity": 1.0,
                "unit_rate": round(rate, 2),
                "total": round(comp_total, 2),
                "type": comp_type,
                "sort_order": idx,
                "cost_item_id": str(getattr(item, "id", "")),
            }
        )

    # Determine confidence based on number of results found
    if len(components) >= 5:
        confidence = 0.8
    elif len(components) >= 3:
        confidence = 0.6
    elif len(components) >= 1:
        confidence = 0.4
    else:
        confidence = 0.1

    timestamp = str(int(time.time()))

    logger.info(
        "AI assembly generated for '%s': %d components, total=%.2f",
        description[:50],
        len(components),
        total_rate,
    )

    return {
        "name": f"Generated: {description[:100]}",
        "code": f"AI-{timestamp}",
        "unit": data.unit,
        "category": "",
        "components": components,
        "total_rate": round(total_rate, 2),
        "source_items_count": len(found_items),
        "confidence": confidence,
        "description": description,
        "region": data.region,
    }


@router.get(
    "/stats/",
    dependencies=[Depends(RequirePermission("assemblies.read"))],
)
async def get_stats(
    service: AssemblyService = Depends(_get_service),
) -> dict:
    """Return aggregated assembly statistics: totals, category breakdown, most-used."""
    return await service.get_stats()


@router.get(
    "/{assembly_id}",
    response_model=AssemblyWithComponents,
    dependencies=[Depends(RequirePermission("assemblies.read"))],
)
async def get_assembly(
    assembly_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyWithComponents:
    """Get an assembly with all its components and computed total."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    return await service.get_assembly_with_components(assembly_id)


@router.patch(
    "/{assembly_id}",
    response_model=AssemblyResponse,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def update_assembly(
    assembly_id: uuid.UUID,
    data: AssemblyUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Update assembly metadata fields."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    assembly = await service.update_assembly(assembly_id, data)
    return _assembly_to_response(assembly)


@router.delete(
    "/{assembly_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("assemblies.delete"))],
)
async def delete_assembly(
    assembly_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> None:
    """Delete an assembly and all its components."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    await service.delete_assembly(assembly_id)


# ── Component CRUD ───────────────────────────────────────────────────────────


@router.post(
    "/{assembly_id}/components/",
    response_model=ComponentResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def add_component(
    assembly_id: uuid.UUID,
    data: ComponentCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> ComponentResponse:
    """Add a new component to an assembly."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    component = await service.add_component(assembly_id, data)
    # Build response directly to avoid MissingGreenlet on expired ORM attrs
    try:
        return _component_to_response(component)
    except Exception:
        # Fallback: construct from known data
        from datetime import datetime

        total = data.factor * data.quantity * data.unit_cost
        now = datetime.now(UTC)
        return ComponentResponse(
            id=component.id,
            assembly_id=assembly_id,
            cost_item_id=data.cost_item_id,
            catalog_resource_id=data.catalog_resource_id,
            description=data.description,
            factor=data.factor,
            quantity=data.quantity,
            unit=data.unit,
            unit_cost=data.unit_cost,
            total=round(total, 2),
            sort_order=0,
            metadata_={},
            created_at=now,
            updated_at=now,
        )


@router.patch(
    "/{assembly_id}/components/{component_id}",
    response_model=ComponentResponse,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def update_component(
    assembly_id: uuid.UUID,
    component_id: uuid.UUID,
    data: ComponentUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> ComponentResponse:
    """Update an assembly component. Recalculates totals."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    component = await service.update_component(assembly_id, component_id, data)
    return _component_to_response(component)


@router.delete(
    "/{assembly_id}/components/{component_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def delete_component(
    assembly_id: uuid.UUID,
    component_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> None:
    """Delete a component from an assembly."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    await service.delete_component(assembly_id, component_id)


# ── Actions ──────────────────────────────────────────────────────────────────


@router.post(
    "/{assembly_id}/apply-to-boq/",
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def apply_to_boq(
    assembly_id: uuid.UUID,
    data: ApplyToBOQRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> dict:
    """Apply an assembly to a BOQ as a new position.

    Creates a BOQ position with unit_rate = assembly total_rate (optionally
    adjusted by a regional factor) and source = "assembly".

    Verifies ownership of both the source assembly AND the target BOQ to
    prevent cross-tenant data injection.
    """
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    await _verify_target_boq_owner(session, data.boq_id, user_id, payload)
    position = await service.apply_to_boq(assembly_id, data)
    return {
        "position_id": str(position.id),  # type: ignore[attr-defined]
        "boq_id": str(data.boq_id),
        "assembly_id": str(assembly_id),
        "message": "Assembly applied to BOQ successfully",
    }


@router.post(
    "/{assembly_id}/clone/",
    response_model=AssemblyResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.create"))],
)
async def clone_assembly(
    assembly_id: uuid.UUID,
    data: CloneAssemblyRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Clone an assembly, optionally into a different project."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    cloned = await service.clone_assembly(assembly_id, data, owner_id=user_id)
    return _assembly_to_response(cloned)


# ── Reorder ──────────────────────────────────────────────────────────────────


@router.post(
    "/{assembly_id}/reorder-components/",
    status_code=200,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def reorder_components(
    assembly_id: uuid.UUID,
    data: ReorderComponentsRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> dict:
    """Reorder components within an assembly.

    Accepts an ordered list of component IDs and updates sort_order
    accordingly.
    """
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    await service.reorder_components(assembly_id, data.component_ids)
    return {"status": "ok", "assembly_id": str(assembly_id)}


# ── Export / Import ──────────────────────────────────────────────────────────


@router.get(
    "/{assembly_id}/export/",
    dependencies=[Depends(RequirePermission("assemblies.read"))],
)
async def export_assembly(
    assembly_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> dict:
    """Export an assembly with all components as a shareable JSON payload."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    return await service.export_assembly(assembly_id)


@router.post(
    "/import/",
    response_model=AssemblyResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.create"))],
)
async def import_assembly(
    data: AssemblyImportRequest,
    user_id: CurrentUserId,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Import an assembly from a JSON payload.

    Creates a new assembly with all components from the exported format.
    If the code already exists, a suffix is appended to make it unique.
    """
    assembly = await service.import_assembly(data.assembly, owner_id=user_id)
    return _assembly_to_response(assembly)


# ── Tags ─────────────────────────────────────────────────────────────────────


class UpdateTagsRequest(BaseModel):
    """Request body for updating assembly tags."""

    tags: list[str] = Field(default_factory=list, max_length=20)


@router.patch(
    "/{assembly_id}/tags/",
    response_model=AssemblyResponse,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def update_tags(
    assembly_id: uuid.UUID,
    data: UpdateTagsRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Update tags on an assembly. Tags are stored in metadata."""
    await _verify_assembly_owner(session, assembly_id, user_id, payload)
    assembly = await service.update_tags(assembly_id, data.tags)
    return _assembly_to_response(assembly)
