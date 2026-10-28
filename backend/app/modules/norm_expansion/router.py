# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Production-norm expansion API routes.

Mounted at ``/api/v1/norm-expansion/`` by the module loader.

Endpoint groups:
    /norms/                         - norm library CRUD
    /norms/{id}/materials/          - material coefficient sub-resource
    /materials/{id}                 - material coefficient delete
    /expand                         - expand one work item's quantity
    /expand-batch                   - expand several work items at once

The library is a shared, platform-wide reference (like a code catalogue), so
reads are open to any authenticated viewer and writes are gated by role. A
missing row returns 404, never 403, so probing never leaks a UUID's existence.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.norm_expansion.models import ProductionNorm
from app.modules.norm_expansion.schemas import (
    BuildAssemblyRequest,
    BuildAssemblyResponse,
    ExpandBatchRequest,
    ExpandBatchResponse,
    ExpandRequest,
    ExpansionResponse,
    MaterialDemandResponse,
    NormCreate,
    NormMaterialCreate,
    NormMaterialResponse,
    NormResponse,
    NormUpdate,
    PricedComponentResponse,
)
from app.modules.norm_expansion.service import (
    ExpansionResult,
    NormExpansionService,
    NormNotFoundError,
    WorkKeyExistsError,
    build_assembly_from_norm,
)

router = APIRouter(tags=["norm-expansion"])


def _norm_to_response(norm: ProductionNorm) -> NormResponse:
    return NormResponse.model_validate(norm)


def _expansion_to_response(
    norm: ProductionNorm,
    result: ExpansionResult,
    quantity: object,
) -> ExpansionResponse:
    """Assemble the API response from a norm and its expansion result."""
    return ExpansionResponse(
        work_key=norm.work_key,
        name=norm.name,
        unit=norm.unit,
        quantity=quantity,  # type: ignore[arg-type]
        labor_hours=result.labor_hours,
        machine_hours=result.machine_hours,
        materials=[MaterialDemandResponse(name=m.name, unit=m.unit, qty=m.qty) for m in result.materials],
    )


async def _load_norm_or_404(service: NormExpansionService, norm_id: uuid.UUID) -> ProductionNorm:
    norm = await service.get_norm(norm_id)
    if norm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Production norm not found")
    return norm


# ── Norm library CRUD ────────────────────────────────────────────────────────


