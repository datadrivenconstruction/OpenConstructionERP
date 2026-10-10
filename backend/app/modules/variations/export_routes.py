# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export routes for variations: three registers and the form of one request.

    GET /variation-requests/export/                 - Variation register, workbook or PDF
    GET /variation-requests/{vr_id}/export/pdf/     - Printable PDF of one variation request
    GET /claims/export/                             - Claims register (disruption + extension of time)
    GET /notices/export/                            - Notice register

The module router includes :data:`export_router` before its own routes, so
``export`` is never read as a record id. The language follows the RFI
export: ``?locale=`` wins, then the first ``Accept-Language`` tag the
catalogue has, then English, and ``Content-Language`` names the language the
body is actually in.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.party_names import resolve_party_names
from app.core.register_context import (
    AcceptLanguageHeader,
    FormatQuery,
    LocaleQuery,
    generated_now,
    load_project_header,
    record_download,
    register_download,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.variations.models import DisruptionClaim, ExtensionOfTimeClaim, Notice, VariationRequest
from app.modules.variations.pdf_export import claim_register, notice_register, variation_record, variation_register
from app.modules.variations.pdf_translations import (
    register_filename,
    resolve_pdf_locale,
    tr,
    variation_pdf_filename,
)
from app.modules.variations.service import VariationsService

export_router = APIRouter()

_MAX_REGISTER_ROWS = 50000


async def _rows(session: Any, model: Any, project_id: uuid.UUID, order_by: Any) -> list[Any]:
    """Every row of ``model`` for a project, in print order."""
    result = await session.execute(
        select(model).where(model.project_id == project_id).order_by(order_by).limit(_MAX_REGISTER_ROWS)
    )
    return list(result.scalars().all())


@export_router.get("/variation-requests/export/", dependencies=[Depends(RequirePermission("variations.read"))])
async def export_variation_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the variation register of a project as a workbook or a PDF."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = variation_register(
        await _rows(session, VariationRequest, project_id, VariationRequest.code),
        project=await load_project_header(session, project_id),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: register_filename("variation", doc_locale, extension)
    )


@export_router.get("/claims/export/", dependencies=[Depends(RequirePermission("variations.read"))])
async def export_claim_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the claims register of a project: disruption and extension of time claims in one list."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = claim_register(
        await _rows(session, DisruptionClaim, project_id, DisruptionClaim.raised_at),
        await _rows(session, ExtensionOfTimeClaim, project_id, ExtensionOfTimeClaim.raised_at),
        project=await load_project_header(session, project_id),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: register_filename("claim", doc_locale, extension)
    )


@export_router.get("/notices/export/", dependencies=[Depends(RequirePermission("variations.read"))])
async def export_notice_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the notice register of a project as a workbook or a PDF."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = notice_register(
        await _rows(session, Notice, project_id, Notice.code),
        project=await load_project_header(session, project_id),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: register_filename("notice", doc_locale, extension)
    )


@export_router.get(
    "/variation-requests/{vr_id}/export/pdf/", dependencies=[Depends(RequirePermission("variations.read"))]
)
async def export_variation_pdf(
    vr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one variation request as a printable PDF form."""
    request = await VariationsService(session).get_request(vr_id)
    await verify_project_access(request.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = variation_record(
        request,
        project=await load_project_header(session, request.project_id),
        people=await resolve_party_names(session, [request.requested_by, request.decided_by]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await record_download(document, variation_pdf_filename(request.code), doc_locale)
