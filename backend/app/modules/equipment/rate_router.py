# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plant rate catalogue routes (mounted under /api/v1/equipment/rate-catalogues/).

GET    /                          - Catalogue versions, newest first (page envelope)
POST   /                          - Start an empty catalogue
POST   /demo/                     - Load the five synthetic demo machines (currency=EUR|USD)
GET    /layouts/                  - Import layouts: own, plus those of the active packs
GET    /profiles/                 - Saved column mappings; POST saves one, DELETE /profiles/{name}
POST   /preview/                  - Live result of the formula for the machine drawer
POST   /import/preview/           - Headers, sample rows and a suggested mapping of an uploaded table
POST   /import/                   - Check (dry_run=true) or create a catalogue version from a table
GET    /rental-defaults/          - Rates a new rental of an asset starts from
POST   /charge-preview/           - Month charge from operational, standby and breakdown hours
GET    /{id}/                     - One catalogue with its machines and rates
PATCH  /{id}/, DELETE /{id}/      - Edit settings (current version only), delete
GET    /{id}/validation/          - Rule results (equip_rate.*) for every machine
POST   /{id}/items/               - Add a machine; PATCH/DELETE /items/{item_id}
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.core.active_markets import ActiveMarkets
from app.dependencies import RequirePermission, SessionDep
from app.modules.equipment.rate_import import ColumnProfile
from app.modules.equipment.rate_schemas import (
    CatalogueCreate,
    CatalogueDetailResponse,
    CatalogueListResponse,
    CatalogueResponse,
    CatalogueUpdate,
    ChargePreviewRequest,
    ChargePreviewResponse,
    ImportCheckResponse,
    ImportPreviewResponse,
    IssueOut,
    ItemCreate,
    ItemResponse,
    ItemUpdate,
    LayoutOut,
    PreviewRequest,
    PreviewResponse,
    ProfileCreate,
    ProfileListResponse,
    ProfileResponse,
    RentalDefaults,
)
from app.modules.equipment.rate_seed import DEMO_SETS, load_demo_catalogue
from app.modules.equipment.rate_service import RateService

router = APIRouter(prefix="/rate-catalogues", tags=["equipment-rates"])

_MAX_UPLOAD = 10 * 1024 * 1024

Read = Depends(RequirePermission("equipment.read"))
Write = Depends(RequirePermission("equipment.update"))
Create = Depends(RequirePermission("equipment.create"))


def _service(session: SessionDep) -> RateService:
    return RateService(session)


Service = Annotated[RateService, Depends(_service)]
_Offset = Annotated[int, Query(ge=0)]
_Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/", response_model=CatalogueListResponse, dependencies=[Read])
async def list_catalogues(service: Service, offset: _Offset = 0, limit: _Limit = 200) -> CatalogueListResponse:
    rows = await service.list_catalogues()
    return CatalogueListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post("/", response_model=CatalogueResponse, status_code=201, dependencies=[Create])
async def create_catalogue(data: CatalogueCreate, service: Service) -> CatalogueResponse:
    row = await service.create_catalogue(data)
    return await service.catalogue_response(row.id)


@router.post("/demo/", response_model=CatalogueResponse, status_code=201, dependencies=[Create])
async def load_demo(service: Service, session: SessionDep, currency: str = Query("EUR")) -> CatalogueResponse:
    if currency.upper() not in DEMO_SETS:
        raise HTTPException(422, f"Demo machines exist for {', '.join(DEMO_SETS)}")
    row = await load_demo_catalogue(session, currency)
    return await service.catalogue_response(row.id)


@router.get("/layouts/", response_model=list[LayoutOut], dependencies=[Read])
async def list_layouts(service: Service, markets: ActiveMarkets) -> list[LayoutOut]:
    return service.layouts(markets)


@router.get("/profiles/", response_model=ProfileListResponse, dependencies=[Read])
async def list_profiles(service: Service, offset: _Offset = 0, limit: _Limit = 200) -> ProfileListResponse:
    rows = await service.list_profiles()
    items = [ProfileResponse.model_validate(p) for p in rows[offset : offset + limit]]
    return ProfileListResponse(items=items, total=len(rows), offset=offset, limit=limit)


@router.post("/profiles/", response_model=ProfileResponse, status_code=201, dependencies=[Write])
async def save_profile(data: ProfileCreate, service: Service) -> Any:
    return ProfileResponse.model_validate(await service.save_profile(data))


@router.delete("/profiles/{name}", status_code=204, dependencies=[Write])
async def delete_profile(name: str, service: Service) -> None:
    await service.delete_profile(name)


