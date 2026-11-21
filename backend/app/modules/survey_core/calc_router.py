# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey calculation routes, included in the survey register router (``/api/v1/survey-core``).

Endpoints:
    GET  /calc/classes                       - closure, corner and instrument classes of the caller's markets
    GET  /calc/demo                          - the riverside demo traverse and level book, ready to compute
    POST /calc/cogo                          - one COGO computation (nothing saved)
    POST /calc/field-traverse                - field traverse closure and adjustment (nothing saved)
    POST /calc/level-book                    - level book reduction (nothing saved)
    POST /calc/field-traverse/report         - adjustment report as PDF (nothing saved)
    POST /projects/{project_id}/computed-points - keep computed points with method and inputs
    POST /projects/{project_id}/field-traverses - keep a field traverse, optionally its stations as control
    POST /projects/{project_id}/level-books  - keep a level book, optionally its RLs on matching points
    GET  /projects/{project_id}/survey-links/{kind}/{target_id}       - diary entries and files of a record
    POST /projects/{project_id}/survey-links/{kind}/{target_id}/diary - record it in the day's site diary
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from app.core.active_markets import ActiveMarkets
from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.survey_core.calc_schemas import (
    CalcClassesOut,
    CalcDemoOut,
    CogoRequest,
    CogoResult,
    ComputedPointsSave,
    DiaryLinkIn,
    DiaryLinkOut,
    FieldTraverseIn,
    FieldTraverseOut,
    LevelBookIn,
    LevelBookOut,
    SavedPoints,
    SurveyLinkKind,
    SurveyLinksOut,
    TraverseReportIn,
)
from app.modules.survey_core.calc_service import CalcService, classes, compute_cogo, demo_inputs
from app.modules.survey_core.survey_links import SurveyLinkService

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)


@router.get("/calc/classes", response_model=CalcClassesOut, dependencies=_READ)
async def calc_classes(markets: ActiveMarkets) -> CalcClassesOut:
    return classes(markets)


@router.get("/calc/demo", response_model=CalcDemoOut, dependencies=_READ)
async def calc_demo() -> CalcDemoOut:
    return demo_inputs()


@router.post("/calc/field-traverse/report", dependencies=_READ)
async def calc_traverse_report(body: TraverseReportIn, markets: ActiveMarkets, locale: str = _LOCALE) -> Response:
    from app.modules.survey_core.traverse_report import render  # noqa: PLC0415

    out = await CalcService.compute_traverse(body.traverse, markets, None, None, locale)
    pdf = render(out, body.title, body.labels)
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.traverse.name)[:60] or "traverse"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}_adjustment.pdf"',
            "Content-Language": normalize_document_locale(locale, SUPPORTED_LOCALES, "en"),
        },
    )


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


@router.get("/projects/{project_id}/survey-links/{kind}/{target_id}", response_model=SurveyLinksOut, dependencies=_READ)
async def survey_links(
    project_id: uuid.UUID, kind: SurveyLinkKind, target_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> SurveyLinksOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyLinkService(session).links(project_id, kind, target_id)


@router.post(
    "/projects/{project_id}/survey-links/{kind}/{target_id}/diary",
    response_model=DiaryLinkOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def link_survey_to_diary(
    project_id: uuid.UUID,
    kind: SurveyLinkKind,
    target_id: uuid.UUID,
    body: DiaryLinkIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DiaryLinkOut:
    await verify_project_access(project_id, user_id, session)
    return await SurveyLinkService(session).link_diary(project_id, kind, target_id, body, user_id)
