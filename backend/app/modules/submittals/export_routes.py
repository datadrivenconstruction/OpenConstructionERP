# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export routes for submittals: the register and the form of one submittal.

    GET /export/                       - Submittal register, workbook or PDF
    GET /{submittal_id}/export/pdf/    - Printable PDF of one submittal

Kept beside the renderer rather than in ``router.py`` so everything that
decides what a printed submittal says lives in three files. The module router
includes :data:`export_router` before its own routes, so ``/export/`` is
never read as a submittal id.

The language follows the RFI export: ``?locale=`` wins, then the first
``Accept-Language`` tag the catalogue has, then English, and
``Content-Language`` names the language the body is actually in.
"""

from __future__ import annotations

import uuid

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
from app.modules.submittals.models import Submittal
from app.modules.submittals.pdf_export import submittal_record, submittal_register
from app.modules.submittals.pdf_translations import (
    resolve_pdf_locale,
    submittal_pdf_filename,
    submittal_register_filename,
    tr,
)
from app.modules.submittals.service import SubmittalService

export_router = APIRouter()

# A register is printed whole. The cap only keeps a runaway project from
# building a document nobody could open.
_MAX_REGISTER_ROWS = 50000


def _named(item: Submittal) -> list[object]:
    return [item.reviewer_id, item.approver_id, item.ball_in_court, item.submitted_by_org]


@export_router.get("/export/", dependencies=[Depends(RequirePermission("submittals.read"))])
async def export_submittal_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the submittal register of a project as a workbook or a PDF."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    items = (
        (
            await session.execute(
                select(Submittal)
                .where(Submittal.project_id == project_id)
                .order_by(Submittal.submittal_number)
                .limit(_MAX_REGISTER_ROWS)
            )
        )
        .scalars()
        .all()
    )
    document = submittal_register(
        items,
        project=await load_project_header(session, project_id),
        people=await resolve_party_names(session, [value for item in items for value in _named(item)]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: submittal_register_filename(doc_locale, extension)
    )


@export_router.get("/{submittal_id}/export/pdf/", dependencies=[Depends(RequirePermission("submittals.read"))])
async def export_submittal_pdf(
    submittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one submittal as a printable PDF form with signature lines."""
    submittal = await SubmittalService(session).get_submittal(submittal_id)
    await verify_project_access(submittal.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = submittal_record(
        submittal,
        project=await load_project_header(session, submittal.project_id),
        people=await resolve_party_names(session, _named(submittal)),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await record_download(document, submittal_pdf_filename(submittal.submittal_number), doc_locale)
