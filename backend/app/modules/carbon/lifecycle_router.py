# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Carbon​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ life-cycle and company reporting routes (included by ``router.py``).

Endpoints (under ``/api/v1/carbon``):
    POST /epd/import                          - ILCD+EPD XML or CSV upload
    GET  /epd/by-catalog-item/{item_id}       - EPDs attached to a supplier product
    POST /inventories/{id}/a4-transport       - A4 transport line
    POST /inventories/{id}/a5-site-energy     - A5 fuel and electricity line
    POST /inventories/{id}/a5-equipment-fuel  - A5 line from equipment fuel logs
    POST /inventories/{id}/a5-waste           - A5 waste line
    GET  /inventories/{id}/hotspots           - Carbon by DIN 276 / NRM / MasterFormat group
    GET  /projects/{id}/budget                - Carbon budget vs latest inventory
    GET  /projects/{id}/checks                - Carbon checks behind the validation rule
    GET  /embodied/{id}/swap                  - CO2 and cost delta of a material swap
    POST /bid-carbon                          - Carbon per bid line (tender comparison)
    GET  /limits                              - National embodied-carbon limit lookup
    GET/POST/DELETE /company/activities       - Company scope 1/2/3 activities
    POST /company/activities/fleet-fuel       - Fleet fuel as scope 1 activities
    GET/POST /company/reports                 - Company E1 / SECR / US reports
    GET  /company/reports/{id}/export         - xlsx | pdf | xbrl_csv
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.carbon import csrd
from app.modules.carbon.lifecycle_service import CarbonLifecycleService
from app.modules.carbon.schemas import EmbodiedCarbonEntryResponse

router = APIRouter(tags=["carbon"])

_DQ = r"^(measured|calculated|estimated)$"
_MAX_EPD_BYTES = 10 * 1024 * 1024


def _svc(session: SessionDep) -> CarbonLifecycleService:
    return CarbonLifecycleService(session)


async def _inv_access(svc: CarbonLifecycleService, inventory_id: uuid.UUID, user_id: str, session: Any) -> None:
    project_id = await svc.base.get_inventory_project_id(inventory_id)
    await verify_project_access(project_id, user_id, session)


class TransportIn(BaseModel):
    mass_kg: Decimal = Field(..., ge=0)
    distance_km: Decimal = Field(..., ge=0)
    mode: str = Field(default="road_truck", pattern=r"^(road_truck|road_van|rail|inland_barge|sea_container|air)$")
    factor_per_tkm: Decimal | None = Field(default=None, ge=0)
    supplier: str | None = Field(default=None, max_length=255)
    description: str = Field(default="", max_length=500)
    data_quality: str = Field(default="calculated", pattern=_DQ)


class SiteEnergyIn(BaseModel):
    fuel_litres: dict[str, Decimal] = Field(default_factory=dict)
    electricity_kwh: Decimal = Field(default=Decimal("0"), ge=0)
    grid_factor: Decimal | None = Field(default=None, ge=0)
    description: str = Field(default="", max_length=500)
    data_quality: str = Field(default="measured", pattern=_DQ)


class EquipmentFuelIn(BaseModel):
    period_start: date
    period_end: date


class WasteIn(BaseModel):
    material_carbon_kg: Decimal = Field(..., ge=0)
    material_mass_kg: Decimal = Field(..., ge=0)
    waste_rate_pct: Decimal = Field(..., ge=0, le=100)
    treatment: str = Field(
        default="landfill_mixed", pattern=r"^(landfill_inert|landfill_mixed|recycling|incineration)$"
    )
    description: str = Field(default="", max_length=500)
    data_quality: str = Field(default="estimated", pattern=_DQ)


class BidLine(BaseModel):
    ref: str = Field(..., max_length=120)
    cost_item_id: uuid.UUID | None = None
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    unit: str | None = Field(default=None, max_length=20)


class BidCarbonIn(BaseModel):
    lines: list[BidLine] = Field(default_factory=list, max_length=5000)


class ActivityIn(BaseModel):
    reporting_year: int = Field(..., ge=1990, le=2100)
    scope: int = Field(..., ge=1, le=3)
    scope3_category: int | None = Field(default=None, ge=1, le=15)
    category: str = Field(default="office", max_length=40)
    description: str = Field(default="", max_length=2000)
    activity_amount: Decimal = Field(..., ge=0)
    activity_unit: str = Field(default="kWh", max_length=20)
    emission_factor: Decimal = Field(..., ge=0)
    factor_source: str = Field(default="", max_length=255)
    energy_kwh: Decimal = Field(default=Decimal("0"), ge=0)
    renewable_share_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    market_based_co2e_kg: Decimal | None = Field(default=None, ge=0)
    data_quality: str = Field(default="calculated", pattern=_DQ)


