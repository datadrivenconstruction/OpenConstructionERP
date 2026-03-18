"""Assembly API routes.

Endpoints:
    POST   /                          — Create a new assembly
    GET    /                          — Search assemblies (q, category, unit, project_id, is_template)
    GET    /{assembly_id}             — Get assembly with all components
    PATCH  /{assembly_id}             — Update assembly
    DELETE /{assembly_id}             — Delete assembly and all components
    POST   /{assembly_id}/components            — Add a component
    PATCH  /{assembly_id}/components/{cid}      — Update a component
    DELETE /{assembly_id}/components/{cid}      — Delete a component
    POST   /{assembly_id}/apply-to-boq          — Apply assembly to a BOQ
    POST   /{assembly_id}/clone                 — Clone assembly
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.assemblies.schemas import (
    ApplyToBOQRequest,
    AssemblyCreate,
    AssemblyResponse,
    AssemblyUpdate,
    AssemblyWithComponents,
    CloneAssemblyRequest,
    ComponentCreate,
    ComponentResponse,
    ComponentUpdate,
)
from app.modules.assemblies.service import AssemblyService, _str_to_float

router = APIRouter()


def _get_service(session: SessionDep) -> AssemblyService:
    return AssemblyService(session)


def _assembly_to_response(assembly: object) -> AssemblyResponse:
    """Convert an Assembly ORM model to an AssemblyResponse schema."""
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
        metadata_=assembly.metadata_,  # type: ignore[attr-defined]
        created_at=assembly.created_at,  # type: ignore[attr-defined]
        updated_at=assembly.updated_at,  # type: ignore[attr-defined]
    )


def _component_to_response(comp: object) -> ComponentResponse:
    """Convert a Component ORM model to a ComponentResponse schema."""
    return ComponentResponse(
        id=comp.id,  # type: ignore[attr-defined]
        assembly_id=comp.assembly_id,  # type: ignore[attr-defined]
        cost_item_id=comp.cost_item_id,  # type: ignore[attr-defined]
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
    response_model=list[AssemblyResponse],
    dependencies=[Depends(RequirePermission("assemblies.read"))],
)
async def search_assemblies(
    q: str | None = Query(default=None, description="Text search on code, name, description"),
    category: str | None = Query(default=None, description="Filter by category"),
    unit: str | None = Query(default=None, description="Filter by unit"),
    project_id: uuid.UUID | None = Query(default=None, description="Filter by project"),
    is_template: bool | None = Query(default=None, description="Filter by template flag"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: AssemblyService = Depends(_get_service),
) -> list[AssemblyResponse]:
    """Search assemblies with optional filters and pagination."""
    assemblies, _ = await service.search_assemblies(
        q=q,
        category=category,
        unit=unit,
        project_id=project_id,
        is_template=is_template,
        offset=offset,
        limit=limit,
    )
    return [_assembly_to_response(a) for a in assemblies]


@router.get(
    "/{assembly_id}",
    response_model=AssemblyWithComponents,
    dependencies=[Depends(RequirePermission("assemblies.read"))],
)
async def get_assembly(
    assembly_id: uuid.UUID,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyWithComponents:
    """Get an assembly with all its components and computed total."""
    return await service.get_assembly_with_components(assembly_id)


@router.patch(
    "/{assembly_id}",
    response_model=AssemblyResponse,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def update_assembly(
    assembly_id: uuid.UUID,
    data: AssemblyUpdate,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Update assembly metadata fields."""
    assembly = await service.update_assembly(assembly_id, data)
    return _assembly_to_response(assembly)


@router.delete(
    "/{assembly_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("assemblies.delete"))],
)
async def delete_assembly(
    assembly_id: uuid.UUID,
    service: AssemblyService = Depends(_get_service),
) -> None:
    """Delete an assembly and all its components."""
    await service.delete_assembly(assembly_id)


# ── Component CRUD ───────────────────────────────────────────────────────────


@router.post(
    "/{assembly_id}/components",
    response_model=ComponentResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def add_component(
    assembly_id: uuid.UUID,
    data: ComponentCreate,
    service: AssemblyService = Depends(_get_service),
) -> ComponentResponse:
    """Add a new component to an assembly."""
    component = await service.add_component(assembly_id, data)
    return _component_to_response(component)


@router.patch(
    "/{assembly_id}/components/{component_id}",
    response_model=ComponentResponse,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def update_component(
    assembly_id: uuid.UUID,
    component_id: uuid.UUID,
    data: ComponentUpdate,
    service: AssemblyService = Depends(_get_service),
) -> ComponentResponse:
    """Update an assembly component. Recalculates totals."""
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
    service: AssemblyService = Depends(_get_service),
) -> None:
    """Delete a component from an assembly."""
    await service.delete_component(assembly_id, component_id)


# ── Actions ──────────────────────────────────────────────────────────────────


@router.post(
    "/{assembly_id}/apply-to-boq",
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.update"))],
)
async def apply_to_boq(
    assembly_id: uuid.UUID,
    data: ApplyToBOQRequest,
    service: AssemblyService = Depends(_get_service),
) -> dict:
    """Apply an assembly to a BOQ as a new position.

    Creates a BOQ position with unit_rate = assembly total_rate (optionally
    adjusted by a regional factor) and source = "assembly".
    """
    position = await service.apply_to_boq(assembly_id, data)
    return {
        "position_id": str(position.id),  # type: ignore[attr-defined]
        "boq_id": str(data.boq_id),
        "assembly_id": str(assembly_id),
        "message": "Assembly applied to BOQ successfully",
    }


@router.post(
    "/{assembly_id}/clone",
    response_model=AssemblyResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("assemblies.create"))],
)
async def clone_assembly(
    assembly_id: uuid.UUID,
    data: CloneAssemblyRequest,
    user_id: CurrentUserId,
    service: AssemblyService = Depends(_get_service),
) -> AssemblyResponse:
    """Clone an assembly, optionally into a different project."""
    cloned = await service.clone_assembly(assembly_id, data, owner_id=user_id)
    return _assembly_to_response(cloned)
