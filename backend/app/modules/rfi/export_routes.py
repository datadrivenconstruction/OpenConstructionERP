# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The RFI log export, in the reader's language, as a workbook or a PDF.

    GET /export/register/    - RFI log for a project (``?format=xlsx`` by default, or ``pdf``)

The older ``GET /export/`` in ``router.py`` is left as it is: a workbook with
English headings whatever the reader's language. This route is the same log
with the same twelve columns, translated, and with a PDF form. Without
``?locale=`` and without an ``Accept-Language`` the catalogue has, it is
English with the headings the log always had.

The module router includes :data:`export_router` before its own routes, so
``export`` is never read as an RFI id.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.register_context import (
    AcceptLanguageHeader,
    FormatQuery,
    LocaleQuery,
    generated_now,
    load_project_header,
    register_download,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.rfi.models import RFI
from app.modules.rfi.register_export import (
    CATALOGUE,
    resolve_register_locale,
    rfi_register,
    rfi_register_filename,
)
from app.modules.rfi.service import RFIService

export_router = APIRouter()

_MAX_REGISTER_ROWS = 50000


@export_router.get("/export/register/", dependencies=[Depends(RequirePermission("rfi.read"))])
async def export_rfi_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the RFI log of a project as a workbook or a PDF.

    People are written by name and statuses as words, in the language asked
    for. An id that matches no user is kept, shortened, so the log never
    loses a value.
    """
    # The router imports this module, so its helper is read at call time.
    from app.modules.rfi.router import _compute_rfi_fields

    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_register_locale(locale, accept_language)
    items = (
        (
            await session.execute(
                select(RFI).where(RFI.project_id == project_id).order_by(RFI.rfi_number).limit(_MAX_REGISTER_ROWS)
            )
        )
        .scalars()
        .all()
    )
    people = await RFIService(session).user_display_names(
        [value for item in items for value in (item.raised_by, item.assigned_to, item.ball_in_court)]
    )
    document = rfi_register(
        items,
        project=await load_project_header(session, project_id),
        people=people,
        # The canonical helper, so the log agrees with the list and detail figure.
        days_open={item.id: _compute_rfi_fields(item)[1] for item in items},
        locale=doc_locale,
        generated=generated_now(CATALOGUE.tr(doc_locale, "datetime_format")),
    )
    return await register_download(
        document, export_format, lambda extension: rfi_register_filename(doc_locale, extension)
    )
