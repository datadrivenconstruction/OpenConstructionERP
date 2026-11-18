# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Norm pricing API routes (auto-mounted at /api/v1/norm_pricing).

Endpoints (RequirePermission + per-project access check on every one):
    GET  /profile?project_id=&locale=      what the country pack offers and what the project chose
    PUT  /settings?project_id=&locale=     store wage, hours, funding class, role, labour location
    GET  /labour-rates?project_id=&grades= hourly rates per grade with their derivation
    POST /check-code?project_id=           verdict on one norm code (ok, retired prefix, wrong shape)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.norm_pricing.schemas import (
    CodeCheckIn,
    CodeCheckOut,
    EstimatePricingSettings,
    LabourRatesOut,
    PricingProfile,
)
from app.modules.norm_pricing.service import NormPricingService

router = APIRouter(tags=["norm_pricing"])


def _service(session: SessionDep) -> NormPricingService:
    return NormPricingService(session)


@router.get("/profile", response_model=PricingProfile)
async def get_profile(
    project_id: uuid.UUID = Query(...),
    locale: str | None = Query(default=None, max_length=16),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("norm_pricing.read")),
    service: NormPricingService = Depends(_service),
) -> PricingProfile:
    """The norm base and pricing rules for the project's country, and its settings."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.profile(project_id, locale)


@router.put("/settings", response_model=PricingProfile)
async def put_settings(
    body: EstimatePricingSettings,
    project_id: uuid.UUID = Query(...),
    locale: str | None = Query(default=None, max_length=16),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("norm_pricing.update")),
    service: NormPricingService = Depends(_service),
) -> PricingProfile:
    """Store the project's norm pricing settings."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.update_settings(project_id, body, locale)


@router.get("/labour-rates", response_model=LabourRatesOut)
async def get_labour_rates(
    project_id: uuid.UUID = Query(...),
    grades: str = Query(default="", max_length=400, description="Comma-separated grades with a dot, e.g. 3.5,3.8"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("norm_pricing.read")),
    service: NormPricingService = Depends(_service),
) -> LabourRatesOut:
    """Hourly labour rates per grade, each with the wage, hours and coefficient behind it."""
    await verify_project_access(project_id, user_id or "", service.session)
    wanted = [g.strip() for g in grades.split(",") if g.strip()]
    return await service.labour_rates(project_id, wanted[:80])


@router.post("/check-code", response_model=CodeCheckOut)
async def post_check_code(
    body: CodeCheckIn,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("norm_pricing.read")),
    service: NormPricingService = Depends(_service),
) -> CodeCheckOut:
    """Whether a norm code is current, uses a retired prefix, or has the wrong shape."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.check_code(project_id, body.code)
