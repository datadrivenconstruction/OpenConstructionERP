# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors routes​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ (mounted at /api/v1/site_sensors/).

GET   /devices/                     - Devices of a project (project_id=, kind=)
POST  /devices/                     - Create a device
PATCH /devices/{id}                 - Update a device
POST  /devices/{id}/token           - Issue a new ingest token (shown once)
POST  /devices/{id}/readings        - Add readings as a user (manual or CSV import on the client)
GET   /devices/{id}/readings        - Raw and hourly readings in a window
GET   /devices/{id}/maturity        - Maturity, strength estimate, hours to strike strength
POST  /ingest/                      - Device ingest, header ``X-Device-Token``
GET   /mixes/  POST /mixes/         - Concrete mix curves
GET   /alerts/                      - Alerts (project_id=, status=)
POST  /alerts/{id}/acknowledge      - Acknowledge with a note
POST  /alerts/{id}/links            - Link a daily diary, inspection or punch list item
GET   /strips/  POST /strips/       - Planned formwork strikes
POST  /strips/{id}/strike           - Record the strike
GET   /summary/                     - Dashboard numbers
GET   /validation/                  - Rule results (site_sensors)
POST  /maintenance/downsample       - Fold old raw readings into hourly rows
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.site_sensors.schemas import (
    AcknowledgeIn,
    AlertLinksIn,
    AlertResponse,
    DeviceCreate,
    DeviceResponse,
    DeviceUpdate,
    MixCreate,
    MixResponse,
    ReadingsIn,
    StrikeIn,
    StripCreate,
    StripResponse,
    TokenResponse,
)
from app.modules.site_sensors.service import SiteSensorsService
from app.modules.site_sensors.validators import run_rules

router = APIRouter(tags=["site-sensors"])


