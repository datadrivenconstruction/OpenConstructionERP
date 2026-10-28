# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Equipment telematics routes​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ (mounted under /api/v1/equipment/telematics/).

POST /telematics/devices/               - Register a device, returns its token once
GET  /telematics/devices/               - List devices (equipment_id=)
POST /telematics/devices/{id}/revoke    - Revoke a device token
POST /telematics/ingest/                - Device ingest, header ``X-Device-Token``
POST /telematics/import/aemp/           - ISO 15143-3 (AEMP 2.0) Fleet snapshot, XML or JSON
POST /telematics/import/csv/            - CSV upload
GET  /telematics/utilisation/           - Worked / idle / off hours per machine
POST /telematics/allocate/              - Book machine-days to projects and cost codes
GET  /telematics/validation/            - Rule results (equipment_telematics)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.rate_limiter import client_identifier, device_ingest_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.equipment.telematics import TelematicsParseError, TelematicsSample, parse_aemp, parse_csv
from app.modules.equipment.telematics_service import DEFAULT_IDLE_THRESHOLD, TelematicsService
from app.modules.equipment.validators import run_rules

router = APIRouter(prefix="/telematics", tags=["equipment-telematics"])

_MAX_UPLOAD = 10 * 1024 * 1024
_MAX_SAMPLES = 5000


class DeviceCreate(BaseModel):
    equipment_id: uuid.UUID
    label: str = Field(default="", max_length=200)


class DeviceResponse(BaseModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    label: str
    token_prefix: str
    active: bool
    last_seen_at: datetime | None = None
    token: str | None = None


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    total: int
    offset: int = 0
    limit: int = 50


class SampleIn(BaseModel):
    recorded_at: datetime
    engine_hours: Decimal | None = None
    idle_hours: Decimal | None = None
    fuel_used_l: Decimal | None = None
    fuel_level_pct: Decimal | None = None
    odometer_km: Decimal | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    engine_status: str | None = Field(default=None, max_length=30)
    fault_codes: list[str] = Field(default_factory=list)


class IngestIn(BaseModel):
    samples: list[SampleIn] = Field(min_length=1, max_length=_MAX_SAMPLES)


class AllocateIn(BaseModel):
    date_from: date
    date_to: date
    project_id: uuid.UUID | None = None


def _service(session: SessionDep) -> TelematicsService:
    return TelematicsService(session)


def _device_out(d: Any, token: str | None = None) -> DeviceResponse:
    return DeviceResponse(
        id=d.id,
        equipment_id=d.equipment_id,
        label=d.label,
        token_prefix=d.token_prefix,
        active=d.active,
        last_seen_at=d.last_seen_at,
        token=token,
    )


async def _read_upload(file: UploadFile) -> bytes:
    payload = await file.read(_MAX_UPLOAD + 1)
    if len(payload) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="file_too_large")
    return payload


@router.post("/devices/", response_model=DeviceResponse, status_code=201)
async def create_device(
    data: DeviceCreate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: TelematicsService = Depends(_service),
) -> DeviceResponse:
    try:
        device, token = await service.create_device(data.equipment_id, data.label)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _device_out(device, token)


@router.get("/devices/", response_model=DeviceListResponse)
async def list_devices(
    equipment_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: TelematicsService = Depends(_service),
) -> DeviceListResponse:
    rows, total = await service.list_devices(equipment_id, offset, limit)
    return DeviceListResponse(items=[_device_out(d) for d in rows], total=total, offset=offset, limit=limit)


@router.post("/devices/{device_id}/revoke", status_code=204)
async def revoke_device(
    device_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: TelematicsService = Depends(_service),
) -> None:
    try:
        await service.revoke_device(device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ingest/")
async def device_ingest(
    request: Request,
    data: IngestIn,
    x_device_token: str | None = Header(default=None),
    service: TelematicsService = Depends(_service),
) -> dict[str, Any]:
    """Machine data from one device, authenticated by its own token (no user session)."""
    allowed, _remaining = device_ingest_limiter.is_allowed(client_identifier(request))
    if not allowed:
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": "60"})
    device = await service.authenticate(x_device_token)
    if device is None:
        raise HTTPException(status_code=401, detail="invalid_device_token")
    samples = [TelematicsSample(equipment_ref="", **s.model_dump()) for s in data.samples]
    return await service.ingest(samples, source="rest", equipment_id=device.equipment_id, device=device)


@router.post("/import/aemp/")
async def import_aemp(
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("equipment.record_telemetry")),
    service: TelematicsService = Depends(_service),
) -> dict[str, Any]:
    try:
        samples = parse_aemp(await _read_upload(file))
    except TelematicsParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await service.ingest(samples[:_MAX_SAMPLES], source="aemp")
    result["parsed"] = len(samples)
    return result


@router.post("/import/csv/")
async def import_csv(
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("equipment.record_telemetry")),
    service: TelematicsService = Depends(_service),
) -> dict[str, Any]:
    try:
        samples, rejected = parse_csv((await _read_upload(file)).decode("utf-8-sig", errors="replace"))
    except TelematicsParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await service.ingest(samples[:_MAX_SAMPLES], source="csv")
    result["parsed"] = len(samples)
    result["rejected"] = rejected[:100]
    return result


def _window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or datetime.now(UTC).date()
    return (date_from or end - timedelta(days=13)), end


@router.get("/utilisation/")
async def utilisation(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    _perm: None = Depends(RequirePermission("equipment.read")),
) -> dict[str, Any]:
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    start, end = _window(date_from, date_to)
    return await TelematicsService(session).utilisation(start, end, project_id)


@router.post("/allocate/")
async def allocate(
    data: AllocateIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("equipment.update")),
) -> dict[str, Any]:
    if data.date_to < data.date_from:
        raise HTTPException(status_code=422, detail="date_to_before_date_from")
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    return await TelematicsService(session).allocate(data.date_from, data.date_to, data.project_id)


@router.get("/validation/")
async def validation(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    idle_threshold: Decimal = Query(default=DEFAULT_IDLE_THRESHOLD, gt=0, le=1),
    _perm: None = Depends(RequirePermission("equipment.read")),
) -> dict[str, Any]:
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    payload = await TelematicsService(session).validation_payload(project_id, idle_threshold)
    results = await run_rules(payload)
    failed = [r for r in results if not r["passed"]]
    return {"results": results, "failed": len(failed), "machines": len(payload["machines"])}
