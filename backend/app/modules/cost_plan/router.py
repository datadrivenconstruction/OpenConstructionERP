# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Elemental cost plan API routes.

Mounted at ``/api/v1/cost-plan``. Two read-only endpoints:

    GET /boqs/{boq_id}/nrm1               - the NRM 1 cost plan of a bill
    GET /boqs/{boq_id}/nrm1/export.xlsx   - the same plan as an Excel workbook

Both take an optional ``gifa`` (m2). Given, it wins over the project's stored
gross floor area for this one reading and is not saved; it must be a positive
number. Reading needs viewer access to the bill's project, checked before
anything else is read, and a bill the caller cannot reach answers 404 exactly
like a bill that does not exist.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.content_disposition import attachment_disposition
from app.core.document_locale import resolve_document_locale
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.boq.models import BOQ
from app.modules.cost_plan.export import DEFAULT_LOCALE, EXPORT_LOCALES, build_cost_plan_workbook
from app.modules.cost_plan.schemas import CostPlanResponse
from app.modules.cost_plan.service import build_nrm1_cost_plan

router = APIRouter()

_READ = Depends(RequirePermission("cost_plan.read"))
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: A floor area typed for one reading. Positive, and bounded so a stray extra
#: digit run cannot turn into a cost per m2 of zero that reads as a real figure.
GifaParam = Annotated[
    Decimal | None,
    Query(gt=0, le=Decimal("100000000"), description="Gross internal floor area in m2 for this reading only."),
]


async def _verify_boq_access(session: SessionDep, boq_id: uuid.UUID, user_id: str) -> None:
    """404 unless the bill exists and the caller may read its project."""
    row = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    await verify_project_access(row[0], user_id, session)


@router.get("/boqs/{boq_id}/nrm1", response_model=CostPlanResponse, dependencies=[_READ])
async def get_nrm1_cost_plan(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    gifa: GifaParam = None,
) -> CostPlanResponse:
    """Roll a bill up into the NRM 1 elemental structure."""
    await _verify_boq_access(session, boq_id, user_id)
    return await build_nrm1_cost_plan(session, boq_id, entered_gifa=gifa)


@router.get("/boqs/{boq_id}/nrm1/export.xlsx", dependencies=[_READ], response_class=Response)
async def export_nrm1_cost_plan(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    gifa: GifaParam = None,
    locale: Annotated[str | None, Query(max_length=16, description="Workbook language, e.g. de.")] = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> Response:
    """Download the NRM 1 cost plan as an Excel workbook.

    The workbook is written from the same plan object the JSON endpoint
    returns, so the two cannot disagree. ``Content-Language`` names the
    language the labels were actually written in, which is English whenever
    the requested one is not in the workbook's catalogue.
    """
    await _verify_boq_access(session, boq_id, user_id)
    plan = await build_nrm1_cost_plan(session, boq_id, entered_gifa=gifa)
    language = resolve_document_locale(locale, accept_language, EXPORT_LOCALES, DEFAULT_LOCALE)
    content = build_cost_plan_workbook(plan, locale=language)
    filename = f"{plan.boq_name or 'BOQ'} - NRM1 cost plan.xlsx"
    return Response(
        content=content,
        media_type=_XLSX,
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "Content-Language": language,
        },
    )
