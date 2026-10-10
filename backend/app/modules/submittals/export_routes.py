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

The register takes the filters the list takes. ``?type=shop_drawing`` is the
shop drawing register and ``?type=product_data`` the material approval
register: the same log, cut by type, under the name that cut has on site. The
filters used are printed in the header, so a partial register says it is one.
The workbook carries every column; the PDF carries the ones that fit a sheet.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.modules.submittals.schemas import DISCIPLINE_PATTERN, REVIEW_OUTCOME_PATTERN, SUBMITTAL_TYPE_PATTERN
from app.modules.submittals.service import SubmittalService

export_router = APIRouter()

# A register is printed whole. The cap only keeps a runaway project from
# building a document nobody could open.
_MAX_REGISTER_ROWS = 50000


def _named(item: Submittal) -> list[object]:
    # Read with a default: a row written before the supplier and the review
    # history existed has neither, and it still has to print.
    fields = ("reviewer_id", "approver_id", "ball_in_court", "submitted_by_org", "supplier")
    named = [getattr(item, name, None) for name in fields]
    stored = getattr(item, "review_history", None)
    history = stored if isinstance(stored, list) else []
    return [*named, *(entry.get("reviewer_id") for entry in history if isinstance(entry, dict))]


async def _drawing_names(session: AsyncSession, project_id: uuid.UUID, items: Iterable[Submittal]) -> dict[str, str]:
    """Names of the drawings the submittals link to, keyed by the id as stored.

    Only documents of the same project are named, so an id pointing into
    another project prints as unavailable rather than leaking its name. The
    documents module is optional and the link is soft: whatever cannot be
    resolved is simply absent, and the form says how many are.
    """
    wanted: dict[uuid.UUID, str] = {}
    for item in items:
        stored = getattr(item, "linked_drawing_ids", None)
        linked = stored if isinstance(stored, list) else []
        for raw in linked:
            try:
                wanted[uuid.UUID(str(raw).strip())] = str(raw)
            except ValueError:
                continue
    if not wanted:
        return {}
    try:
        from app.modules.documents.models import Document
    except ImportError:
        return {}
    rows = (
        await session.execute(
            select(Document.id, Document.name).where(Document.id.in_(wanted), Document.project_id == project_id)
        )
    ).all()
    return {wanted[doc_id]: name for doc_id, name in rows if doc_id in wanted and name}


@export_router.get("/export/", dependencies=[Depends(RequirePermission("submittals.read"))])
async def export_submittal_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    export_format: FormatQuery = "xlsx",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type", pattern=SUBMITTAL_TYPE_PATTERN),
    discipline: str | None = Query(default=None, pattern=DISCIPLINE_PATTERN),
    outcome: str | None = Query(default=None, pattern=REVIEW_OUTCOME_PATTERN),
    review_code: str | None = Query(default=None, max_length=20),
    long_lead: bool | None = Query(default=None),
    review_overdue: bool | None = Query(default=None),
    approval_late: bool | None = Query(default=None),
) -> StreamingResponse:
    """Download the submittal register of a project as a workbook or a PDF.

    Unfiltered it is the whole log. With ``type`` it is that type's register
    (shop drawings, material approvals); the other filters are the ones the
    list takes, and each one used is named in the document's header.
    """
    await verify_project_access(project_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    filters: dict[str, Any] = {
        "status": status_filter,
        "submittal_type": type_filter,
        "discipline": discipline,
        "review_outcome": outcome,
        "review_code": review_code,
        "long_lead": long_lead,
        "review_overdue": review_overdue,
        "approval_late": approval_late,
    }
    items, _ = await SubmittalService(session).list_submittals(
        project_id,
        offset=0,
        limit=_MAX_REGISTER_ROWS,
        status_filter=status_filter,
        submittal_type=type_filter,
        discipline=discipline,
        review_outcome=outcome,
        review_code=review_code,
        long_lead=long_lead,
        review_overdue=review_overdue,
        approval_late=approval_late,
        sort="submittal_number",
        descending=False,
    )
    project = await load_project_header(session, project_id)
    document = submittal_register(
        items,
        project=project,
        people=await resolve_party_names(session, [value for item in items for value in _named(item)]),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
        # The sheet gets the columns that fit it, the workbook all of them.
        layout="print" if export_format == "pdf" else "full",
        filters=filters,
        drawings=await _drawing_names(session, project_id, items),
    )
    return await register_download(
        document, export_format, lambda extension: submittal_register_filename(doc_locale, extension, type_filter)
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
    project = await load_project_header(session, submittal.project_id)
    document = submittal_record(
        submittal,
        project=project,
        people=await resolve_party_names(session, _named(submittal)),
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
        drawings=await _drawing_names(session, submittal.project_id, [submittal]),
    )
    return await record_download(document, submittal_pdf_filename(submittal.submittal_number), doc_locale)