@router.get("/norms/", response_model=list[NormResponse])
async def list_norms(
    session: SessionDep,
    _user_id: CurrentUserId,
    q: str | None = Query(default=None, description="Search work_key / name"),
    category: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[NormResponse]:
    """List production norms in the shared library."""
    service = NormExpansionService(session)
    norms = await service.list_norms(
        q=q,
        category=category,
        active_only=active_only,
        offset=offset,
        limit=limit,
    )
    return [_norm_to_response(n) for n in norms]


@router.post(
    "/norms/",
    response_model=NormResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("norm_expansion.write"))],
)
async def create_norm(
    data: NormCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> NormResponse:
    """Create a production norm with its material coefficients."""
    service = NormExpansionService(session)
    try:
        norm = await service.create_norm(data)
    except WorkKeyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _norm_to_response(norm)


@router.get("/norms/{norm_id}", response_model=NormResponse)
async def get_norm(
    norm_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> NormResponse:
    """Fetch a single norm with its materials."""
    service = NormExpansionService(session)
    norm = await _load_norm_or_404(service, norm_id)
    return _norm_to_response(norm)


@router.patch(
    "/norms/{norm_id}",
    response_model=NormResponse,
    dependencies=[Depends(RequirePermission("norm_expansion.write"))],
)
async def update_norm(
    norm_id: uuid.UUID,
    data: NormUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> NormResponse:
    """Patch a norm's scalar fields."""
    service = NormExpansionService(session)
    await _load_norm_or_404(service, norm_id)
    try:
        norm = await service.update_norm(norm_id, data)
    except WorkKeyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert norm is not None  # the load_or_404 above proved existence
    return _norm_to_response(norm)


@router.delete(
    "/norms/{norm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("norm_expansion.manage"))],
)
async def delete_norm(
    norm_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Delete a norm and all its material coefficients."""
    service = NormExpansionService(session)
    await _load_norm_or_404(service, norm_id)
    await service.delete_norm(norm_id)


# ── Material coefficients ────────────────────────────────────────────────────


@router.post(
    "/norms/{norm_id}/materials/",
    response_model=NormMaterialResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("norm_expansion.write"))],
)
async def add_material(
    norm_id: uuid.UUID,
    data: NormMaterialCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> NormMaterialResponse:
    """Attach a material coefficient to a norm."""
    service = NormExpansionService(session)
    norm = await _load_norm_or_404(service, norm_id)
    material = await service.add_material(norm, data)
    return NormMaterialResponse.model_validate(material)


@router.delete(
    "/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("norm_expansion.write"))],
)
async def delete_material(
    material_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Remove a single material coefficient."""
    service = NormExpansionService(session)
    if await service.get_material(material_id) is None:
        # IDOR posture: unknown id is a 404, never a 403 / 422.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found")
    await service.delete_material(material_id)


# ── Expansion ────────────────────────────────────────────────────────────────


@router.post(
    "/expand",
    response_model=ExpansionResponse,
    dependencies=[Depends(RequirePermission("norm_expansion.read"))],
)
async def expand_one(
    data: ExpandRequest,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> ExpansionResponse:
    """Expand a single work item's quantity into unpriced resource demand."""
    service = NormExpansionService(session)
    outcome = await service.expand_work_key(data.work_key, data.quantity)
    if outcome is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No production norm for work_key: {data.work_key}",
        )
    norm, result = outcome
    return _expansion_to_response(norm, result, data.quantity)


@router.post(
    "/expand-batch",
    response_model=ExpandBatchResponse,
    dependencies=[Depends(RequirePermission("norm_expansion.read"))],
)
async def expand_batch(
    data: ExpandBatchRequest,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> ExpandBatchResponse:
    """Expand several work items at once.

    Work keys with no matching norm are collected under ``unmatched`` rather
    than failing the whole request, so a partial BOQ still returns the demand
    it can compute.
    """
    service = NormExpansionService(session)
    results: list[ExpansionResponse] = []
    unmatched: list[str] = []
    for item in data.items:
        outcome = await service.expand_work_key(item.work_key, item.quantity)
        if outcome is None:
            unmatched.append(item.work_key)
            continue
        norm, result = outcome
        results.append(_expansion_to_response(norm, result, item.quantity))
    return ExpandBatchResponse(results=results, unmatched=unmatched)


# ── Priced assembly build ────────────────────────────────────────────────────


def _dec(value: object) -> Decimal:
    """Read a string-stored numeric back as a finite, non-negative Decimal."""
    try:
        dec = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    if not dec.is_finite() or dec < 0:
        return Decimal("0")
    return dec


def _build_assembly_response(assembly: Any) -> BuildAssemblyResponse:
    """Map a persisted, norm-derived Assembly onto the build response."""
    metadata = assembly.metadata_ or {}
    components: list[PricedComponentResponse] = []
    unpriced: list[str] = []
    needs_review: list[str] = []
    for comp in assembly.components:
        comp_meta = comp.metadata_ or {}
        priced = bool(comp_meta.get("priced", True))
        component_needs_review = bool(comp_meta.get("needs_review", False))
        raw_confidence = comp_meta.get("match_confidence")
        # Waste fields are written only onto material components; leave them
        # None for labour / equipment so the response reflects "no waste here".
        has_waste = "waste_pct" in comp_meta
        components.append(
            PricedComponentResponse(
                resource_type=comp.resource_type,
                description=comp.description,
                unit=comp.unit,
                quantity=_dec(comp.quantity),
                unit_cost=_dec(comp.unit_cost),
                total=_dec(comp.total),
                cost_item_id=comp.cost_item_id,
                priced=priced,
                unpriced_reason=str(comp_meta.get("unpriced_reason", "") or ""),
                net_qty=_dec(comp_meta["net_qty"]) if "net_qty" in comp_meta else None,
                waste_pct=_dec(comp_meta["waste_pct"]) if has_waste else None,
                gross_qty=_dec(comp_meta["gross_qty"]) if "gross_qty" in comp_meta else None,
                waste_matched=bool(comp_meta.get("waste_matched")) if has_waste else None,
                price_source=str(comp_meta.get("price_source", "") or ""),
                # Confidence stays None for an unpriced line: a zero would read
                # as "priced, with no confidence" rather than "not priced".
                match_confidence=(None if raw_confidence in (None, "") else _dec(raw_confidence)),
                matched_description=str(comp_meta.get("matched_description", "") or ""),
                matched_code=str(comp_meta.get("matched_code", "") or ""),
                matched_source=str(comp_meta.get("matched_source", "") or ""),
                price_as_of=str(comp_meta.get("price_as_of", "") or ""),
                needs_review=component_needs_review,
            )
        )
        if not priced:
            unpriced.append(comp.description)
        elif component_needs_review:
            needs_review.append(comp.description)

    raw_unmatched = metadata.get("waste_unmatched", [])
    waste_unmatched = [str(x) for x in raw_unmatched] if isinstance(raw_unmatched, list) else []

    return BuildAssemblyResponse(
        id=assembly.id,
        code=assembly.code,
        name=assembly.name,
        unit=assembly.unit,
        category=assembly.category,
        currency=assembly.currency,
        total_rate=_dec(assembly.total_rate),
        project_id=assembly.project_id,
        is_template=assembly.is_template,
        work_key=str(metadata.get("work_key", "") or ""),
        components=components,
        unpriced=unpriced,
        # Derived from the components actually persisted, not from the metadata
        # list, so the verdict can never disagree with the lines it describes.
        total_rate_complete=not unpriced,
        unpriced_count=len(unpriced),
        needs_review=needs_review,
        needs_review_count=len(needs_review),
        labor_rate_source=str(metadata.get("labor_rate_source", "") or ""),
        machine_rate_source=str(metadata.get("machine_rate_source", "") or ""),
        waste_applied=bool(metadata.get("waste_applied", True)),
        waste_unmatched=waste_unmatched,
    )


@router.post(
    "/norms/{norm_id}/build-assembly",
    response_model=BuildAssemblyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(RequirePermission("norm_expansion.read")),
        Depends(RequirePermission("assemblies.create")),
    ],
)
async def build_assembly(
    norm_id: uuid.UUID,
    data: BuildAssemblyRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> BuildAssemblyResponse:
    """Build a priced assembly from a production norm's per-unit coefficients.

    Costs the norm's labour-hours, machine-hours and materials, then saves the
    result as a new assembly whose ``total_rate`` is the built-up unit rate. When
    ``apply_waste`` is set (the default) each material's net (installed) quantity
    is grossed up to its purchased quantity via the waste-factor library, and the
    per-material waste plus any unmatched materials are surfaced on the response.

    Each material is priced from an exact normalized name match against the cost
    items where one exists, and only otherwise from a fuzzy catalogue match; every
    component reports which of the two priced it, what it matched and with what
    confidence, and a fuzzy match is flagged ``needs_review`` because a heuristic
    that puts money on a line is a proposal, not a settled price. Labour and
    machine hours are priced from an explicit rate on the request or from a rate
    template, never from an invented number.

    Any line that could not be priced is created at a zero unit cost and flagged,
    and ``total_rate_complete`` then says the built-up rate is missing a cost line
    rather than finished. Requires both ``norm_expansion.read`` (to read the norm)
    and ``assemblies.create`` (the output is a new assembly).
    """
    try:
        assembly = await build_assembly_from_norm(
            session,
            norm_id,
            labor_rate_template_id=data.labor_rate_template_id,
            machine_rate_template_id=data.machine_rate_template_id,
            labor_rate=data.labor_rate,
            machine_rate=data.machine_rate,
            project_id=data.project_id,
            owner_id=user_id,
            region=data.region,
            apply_waste=data.apply_waste,
        )
    except NormNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No production norm for id: {norm_id}",
        ) from exc
    return _build_assembly_response(assembly)
