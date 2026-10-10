# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export routes for transmittals: the register and the cover sheet of one.

    GET /export/                          - Transmittal register, workbook or PDF
    GET /{transmittal_id}/export/pdf/     - Printable cover sheet of one transmittal

The module router includes :data:`export_router` before its own routes, so
``/export/`` is never read as a transmittal id. The language follows the RFI
export: ``?locale=`` wins, then the first ``Accept-Language`` tag the
catalogue has, then English, and ``Content-Language`` names the language the
body is actually in.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

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
from app.modules.transmittals.models import Transmittal
from app.modules.transmittals.pdf_export import transmittal_record, transmittal_register
from app.modules.transmittals.pdf_translations import (
    resolve_pdf_locale,
    tr,
    transmittal_pdf_filename,
    transmittal_register_filename,
)

export_router = APIRouter()

_MAX_REGISTER_ROWS = 50000


def _named(item: Transmittal) -> list[object]:
    values: list[object] = [item.sender_org_id]
    for recipient in item.recipients or []:
        values.extend([recipient.recipient_user_id, recipient.recipient_org_id])
    return values


@export_router.get("/export/", dependencies=[Depends(RequirePermission("transmittals.read"))])
async def export_transmittal_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the transmittal register of a project as a workbook or a PDF."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    items = (
        (
            await session.execute(
                select(Transmittal)
                .where(Transmittal.project_id == project_id)
                .options(selectinload(Transmittal.recipients), selectinload(Transmittal.items))
                .order_by(Transmittal.transmittal_number)
                .limit(_MAX_REGISTER_ROWS)
            )
        )
        .scalars()
        .all()
    )
    document = transmittal_register(
        items,
        project=await load_project_header(session, project_id),
        people=await resolve_party_names(session, [value for item in items for value in _named(item)]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: transmittal_register_filename(doc_locale, extension)
    )


@export_router.get("/{transmittal_id}/export/pdf/", dependencies=[Depends(RequirePermission("transmittals.read"))])
async def export_transmittal_pdf(
    transmittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one transmittal as a printable cover sheet with its recipients and items."""
    transmittal = (
        await session.execute(
            select(Transmittal)
            .where(Transmittal.id == transmittal_id)
            .options(selectinload(Transmittal.recipients), selectinload(Transmittal.items))
        )
    ).scalar_one_or_none()
    if transmittal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transmittal not found")
    await verify_project_access(transmittal.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = transmittal_record(
        transmittal,
        project=await load_project_header(session, transmittal.project_id),
        people=await resolve_party_names(session, _named(transmittal)),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format")),
    )
    return await record_download(document, transmittal_pdf_filename(transmittal.transmittal_number), doc_locale)
