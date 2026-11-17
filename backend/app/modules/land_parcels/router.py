# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels API routes (mounted at ``/api/v1/land-parcels``).

Endpoints:
    GET    /projects/{project_id}/profile          - parcel id label, rounding, export formats (active pack)
    GET    /projects/{project_id}/settings         - PAR thresholds;  PUT to change them (audited)
    GET    /projects/{project_id}/parcels          - the schedule with areas and findings per parcel
    POST   /projects/{project_id}/parcels          - add a parcel with typed boundary points
    GET    /projects/{project_id}/summary          - KPIs
    POST   /projects/{project_id}/validate         - the ``land_parcels`` rule set
    POST   /projects/{project_id}/import/preview   - read a GeoJSON / Shapefile zip, nothing saved
    POST   /projects/{project_id}/import           - import parcels or a work zone
    GET    /projects/{project_id}/export?format=   - geojson | shapefile | dxf | a pack format
    GET    /projects/{project_id}/schedule.pdf     - parcel schedule
    GET    /projects/{project_id}/plan             - GeoJSON (WGS 84) for the map
    GET    /projects/{project_id}/parties          - parties;  POST to add one
    GET    /projects/{project_id}/rights           - all rights of the project
    GET    /projects/{project_id}/work-zones       - work zones
    GET    /parcels/{parcel_id}                    - one parcel with points and rights
    PATCH  /parcels/{parcel_id}                    - change status, cost, legal area (audited)
    PUT    /parcels/{parcel_id}/points             - replace the boundary points
    DELETE /parcels/{parcel_id}
    POST   /parcels/{parcel_id}/rights             - add a right
    POST   /parcels/{parcel_id}/send-to-boq        - compensation into a BOQ position (survey.confirm)
    PATCH  /parties/{party_id}, DELETE /parties/{party_id}, DELETE /rights/{right_id}, DELETE /work-zones/{zone_id}
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.core.active_markets import ActiveMarkets
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_current_user_payload,
    verify_project_access,
)
from app.modules.land_parcels.schemas import (
    BoundaryPointIn,
    ImportPreview,
    ImportRequest,
    ImportResult,
    ParcelCreate,
    ParcelDetail,
    ParcelOut,
    ParcelSummary,
    ParcelUpdate,
    PartyIn,
    PartyOut,
    ProfileOut,
    RightIn,
    RightOut,
    SendToBoqRequest,
    SendToBoqResult,
    SettingsIn,
    SettingsOut,
    ValidationReportOut,
    WorkZoneOut,
)
from app.modules.land_parcels.service import ParcelService
from app.modules.survey_core.permissions import require_survey_confirm

router = APIRouter(tags=["land_parcels"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
Payload = Annotated[dict[str, Any], Depends(get_current_user_payload)]
Locale = Annotated[str, Query(max_length=10)]


class PointsIn(BaseModel):
    points: list[BoundaryPointIn] = Field(max_length=2000)


class SendBody(SendToBoqRequest):
    #: The new position's text, in the user's language.
    description: str = Field("", max_length=2000)


async def _parcel(service: ParcelService, parcel_id: uuid.UUID, user_id: str) -> Any:
    parcel = await service.get_parcel(parcel_id)
    await verify_project_access(parcel.project_id, user_id, service.session)
    return parcel


@router.get("/projects/{project_id}/profile", response_model=ProfileOut, dependencies=_READ)
async def get_profile(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ProfileOut:
    await verify_project_access(project_id, user_id, session)
    service = ParcelService(session)
    return service.profile_out(await service.profile(project_id, markets))


@router.get("/projects/{project_id}/settings", response_model=SettingsOut, dependencies=_READ)
async def get_settings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SettingsOut:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).settings(project_id)


@router.put("/projects/{project_id}/settings", response_model=SettingsOut, dependencies=_WRITE)
async def put_settings(
    project_id: uuid.UUID, body: SettingsIn, session: SessionDep, user_id: CurrentUserId
) -> SettingsOut:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).set_settings(project_id, body, user_id)


@router.get("/projects/{project_id}/parcels", response_model=list[ParcelOut], dependencies=_READ)
async def list_parcels(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: Locale = "en"
) -> list[ParcelOut]:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).list_parcels(project_id, markets, locale)