@router.post("/preview/", response_model=PreviewResponse, dependencies=[Read])
async def preview(data: PreviewRequest, service: Service) -> PreviewResponse:
    return await service.preview(data)


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(413, "The table is larger than 10 MB")
    return data


@router.post("/import/preview/", response_model=ImportPreviewResponse, dependencies=[Write])
async def import_preview(
    service: Service, markets: ActiveMarkets, file: UploadFile = File(...)
) -> ImportPreviewResponse:
    return service.import_preview(file.filename or "table.csv", await _read_upload(file), markets)


@router.post("/import/", response_model=ImportCheckResponse, dependencies=[Write])
async def import_table(
    service: Service,
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    decimal_comma: bool = Form(False),
    percent_fields: str = Form('["interest","repair"]'),
    dry_run: bool = Form(True),
    name: str = Form(""),
    valid_from: str = Form(""),
    licence_note: str = Form(""),
    source_label: str = Form(""),
    currency: str = Form(""),
    interest_convention: str = Form("average_value"),
    family_id: str = Form(""),
) -> ImportCheckResponse:
    try:
        column_map = {str(k): str(v) for k, v in json.loads(mapping).items()}
        percents = tuple(str(p) for p in json.loads(percent_fields))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(422, "mapping and percent_fields must be JSON") from exc
    profile = ColumnProfile(mapping=column_map, decimal_comma=decimal_comma, percent_fields=percents)
    filename = file.filename or "table.csv"
    result = service.dry_run(filename, await _read_upload(file), profile)
    issues = [
        IssueOut(
            rule_id=i["rule_id"],
            severity=i["severity"],
            message=i["message"],
            field=i["field"],
            row=i["row"],
            details=i["details"],
        )
        for i in result.issues[:500]
    ]
    out = ImportCheckResponse(
        ready=result.ready, error_rows=result.error_rows, total_rows=result.total_rows, issues=issues
    )
    if dry_run:
        return out
    try:
        header = CatalogueCreate(
            name=name,
            valid_from=valid_from,
            licence_note=licence_note,
            source_label=source_label,
            currency=currency,
            interest_convention=interest_convention,
        )
        family = uuid.UUID(family_id) if family_id else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = await service.commit_import(result, header, family)
    out.catalogue_id = row.id
    return out


@router.get("/rental-defaults/", response_model=RentalDefaults, dependencies=[Read])
async def rental_defaults(service: Service, equipment_id: uuid.UUID) -> RentalDefaults:
    return await service.rental_defaults(equipment_id)


@router.post("/charge-preview/", response_model=ChargePreviewResponse, dependencies=[Read])
async def charge_preview(data: ChargePreviewRequest, service: Service) -> ChargePreviewResponse:
    return await service.charge_preview(data)


@router.get("/{catalogue_id}/", response_model=CatalogueDetailResponse, dependencies=[Read])
async def get_catalogue(catalogue_id: uuid.UUID, service: Service) -> CatalogueDetailResponse:
    head = await service.catalogue_response(catalogue_id)
    return CatalogueDetailResponse(**head.model_dump(), items=await service.items(catalogue_id))


@router.patch("/{catalogue_id}/", response_model=CatalogueResponse, dependencies=[Write])
async def update_catalogue(catalogue_id: uuid.UUID, data: CatalogueUpdate, service: Service) -> CatalogueResponse:
    await service.update_catalogue(catalogue_id, data)
    return await service.catalogue_response(catalogue_id)


@router.delete("/{catalogue_id}/", status_code=204, dependencies=[Write])
async def delete_catalogue(catalogue_id: uuid.UUID, service: Service) -> None:
    await service.delete_catalogue(catalogue_id)


@router.get("/{catalogue_id}/validation/", response_model=list[IssueOut], dependencies=[Read])
async def validate_catalogue(catalogue_id: uuid.UUID, service: Service) -> list[IssueOut]:
    return await service.validate_catalogue(catalogue_id)


@router.post("/{catalogue_id}/items/", response_model=ItemResponse, status_code=201, dependencies=[Write])
async def create_item(catalogue_id: uuid.UUID, data: ItemCreate, service: Service) -> ItemResponse:
    return await service.create_item(catalogue_id, data)


@router.patch("/items/{item_id}", response_model=ItemResponse, dependencies=[Write])
async def update_item(item_id: uuid.UUID, data: ItemUpdate, service: Service) -> ItemResponse:
    return await service.update_item(item_id, data)


@router.delete("/items/{item_id}", status_code=204, dependencies=[Write])
async def delete_item(item_id: uuid.UUID, service: Service) -> None:
    await service.delete_item(item_id)