async def _device_for_user(service: SiteSensorsService, device_id: uuid.UUID, user_id: str) -> Any:
    try:
        device = await service.get_device(device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await verify_project_access(device.project_id, user_id, service.session)
    return device


@router.get("/devices/", response_model=list[DeviceResponse])
async def list_devices(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    kind: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> list[DeviceResponse]:
    await verify_project_access(project_id, user_id, session)
    devices = await SiteSensorsService(session).repo.devices(project_id, kind)
    return [DeviceResponse.model_validate(d) for d in devices]


@router.post("/devices/", response_model=DeviceResponse, status_code=201)
async def create_device(
    data: DeviceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> DeviceResponse:
    await verify_project_access(data.project_id, user_id, session)
    return DeviceResponse.model_validate(await SiteSensorsService(session).create_device(data))


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: uuid.UUID,
    data: DeviceUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> DeviceResponse:
    service = SiteSensorsService(session)
    await _device_for_user(service, device_id, user_id)
    return DeviceResponse.model_validate(await service.update_device(device_id, data))


@router.post("/devices/{device_id}/token", response_model=TokenResponse)
async def issue_token(
    device_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> TokenResponse:
    service = SiteSensorsService(session)
    await _device_for_user(service, device_id, user_id)
    token = await service.issue_token(device_id)
    return TokenResponse(device_id=device_id, token=token, token_prefix=token[:10])


@router.post("/devices/{device_id}/readings")
async def add_readings(
    device_id: uuid.UUID,
    data: ReadingsIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.record")),
) -> dict[str, Any]:
    service = SiteSensorsService(session)
    device = await _device_for_user(service, device_id, user_id)
    return await service.ingest(device, [(r.recorded_at, r.value) for r in data.readings])


@router.get("/devices/{device_id}/readings")
async def get_readings(
    device_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, Any]:
    service = SiteSensorsService(session)
    await _device_for_user(service, device_id, user_id)
    return await service.readings(device_id, since, until)


@router.get("/devices/{device_id}/maturity")
async def get_maturity(
    device_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, Any]:
    service = SiteSensorsService(session)
    await _device_for_user(service, device_id, user_id)
    return await service.maturity(device_id)


@router.post("/ingest/")
async def device_ingest(
    data: ReadingsIn,
    session: SessionDep,
    x_device_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Readings from one sensor, authenticated by its own token (no user session)."""
    service = SiteSensorsService(session)
    device = await service.authenticate(x_device_token)
    if device is None:
        raise HTTPException(status_code=401, detail="invalid_device_token")
    return await service.ingest(device, [(r.recorded_at, r.value) for r in data.readings])


@router.get("/mixes/", response_model=list[MixResponse])
async def list_mixes(
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> list[MixResponse]:
    return [MixResponse.model_validate(m) for m in await SiteSensorsService(session).list_mixes(project_id)]


@router.post("/mixes/", response_model=MixResponse, status_code=201)
async def create_mix(
    data: MixCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> MixResponse:
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    return MixResponse.model_validate(await SiteSensorsService(session).create_mix(data))


@router.get("/alerts/", response_model=list[AlertResponse])
async def list_alerts(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> list[AlertResponse]:
    await verify_project_access(project_id, user_id, session)
    service = SiteSensorsService(session)
    await service.sweep_offline(project_id)
    return [AlertResponse.model_validate(a) for a in await service.repo.alerts(project_id, status)]


async def _alert_for_user(service: SiteSensorsService, alert_id: uuid.UUID, user_id: str) -> None:
    from app.modules.site_sensors.models import SensorAlert

    alert = await service.session.get(SensorAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert_not_found")
    await verify_project_access(alert.project_id, user_id, service.session)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge(
    alert_id: uuid.UUID,
    data: AcknowledgeIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.acknowledge")),
) -> AlertResponse:
    service = SiteSensorsService(session)
    await _alert_for_user(service, alert_id, user_id)
    return AlertResponse.model_validate(await service.acknowledge(alert_id, user_id, data.note))


@router.post("/alerts/{alert_id}/links", response_model=AlertResponse)
async def link_alert(
    alert_id: uuid.UUID,
    data: AlertLinksIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.acknowledge")),
) -> AlertResponse:
    service = SiteSensorsService(session)
    await _alert_for_user(service, alert_id, user_id)
    return AlertResponse.model_validate(await service.link(alert_id, data.model_dump()))


@router.get("/strips/", response_model=list[StripResponse])
async def list_strips(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> list[StripResponse]:
    await verify_project_access(project_id, user_id, session)
    return [StripResponse.model_validate(s) for s in await SiteSensorsService(session).list_strips(project_id)]


@router.post("/strips/", response_model=StripResponse, status_code=201)
async def create_strip(
    data: StripCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> StripResponse:
    service = SiteSensorsService(session)
    await _device_for_user(service, data.device_id, user_id)
    try:
        return StripResponse.model_validate(await service.create_strip(data))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/strips/{strip_id}/strike", response_model=StripResponse)
async def strike(
    strip_id: uuid.UUID,
    data: StrikeIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.record")),
) -> StripResponse:
    from app.modules.site_sensors.models import FormworkStrip

    strip = await session.get(FormworkStrip, strip_id)
    if strip is None:
        raise HTTPException(status_code=404, detail="strip_not_found")
    await verify_project_access(strip.project_id, user_id, session)
    return StripResponse.model_validate(await SiteSensorsService(session).strike(strip_id, data.struck_at))


@router.get("/summary/")
async def summary(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, Any]:
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        return await SiteSensorsService(session).summary(project_id)
    from app.dependencies import accessible_project_ids

    out: dict[str, Any] = {
        "devices": 0,
        "online": 0,
        "open_alerts": 0,
        "open_by_kind": {},
        "pours": [],
        "latest_alerts": [],
    }
    service = SiteSensorsService(session)
    ids = await accessible_project_ids(session, user_id)
    if ids is None:
        return await service.summary(None)
    for pid in sorted(ids):
        part = await service.summary(pid)
        for k in ("devices", "online", "open_alerts"):
            out[k] += part[k]
        for k, v in part["open_by_kind"].items():
            out["open_by_kind"][k] = out["open_by_kind"].get(k, 0) + v
        out["pours"] += part["pours"]
        out["latest_alerts"] += part["latest_alerts"]
    out["latest_alerts"] = sorted(out["latest_alerts"], key=lambda a: a["raised_at"], reverse=True)[:5]
    return out


@router.get("/validation/")
async def validation(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    results = await run_rules(await SiteSensorsService(session).validation_payload(project_id))
    return {"results": results, "failed": len([r for r in results if not r["passed"]])}


@router.post("/maintenance/downsample")
async def downsample(
    session: SessionDep,
    older_than_days: int = Query(default=30, ge=1, le=3650),
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> dict[str, int]:
    return {"folded": await SiteSensorsService(session).downsample(older_than_days)}
