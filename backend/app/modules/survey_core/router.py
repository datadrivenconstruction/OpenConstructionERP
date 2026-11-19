# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register API routes (mounted at ``/api/v1/survey-core``).

Endpoints:
    GET    /crs/search?q=                         - EPSG systems by code or name
    POST   /transform                             - transform points between two EPSG systems
    GET    /projects/{project_id}/crs             - project CRS, picker suggestions, point count
    PUT    /projects/{project_id}/crs             - set or change the project CRS (audited)
    POST   /projects/{project_id}/crs/confirm     - confirm a detected CRS (survey.confirm)
    POST   /projects/{project_id}/import/preview  - read a point file without saving anything
    POST   /projects/{project_id}/import          - import a point file as a new point set
    GET    /projects/{project_id}/points          - points, filtered by kind, set, code, text
    GET    /projects/{project_id}/point-sets      - imported point files
    GET    /projects/{project_id}/summary         - register KPIs
    POST   /projects/{project_id}/validate        - the ``survey_core`` rule set
    POST   /point-sets/{set_id}/declare-crs       - say which EPSG a set without one is in
    DELETE /point-sets/{set_id}                   - remove a point set and its points
    GET    /projects/{project_id}/plan            - survey points as GeoJSON (WGS 84) for the map
    GET    /projects/{project_id}/traverses       - closed traverses and level runs
    POST   /projects/{project_id}/traverses       - compute a traverse from its legs, or a level run
    DELETE /traverses/{traverse_id}               - remove a traverse
    GET    /projects/{project_id}/profile         - survey thresholds in force for the project
    PUT    /projects/{project_id}/profile         - the project's own thresholds (survey.confirm)
    GET    /profile                               - the workspace default thresholds
    PUT    /profile                               - set the workspace default (survey.confirm)
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
from app.modules.survey_core.crs import search
from app.modules.survey_core.permissions import can_confirm, require_survey_confirm
from app.modules.survey_core.schemas import (
    CrsInfoListResponse,
    CrsInfoOut,
    ImportPreview,
    ImportRequest,
    ImportResult,
    PointListResponse,
    PointSetListResponse,
    PointSetOut,
    ProjectCrsOut,
    ProjectCrsSet,
    ProjectCrsState,
    RegisterSummary,
    SurveyProfileIn,
    SurveyProfileOut,
    TransformRequest,
    TransformResponse,
    TraverseCreate,
    TraverseListResponse,
    TraverseOut,
    ValidationReportOut,
)
from app.modules.survey_core.service import SurveyService

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_KIND = "^(|control|benchmark|topo|stake|asbuilt)$"

Payload = Annotated[dict[str, Any], Depends(get_current_user_payload)]


class DeclareCrs(BaseModel):
    epsg: int = Field(ge=1000, le=999999)


@router.get("/crs/search", response_model=CrsInfoListResponse, dependencies=_READ)
async def crs_search(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50)) -> CrsInfoListResponse:
    """EPSG systems whose code or name matches what the person typed."""
    rows = [CrsInfoOut(**vars(i)) for i in search(q, limit)]
    return CrsInfoListResponse(items=rows, total=len(rows), offset=0, limit=limit)


@router.post("/transform", response_model=TransformResponse, dependencies=_READ)
async def transform(body: TransformRequest) -> TransformResponse:
    """Coordinates from one EPSG system in another, with both systems named."""
    return SurveyService.transform(body)


@router.get("/projects/{project_id}/crs", response_model=ProjectCrsState, dependencies=_READ)
async def get_crs(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> ProjectCrsState:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).crs_state(project_id, markets)


@router.put("/projects/{project_id}/crs", response_model=ProjectCrsOut, dependencies=_WRITE)
async def put_crs(
    project_id: uuid.UUID, body: ProjectCrsSet, session: SessionDep, user_id: CurrentUserId, payload: Payload
) -> ProjectCrsOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).set_crs(project_id, body, user_id, can_confirm(payload))


@router.post(
    "/projects/{project_id}/crs/confirm",
    response_model=ProjectCrsOut,
    dependencies=[*_READ, Depends(require_survey_confirm)],
)
async def confirm_crs(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ProjectCrsOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).confirm_crs(project_id, user_id)


