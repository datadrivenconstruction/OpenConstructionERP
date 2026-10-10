# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export routes for correspondence: the log and the record of one item.

    GET /export/                            - Correspondence log, workbook or PDF
    GET /{correspondence_id}/export/pdf/    - Printable PDF of one item

The module router includes :data:`export_router` before its own routes, so
``/export/`` is never read as a correspondence id. The language follows the
RFI export: ``?locale=`` wins, then the first ``Accept-Language`` tag the
catalogue has, then English, and ``Content-Language`` names the language the
body is actually in.
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
from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.pdf_export import correspondence_record, correspondence_register
from app.modules.correspondence.pdf_translations import (
    correspondence_pdf_filename,
    correspondence_register_filename,
    resolve_pdf_locale,
    tr,
)
from app.modules.correspondence.service import CorrespondenceService

export_router = APIRouter()

_MAX_REGISTER_ROWS = 50000


def _named(item: Correspondence) -> list[object]:
    return [item.from_contact_id, *(item.to_contact_ids or [])]


@export_router.get("/export/", dependencies=[Depends(RequirePermission("correspondence.read"))])
async def export_correspondence_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the correspondence log of a project as a workbook or a PDF."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    items = (
        (
            await session.execute(
                select(Correspondence)
                .where(Correspondence.project_id == project_id)
                .order_by(Correspondence.reference_number)
                .limit(_MAX_REGISTER_ROWS)
            )
        )
        .scalars()
        .all()
    )
    document = correspondence_register(
        items,
        project=await load_project_header(session, project_id),
        people=await resolve_party_names(session, [value for item in items for value in _named(item)]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: correspondence_register_filename(doc_locale, extension)
    )


@export_router.get("/{correspondence_id}/export/pdf/", dependencies=[Depends(RequirePermission("correspondence.read"))])
async def export_correspondence_pdf(
    correspondence_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one piece of correspondence as a printable PDF record."""
    item = await CorrespondenceService(session).get_correspondence(correspondence_id)
    await verify_project_access(item.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = correspondence_record(
        item,
        project=await load_project_header(session, item.project_id),
        people=await resolve_party_names(session, _named(item)),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await record_download(document, correspondence_pdf_filename(item.reference_number), doc_locale)
