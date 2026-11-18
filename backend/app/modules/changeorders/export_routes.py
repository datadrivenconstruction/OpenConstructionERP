# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export routes for change orders: the register and the form of one order.

    GET /export/                    - Change order register, workbook or PDF
    GET /{order_id}/export/pdf/     - Printable PDF of one change order

The module router includes :data:`export_router` before its own routes, so
``/export/`` is never read as an order id. The language follows the RFI
export: ``?locale=`` wins, then the first ``Accept-Language`` tag the
catalogue has, then English, and ``Content-Language`` names the language the
body is actually in.
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
    record_download,
    register_download,
)
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.pdf_export import change_order_register
from app.modules.changeorders.pdf_translations import (
    change_order_pdf_filename,
    change_order_register_filename,
    resolve_pdf_locale,
    tr,
)
from app.modules.changeorders.service import ChangeOrderService

export_router = APIRouter()

_MAX_REGISTER_ROWS = 50000


@export_router.get("/export/", dependencies=[Depends(RequirePermission("changeorders.read"))])
async def export_change_order_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download the change order register of a project as a workbook or a PDF."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    orders = (
        (
            await session.execute(
                select(ChangeOrder)
                .where(ChangeOrder.project_id == project_id)
                .order_by(ChangeOrder.code)
                .limit(_MAX_REGISTER_ROWS)
            )
        )
        .scalars()
        .all()
    )
    project = await load_project_header(session, project_id)
    document = change_order_register(
        orders,
        project=project,
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    return await register_download(
        document, export_format, lambda extension: change_order_register_filename(doc_locale, extension)
    )


@export_router.get("/{order_id}/export/pdf/", dependencies=[Depends(RequirePermission("changeorders.read"))])
async def export_change_order_pdf(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
    variant: str | None = Query(None, max_length=40, description="Named layout variant; the default one when absent"),
    layout_version: uuid.UUID | None = Query(None, description="Print with this published layout version (reprint)"),
) -> StreamingResponse:
    """Download one change order as a printable PDF form with its items."""
    from app.modules.changeorders.layouts import CHANGE_ORDER, change_order_layout_context, change_order_standard
    from app.modules.doc_templates.layout_service import issue_for_user

    order = await ChangeOrderService(session).get_order(order_id)
    await verify_project_access(order.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = await issue_for_user(
        session,
        CHANGE_ORDER,
        await change_order_layout_context(session, order, doc_locale),
        standard=change_order_standard(),
        record_id=str(order.id),
        project_id=order.project_id,
        user_id=str(user_id),
        payload=payload,
        variant=variant,
        version_id=layout_version,
    )
    await session.commit()
    return await record_download(document, change_order_pdf_filename(order.code), doc_locale)
