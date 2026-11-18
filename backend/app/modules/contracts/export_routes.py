# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export route for contracts: the printable form of one contract.

    GET /contracts/{contract_id}/export/pdf/   - Printable PDF of one contract

The form is the ``contracts.contract`` document layout, so a firm's own published
layout applies. ``?locale=`` wins, then ``Accept-Language``, then English.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.register_context import AcceptLanguageHeader, LocaleQuery, record_download
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.contracts.pdf_translations import contract_pdf_filename, resolve_pdf_locale
from app.modules.contracts.service import ContractsService

export_router = APIRouter()


@export_router.get(
    "/contracts/{contract_id}/export/pdf/",
    dependencies=[Depends(RequirePermission("contracts.read"))],
    summary="Printable PDF of one contract",
)
async def export_contract_pdf(
    contract_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
    variant: str | None = Query(None, max_length=40, description="Named layout variant; the default one when absent"),
    layout_version: uuid.UUID | None = Query(None, description="Print with this published layout version (reprint)"),
) -> StreamingResponse:
    """Download one contract as a printable PDF form with its schedule of values."""
    from app.modules.contracts.layouts import CONTRACT, contract_layout_context, contract_standard
    from app.modules.doc_templates.layout_service import issue_for_user

    contract = await ContractsService(session).get_contract(contract_id)
    await verify_project_access(contract.project_id, str(user_id), session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    document = await issue_for_user(
        session,
        CONTRACT,
        await contract_layout_context(session, contract, doc_locale),
        standard=contract_standard(),
        record_id=str(contract.id),
        project_id=contract.project_id,
        user_id=str(user_id),
        payload=payload,
        variant=variant,
        version_id=layout_version,
    )
    await session.commit()
    return await record_download(document, contract_pdf_filename(contract.code), doc_locale)
