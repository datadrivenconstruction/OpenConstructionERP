# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Norm pricing API routes (auto-mounted at /api/v1/norm_pricing).

Endpoints (RequirePermission + per-project access check on every one):
    GET  /profile?project_id=&locale=      what the country pack offers and what the project chose
    PUT  /settings?project_id=&locale=     store wage, hours, funding class, role, labour location
    GET  /labour-rates?project_id=&grades= hourly rates per grade with their derivation
    POST /check-code?project_id=           verdict on one norm code (ok, retired prefix, wrong shape)
    GET  /labour-writeback?project_id=&boq_id=   preview: labour resources that would take the graded rate
    POST /labour-writeback?project_id=&boq_id=   write the rates the person confirmed in the preview
    GET  /export/xlsx?project_id=&boq_id=&locale= the bill in the pack's estimate sheet column order
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.norm_pricing.schemas import (
    CodeCheckIn,
    CodeCheckOut,
    EstimatePricingSettings,
    LabourRatesOut,
    PricingProfile,
    WritebackApply,
    WritebackPreview,
    WritebackResult,
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


@router.get("/labour-writeback", response_model=WritebackPreview)
async def get_labour_writeback(
    project_id: uuid.UUID = Query(...),
    boq_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("norm_pricing.read")),
    service: NormPricingService = Depends(_service),
) -> WritebackPreview:
    """The labour resources of a bill whose rate would change to the project's graded rate. Writes nothing."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await service.writeback_preview(project_id, boq_id)


@router.post("/labour-writeback", response_model=WritebackResult)
async def post_labour_writeback(
    body: WritebackApply,
    project_id: uuid.UUID = Query(...),
    boq_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("boq.update")),
    service: NormPricingService = Depends(_service),
) -> WritebackResult:
    """Write the rates the person confirmed; a stale preview is refused with 409."""
    await verify_project_access(project_id, user_id or "", service.session)
    actor = uuid.UUID(str(user_id)) if user_id else None
    return await service.writeback_apply(project_id, boq_id, body, actor)


@router.get("/export/xlsx")
async def get_export_xlsx(
    project_id: uuid.UUID = Query(...),
    boq_id: uuid.UUID = Query(...),
    locale: str | None = Query(default=None, max_length=16),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("boq.export")),
    service: NormPricingService = Depends(_service),
) -> Response:
    """The bill as the market's estimate sheet, in the column order the country pack lays down."""
    await verify_project_access(project_id, user_id or "", service.session)
    content, filename = await service.export_sheet(project_id, boq_id, locale)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
