# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Waste-factor API routes.

Mounted at ``/api/v1/waste-factors/`` by the module loader.

Endpoint groups:
    /factors/          - factor-library CRUD
    /seed-defaults     - idempotent load of the starter library
    /apply             - convert net quantities to gross procurement quantities

The library is a shared reference catalogue (no project scope), so reads only
require an authenticated user while writes are gated by ``waste_factors.manage``.
A missing factor id returns 404, never 403, so probing never leaks existence.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.waste_factors.models import WasteFactor
from app.modules.waste_factors.schemas import (
    ApplyLineResult,
    ApplyRequest,
    ApplyResponse,
    WasteFactorCreate,
    WasteFactorResponse,
    WasteFactorSeedResult,
    WasteFactorUpdate,
)
from app.modules.waste_factors.service import WasteFactorService

router = APIRouter(tags=["waste-factors"])

_MANAGE = Depends(RequirePermission("waste_factors.manage"))


def _to_response(item: WasteFactor) -> WasteFactorResponse:
    return WasteFactorResponse.model_validate(item)


async def _load_or_404(session: AsyncSession, factor_id: uuid.UUID) -> WasteFactor:
    obj = await session.get(WasteFactor, factor_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Waste factor not found")
    return obj


# -- Factor library CRUD ---------------------------------------------------


@router.get("/factors/", response_model=list[WasteFactorResponse])
async def list_factors(
    session: SessionDep,
    _user_id: CurrentUserId,
    category: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[WasteFactorResponse]:
    """List factor-library rows, optionally filtered by exact category."""
    service = WasteFactorService(session)
    items = await service.list_factors(category=category, offset=offset, limit=limit)
    return [_to_response(it) for it in items]


@router.post(
    "/factors/",
    response_model=WasteFactorResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_factor(
    data: WasteFactorCreate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> WasteFactorResponse:
    """Create a new factor-library row."""
    service = WasteFactorService(session)
    obj = await service.create(data)
    return _to_response(obj)


@router.get("/factors/{factor_id}", response_model=WasteFactorResponse)
async def get_factor(
    factor_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> WasteFactorResponse:
    """Fetch one factor-library row."""
    obj = await _load_or_404(session, factor_id)
    return _to_response(obj)


@router.patch(
    "/factors/{factor_id}",
    response_model=WasteFactorResponse,
    dependencies=[_MANAGE],
)
async def update_factor(
    factor_id: uuid.UUID,
    data: WasteFactorUpdate,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> WasteFactorResponse:
    """Patch a factor-library row."""
    await _load_or_404(session, factor_id)
    service = WasteFactorService(session)
    obj = await service.update(factor_id, data)
    assert obj is not None  # the load_or_404 above proved existence
    return _to_response(obj)


@router.delete(
    "/factors/{factor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
)
async def delete_factor(
    factor_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> None:
    """Delete a factor-library row (404 when it does not exist)."""
    await _load_or_404(session, factor_id)
    service = WasteFactorService(session)
    await service.delete(factor_id)


@router.post(
    "/seed-defaults",
    response_model=WasteFactorSeedResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def seed_defaults(
    session: SessionDep,
    _user_id: CurrentUserId,
    tenant_id: uuid.UUID | None = Query(default=None),
) -> WasteFactorSeedResult:
    """Idempotently load the starter factor library (never duplicates a category)."""
    service = WasteFactorService(session)
    result = await service.seed_defaults(tenant_id=tenant_id)
    return WasteFactorSeedResult(**result)


# -- Apply (net -> gross) --------------------------------------------------


@router.post("/apply", response_model=ApplyResponse)
async def apply_factors(
    data: ApplyRequest,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> ApplyResponse:
    """Convert net measured quantities into gross procurement quantities.

    Each line is multiplied by the factor resolved for its category; a
    category with no library entry passes through unchanged (factor 1.0) and
    is flagged ``matched=false`` so the estimator can spot uncovered lines.
    """
    service = WasteFactorService(session)
    gross_lines = await service.apply(data.lines)
    return ApplyResponse(
        lines=[
            ApplyLineResult(
                category=gl.category,
                net_qty=gl.net_qty,
                factor=gl.factor,
                gross_qty=gl.gross_qty,
                matched=gl.matched,
            )
            for gl in gross_lines
        ],
    )