@router.post(
    "/projects/{project_id}/parcels",
    response_model=ParcelDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_parcel(
    project_id: uuid.UUID, body: ParcelCreate, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ParcelDetail:
    await verify_project_access(project_id, user_id, session)
    service = ParcelService(session)
    parcel = await service.create_parcel(project_id, body, user_id)
    return await service.detail(parcel, markets, "en")


@router.get("/projects/{project_id}/summary", response_model=ParcelSummary, dependencies=_READ)
async def summary(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ParcelSummary:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).summary(project_id, markets)


@router.post("/projects/{project_id}/validate", response_model=ValidationReportOut, dependencies=_READ)
async def validate(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: Locale = "en"
) -> ValidationReportOut:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).validate(project_id, markets, locale)


@router.post("/projects/{project_id}/import/preview", response_model=ImportPreview, dependencies=_WRITE)
async def import_preview(
    project_id: uuid.UUID, body: ImportRequest, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ImportPreview:
    """What an import would read; nothing is saved."""
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).preview(project_id, body, markets)


@router.post(
    "/projects/{project_id}/import",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def import_file(
    project_id: uuid.UUID, body: ImportRequest, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ImportResult:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).import_file(project_id, body, user_id, markets)


@router.get("/projects/{project_id}/export", dependencies=_READ, response_model=None)
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    format: str = Query("geojson", max_length=30, pattern="^[a-z0-9_]+$"),  # noqa: A002
) -> Response:
    await verify_project_access(project_id, user_id, session)
    data, filename, media = await ParcelService(session).export(project_id, format, markets)
    return Response(
        content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/projects/{project_id}/schedule.pdf", dependencies=_READ, response_model=None)
async def schedule_pdf(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    payload: Payload,
    locale: Locale = "en",
) -> Response:
    await verify_project_access(project_id, user_id, session)
    who = str(payload.get("full_name") or payload.get("email") or payload.get("sub") or "")
    data = await ParcelService(session).schedule_pdf(project_id, markets, locale, who)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="parcel_schedule.pdf"'},
    )


@router.get("/projects/{project_id}/plan", dependencies=_READ, response_model=None)
async def plan(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets) -> dict:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).plan(project_id, markets)


@router.get("/projects/{project_id}/parties", response_model=list[PartyOut], dependencies=_READ)
async def list_parties(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[PartyOut]:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).list_parties(project_id)


@router.post(
    "/projects/{project_id}/parties", response_model=PartyOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def create_party(project_id: uuid.UUID, body: PartyIn, session: SessionDep, user_id: CurrentUserId) -> PartyOut:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).create_party(project_id, body, user_id)


@router.get("/projects/{project_id}/rights", response_model=list[RightOut], dependencies=_READ)
async def list_rights(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[RightOut]:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).list_rights(project_id)


@router.get("/projects/{project_id}/work-zones", response_model=list[WorkZoneOut], dependencies=_READ)
async def list_zones(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[WorkZoneOut]:
    await verify_project_access(project_id, user_id, session)
    return await ParcelService(session).list_zones(project_id)


@router.get("/parcels/{parcel_id}", response_model=ParcelDetail, dependencies=_READ)
async def get_parcel(
    parcel_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: Locale = "en"
) -> ParcelDetail:
    service = ParcelService(session)
    return await service.detail(await _parcel(service, parcel_id, user_id), markets, locale)


@router.patch("/parcels/{parcel_id}", response_model=ParcelDetail, dependencies=_WRITE)
async def update_parcel(
    parcel_id: uuid.UUID, body: ParcelUpdate, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets,
    locale: Locale = "en",
) -> ParcelDetail:  # fmt: skip
    service = ParcelService(session)
    parcel = await service.update_parcel(await _parcel(service, parcel_id, user_id), body, user_id)
    return await service.detail(parcel, markets, locale)


@router.put("/parcels/{parcel_id}/points", response_model=ParcelDetail, dependencies=_WRITE)
async def put_points(
    parcel_id: uuid.UUID, body: PointsIn, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ParcelDetail:
    service = ParcelService(session)
    parcel = await service.set_points(await _parcel(service, parcel_id, user_id), body.points, user_id)
    return await service.detail(parcel, markets, "en")


@router.delete("/parcels/{parcel_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_parcel(parcel_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = ParcelService(session)
    await service.delete_parcel(await _parcel(service, parcel_id, user_id), user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/parcels/{parcel_id}/rights", response_model=RightOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def add_right(parcel_id: uuid.UUID, body: RightIn, session: SessionDep, user_id: CurrentUserId) -> RightOut:
    service = ParcelService(session)
    return await service.add_right(await _parcel(service, parcel_id, user_id), body, user_id)


@router.post(
    "/parcels/{parcel_id}/send-to-boq",
    response_model=SendToBoqResult,
    dependencies=[*_WRITE, Depends(require_survey_confirm)],
)
async def send_to_boq(
    parcel_id: uuid.UUID, body: SendBody, session: SessionDep, user_id: CurrentUserId
) -> SendToBoqResult:
    service = ParcelService(session)
    parcel = await _parcel(service, parcel_id, user_id)
    return await service.send_to_boq(parcel, body, body.description, user_id)


@router.patch("/parties/{party_id}", response_model=PartyOut, dependencies=_WRITE)
async def update_party(party_id: uuid.UUID, body: PartyIn, session: SessionDep, user_id: CurrentUserId) -> PartyOut:
    service = ParcelService(session)
    party = await service.get_party(party_id)
    await verify_project_access(party.project_id, user_id, session)
    return await service.update_party(party, body, user_id)


@router.delete("/parties/{party_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_party(party_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = ParcelService(session)
    party = await service.get_party(party_id)
    await verify_project_access(party.project_id, user_id, session)
    await service.delete_party(party, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/rights/{right_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_right(right_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = ParcelService(session)
    right = await service.get_right(right_id)
    await verify_project_access(right.project_id, user_id, session)
    await service.delete_right(right, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/work-zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_zone(zone_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = ParcelService(session)
    zone = await service.get_zone(zone_id)
    await verify_project_access(zone.project_id, user_id, session)
    await service.delete_zone(zone, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
