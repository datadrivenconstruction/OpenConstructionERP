# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Conceptual (ROM) estimate API routes.

Endpoints:
    GET    /reference/                          - building types, quality levels,
                                                   regions and elements for the form
    POST   /generate/                           - instant order-of-magnitude estimate
                                                   (stateless, no persistence)
    GET    /projects/{project_id}/estimates/    - list a project's saved estimates
    POST   /projects/{project_id}/estimates/    - compute and save an estimate
    POST   /projects/{project_id}/estimates/create-boq/ - save the estimate as the
                                                   baseline and seed a provisional BOQ
    DELETE /projects/{project_id}/estimates/{estimate_id} - delete a saved estimate
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.rom_estimate.models import RomEstimate
from app.modules.rom_estimate.schemas import (
    RomCreateBoqRequest,
    RomCreateBoqResponse,
    RomElementBreakdown,
    RomEstimateRecord,
    RomEstimateRequest,
    RomEstimateResult,
    RomReconciliation,
    RomReferenceResponse,
)
from app.modules.rom_estimate.service import (
    BUILDING_TYPES,
    RomEstimateService,
    build_reference,
    build_rom_estimate,
)

router = APIRouter(tags=["rom_estimate"])


def _get_service(session: SessionDep) -> RomEstimateService:
    return RomEstimateService(session)


def _row_to_record(row: RomEstimate) -> RomEstimateRecord:
    """Convert a saved :class:`RomEstimate` row to its response schema.

    The building-type label is resolved from the live reference table (falling
    back to the stored key), and the JSON breakdown snapshot is parsed back into
    typed element lines.
    """
    profile = BUILDING_TYPES.get(row.building_type)
    label = profile.label if profile is not None else row.building_type
    elements = [RomElementBreakdown.model_validate(line) for line in (row.breakdown or [])]
    return RomEstimateRecord(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        building_type=row.building_type,
        building_type_label=label,
        quality=row.quality,
        region=row.region,
        currency=row.currency,
        gross_floor_area=row.gross_floor_area,
        gfa_unit=row.gfa_unit,
        cost_per_m2=row.cost_per_m2,
        total=row.total_cost,
        estimate_class=row.estimate_class,
        accuracy_low_pct=row.accuracy_low_pct,
        accuracy_high_pct=row.accuracy_high_pct,
        accuracy_low_amount=row.accuracy_low_amount,
        accuracy_high_amount=row.accuracy_high_amount,
        elements=elements,
        created_at=row.created_at,
        created_by=row.created_by,
    )


# ── Reference metadata ───────────────────────────────────────────────────────


@router.get(
    "/reference/",
    response_model=RomReferenceResponse,
    dependencies=[Depends(RequirePermission("rom_estimate.read"))],
)
async def get_reference() -> RomReferenceResponse:
    """Return building types, quality levels, regions and elements for the form."""
    return build_reference()


# ── Instant estimate (stateless) ─────────────────────────────────────────────


@router.post(
    "/generate/",
    response_model=RomEstimateResult,
    dependencies=[Depends(RequirePermission("rom_estimate.read"))],
)
async def generate_estimate(request: RomEstimateRequest) -> RomEstimateResult:
    """Produce an instant order-of-magnitude estimate from minimal input.

    Pure calculation, no persistence. Invalid input (unknown building type,
    quality or region, unsupported unit, non-positive area) becomes a 422.
    """
    try:
        return build_rom_estimate(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


# ── Saved estimates (project-scoped) ─────────────────────────────────────────


@router.get(
    "/projects/{project_id}/estimates/",
    response_model=list[RomEstimateRecord],
    dependencies=[Depends(RequirePermission("rom_estimate.read"))],
)
async def list_estimates(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: RomEstimateService = Depends(_get_service),
) -> list[RomEstimateRecord]:
    """List the conceptual estimates saved against a project (newest first)."""
    await verify_project_access(project_id, user_id, session)
    rows = await service.list_estimates(project_id, offset=offset, limit=limit)
    return [_row_to_record(row) for row in rows]


@router.get(
    "/projects/{project_id}/reconciliation/",
    response_model=RomReconciliation,
    dependencies=[Depends(RequirePermission("rom_estimate.read"))],
)
async def get_reconciliation(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RomEstimateService = Depends(_get_service),
) -> RomReconciliation:
    """Reconcile the project's conceptual baseline against its live detailed BOQ.

    Compares the most-recent saved conceptual (ROM) total to the FX-correct sum
    of the project's detailed BOQ grand totals and returns the drift: the
    conceptual total, the detailed total, the variance amount and percentage, the
    reconciliation currency and a traffic-light status band (on_track / over /
    under). Degrades gracefully - with no saved conceptual estimate the status is
    ``no_baseline`` and the variance is null; with no BOQ the detailed total is 0.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.reconcile_with_boq(project_id)


@router.post(
    "/projects/{project_id}/estimates/",
    response_model=RomEstimateRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("rom_estimate.write"))],
)
async def create_estimate(
    project_id: uuid.UUID,
    request: RomEstimateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RomEstimateService = Depends(_get_service),
) -> RomEstimateRecord:
    """Compute a conceptual estimate and save it against a project."""
    await verify_project_access(project_id, user_id, session)
    try:
        created_by = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        created_by = None
    try:
        row = await service.create_estimate(project_id, request, created_by)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _row_to_record(row)


@router.post(
    "/projects/{project_id}/estimates/create-boq/",
    response_model=RomCreateBoqResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("rom_estimate.write"))],
)
async def create_boq_from_rom(
    project_id: uuid.UUID,
    request: RomCreateBoqRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RomEstimateService = Depends(_get_service),
) -> RomCreateBoqResponse:
    """Save the conceptual estimate as the baseline and seed a provisional BOQ.

    The concept-to-detailed handoff: the estimate is persisted as the project
    baseline (so the reconciliation goes live) and a draft BOQ is generated with
    one elemental section and one concept-rate line item per element, ready to
    refine with a detailed take-off. Invalid input (unknown building type,
    quality or region, unsupported unit, non-positive area) becomes a 422.
    """
    await verify_project_access(project_id, user_id, session)
    try:
        created_by = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        created_by = None
    try:
        return await service.create_boq_from_rom(project_id, request, created_by)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.delete(
    "/projects/{project_id}/estimates/{estimate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("rom_estimate.write"))],
)
async def delete_estimate(
    project_id: uuid.UUID,
    estimate_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RomEstimateService = Depends(_get_service),
) -> None:
    """Delete a saved conceptual estimate (404 when it is not in this project)."""
    await verify_project_access(project_id, user_id, session)
    existing = await service.get_estimate(estimate_id)
    if existing is None or str(existing.project_id) != str(project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estimate not found")
    await service.delete_estimate(estimate_id)