class ActivityOut(ActivityIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    co2e_kg: Decimal
    source_module: str


class ReportIn(BaseModel):
    reporting_year: int = Field(..., ge=1990, le=2100)
    template: str = Field(default="esrs_e1", max_length=32)
    company_name: str = Field(default="", max_length=255)
    net_revenue: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reporting_year: int
    template: str
    company_name: str
    net_revenue: Decimal
    currency: str
    status: str
    datapoints: dict[str, Any]
    audit: dict[str, Any]


# ── EPD ──────────────────────────────────────────────────────────────────


@router.post("/epd/import")
async def import_epd(
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    material_class: str = Form(default="other", max_length=80),
    supplier_catalog_item_id: uuid.UUID | None = Form(default=None),
    _perm: None = Depends(RequirePermission("carbon.import_epd")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> dict[str, Any]:
    """Import EPDs from an EN 15804 ILCD+EPD XML dataset or a flat CSV."""
    payload = await file.read(_MAX_EPD_BYTES + 1)
    if len(payload) > _MAX_EPD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file too large")
    return await svc.import_epd_file(
        payload,
        file.filename or "",
        material_class=material_class,
        supplier_catalog_item_id=supplier_catalog_item_id,
    )


@router.get("/epd/by-catalog-item/{item_id}")
async def epds_for_item(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    svc: CarbonLifecycleService = Depends(_svc),
) -> list[dict[str, Any]]:
    """EPDs attached to a supplier catalogue product."""
    return [
        {
            "id": str(r.id),
            "epd_id": r.epd_id,
            "product_name": r.product_name,
            "declared_unit": r.declared_unit,
            "gwp_a1a3": str(r.gwp_a1a3),
            "validity_until": r.validity_until.isoformat() if r.validity_until else None,
        }
        for r in await svc.epds_for_catalog_item(item_id)
    ]


# ── Stage lines ──────────────────────────────────────────────────────────


@router.post("/inventories/{inventory_id}/a4-transport", response_model=EmbodiedCarbonEntryResponse, status_code=201)
async def add_a4(
    inventory_id: uuid.UUID,
    body: TransportIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("carbon.create")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    await _inv_access(svc, inventory_id, user_id, session)
    return await svc.add_transport_a4(inventory_id, **body.model_dump())


@router.post("/inventories/{inventory_id}/a5-site-energy", response_model=EmbodiedCarbonEntryResponse, status_code=201)
async def add_a5_energy(
    inventory_id: uuid.UUID,
    body: SiteEnergyIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("carbon.create")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    await _inv_access(svc, inventory_id, user_id, session)
    return await svc.add_site_energy_a5(inventory_id, **body.model_dump())


@router.post("/inventories/{inventory_id}/a5-equipment-fuel")
async def add_a5_equipment(
    inventory_id: uuid.UUID,
    body: EquipmentFuelIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("carbon.create")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> dict[str, Any]:
    await _inv_access(svc, inventory_id, user_id, session)
    entry = await svc.import_equipment_fuel_a5(inventory_id, period_start=body.period_start, period_end=body.period_end)
    if entry is None:
        return {"created": False, "entry": None}
    return {"created": True, "entry": EmbodiedCarbonEntryResponse.model_validate(entry).model_dump(mode="json")}


@router.post("/inventories/{inventory_id}/a5-waste", response_model=EmbodiedCarbonEntryResponse, status_code=201)
async def add_a5_waste(
    inventory_id: uuid.UUID,
    body: WasteIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("carbon.create")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    await _inv_access(svc, inventory_id, user_id, session)
    return await svc.add_waste_a5(inventory_id, **body.model_dump())


# ── Analysis ─────────────────────────────────────────────────────────────


@router.get("/inventories/{inventory_id}/hotspots")
async def hotspots(
    inventory_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    system: str = Query(default="din276", pattern=r"^(din276|nrm|masterformat)$"),
    svc: CarbonLifecycleService = Depends(_svc),
) -> list[dict[str, Any]]:
    await _inv_access(svc, inventory_id, user_id, session)
    return await svc.hotspots(inventory_id, system)


@router.get("/projects/{project_id}/budget")
async def budget(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: CarbonLifecycleService = Depends(_svc),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await svc.budget(project_id)


@router.get("/projects/{project_id}/checks")
async def checks(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: CarbonLifecycleService = Depends(_svc),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await svc.checks(project_id)


@router.get("/embodied/{entry_id}/swap")
async def swap(
    entry_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    alternative_factor_id: uuid.UUID = Query(...),
    current_unit_rate: Decimal = Query(default=Decimal("0"), ge=0),
    alternative_unit_rate: Decimal = Query(default=Decimal("0"), ge=0),
    svc: CarbonLifecycleService = Depends(_svc),
) -> dict[str, Any]:
    project_id = await svc.base.get_embodied_project_id(entry_id)
    await verify_project_access(project_id, user_id, session)
    return await svc.swap(
        entry_id,
        alternative_factor_id=alternative_factor_id,
        current_unit_rate=current_unit_rate,
        alternative_unit_rate=alternative_unit_rate,
    )


@router.post("/bid-carbon")
async def bid_carbon(
    body: BidCarbonIn,
    user_id: CurrentUserId,
    svc: CarbonLifecycleService = Depends(_svc),
) -> dict[str, Any]:
    """Carbon per bid line; the tender comparison shows it as an optional column."""
    return await svc.bid_carbon([line.model_dump() for line in body.lines])


@router.get("/limits")
async def limits(
    user_id: CurrentUserId,
    country: str = Query(..., min_length=2, max_length=2),
    building_type: str = Query(..., max_length=60),
    on_date: date | None = None,
) -> dict[str, Any]:
    hit = csrd.embodied_limit(country, building_type, (on_date or date.today()).isoformat())
    return hit or {"country": country.upper(), "limit": None, "review_status": "not_available"}


# ── Company reporting ────────────────────────────────────────────────────


async def _admin(session: Any, user_id: str) -> tuple[set[uuid.UUID] | None, bool]:
    ids = await accessible_project_ids(session, user_id)
    return ids, ids is None


@router.get("/company/activities", response_model=list[ActivityOut])
async def list_activities(
    user_id: CurrentUserId,
    session: SessionDep,
    year: int = Query(..., ge=1990, le=2100),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    _, admin = await _admin(session, user_id)
    return await svc.list_activities(year, user_id, admin)


@router.post("/company/activities", response_model=ActivityOut, status_code=201)
async def create_activity(
    body: ActivityIn,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("carbon.create")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    return await svc.create_activity(body.model_dump(), user_id)


@router.post("/company/activities/fleet-fuel", response_model=list[ActivityOut], status_code=201)
async def fleet_fuel(
    user_id: CurrentUserId,
    year: int = Query(..., ge=1990, le=2100),
    _perm: None = Depends(RequirePermission("carbon.create")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    return await svc.import_fleet_fuel(year, user_id)


@router.delete("/company/activities/{activity_id}", status_code=204)
async def delete_activity(
    activity_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("carbon.delete")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Response:
    _, admin = await _admin(session, user_id)
    await svc.delete_activity(activity_id, user_id, admin)
    return Response(status_code=204)


@router.get("/company/templates")
async def templates(user_id: CurrentUserId) -> dict[str, Any]:
    return csrd.report_templates()


@router.get("/company/reports", response_model=list[ReportOut])
async def list_reports(
    user_id: CurrentUserId,
    session: SessionDep,
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    _, admin = await _admin(session, user_id)
    return await svc.list_company_reports(user_id, admin)


@router.post("/company/reports", response_model=ReportOut, status_code=201)
async def generate_report(
    body: ReportIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("carbon.generate_report")),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Any:
    ids, admin = await _admin(session, user_id)
    return await svc.generate_company_report(
        year=body.reporting_year,
        template=body.template,
        net_revenue=body.net_revenue,
        currency=body.currency.upper(),
        company_name=body.company_name,
        project_ids=ids,
        user_id=user_id,
        admin=admin,
    )


@router.get("/company/reports/{report_id}/export")
async def export_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    fmt: str = Query(default="xlsx", pattern=r"^(xlsx|pdf|xbrl_csv)$"),
    svc: CarbonLifecycleService = Depends(_svc),
) -> Response:
    _, admin = await _admin(session, user_id)
    rep = await svc.get_company_report(report_id, user_id, admin)
    data = ReportOut.model_validate(rep).model_dump(mode="json")
    stem = f"{rep.template}_{rep.reporting_year}"
    if fmt == "xlsx":
        body, media, ext = (
            csrd.to_xlsx(data),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    elif fmt == "pdf":
        body, media, ext = csrd.to_pdf(data), "application/pdf", "pdf"
    else:
        body, media, ext = csrd.to_xbrl_csv(data).encode("utf-8"), "text/csv", "csv"
    return Response(
        content=body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'}
    )
