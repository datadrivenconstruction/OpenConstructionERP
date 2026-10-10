# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Printable evidence packs.

    GET /projects/{project_id}/pack/export/                                     - Project evidence pack
    GET /projects/{project_id}/reconstruct/{subject_type}/{subject_id}/export/  - One subject's pack

Both return the pack the JSON routes return, as a PDF (the default, since a
pack is a document to attach) or a workbook. Printing a pack is a read: the
audit row for a deliberate export stays with the existing POST route. The
language follows the RFI export: ``?locale=`` wins, then the first
``Accept-Language`` tag the catalogue has, then English, and
``Content-Language`` names the language the body is actually in.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.core.register_context import (
    AcceptLanguageHeader,
    LocaleQuery,
    generated_now,
    load_project_header,
    register_download,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.claims_evidence.pdf_export import evidence_pack_register
from app.modules.claims_evidence.pdf_translations import evidence_pack_filename, resolve_pdf_locale, tr
from app.modules.claims_evidence.service import assemble_evidence, reconstruct_subject

export_router = APIRouter()

#: Subject types a thread can be reconstructed from; mirrors the JSON route.
_RECONSTRUCT_KINDS = ("change_order", "variation_request", "variation_order", "notice", "moc", "correspondence")

_FORMAT = Query(
    "pdf", alias="format", pattern="^(pdf|xlsx)$", description="'pdf' for a printable pack, 'xlsx' for a workbook."
)


@export_router.get(
    "/projects/{project_id}/pack/export/", dependencies=[Depends(RequirePermission("claims_evidence.read"))]
)
async def export_evidence_pack(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    subject_ref: str = Query(description="Identifier of the claim or dispute the pack supports."),
    basis: str = Query(default="dispute", description="The basis the pack is assembled under."),
    limit: int = Query(default=500, ge=1, le=2000, description="Max activity rows to include."),
    export_format: str = _FORMAT,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download a project's evidence pack as a printable PDF or a workbook."""
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    pack = await assemble_evidence(
        session, project_id=project_id, subject_ref=subject_ref, basis=basis, activity_limit=limit
    )
    project = await load_project_header(session, project_id)
    document = evidence_pack_register(
        pack,
        project=project,
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    return await register_download(
        document, export_format, lambda extension: evidence_pack_filename(doc_locale, extension)
    )


@export_router.get(
    "/projects/{project_id}/reconstruct/{subject_type}/{subject_id}/export/",
    dependencies=[Depends(RequirePermission("claims_evidence.read"))],
)
async def export_reconstructed_pack_document(
    project_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    basis: str = Query(default="dispute", description="The basis the pack is assembled under."),
    export_format: str = _FORMAT,
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """Download one subject's reconstructed evidence pack as a printable PDF or a workbook."""
    await verify_project_access(project_id, user_id, session)
    if subject_type not in _RECONSTRUCT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown subject type '{subject_type}'. Expected one of: {', '.join(_RECONSTRUCT_KINDS)}.",
        )
    doc_locale = resolve_pdf_locale(locale, accept_language)
    pack = await reconstruct_subject(
        session, project_id=project_id, subject_type=subject_type, subject_id=subject_id, basis=basis
    )
    project = await load_project_header(session, project_id)
    document = evidence_pack_register(
        pack,
        project=project,
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    return await register_download(
        document, export_format, lambda extension: evidence_pack_filename(doc_locale, extension)
    )