@router.post("/projects/{project_id}/import/preview", response_model=ImportPreview, dependencies=_WRITE)
async def import_preview(
    project_id: uuid.UUID, body: ImportRequest, session: SessionDep, user_id: CurrentUserId
) -> ImportPreview:
    """What an import would read; nothing is saved."""
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).preview(project_id, body)


@router.post(
    "/projects/{project_id}/import",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def import_points(
    project_id: uuid.UUID, body: ImportRequest, session: SessionDep, user_id: CurrentUserId
) -> ImportResult:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).import_points(project_id, body, user_id)


@router.get("/projects/{project_id}/points", response_model=PointListResponse, dependencies=_READ)
async def list_points(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    kind: str = Query("", pattern=_KIND),
    set_id: uuid.UUID | None = None,
    code: str = Query("", max_length=64),
    q: str = Query("", max_length=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> PointListResponse:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).list_points(
        project_id, kind=kind, set_id=set_id, code=code.strip(), q=q.strip(), offset=offset, limit=limit
    )


@router.get("/projects/{project_id}/point-sets", response_model=PointSetListResponse, dependencies=_READ)
async def list_sets(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> PointSetListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await SurveyService(session).list_sets(project_id)
    return PointSetListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.get("/projects/{project_id}/summary", response_model=RegisterSummary, dependencies=_READ)
async def summary(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> RegisterSummary:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).summary(project_id)


@router.post("/projects/{project_id}/validate", response_model=ValidationReportOut, dependencies=_READ)
async def validate(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query("en", max_length=10),
) -> ValidationReportOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).validate(project_id, locale)


@router.post("/point-sets/{set_id}/declare-crs", response_model=PointSetOut, dependencies=_WRITE)
async def declare_crs(set_id: uuid.UUID, body: DeclareCrs, session: SessionDep, user_id: CurrentUserId) -> PointSetOut:
    service = SurveyService(session)
    point_set = await service.get_set(set_id)
    await verify_project_access(point_set.project_id, user_id, session)
    return await service.declare_set_crs(point_set, body.epsg)


@router.delete("/point-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_set(set_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = SurveyService(session)
    point_set = await service.get_set(set_id)
    await verify_project_access(point_set.project_id, user_id, session)
    await service.delete_set(point_set)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/traverses", response_model=TraverseListResponse, dependencies=_READ)
async def list_traverses(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> TraverseListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await SurveyService(session).list_traverses(project_id)
    return TraverseListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/traverses",
    response_model=TraverseOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_traverse(
    project_id: uuid.UUID, body: TraverseCreate, session: SessionDep, user_id: CurrentUserId
) -> TraverseOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).create_traverse(project_id, body, user_id)


@router.delete("/traverses/{traverse_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_traverse(traverse_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = SurveyService(session)
    row = await service.get_traverse(traverse_id)
    await verify_project_access(row.project_id, user_id, session)
    await service.delete_traverse(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/profile", response_model=SurveyProfileOut, dependencies=_READ)
async def get_profile(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SurveyProfileOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).profile(project_id)


@router.put(
    "/projects/{project_id}/profile",
    response_model=SurveyProfileOut,
    dependencies=[*_WRITE, Depends(require_survey_confirm)],
)
async def put_profile(
    project_id: uuid.UUID, body: SurveyProfileIn, session: SessionDep, user_id: CurrentUserId
) -> SurveyProfileOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).set_profile(project_id, body, user_id)


@router.get("/profile", response_model=SurveyProfileOut, dependencies=_READ)
async def get_default_profile(session: SessionDep) -> SurveyProfileOut:
    """The workspace default (Settings > Modules > Survey & Land)."""
    return await SurveyService(session).profile(None)


@router.put("/profile", response_model=SurveyProfileOut, dependencies=[*_WRITE, Depends(require_survey_confirm)])
async def put_default_profile(body: SurveyProfileIn, session: SessionDep, user_id: CurrentUserId) -> SurveyProfileOut:
    return await SurveyService(session).set_profile(None, body, user_id)


@router.get("/projects/{project_id}/plan", dependencies=_READ)
async def plan(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await SurveyService(session).plan(project_id)


# Point detail, bulk actions, export and control checks live in their own file; same prefix and permissions.
from app.modules.survey_core.register_router import router as _register_router  # noqa: E402

router.include_router(_register_router)
