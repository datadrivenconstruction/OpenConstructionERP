# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable PDFs of one purchase order and one goods receipt.

    GET /{po_id}/export/pdf/                   - Printable PDF of one purchase order
    GET /goods-receipts/{gr_id}/export/pdf/    - Printable PDF of one goods receipt

Access is the detail route's: ``procurement.read`` and access to the order's
project, so a reader who cannot open the record cannot print it either. The
language follows the RFI export: ``?locale=`` wins, then the first
``Accept-Language`` tag the catalogue has, then English, and
``Content-Language`` names the language the body is actually in. Which
sections print is the workspace's per-type document setting.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.party_names import resolve_party_details, resolve_party_names
from app.core.pdf_appearance import resolve_sections
from app.core.register_context import (
    AcceptLanguageHeader,
    LocaleQuery,
    generated_now,
    load_project_header,
    record_download,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.procurement.pdf_export import goods_receipt_record, purchase_order_record
from app.modules.procurement.pdf_translations import (
    goods_receipt_pdf_filename,
    purchase_order_pdf_filename,
    resolve_pdf_locale,
    tr,
)
from app.modules.procurement.service import ProcurementService

export_router = APIRouter()


@export_router.get("/{po_id}/export/pdf/", dependencies=[Depends(RequirePermission("procurement.read"))])
async def export_purchase_order_pdf(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one purchase order as a printable PDF form with its line items."""
    po = await ProcurementService(session).get_po(po_id)
    await verify_project_access(po.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    project = await load_project_header(session, po.project_id)
    document = purchase_order_record(
        po,
        project=project,
        people=await resolve_party_names(session, [po.vendor_contact_id, po.created_by]),
        parties=await resolve_party_details(session, [po.vendor_contact_id]),
        sections=resolve_sections("purchase_order"),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    return await record_download(document, purchase_order_pdf_filename(po.po_number), doc_locale)


@export_router.get("/goods-receipts/{gr_id}/export/pdf/", dependencies=[Depends(RequirePermission("procurement.read"))])
async def export_goods_receipt_pdf(
    gr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one goods receipt as a printable PDF form with its lines."""
    service = ProcurementService(session)
    receipt = await service.get_goods_receipt(gr_id)
    po = await service.get_po(receipt.po_id)
    await verify_project_access(po.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    project = await load_project_header(session, po.project_id)
    document = goods_receipt_record(
        receipt,
        po=po,
        project=project,
        people=await resolve_party_names(session, [po.vendor_contact_id, receipt.received_by_id]),
        parties=await resolve_party_details(session, [po.vendor_contact_id]),
        sections=resolve_sections("goods_receipt"),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    filename = goods_receipt_pdf_filename(po.po_number, receipt.delivery_note_number)
    return await record_download(document, filename, doc_locale)
