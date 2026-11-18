# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile API routes (mounted at ``/api/v1/stockpiles``).

Endpoints:
    GET    /projects/{project_id}/stockpiles      - stockpiles with their latest survey
    POST   /projects/{project_id}/stockpiles      - new stockpile
    GET    /projects/{project_id}/summary         - KPI band
    GET    /stockpiles/{stockpile_id}             - one stockpile with all its surveys
    PATCH  /stockpiles/{stockpile_id}             - rename, book stock, base, tolerance
    DELETE /stockpiles/{stockpile_id}             - remove (not when a survey is booked)
    POST   /stockpiles/{stockpile_id}/surveys     - add a survey
    PATCH  /surveys/{survey_id}                   - change density, source, volume (not when booked)
    DELETE /surveys/{survey_id}                   - remove an open survey
    POST   /surveys/{survey_id}/propose-adjustment - draft an inventory correction
    POST   /adjustments/{adjustment_id}/confirm   - book it (survey.confirm)
    POST   /adjustments/{adjustment_id}/cancel    - drop the proposal
    GET    /surveys/{survey_id}/report.pdf        - stockpile report
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.stockpiles.schemas import (
    AdjustmentConfirm,
    AdjustmentOut,
    StockpileCreate,
    StockpileDetail,
    StockpileListResponse,
    StockpileSummary,
    StockpileUpdate,
    SurveyCreate,
    SurveyOut,
    SurveyUpdate,
)
from app.modules.stockpiles.service import StockpileService
from app.modules.survey_core.permissions import require_survey_confirm

router = APIRouter(tags=["stockpiles"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)


async def _pile(stockpile_id: uuid.UUID, session: SessionDep, user_id: str):
    service = StockpileService(session)
    p = await service.get_stockpile(stockpile_id)
    await verify_project_access(p.project_id, user_id, session)
    return service, p


async def _survey(survey_id: uuid.UUID, session: SessionDep, user_id: str):
    service = StockpileService(session)
    s = await service.get_survey(survey_id)
    await verify_project_access(s.project_id, user_id, session)
    return service, s


@router.get("/projects/{project_id}/stockpiles", response_model=StockpileListResponse, dependencies=_READ)
async def list_stockpiles(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = _LOCALE,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> StockpileListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await StockpileService(session).list_stockpiles(project_id, locale)
    return StockpileListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/stockpiles",
    response_model=StockpileDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_stockpile(
    project_id: uuid.UUID, body: StockpileCreate, session: SessionDep, user_id: CurrentUserId
) -> StockpileDetail:
    await verify_project_access(project_id, user_id, session)
    return await StockpileService(session).create_stockpile(project_id, body, user_id)


@router.get("/projects/{project_id}/summary", response_model=StockpileSummary, dependencies=_READ)
async def summary(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> StockpileSummary:
    await verify_project_access(project_id, user_id, session)
    return await StockpileService(session).summary(project_id)


@router.get("/stockpiles/{stockpile_id}", response_model=StockpileDetail, dependencies=_READ)
async def get_stockpile(
    stockpile_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> StockpileDetail:
    service, p = await _pile(stockpile_id, session, user_id)
    return await service.detail(p, locale)


@router.patch("/stockpiles/{stockpile_id}", response_model=StockpileDetail, dependencies=_WRITE)
async def update_stockpile(
    stockpile_id: uuid.UUID, body: StockpileUpdate, session: SessionDep, user_id: CurrentUserId
) -> StockpileDetail:
    service, p = await _pile(stockpile_id, session, user_id)
    return await service.update_stockpile(p, body, user_id)


@router.delete("/stockpiles/{stockpile_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_stockpile(stockpile_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, p = await _pile(stockpile_id, session, user_id)
    await service.delete_stockpile(p, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/stockpiles/{stockpile_id}/surveys",
    response_model=SurveyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def add_survey(
    stockpile_id: uuid.UUID, body: SurveyCreate, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> SurveyOut:
    service, p = await _pile(stockpile_id, session, user_id)
    return await service.add_survey(p, body, user_id, locale)


@router.patch("/surveys/{survey_id}", response_model=SurveyOut, dependencies=_WRITE)
async def update_survey(
    survey_id: uuid.UUID, body: SurveyUpdate, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> SurveyOut:
    service, s = await _survey(survey_id, session, user_id)
    return await service.update_survey(s, body, user_id, locale)


@router.delete("/surveys/{survey_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_survey(survey_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, s = await _survey(survey_id, session, user_id)
    await service.delete_survey(s, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/surveys/{survey_id}/propose-adjustment",
    response_model=AdjustmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def propose_adjustment(
    survey_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> AdjustmentOut:
    service, s = await _survey(survey_id, session, user_id)
    return await service.propose_adjustment(s, user_id, locale)


async def _adjustment(adjustment_id: uuid.UUID, session: SessionDep, user_id: str):
    service = StockpileService(session)
    a = await service.get_adjustment(adjustment_id)
    await verify_project_access(a.project_id, user_id, session)
    return service, a


@router.post(
    "/adjustments/{adjustment_id}/confirm",
    response_model=SurveyOut,
    dependencies=[*_WRITE, Depends(require_survey_confirm), Depends(RequirePermission("site_inventory.write"))],
)
async def confirm_adjustment(
    adjustment_id: uuid.UUID,
    body: AdjustmentConfirm,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = _LOCALE,
) -> SurveyOut:
    service, a = await _adjustment(adjustment_id, session, user_id)
    return await service.confirm_adjustment(a, body, user_id, locale)


@router.post("/adjustments/{adjustment_id}/cancel", response_model=SurveyOut, dependencies=_WRITE)
async def cancel_adjustment(
    adjustment_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> SurveyOut:
    service, a = await _adjustment(adjustment_id, session, user_id)
    return await service.cancel_adjustment(a, user_id, locale)


@router.get("/surveys/{survey_id}/report.pdf", dependencies=_READ)
async def report_pdf(
    survey_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> Response:
    from app.modules.projects.models import Project  # noqa: PLC0415
    from app.modules.stockpiles.report_pdf import build_stockpile_report  # noqa: PLC0415

    service, s = await _survey(survey_id, session, user_id)
    data = await service.report_data(s, locale)
    project = await session.get(Project, s.project_id)
    pdf = build_stockpile_report(data, project.name if project else "")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{data["stockpile"]["code"]}-{s.surveyed_on}.pdf"',
            "Content-Language": normalize_document_locale(locale, SUPPORTED_LOCALES, "en"),
        },
    )
