# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable PDFs of one purchase order and one goods receipt.

    GET /{po_id}/export/pdf/                   - Printable PDF of one purchase order
    GET /goods-receipts/{gr_id}/export/pdf/    - Printable PDF of one goods receipt

Access is the detail route's: ``procurement.read`` and access to the order's
project, so a reader who cannot open the record cannot print it either. The
language follows the RFI export: ``?locale=`` wins, then the first
``Accept-Language`` tag the catalogue has, then English, and
``Content-Language`` names the language the body is actually in.

The form follows the firm's published document layout (the project's
override, then the company default; ``?variant=`` picks a named variant and
``?layout_version=`` reprints with an older version), else the standard
layout with the workspace's per-type section switches. Each print is logged
with the layout version it used.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.doc_templates.layout.spec import LayoutContext, LayoutSpec
from app.core.party_names import resolve_party_details, resolve_party_names
from app.core.pdf_appearance import resolve_sections
from app.core.register_context import (
    AcceptLanguageHeader,
    LocaleQuery,
    generated_now,
    load_project_header,
    record_download,
)
from app.core.register_export import RecordDocument
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.procurement.layouts import (
    GOODS_RECEIPT,
    PURCHASE_ORDER,
    goods_receipt_standard,
    purchase_order_standard,
)
from app.modules.procurement.pdf_export import goods_receipt_context, purchase_order_context
from app.modules.procurement.pdf_translations import (
    goods_receipt_pdf_filename,
    purchase_order_pdf_filename,
    resolve_pdf_locale,
    tr,
)
from app.modules.procurement.service import ProcurementService

export_router = APIRouter()

_VARIANT = Query(None, max_length=40, description="Named layout variant; the default one when absent")
_VERSION = Query(None, description="Print with this published layout version (reprint)")


async def _issue(
    session: Any,
    spec: LayoutSpec,
    ctx: LayoutContext,
    *,
    standard: dict[str, Any],
    record_id: str,
    project_id: uuid.UUID | None,
    user_id: str,
    variant: str | None,
    version: uuid.UUID | None,
) -> RecordDocument:
    from app.modules.doc_templates.layout_service import clean_variant, issue_document

    return await issue_document(
        session,
        spec,
        ctx,
        standard=standard,
        record_id=record_id,
        project_id=project_id,
        user_id=user_id,
        variant=clean_variant(variant) if variant else None,
        version_id=version,
    )


@export_router.get("/{po_id}/export/pdf/", dependencies=[Depends(RequirePermission("procurement.read"))])
async def export_purchase_order_pdf(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
    variant: str | None = _VARIANT,
    layout_version: uuid.UUID | None = _VERSION,
) -> StreamingResponse:
    """Download one purchase order as a printable PDF form with its line items."""
    po = await ProcurementService(session).get_po(po_id)
    await verify_project_access(po.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    project = await load_project_header(session, po.project_id)
    ctx = purchase_order_context(
        po,
        project=project,
        people=await resolve_party_names(session, [po.vendor_contact_id, po.created_by]),
        parties=await resolve_party_details(session, [po.vendor_contact_id]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    document = await _issue(
        session,
        PURCHASE_ORDER,
        ctx,
        standard=purchase_order_standard(resolve_sections("purchase_order")),
        record_id=str(po.id),
        project_id=po.project_id,
        user_id=str(user_id),
        variant=variant,
        version=layout_version,
    )
    await session.commit()
    return await record_download(document, purchase_order_pdf_filename(po.po_number), doc_locale)


@export_router.get("/goods-receipts/{gr_id}/export/pdf/", dependencies=[Depends(RequirePermission("procurement.read"))])
async def export_goods_receipt_pdf(
    gr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
    variant: str | None = _VARIANT,
    layout_version: uuid.UUID | None = _VERSION,
) -> StreamingResponse:
    """Download one goods receipt as a printable PDF form with its lines."""
    service = ProcurementService(session)
    receipt = await service.get_goods_receipt(gr_id)
    po = await service.get_po(receipt.po_id)
    await verify_project_access(po.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    project = await load_project_header(session, po.project_id)
    ctx = goods_receipt_context(
        receipt,
        po=po,
        project=project,
        people=await resolve_party_names(session, [po.vendor_contact_id, receipt.received_by_id]),
        parties=await resolve_party_details(session, [po.vendor_contact_id]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    document = await _issue(
        session,
        GOODS_RECEIPT,
        ctx,
        standard=goods_receipt_standard(resolve_sections("goods_receipt")),
        record_id=str(receipt.id),
        project_id=po.project_id,
        user_id=str(user_id),
        variant=variant,
        version=layout_version,
    )
    await session.commit()
    filename = goods_receipt_pdf_filename(po.po_number, receipt.delivery_note_number)
    return await record_download(document, filename, doc_locale)
