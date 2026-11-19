# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey calculation routes, included in the survey register router (``/api/v1/survey-core``).

Endpoints:
    GET  /calc/classes                       - closure and corner classes of the caller's markets
    POST /calc/cogo                          - one COGO computation (nothing saved)
    POST /calc/field-traverse                - field traverse closure and adjustment (nothing saved)
    POST /calc/level-book                    - level book reduction (nothing saved)
    POST /projects/{project_id}/computed-points - keep computed points with method and inputs
    POST /projects/{project_id}/field-traverses - keep a field traverse, optionally its stations as control
    POST /projects/{project_id}/level-books  - keep a level book, optionally its RLs on matching points
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.survey_core.calc_schemas import (
    CalcClassesOut,
    CogoRequest,
    CogoResult,
    ComputedPointsSave,
    FieldTraverseIn,
    FieldTraverseOut,
    LevelBookIn,
    LevelBookOut,
    SavedPoints,
)
from app.modules.survey_core.calc_service import CalcService, classes, compute_cogo

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)


@router.get("/calc/classes", response_model=CalcClassesOut, dependencies=_READ)
async def calc_classes(markets: ActiveMarkets) -> CalcClassesOut:
    return classes(markets)


@router.post("/calc/cogo", response_model=CogoResult, dependencies=_READ)
async def calc_cogo(body: CogoRequest, locale: str = _LOCALE) -> CogoResult:
    return await compute_cogo(body, locale)


@router.post("/calc/field-traverse", response_model=FieldTraverseOut, dependencies=_READ)
async def calc_field_traverse(body: FieldTraverseIn, markets: ActiveMarkets, locale: str = _LOCALE) -> FieldTraverseOut:
    return await CalcService.compute_traverse(body, markets, None, None, locale)


@router.post("/calc/level-book", response_model=LevelBookOut, dependencies=_READ)
async def calc_level_book(body: LevelBookIn, markets: ActiveMarkets, locale: str = _LOCALE) -> LevelBookOut:
    return await CalcService.compute_level_book(body, markets, None, locale)


@router.post(
    "/projects/{project_id}/computed-points",
    response_model=SavedPoints,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def save_computed_points(
    project_id: uuid.UUID, body: ComputedPointsSave, session: SessionDep, user_id: CurrentUserId
) -> SavedPoints:
    await verify_project_access(project_id, user_id, session)
    return await CalcService(session).save_points(project_id, body, user_id)


@router.post(
    "/projects/{project_id}/field-traverses",
    response_model=FieldTraverseOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_field_traverse(
    project_id: uuid.UUID,
    body: FieldTraverseIn,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: str = _LOCALE,
) -> FieldTraverseOut:
    await verify_project_access(project_id, user_id, session)
    return await CalcService(session).create_traverse(project_id, body, markets, user_id, locale)


@router.post(
    "/projects/{project_id}/level-books",
    response_model=LevelBookOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_level_book(
    project_id: uuid.UUID,
    body: LevelBookIn,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: str = _LOCALE,
) -> LevelBookOut:
    await verify_project_access(project_id, user_id, session)
    return await CalcService(session).create_level_book(project_id, body, markets, user_id, locale)
