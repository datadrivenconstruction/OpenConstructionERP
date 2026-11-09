# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors routes​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ (mounted at /api/v1/site_sensors/).

GET   /devices/                     - Devices of a project (project_id=, kind=)
POST  /devices/                     - Create a device
PATCH /devices/{id}                 - Update a device
POST  /devices/{id}/token           - Issue a new ingest token (shown once)
POST  /devices/{id}/readings        - Add readings as a user (source manual or import), with a note each
GET   /devices/{id}/readings        - Raw and hourly readings in a window, raw with source and author
PATCH /devices/{id}/readings/manual - Change a hand-entered reading (its author or a manager)
DELETE /devices/{id}/readings/manual?recorded_at= - Delete a hand-entered reading (its author or a manager)
GET   /devices/{id}/readings/audit  - Who added, changed or deleted hand-entered readings
GET   /devices/{id}/maturity        - Maturity, strength estimate, hours to strike strength
POST  /ingest/                      - Device ingest, header ``X-Device-Token``
GET   /mixes/  POST /mixes/         - Concrete mix curves
PATCH /mixes/{id}                   - Own datum temperature, method constants, curve or strike strength
GET   /mixes/{id}/calibration       - Calibration cubes of a mix
PUT   /mixes/{id}/calibration       - Replace the cubes and refit the curve (a, b, R²)
GET   /alerts/                      - Alerts (project_id=, status=)
POST  /alerts/{id}/acknowledge      - Acknowledge with a note
POST  /alerts/{id}/links            - Link a daily diary, inspection or punch list item
GET   /strips/  POST /strips/       - Planned formwork strikes
POST  /strips/{id}/strike           - Record the strike (a reason is required below target)
GET   /strips/{id}/record           - Pour record of a strike, format=csv|pdf
GET   /context/                     - Country, unit system and the pours ready to strike
GET   /sparklines/                  - Last 24 h per device, hourly, with its limit
GET   /summary/                     - Dashboard numbers
GET   /validation/                  - Rule results (site_sensors)
POST  /maintenance/downsample       - Fold old raw readings into hourly rows
POST  /devices/{id}/evidence        - File a hashed CSV and PDF of readings (evidence_routes.py)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.core.rate_limiter import client_identifier, device_ingest_limiter
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_current_user_payload,
    verify_project_access,
)
from app.modules.site_sensors.evidence_routes import router as evidence_router
from app.modules.site_sensors.schemas import (
    AcknowledgeIn,
    AlertLinksIn,
    AlertListResponse,
    AlertResponse,
    CalibrationIn,
    CalibrationPointOut,
    CalibrationResponse,
    DeviceCreate,
    DeviceListResponse,
    DeviceResponse,
    DeviceUpdate,
    MixCreate,
    MixListResponse,
    MixResponse,
    MixUpdate,
    ReadingAuditListResponse,
    ReadingEdit,
    ReadingsIn,
    StrikeIn,
    StripCreate,
    StripListResponse,
    StripResponse,
    TokenResponse,
    UserReadingsIn,
)
from app.modules.site_sensors.service import SiteSensorsService
from app.modules.site_sensors.validators import run_rules

router = APIRouter(tags=["site-sensors"])
router.include_router(evidence_router)

UserPayload = Annotated[dict[str, Any], Depends(get_current_user_payload)]


def _is_manager(payload: dict[str, Any]) -> bool:
    """A manager may change or delete anybody's hand-entered readings."""
    from app.core.permissions import permission_registry

    role = str(payload.get("role", ""))
    return (
        role == "admin"
        or "site_sensors.manage" in (payload.get("permissions") or [])
        or permission_registry.role_has_permission(role, "site_sensors.manage")
    )


async def _device_out(service: SiteSensorsService, device: Any) -> DeviceResponse:
    out = DeviceResponse.model_validate(device)
    return out.model_copy(update=await service.describe_limit(device))


async def _device_for_user(service: SiteSensorsService, device_id: uuid.UUID, user_id: str) -> Any:
    try:
        device = await service.get_device(device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await verify_project_access(device.project_id, user_id, service.session)
    return device


@router.get("/devices/", response_model=DeviceListResponse)
async def list_devices(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    kind: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> DeviceListResponse:
    await verify_project_access(project_id, user_id, session)
    service = SiteSensorsService(session)
    devices = await service.repo.devices(project_id, kind)
    page = [await _device_out(service, d) for d in devices[offset : offset + limit]]
    return DeviceListResponse(items=page, total=len(devices), offset=offset, limit=limit)


@router.post("/devices/", response_model=DeviceResponse, status_code=201)
async def create_device(
    data: DeviceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> DeviceResponse:
    await verify_project_access(data.project_id, user_id, session)
    service = SiteSensorsService(session)
    return await _device_out(service, await service.create_device(data))


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
    try:
        device = await service.update_device(device_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _device_out(service, device)


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
    data: UserReadingsIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.record")),
) -> dict[str, Any]:
    service = SiteSensorsService(session)
    device = await _device_for_user(service, device_id, user_id)
    return await service.add_user_readings(device, data.readings, data.source, user_id)


def _reading_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.patch("/devices/{device_id}/readings/manual")
async def edit_reading(
    device_id: uuid.UUID,
    data: ReadingEdit,
    user_id: CurrentUserId,
    payload: UserPayload,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.record")),
) -> dict[str, Any]:
    service = SiteSensorsService(session)
    device = await _device_for_user(service, device_id, user_id)
    try:
        return await service.edit_reading(
            device, data.recorded_at, data.value, data.note, user_id, is_manager=_is_manager(payload)
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _reading_error(exc) from exc


@router.delete("/devices/{device_id}/readings/manual", status_code=204)
async def delete_reading(
    device_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: UserPayload,
    session: SessionDep,
    recorded_at: datetime = Query(...),
    _perm: None = Depends(RequirePermission("site_sensors.record")),
) -> Response:
    service = SiteSensorsService(session)
    device = await _device_for_user(service, device_id, user_id)
    try:
        await service.delete_reading(device, recorded_at, user_id, is_manager=_is_manager(payload))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _reading_error(exc) from exc
    return Response(status_code=204)


@router.get("/devices/{device_id}/readings/audit", response_model=ReadingAuditListResponse)
async def reading_audit(
    device_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> ReadingAuditListResponse:
    service = SiteSensorsService(session)
    await _device_for_user(service, device_id, user_id)
    rows = [{**r, "created_at": r["at"]} for r in await service.reading_audit(device_id)]
    return ReadingAuditListResponse.model_validate({"items": rows, "total": len(rows), "limit": 200})


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
    request: Request,
    data: ReadingsIn,
    session: SessionDep,
    x_device_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Readings from one sensor, authenticated by its own token (no user session)."""
    allowed, _remaining = device_ingest_limiter.is_allowed(client_identifier(request))
    if not allowed:
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": "60"})
    service = SiteSensorsService(session)
    device = await service.authenticate(x_device_token)
    if device is None:
        raise HTTPException(status_code=401, detail="invalid_device_token")
    return await service.ingest(device, [(r.recorded_at, r.value) for r in data.readings], _frequencies(data))


def _frequencies(data: ReadingsIn) -> dict[datetime, float]:
    return {r.recorded_at: r.frequency_hz for r in data.readings if r.frequency_hz is not None}


@router.get("/mixes/", response_model=MixListResponse)
async def list_mixes(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> MixListResponse:
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    rows = await SiteSensorsService(session).list_mixes(project_id)
    page = [MixResponse.model_validate(m) for m in rows[offset : offset + limit]]
    return MixListResponse(items=page, total=len(rows), offset=offset, limit=limit)


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


@router.patch("/mixes/{mix_id}", response_model=MixResponse)
async def update_mix(
    mix_id: uuid.UUID,
    data: MixUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> MixResponse:
    service = SiteSensorsService(session)
    mix = await _mix_for_user(service, mix_id, user_id)
    if mix.project_id is None:
        raise HTTPException(status_code=403, detail="shared_mix_read_only")
    return MixResponse.model_validate(await service.update_mix(mix_id, data))


async def _mix_for_user(service: SiteSensorsService, mix_id: uuid.UUID, user_id: str) -> Any:
    try:
        mix = await service.get_mix(mix_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if mix.project_id is not None:
        await verify_project_access(mix.project_id, user_id, service.session)
    return mix


@router.get("/mixes/{mix_id}/calibration", response_model=CalibrationResponse)
async def get_calibration(
    mix_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> CalibrationResponse:
    service = SiteSensorsService(session)
    mix = await _mix_for_user(service, mix_id, user_id)
    points = await service.repo.calibration(mix.id)
    return CalibrationResponse(
        mix=MixResponse.model_validate(mix), points=[CalibrationPointOut.model_validate(p) for p in points]
    )


@router.put("/mixes/{mix_id}/calibration", response_model=CalibrationResponse)
async def put_calibration(
    mix_id: uuid.UUID,
    data: CalibrationIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.manage")),
) -> CalibrationResponse:
    service = SiteSensorsService(session)
    await _mix_for_user(service, mix_id, user_id)
    mix = await service.set_calibration(mix_id, data.points)
    points = await service.repo.calibration(mix.id)
    return CalibrationResponse(
        mix=MixResponse.model_validate(mix), points=[CalibrationPointOut.model_validate(p) for p in points]
    )


@router.get("/alerts/", response_model=AlertListResponse)
async def list_alerts(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> AlertListResponse:
    await verify_project_access(project_id, user_id, session)
    service = SiteSensorsService(session)
    await service.sweep_offline(project_id)
    rows = await service.repo.alerts(project_id, status)
    page = [AlertResponse.model_validate(a) for a in rows[offset : offset + limit]]
    return AlertListResponse(items=page, total=len(rows), offset=offset, limit=limit)


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


@router.get("/strips/", response_model=StripListResponse)
async def list_strips(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> StripListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await SiteSensorsService(session).list_strips(project_id)
    page = [StripResponse.model_validate(s) for s in rows[offset : offset + limit]]
    return StripListResponse(items=page, total=len(rows), offset=offset, limit=limit)


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
    try:
        struck = await SiteSensorsService(session).strike(strip_id, data.struck_at, data.reason, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StripResponse.model_validate(struck)


@router.get("/strips/{strip_id}/record")
async def pour_record(
    strip_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    format: str = Query(default="pdf", pattern="^(csv|pdf)$"),  # noqa: A002
    lang: str = Query(default="en", max_length=10),
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> Response:
    from app.modules.site_sensors.models import FormworkStrip
    from app.modules.site_sensors.pour_record import pour_record_csv, pour_record_pdf, written_language

    strip = await session.get(FormworkStrip, strip_id)
    if strip is None:
        raise HTTPException(status_code=404, detail="strip_not_found")
    await verify_project_access(strip.project_id, user_id, session)
    record = await SiteSensorsService(session).pour_record(strip_id)
    stem = f"pour-record-{record['element'] or record['device_code']}".replace(" ", "_")[:80]
    if format == "csv":
        return Response(
            content=pour_record_csv(record, lang),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{stem}.csv"',
                "Content-Language": written_language(lang),
            },
        )
    from app.modules.site_sensors.evidence import file_pour_record

    pdf = pour_record_pdf(record, lang)
    await file_pour_record(
        session,
        project_id=strip.project_id,
        strip_id=strip.id,
        user_id=str(user_id),
        filename=f"{stem}.pdf",
        content=pdf,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.pdf"',
            "Content-Language": written_language(lang),
        },
    )


@router.get("/context/")
async def sensor_context(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await SiteSensorsService(session).context(project_id)


@router.get("/sparklines/")
async def sparklines(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_sensors.read")),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await SiteSensorsService(session).sparklines(project_id)


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
